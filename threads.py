import traceback

import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from config import CAPTURE_DIR


class CameraDetectThread(QThread):
    """Scan indices 0-9 for available cameras (runs once on startup)."""
    cameras_found = pyqtSignal(list)

    def run(self):
        found = []
        for idx in range(10):
            for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
                cap = cv2.VideoCapture(idx, backend)
                if cap.isOpened():
                    ret, _ = cap.read()
                    cap.release()
                    if ret:
                        found.append((idx, f"Камера {idx}"))
                        break
                else:
                    cap.release()
        self.cameras_found.emit(found)


class SingleCamThread(QThread):
    """Continuous feed from one camera."""
    frame_ready = pyqtSignal(object)
    camera_error = pyqtSignal(str)

    def __init__(self, idx: int, w: int = 640, h: int = 480):
        super().__init__()
        self.idx = idx
        self.w = w
        self.h = h
        self._running = False
        self._stop_requested = False

    def run(self):
        cap = None
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
            if self._stop_requested:
                return
            cap = cv2.VideoCapture(self.idx, backend)
            if cap.isOpened():
                break
            cap.release()
            cap = None
        if self._stop_requested:
            if cap:
                cap.release()
            return
        if cap is None or not cap.isOpened():
            self.camera_error.emit(f"Не удалось открыть камеру {self.idx}")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.h)
        cap.set(cv2.CAP_PROP_FPS, 30)
        self._running = True
        consecutive_failures = 0
        while self._running:
            ret, frame = cap.read()
            if ret:
                consecutive_failures = 0
                self.frame_ready.emit(frame.copy())
            else:
                consecutive_failures += 1
                if consecutive_failures >= 30:
                    self.camera_error.emit(f"Камера {self.idx} перестала отвечать")
                    break
            self.msleep(33)
        cap.release()

    def stop(self):
        self._stop_requested = True
        self._running = False
        self.wait(5000)


class DualCamThread(QThread):
    """Continuous feed from two cameras simultaneously."""
    frames_ready = pyqtSignal(object, object)  # left BGR, right BGR
    focal_lengths_ready = pyqtSignal(float, float)  # left fl, right fl
    camera_error = pyqtSignal(str)

    def __init__(self, l_idx: int, r_idx: int, w: int = 640, h: int = 480):
        super().__init__()
        self.l_idx = l_idx
        self.r_idx = r_idx
        self.w = w
        self.h = h
        self._running = False
        self._stop_requested = False

    def _open_camera(self, idx):
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
            if self._stop_requested:
                return None
            cap = cv2.VideoCapture(idx, backend)
            if cap.isOpened():
                return cap
            cap.release()
        return None

    def run(self):
        cap_l = self._open_camera(self.l_idx)
        if self._stop_requested:
            if cap_l:
                cap_l.release()
            return
        cap_r = self._open_camera(self.r_idx)
        if self._stop_requested:
            if cap_l:
                cap_l.release()
            if cap_r:
                cap_r.release()
            return
        if cap_l is None or not cap_l.isOpened():
            self.camera_error.emit(f"Не удалось открыть левую камеру {self.l_idx}")
            if cap_l:
                cap_l.release()
            if cap_r:
                cap_r.release()
            return
        if cap_r is None or not cap_r.isOpened():
            self.camera_error.emit(f"Не удалось открыть правую камеру {self.r_idx}")
            cap_l.release()
            if cap_r:
                cap_r.release()
            return
        for cap in (cap_l, cap_r):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.h)
            cap.set(cv2.CAP_PROP_FPS, 30)
        fl_l = 0
        fl_r = 0
        self.focal_lengths_ready.emit(fl_l, fl_r)

        if self._stop_requested:
            cap_l.release()
            cap_r.release()
            return
        self._running = True
        consecutive_failures = 0
        while self._running:
            retL, fL = cap_l.read()
            retR, fR = cap_r.read()
            if retL and retR:
                consecutive_failures = 0
                self.frames_ready.emit(fL.copy(), fR.copy())
            else:
                consecutive_failures += 1
                if consecutive_failures >= 30:
                    side = "левая" if not retL else "правая"
                    self.camera_error.emit(f"{side.capitalize()} камера перестала отвечать")
                    break
            self.msleep(33)
        cap_l.release()
        cap_r.release()

    def stop(self):
        self._stop_requested = True
        self._running = False
        self.wait(5000)


