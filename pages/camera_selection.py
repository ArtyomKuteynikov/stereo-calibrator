from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QComboBox,
    QPushButton, QSpinBox, QDoubleSpinBox, QGroupBox, QMessageBox,
)

from config import CAPTURE_DIR
from threads import SingleCamThread, CameraDetectThread
from utils import bgr_to_pixmap


class CameraSelectionPage(QWidget):
    """Screen 1 — pick cameras, set parameters, start capture."""
    start_capture = pyqtSignal(int, int, int, tuple, float)  # l, r, target, cb, sq_m
    calibrate_existing = pyqtSignal(tuple, float)  # cb, sq_m

    def __init__(self):
        super().__init__()
        self._cameras: list = []
        self._left_thread: SingleCamThread | None = None
        self._right_thread: SingleCamThread | None = None
        self._left_loaded = False
        self._right_loaded = False
        self._spinner_chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        self._spinner_idx = 0
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Калибровка стереокамеры")
        title.setFont(QFont("Arial", 22, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        sg = QGroupBox("Настройки калибровки")
        sl = QGridLayout(sg)
        sl.setColumnStretch(1, 1)
        sl.setColumnStretch(3, 1)

        sl.addWidget(QLabel("Кол-во фото:"), 0, 0)
        self.target_spin = QSpinBox()
        self.target_spin.setRange(5, 300)
        self.target_spin.setValue(30)
        sl.addWidget(self.target_spin, 0, 1)

        sl.addWidget(QLabel("Клетки шахматной доски (ширина):"), 1, 0)
        self.cb_cols = QSpinBox()
        self.cb_cols.setRange(3, 25)
        self.cb_cols.setValue(8)
        self.cb_cols.setToolTip("Количество клеток по ширине — OpenCV ищет (N-1) внутренних углов")
        sl.addWidget(self.cb_cols, 1, 1)

        sl.addWidget(QLabel("Клетки шахматной доски (высота):"), 1, 2)
        self.cb_rows = QSpinBox()
        self.cb_rows.setRange(3, 25)
        self.cb_rows.setValue(5)
        self.cb_rows.setToolTip("Количество клеток по высоте — OpenCV ищет (N-1) внутренних углов")
        sl.addWidget(self.cb_rows, 1, 3)

        sl.addWidget(QLabel("Размер клетки (мм):"), 2, 0)
        self.sq_spin = QDoubleSpinBox()
        self.sq_spin.setRange(1.0, 500.0)
        self.sq_spin.setValue(15.0)
        self.sq_spin.setDecimals(1)
        self.sq_spin.setSuffix(" мм")
        sl.addWidget(self.sq_spin, 2, 1)

        root.addWidget(sg)

        cg = QGroupBox("Выбор камер")
        cl = QGridLayout(cg)

        cl.addWidget(QLabel("Левая камера:"), 0, 0, Qt.AlignRight)
        self.left_combo = QComboBox()
        self.left_combo.setMinimumWidth(150)
        self.left_combo.currentIndexChanged.connect(self._on_left_changed)
        cl.addWidget(self.left_combo, 0, 1)

        cl.addWidget(QLabel("Правая камера:"), 0, 2, Qt.AlignRight)
        self.right_combo = QComboBox()
        self.right_combo.setMinimumWidth(150)
        self.right_combo.currentIndexChanged.connect(self._on_right_changed)
        cl.addWidget(self.right_combo, 0, 3)

        def _preview_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedSize(340, 255)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("background:#1a1a2e; color:#aaa; border:1px solid #444; border-radius:4px;")
            return lbl

        self.left_prev = _preview_label("Левая камера\n(не подключена)")
        self.right_prev = _preview_label("Правая камера\n(не подключена)")
        cl.addWidget(self.left_prev, 1, 0, 1, 2, Qt.AlignCenter)
        cl.addWidget(self.right_prev, 1, 2, 1, 2, Qt.AlignCenter)

        root.addWidget(cg)

        self.status_lbl = QLabel("Обнаружение камер, пожалуйста подождите…")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setStyleSheet("color: #888; font-style: italic;")
        root.addWidget(self.status_lbl)

        self.existing_btn = QPushButton("Калибровать по существующим снимкам  ▶")
        self.existing_btn.setMinimumHeight(40)
        self.existing_btn.setStyleSheet(
            "QPushButton{background:#7c3aed;color:white;border-radius:6px;}"
            "QPushButton:hover{background:#6d28d9;}"
            "QPushButton:disabled{background:#555;color:#888;}"
        )
        self.existing_btn.clicked.connect(self._on_calibrate_existing)
        self._update_existing_btn()
        root.addWidget(self.existing_btn)

        self.start_btn = QPushButton("Начать съёмку")
        self.start_btn.setEnabled(False)
        self.start_btn.setFont(QFont("Arial", 14, QFont.Bold))
        self.start_btn.setMinimumHeight(52)
        self.start_btn.setStyleSheet(
            "QPushButton{background:#2563eb;color:white;border-radius:6px;}"
            "QPushButton:hover{background:#1d4ed8;}"
            "QPushButton:disabled{background:#555;color:#888;}"
        )
        self.start_btn.clicked.connect(self._on_start)
        root.addWidget(self.start_btn)

        self._spinner_timer = QTimer()
        self._spinner_timer.setInterval(100)
        self._spinner_timer.timeout.connect(self._spin_tick)

        self._prev_spinner_timer = QTimer()
        self._prev_spinner_timer.setInterval(120)
        self._prev_spinner_timer.timeout.connect(self._prev_spin_tick)

    def _spin_tick(self):
        self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner_chars)
        ch = self._spinner_chars[self._spinner_idx]
        self.status_lbl.setText(f"{ch}  Обнаружение камер, пожалуйста подождите…")

    def _prev_spin_tick(self):
        self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner_chars)
        ch = self._spinner_chars[self._spinner_idx]
        if not self._left_loaded:
            self.left_prev.setText(f"{ch}  Загрузка\nлевой камеры…")
        if not self._right_loaded:
            self.right_prev.setText(f"{ch}  Загрузка\nправой камеры…")
        if self._left_loaded and self._right_loaded:
            self._prev_spinner_timer.stop()

    def detect_cameras(self):
        self._spinner_idx = 0
        self._spinner_timer.start()
        self.start_btn.setEnabled(False)
        self._detect_thread = CameraDetectThread()
        self._detect_thread.cameras_found.connect(self._on_cameras_found)
        self._detect_thread.start()

    def _on_cameras_found(self, cameras: list):
        self._spinner_timer.stop()
        self._cameras = cameras
        for combo in (self.left_combo, self.right_combo):
            combo.blockSignals(True)
            combo.clear()
            for idx, name in cameras:
                combo.addItem(name, idx)
            combo.blockSignals(False)

        if len(cameras) == 0:
            self.status_lbl.setText("Камеры не найдены. Подключите камеры и перезапустите.")
            return

        if len(cameras) >= 2:
            self.right_combo.setCurrentIndex(1)

        self.status_lbl.setText(f"Найдено камер: {len(cameras)}. Выберите левую и правую.")
        self.start_btn.setEnabled(len(cameras) >= 2)

        self._start_left_preview(cameras[0][0])
        if len(cameras) >= 2:
            self._start_right_preview(cameras[1][0])

    def _start_left_preview(self, idx: int):
        if self._left_thread:
            self._left_thread.stop()
        self._left_loaded = False
        self._set_nav_enabled(False)
        self.left_prev.setText("⠋  Загрузка\nлевой камеры…")
        self._prev_spinner_timer.start()
        self._left_thread = SingleCamThread(idx)
        self._left_thread.frame_ready.connect(self._show_left)
        self._left_thread.camera_error.connect(
            lambda msg: (self.left_prev.setText(f"Ошибка камеры:\n{msg}"),
                         self._check_cameras_ready()))
        self._left_thread.start()

    def _start_right_preview(self, idx: int):
        if self._right_thread:
            self._right_thread.stop()
        self._right_loaded = False
        self._set_nav_enabled(False)
        self.right_prev.setText("⠋  Загрузка\nправой камеры…")
        self._prev_spinner_timer.start()
        self._right_thread = SingleCamThread(idx)
        self._right_thread.frame_ready.connect(self._show_right)
        self._right_thread.camera_error.connect(
            lambda msg: (self.right_prev.setText(f"Ошибка камеры:\n{msg}"),
                         self._check_cameras_ready()))
        self._right_thread.start()

    def _show_left(self, frame):
        self._left_loaded = True
        self.left_prev.setPixmap(bgr_to_pixmap(frame, 340, 255))
        self._check_cameras_ready()

    def _show_right(self, frame):
        self._right_loaded = True
        self.right_prev.setPixmap(bgr_to_pixmap(frame, 340, 255))
        self._check_cameras_ready()

    def _set_nav_enabled(self, enabled: bool):
        if not enabled:
            self.start_btn.setEnabled(False)
            self.existing_btn.setEnabled(False)

    def _check_cameras_ready(self):
        if self._left_loaded and self._right_loaded:
            if len(self._cameras) >= 2:
                self.start_btn.setEnabled(True)
            self._update_existing_btn()

    def _on_left_changed(self, _):
        idx = self.left_combo.currentData()
        if idx is not None:
            self._start_left_preview(idx)

    def _on_right_changed(self, _):
        idx = self.right_combo.currentData()
        if idx is not None:
            self._start_right_preview(idx)

    def stop_previews(self):
        for t in (self._left_thread, self._right_thread):
            if t:
                t.stop()
        self._left_thread = None
        self._right_thread = None

    def _update_existing_btn(self):
        left_count = len(list((CAPTURE_DIR / "left").glob("*.jpg"))) if (CAPTURE_DIR / "left").exists() else 0
        right_count = len(list((CAPTURE_DIR / "right").glob("*.jpg"))) if (CAPTURE_DIR / "right").exists() else 0
        n = min(left_count, right_count)
        if n >= 4:
            self.existing_btn.setEnabled(True)
            self.existing_btn.setText(f"Калибровать по существующим снимкам  ({n} пар)")
        else:
            self.existing_btn.setEnabled(False)
            self.existing_btn.setText("Калибровать по существующим снимкам  (нет снимков)")

    def _on_calibrate_existing(self):
        sq_cols = self.cb_cols.value()
        sq_rows = self.cb_rows.value()
        cb_opencv = (sq_cols - 1, sq_rows - 1)
        sq_m = self.sq_spin.value() / 1000.0
        self.stop_previews()
        self.calibrate_existing.emit(cb_opencv, sq_m)

    def _on_start(self):
        l_idx = self.left_combo.currentData()
        r_idx = self.right_combo.currentData()
        if l_idx == r_idx:
            QMessageBox.warning(self, "Одна камера", "Левая и правая камеры должны быть разными устройствами.")
            return
        target = self.target_spin.value()
        sq_cols = self.cb_cols.value()
        sq_rows = self.cb_rows.value()
        cb_opencv = (sq_cols - 1, sq_rows - 1)
        sq_m = self.sq_spin.value() / 1000.0
        self.stop_previews()
        self.start_capture.emit(l_idx, r_idx, target, cb_opencv, sq_m)
