import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap

from config import CAPTURE_DIR, ZONE_NAMES


def _board_zone(cx_norm, cy_norm):
    """Return (row, col) zone in a 3×3 grid from normalised [0..1] coords."""
    return min(int(cy_norm * 3), 2), min(int(cx_norm * 3), 2)


def _board_center_norm(corners, frame_shape):
    """Return normalised (cx, cy) of board bounding box centre."""
    h, w = frame_shape[:2]
    pts = corners.reshape(-1, 2)
    cx = (pts[:, 0].min() + pts[:, 0].max()) / 2 / w
    cy = (pts[:, 1].min() + pts[:, 1].max()) / 2 / h
    return cx, cy


def analyze_board_placement(corners_l, shape_l, corners_r, shape_r, cb, covered_zones):
    """
    Analyse checkerboard position using BOTH cameras.
    Zone is determined from the average board centre so it reflects the
    shared field of view rather than one camera's edge.
    covered_zones: dict[(row,col) -> int]
    """
    h, w = shape_l[:2]
    pts = corners_l.reshape(-1, 2)
    x_min, y_min = pts.min(axis=0)
    x_max, y_max = pts.max(axis=0)
    coverage = ((x_max - x_min) * (y_max - y_min)) / (w * h)

    cx_l, cy_l = _board_center_norm(corners_l, shape_l)
    cx_r, cy_r = _board_center_norm(corners_r, shape_r)
    cx_avg = (cx_l + cx_r) / 2
    cy_avg = (cy_l + cy_r) / 2

    zone = _board_zone(cx_avg, cy_avg)
    zone_name = ZONE_NAMES[zone]

    n_cols = cb[0]
    n_rows = cb[1]
    tl = pts[0]
    tr = pts[n_cols - 1]
    bl = pts[(n_rows - 1) * n_cols]
    angle_h = np.degrees(np.arctan2(tr[1] - tl[1], tr[0] - tl[0]))
    angle_v = np.degrees(np.arctan2(bl[0] - tl[0], bl[1] - tl[1]))
    is_tilted = abs(angle_h) > 8 or abs(angle_v) > 8

    parts = []

    if coverage < 0.08:
        parts.append("Приблизьте доску")
    elif coverage > 0.55:
        parts.append("Отдалите доску")

    center_count = covered_zones.get((1, 1), 0)
    missing = [z for z in ZONE_NAMES if covered_zones.get(z, 0) == 0]

    if center_count < 3:
        if zone == (1, 1):
            if not is_tilted and center_count > 0:
                parts.append(f"Наклоните доску ({center_count + 1}/3 центр)")
            else:
                parts.append(f"Сохраните снимок — центр {center_count + 1}/3")
        else:
            parts.append("Переместите доску в ЦЕНТР кадра")
    elif missing:
        target_name = ZONE_NAMES[missing[0]]
        if zone == missing[0]:
            parts.append(f"Отлично! Сохраните — {target_name}")
        else:
            parts.append(f"Переместите в: {target_name}")
    else:
        total = sum(covered_zones.values())
        if total < 20:
            parts.append("Меняйте расстояние и угол наклона")
        else:
            parts.append("Все зоны покрыты — можно калибровать!")

    cov_pct = int(coverage * 100)
    status = f"[{zone_name}]  {cov_pct}%  H{angle_h:+.0f}°  V{angle_v:+.0f}°"
    advice = "  •  ".join(parts) if parts else "Хорошая позиция!"
    return zone, status, advice


def make_zone_map_pixmap(covered_zones: dict, cell: int = 30) -> QPixmap:
    """Draw a 3×3 zone map and return a QPixmap."""
    size = cell * 3 + 4
    img = np.full((size, size, 3), 30, dtype=np.uint8)
    for (r, c) in ZONE_NAMES:
        x1, y1 = c * cell + 1, r * cell + 1
        x2, y2 = x1 + cell - 2, y1 + cell - 2
        count = covered_zones.get((r, c), 0)
        if count == 0:
            color = (60, 60, 60)
        elif count < 3:
            color = (0, 130, 220)
        else:
            color = (30, 180, 50)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, -1)
        cv2.rectangle(img, (x1, y1), (x2, y2), (160, 160, 160), 1)
        if count > 0:
            cv2.putText(img, str(count), (x1 + 8, y1 + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    qi = QImage(rgb.data.tobytes(), size, size, 3 * size, QImage.Format_RGB888)
    return QPixmap.fromImage(qi)


def bgr_to_pixmap(frame: np.ndarray, w: int, h: int) -> QPixmap:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    fh, fw, ch = rgb.shape
    qi = QImage(rgb.data.tobytes(), fw, fh, ch * fw, QImage.Format_RGB888)
    return QPixmap.fromImage(qi).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def make_ref_checkerboard(sq_cols: int, sq_rows: int, sq_px: int = 80) -> np.ndarray:
    """Generate a reference checkerboard BGR image.

    sq_cols / sq_rows — number of SQUARES (what the user counts visually).
    OpenCV inner corners = (sq_cols-1, sq_rows-1).
    """
    border = sq_px
    h = sq_rows * sq_px
    w = sq_cols * sq_px
    img = np.zeros((h, w), dtype=np.uint8)
    for r in range(sq_rows):
        for c in range(sq_cols):
            if (r + c) % 2 == 0:
                img[r * sq_px:(r + 1) * sq_px, c * sq_px:(c + 1) * sq_px] = 255
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    bgr = cv2.copyMakeBorder(bgr, border, border, border, border,
                             cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.rectangle(bgr, (border - 1, border - 1),
                  (w + border, h + border), (180, 180, 180), 1)
    return bgr


def ensure_dirs():
    (CAPTURE_DIR / "left").mkdir(parents=True, exist_ok=True)
    (CAPTURE_DIR / "right").mkdir(parents=True, exist_ok=True)


def clear_capture_dirs():
    for side in ("left", "right"):
        for f in (CAPTURE_DIR / side).glob("*.jpg"):
            f.unlink(missing_ok=True)
