from PyQt5.QtWidgets import QMainWindow, QStackedWidget

from pages.camera_selection import CameraSelectionPage
from pages.capture import CapturePage
from pages.photo_selection import PhotoSelectionPage
from pages.results import ResultsPage
from utils import ensure_dirs


class CalibrationApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Калибровка стереокамеры")
        self.setMinimumSize(800, 680)
        self.resize(960, 760)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.sel_page = CameraSelectionPage()
        self.cap_page = CapturePage()
        self.res_page = ResultsPage()
        self.photo_page = PhotoSelectionPage()

        self.stack.addWidget(self.sel_page)  # 0
        self.stack.addWidget(self.cap_page)  # 1
        self.stack.addWidget(self.res_page)  # 2
        self.stack.addWidget(self.photo_page)  # 3

        self._pending_cb: tuple = (7, 4)
        self._pending_sq_m: float = 0.015
        self._photo_source: str = "selection"  # "capture" or "selection"

        self.sel_page.start_capture.connect(self._go_capture)
        self.sel_page.calibrate_existing.connect(self._go_calibrate_existing)
        self.cap_page.run_calibration.connect(self._go_photo_selection_from_capture)
        self.cap_page.back_to_start.connect(self._go_selection)
        self.res_page.recalibrate.connect(self._go_selection)
        self.photo_page.proceed.connect(self._go_calibrate)
        self.photo_page.go_back.connect(self._photo_go_back)

        self.sel_page.detect_cameras()

    def _go_capture(self, l_idx, r_idx, target, cb, sq_m):
        ensure_dirs()
        self.cap_page.setup(l_idx, r_idx, target, cb, sq_m)
        self.stack.setCurrentIndex(1)

    def _go_calibrate_existing(self, cb, sq_m):
        self._pending_cb = cb
        self._pending_sq_m = sq_m
        self._photo_source = "selection"
        self.sel_page._update_existing_btn()
        self.photo_page.load_images()
        self.stack.setCurrentIndex(3)

    def _go_photo_selection_from_capture(self, cb, sq_m):
        self._pending_cb = cb
        self._pending_sq_m = sq_m
        self._photo_source = "capture"
        self.photo_page.load_images()
        self.stack.setCurrentIndex(3)

    def _go_calibrate(self, selected_pairs: list):
        l_data = self.sel_page.left_combo.currentData()
        r_data = self.sel_page.right_combo.currentData()
        l_idx = l_data if l_data is not None else 0
        r_idx = r_data if r_data is not None else 1
        self.res_page.start_calibration(
            l_idx, r_idx, self._pending_cb, self._pending_sq_m, selected_pairs
        )
        self.stack.setCurrentIndex(2)

    def _photo_go_back(self):
        if self._photo_source == "capture":
            self.stack.setCurrentIndex(1)
            self.cap_page.restart_cameras()
        else:
            self.sel_page.detect_cameras()
            self.sel_page._update_existing_btn()
            self.stack.setCurrentIndex(0)

    def _go_selection(self):
        self.cap_page.stop()
        self.res_page.stop()
        self.sel_page.detect_cameras()
        self.sel_page._update_existing_btn()
        self.stack.setCurrentIndex(0)

    def closeEvent(self, event):
        self.sel_page.stop_previews()
        self.cap_page.stop()
        self.res_page.stop()
        super().closeEvent(event)
