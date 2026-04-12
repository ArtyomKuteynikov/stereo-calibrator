import time

import cv2
import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QGroupBox, QSizePolicy,
)

from config import (
    CAPTURE_DIR, COUNTDOWN_SECS, COOLDOWN_SECS,
    STATE_IDLE, STATE_COUNTDOWN, STATE_COOLDOWN,
)
from threads import DualCamThread
from utils import bgr_to_pixmap, make_ref_checkerboard, make_zone_map_pixmap, analyze_board_placement


class CapturePage(QWidget):
    """Screen 2 — auto-capture checkerboard pairs."""
    run_calibration = pyqtSignal(tuple, float)  # checkerboard, square_m
    back_to_start = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._cam_thread: DualCamThread | None = None
        self._cb = (10, 7)
        self._sq_m = 0.015
        self._target = 30
        self._count = 0
        self._state = STATE_IDLE
        self._t_state = 0.0
        self._last_detect = 0.0
        self._ref_pixmap: QPixmap | None = None
        self._covered_zones: dict = {}
        self._last_corners_l = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(12, 8, 12, 8)

        self.title_lbl = QLabel("Фаза съёмки")
        self.title_lbl.setFont(QFont("Arial", 16, QFont.Bold))
        self.title_lbl.setAlignment(Qt.AlignCenter)
        self.title_lbl.setFixedHeight(30)
        root.addWidget(self.title_lbl)

        ref_group = QGroupBox("Reference: OpenCV Checkerboard Pattern")
        rg_lay = QVBoxLayout(ref_group)
        rg_lay.setContentsMargins(4, 4, 4, 4)
        rg_lay.setSpacing(4)
        self.ref_lbl = QLabel()
        self.ref_lbl.setAlignment(Qt.AlignCenter)
        self.ref_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ref_lbl.setStyleSheet("background:#1a1a1a;")
        rg_lay.addWidget(self.ref_lbl, stretch=1)

        self.focal_lbl = QLabel("Фокусное расстояние  -  Левая: …   Правая: …")
        self.focal_lbl.setAlignment(Qt.AlignCenter)
        self.focal_lbl.setStyleSheet("color:#94a3b8; font-size:11px; padding:2px 0;")
        rg_lay.addWidget(self.focal_lbl, stretch=0)

        root.addWidget(ref_group, stretch=1)

        bottom = QWidget()
        bottom.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bot_lay = QVBoxLayout(bottom)
        bot_lay.setSpacing(4)
        bot_lay.setContentsMargins(0, 0, 0, 0)

        status_row = QHBoxLayout()
        self.detect_lbl = QLabel("Ожидание шахматной доски…")
        self.detect_lbl.setFont(QFont("Arial", 12))
        self.detect_lbl.setStyleSheet("color:#f59e0b; padding:3px 8px;"
                                      "background:#1c1c1c; border-radius:4px;")
        status_row.addWidget(self.detect_lbl, stretch=1)

        self.countdown_lbl = QLabel("")
        self.countdown_lbl.setFont(QFont("Arial", 20, QFont.Bold))
        self.countdown_lbl.setAlignment(Qt.AlignCenter)
        self.countdown_lbl.setFixedWidth(130)
        self.countdown_lbl.setStyleSheet("color:#38bdf8; padding:3px 10px;"
                                         "background:#1c1c1c; border-radius:4px;")
        status_row.addWidget(self.countdown_lbl)
        bot_lay.addLayout(status_row)

        advice_row = QHBoxLayout()
        self.position_lbl = QLabel("Поднесите шахматную доску к камерам")
        self.position_lbl.setFont(QFont("Arial", 11))
        self.position_lbl.setWordWrap(True)
        self.position_lbl.setStyleSheet(
            "color:#fbbf24; padding:3px 8px; background:#1c1c1c; border-radius:4px;"
        )
        advice_row.addWidget(self.position_lbl, stretch=1)

        self.advice_lbl = QLabel("")
        self.advice_lbl.setFont(QFont("Arial", 11, QFont.Bold))
        self.advice_lbl.setWordWrap(True)
        self.advice_lbl.setStyleSheet(
            "color:#4ade80; padding:3px 8px; background:#1c1c1c; border-radius:4px;"
        )
        advice_row.addWidget(self.advice_lbl, stretch=2)
        bot_lay.addLayout(advice_row)

        feeds_row = QHBoxLayout()

        left_box = QGroupBox("Левая камера")
        ll = QVBoxLayout(left_box)
        ll.setContentsMargins(4, 4, 4, 4)
        self.left_feed = QLabel()
        self.left_feed.setFixedSize(240, 135)
        self.left_feed.setAlignment(Qt.AlignCenter)
        self.left_feed.setStyleSheet("background:#111;")
        ll.addWidget(self.left_feed)
        feeds_row.addWidget(left_box)

        right_box = QGroupBox("Правая камера")
        rl = QVBoxLayout(right_box)
        rl.setContentsMargins(4, 4, 4, 4)
        self.right_feed = QLabel()
        self.right_feed.setFixedSize(240, 135)
        self.right_feed.setAlignment(Qt.AlignCenter)
        self.right_feed.setStyleSheet("background:#111;")
        rl.addWidget(self.right_feed)
        feeds_row.addWidget(right_box)

        zone_box = QGroupBox("Покрытие зон")
        zl = QVBoxLayout(zone_box)
        zl.setContentsMargins(6, 4, 6, 4)
        self.zone_map_lbl = QLabel()
        self.zone_map_lbl.setFixedSize(96, 96)
        self.zone_map_lbl.setAlignment(Qt.AlignCenter)
        zl.addWidget(self.zone_map_lbl)
        zl.addStretch()
        zone_legend = QLabel("⬛ нет  🟦 1-2  🟩 3+")
        zone_legend.setStyleSheet("color:#888; font-size:9px;")
        zone_legend.setAlignment(Qt.AlignCenter)
        zl.addWidget(zone_legend)
        feeds_row.addWidget(zone_box)

        bot_lay.addLayout(feeds_row)

        prog_row = QHBoxLayout()
        self.progress_lbl = QLabel("0 / 30")
        self.progress_lbl.setFont(QFont("Arial", 11))
        self.progress_lbl.setFixedWidth(70)
        prog_row.addWidget(self.progress_lbl)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setStyleSheet(
            "QProgressBar{border:1px solid #444;border-radius:3px;background:#222;}"
            "QProgressBar::chunk{background:#22c55e;border-radius:3px;}"
        )
        prog_row.addWidget(self.progress_bar)
        bot_lay.addLayout(prog_row)

        root.addWidget(bottom, stretch=0)

        btn_row = QHBoxLayout()

        self.back_btn = QPushButton("Назад")
        self.back_btn.setMinimumHeight(44)
        self.back_btn.clicked.connect(self._on_back)
        btn_row.addWidget(self.back_btn)

        self.calib_btn = QPushButton("Запустить калибровку")
        self.calib_btn.setEnabled(False)
        self.calib_btn.setMinimumHeight(44)
        self.calib_btn.setFont(QFont("Arial", 13, QFont.Bold))
        self.calib_btn.setStyleSheet(
            "QPushButton{background:#16a34a;color:white;border-radius:6px;}"
            "QPushButton:hover{background:#15803d;}"
            "QPushButton:disabled{background:#555;color:#888;}"
        )
        self.calib_btn.clicked.connect(self._on_run_calib)
        btn_row.addWidget(self.calib_btn)

        root.addLayout(btn_row)

        self._tick_timer = QTimer()
        self._tick_timer.setInterval(200)
        self._tick_timer.timeout.connect(self._tick)

    def setup(self, l_idx: int, r_idx: int, target: int, cb: tuple, sq_m: float = 0.015):
        self._l_idx = l_idx
        self._r_idx = r_idx
        self._cb = cb
        self._sq_m = sq_m
        self._target = target
        self._count = 0
        self._state = STATE_IDLE
        self._t_state = 0.0
        self._last_detect = 0.0
        self._covered_zones = {}
        self._last_corners_l = None

        self.advice_lbl.setText("")
        self.position_lbl.setText("Поднесите шахматную доску к камерам")
        self.zone_map_lbl.setPixmap(make_zone_map_pixmap({}, cell=32))

        self.title_lbl.setText(f"Фаза съёмки  -  цель: {target} фото")
        self.progress_bar.setMaximum(target)
        self.progress_bar.setValue(0)
        self.progress_lbl.setText(f"0 / {target} фото")
        self.calib_btn.setEnabled(False)
        self._set_detect_status(False, False)
        self.countdown_lbl.setText("")

        ref = make_ref_checkerboard(cb[0] + 1, cb[1] + 1)
        rgb = cv2.cvtColor(ref, cv2.COLOR_BGR2RGB)
        self._ref_pixmap = QPixmap.fromImage(
            QImage(rgb.data.tobytes(),
                   ref.shape[1], ref.shape[0], ref.shape[2] * ref.shape[1],
                   QImage.Format_RGB888)
        )
        QTimer.singleShot(50, self._resize_ref)

        self._cam_thread = DualCamThread(l_idx, r_idx)
        self._cam_thread.frames_ready.connect(self._on_frames)
        self._cam_thread.focal_lengths_ready.connect(self._on_focal_lengths)
        self._cam_thread.camera_error.connect(
            lambda msg: self.detect_lbl.setText(f"Ошибка камеры: {msg}"))
        self._cam_thread.start()
        self._tick_timer.start()

    def stop(self):
        self._tick_timer.stop()
        if self._cam_thread:
            self._cam_thread.stop()
            self._cam_thread = None

    def restart_cameras(self):
        """Restart the dual-camera thread after returning from photo selection."""
        if self._cam_thread:
            self._cam_thread.stop()
            self._cam_thread = None
        self._state = STATE_IDLE
        self._t_state = 0.0
        self._last_detect = 0.0
        self.countdown_lbl.setText("")
        self._set_detect_status(False, False)
        self._cam_thread = DualCamThread(self._l_idx, self._r_idx)
        self._cam_thread.frames_ready.connect(self._on_frames)
        self._cam_thread.focal_lengths_ready.connect(self._on_focal_lengths)
        self._cam_thread.camera_error.connect(
            lambda msg: self.detect_lbl.setText(f"Ошибка камеры: {msg}"))
        self._cam_thread.start()
        self._tick_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_ref()

    def _resize_ref(self):
        if self._ref_pixmap is None:
            return
        w = self.ref_lbl.width()
        h = self.ref_lbl.height()
        if w < 20 or h < 20:
            QTimer.singleShot(100, self._resize_ref)
            return
        self.ref_lbl.setPixmap(
            self._ref_pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _on_focal_lengths(self, fl_l: float, fl_r: float):
        def _fmt(v):
            return f"{v:.1f} мм" if v > 0 else "н/д"

        self.focal_lbl.setText(
            f"Фокусное расстояние  -  Левая: {_fmt(fl_l)}    Правая: {_fmt(fl_r)}"
        )

    def _on_frames(self, fL: np.ndarray, fR: np.ndarray):
        now = time.time()
        if now - self._last_detect < 0.20:
            self.left_feed.setPixmap(bgr_to_pixmap(fL, 240, 135))
            self.right_feed.setPixmap(bgr_to_pixmap(fR, 240, 135))
            return
        self._last_detect = now

        flags = cv2.CALIB_CB_FAST_CHECK
        CB = (self._cb[0], self._cb[1])
        retL, cL = cv2.findChessboardCorners(fL, CB, None, flags=flags)
        retR, cR = cv2.findChessboardCorners(fR, CB, None, flags=flags)

        disp_l = fL.copy()
        disp_r = fR.copy()
        if retL and cL is not None:
            cv2.drawChessboardCorners(disp_l, CB, cL, retL)
        if retR and cR is not None:
            cv2.drawChessboardCorners(disp_r, CB, cR, retR)

        self.left_feed.setPixmap(bgr_to_pixmap(disp_l, 240, 135))
        self.right_feed.setPixmap(bgr_to_pixmap(disp_r, 240, 135))
        self._set_detect_status(retL, retR)

        if retL and cL is not None and retR and cR is not None:
            self._last_corners_l = cL
            try:
                zone, status, advice = analyze_board_placement(
                    cL, fL.shape, cR, fR.shape, CB, self._covered_zones
                )
                self._last_zone = zone
                self.position_lbl.setText(status)
                self.advice_lbl.setText(advice)
            except Exception:
                pass
        else:
            self._last_corners_l = None
            self.position_lbl.setText("Доска не обнаружена")
            self.advice_lbl.setText("")

        both = retL and retR
        self._advance_state(both, fL, fR)
        time.sleep(0.05)

    def _advance_state(self, both: bool, fL: np.ndarray, fR: np.ndarray):
        now = time.time()

        if self._state == STATE_IDLE:
            if both:
                self._state = STATE_COUNTDOWN
                self._t_state = now

        elif self._state == STATE_COUNTDOWN:
            if not both:
                self._state = STATE_IDLE
                self.countdown_lbl.setText("")
            elif now - self._t_state >= COUNTDOWN_SECS:
                self._capture(fL, fR)
                self._state = STATE_COOLDOWN
                self._t_state = now

        elif self._state == STATE_COOLDOWN:
            if now - self._t_state >= COOLDOWN_SECS:
                self._state = STATE_IDLE
                self.countdown_lbl.setText("")

    def _capture(self, fL: np.ndarray, fR: np.ndarray):
        cv2.imwrite(str(CAPTURE_DIR / "left" / f"image_{self._count}.jpg"), fL)
        cv2.imwrite(str(CAPTURE_DIR / "right" / f"image_{self._count}.jpg"), fR)
        self._count += 1
        self.progress_bar.setValue(self._count)
        self.progress_lbl.setText(f"{self._count} / {self._target} фото")

        if self._last_corners_l is not None and hasattr(self, '_last_zone'):
            try:
                zone = self._last_zone
                self._covered_zones[zone] = self._covered_zones.get(zone, 0) + 1
                self.zone_map_lbl.setPixmap(make_zone_map_pixmap(self._covered_zones, cell=32))
            except Exception:
                pass

        if self._count >= self._target:
            self.calib_btn.setEnabled(True)
            self.detect_lbl.setText("Цель достигнута! Нажмите «Запустить калибровку»")
            self.detect_lbl.setStyleSheet(
                "color:#22c55e; padding:4px 8px;"
                "background:#1c1c1c; border-radius:4px;"
            )

    def _tick(self):
        now = time.time()
        if self._state == STATE_COUNTDOWN:
            remaining = COUNTDOWN_SECS - (now - self._t_state)
            self.countdown_lbl.setText(f"📸 {max(0, remaining):.1f}s")
        elif self._state == STATE_COOLDOWN:
            remaining = COOLDOWN_SECS - (now - self._t_state)
            if remaining > 0:
                self.countdown_lbl.setText(f"↺ {remaining:.0f}s")
            else:
                self.countdown_lbl.setText("")
        else:
            self.countdown_lbl.setText("")

    def _set_detect_status(self, left_ok: bool, right_ok: bool):
        if self._count >= self._target:
            return
        both = left_ok and right_ok
        icons = (
            ("✔" if left_ok else "✗") + " Лев.",
            ("✔" if right_ok else "✗") + " Пр.",
        )
        if both:
            txt = f"{icons[0]}  -  {icons[1]} - не двигайте…"
            style = "color:#22c55e;"
        elif left_ok or right_ok:
            txt = f"{icons[0]}  -  {icons[1]}"
            style = "color:#f59e0b;"
        else:
            txt = ("Ожидание шахматной доски…\n"
                   "Совет: уменьшите яркость экрана или перейдите в более освещённое место")
            style = "color:#f59e0b;"
        self.detect_lbl.setText(txt)
        self.detect_lbl.setStyleSheet(
            style + " padding:4px 8px; background:#1c1c1c; border-radius:4px;"
        )

    def _on_back(self):
        self.stop()
        self.back_to_start.emit()

    def _on_run_calib(self):
        self.stop()
        self.run_calibration.emit(self._cb, self._sq_m)