class CalibThread(QThread):
    """Run full stereo calibration pipeline in background.

    NOTE: does NOT save anything to disk — the caller handles saving.
    """
    progress = pyqtSignal(str, int)  # message, 0–100
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, cb: tuple, sq_m: float, selected_pairs=None):
        super().__init__()
        self.cb = cb
        self.sq_m = sq_m
        self.selected_pairs = selected_pairs  # list[(left_path_str, right_path_str)] or None

    def run(self):
        try:
            result = self._calibrate()
            self.finished.emit(result)
        except Exception:
            self.error.emit(traceback.format_exc())

    def _calibrate(self) -> dict:
        cb = self.cb[::-1]
        sq = self.sq_m
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

        objp = np.zeros((cb[0] * cb[1], 3), np.float32)
        objp[:, :2] = np.mgrid[0:cb[0], 0:cb[1]].T.reshape(-1, 2)
        objp *= sq

        self.progress.emit("Чтение снимков…", 5)

        def _sorted_imgs(side):
            files = sorted(
                (CAPTURE_DIR / side).glob("*.jpg"),
                key=lambda p: int(p.stem.split("_")[1])
            )
            return [cv2.imread(str(f)) for f in files]

        if self.selected_pairs:
            pairs_loaded = [(cv2.imread(lp), cv2.imread(rp)) for lp, rp in self.selected_pairs]
            pairs_loaded = [(l, r) for l, r in pairs_loaded if l is not None and r is not None]
            imgs_l = [p[0] for p in pairs_loaded]
            imgs_r = [p[1] for p in pairs_loaded]
        else:
            imgs_l = _sorted_imgs("left")
            imgs_r = _sorted_imgs("right")

        if not imgs_l:
            raise RuntimeError("Снимки не найдены.")
        self.progress.emit("Дополнение датасета (поворот 180°)…", 10)
        orig_l = imgs_l.copy()
        orig_r = imgs_r.copy()
        imgs_l += [cv2.rotate(img, cv2.ROTATE_180) for img in orig_r]
        imgs_r += [cv2.rotate(img, cv2.ROTATE_180) for img in orig_l]
        total = len(imgs_l)
        obj_pts, pts_l, pts_r = [], [], []

        self.progress.emit("Поиск углов шахматной доски…", 15)
        for i, (iL, iR) in enumerate(zip(imgs_l, imgs_r)):
            pct = 15 + int(30 * i / total)
            self.progress.emit(f"Обнаружение углов: пара {i + 1}/{total}", pct)
            gL = cv2.cvtColor(iL, cv2.COLOR_BGR2GRAY)
            gR = cv2.cvtColor(iR, cv2.COLOR_BGR2GRAY)
            retL, cL = cv2.findChessboardCorners(iL, cb, None)
            retR, cR = cv2.findChessboardCorners(iR, cb, None)
            if retL and retR:
                cv2.cornerSubPix(gL, cL, (11, 11), (-1, -1), criteria)
                cv2.cornerSubPix(gR, cR, (11, 11), (-1, -1), criteria)
                obj_pts.append(objp)
                pts_l.append(cL)
                pts_r.append(cR)

        if len(obj_pts) < 4:
            raise RuntimeError(
                f"Найдено только {len(obj_pts)} валидных пар — нужно минимум 4. "
                "Сделайте больше снимков с хорошо видимой шахматной доской."
            )

        h, w = cv2.cvtColor(imgs_l[0], cv2.COLOR_BGR2GRAY).shape[:2]
        img_sz = cv2.cvtColor(imgs_l[0], cv2.COLOR_BGR2GRAY).shape[::-1]

        self.progress.emit("Калибровка ЛЕВОЙ камеры…", 47)
        _, mtxL, distL, _, _ = cv2.calibrateCamera(obj_pts, pts_l, img_sz, None, None)
        mtxL, _ = cv2.getOptimalNewCameraMatrix(mtxL, distL, (w, h), 1, (w, h))

        self.progress.emit("Калибровка ПРАВОЙ камеры…", 58)
        _, mtxR, distR, _, _ = cv2.calibrateCamera(obj_pts, pts_r, img_sz, None, None)
        mtxR, _ = cv2.getOptimalNewCameraMatrix(mtxR, distR, (w, h), 1, (w, h))

        self.progress.emit("Стереокалибровка…", 70)
        flags = cv2.CALIB_FIX_INTRINSIC
        rms, new_mtxL, distL, new_mtxR, distR, Rot, Trns, _, _ = cv2.stereoCalibrate(
            obj_pts, pts_l, pts_r,
            mtxL, distL, mtxR, distR,
            img_sz, criteria, flags
        )

        self.progress.emit("Вычисление карт ректификации…", 83)
        rl, rr, pl, pr, Q, _, _ = cv2.stereoRectify(
            new_mtxL, distL, new_mtxR, distR, img_sz, Rot, Trns, alpha=0
        )
        mapLx, mapLy = cv2.initUndistortRectifyMap(
            new_mtxL, distL, rl, pl, img_sz, cv2.CV_16SC2)
        mapRx, mapRy = cv2.initUndistortRectifyMap(
            new_mtxR, distR, rr, pr, img_sz, cv2.CV_16SC2)

        self.progress.emit("Калибровка завершена!", 100)
        return {
            "rms": rms,
            "mtxL": new_mtxL, "distL": distL,
            "mtxR": new_mtxR, "distR": distR,
            "Rot": Rot, "Trns": Trns,
            "Q": Q,
            "mapLx": mapLx, "mapLy": mapLy,
            "mapRx": mapRx, "mapRy": mapRy,
            "valid_pairs": len(obj_pts),
        }
