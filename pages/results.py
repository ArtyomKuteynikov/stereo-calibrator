from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QGroupBox, QTextEdit, QMessageBox, QFileDialog,
    QLineEdit,
)

from threads import CalibThread, DualCamThread
from utils import bgr_to_pixmap, clear_capture_dirs


class ResultsPage(QWidget):
    """Screen 3 — progress bar, params display, live rectified preview."""
    recalibrate = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._calib_thread: CalibThread | None = None
        self._cam_thread: DualCamThread | None = None
        self._result: dict | None = None
        self._l_idx = 0
        self._r_idx = 1
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        title = QLabel("Результаты калибровки")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        from PyQt5.QtCore import Qt
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        prog_box = QGroupBox("Прогресс калибровки")
        pb_lay = QVBoxLayout(prog_box)
        self.calib_status = QLabel("Запуск…")
        self.calib_status.setAlignment(Qt.AlignCenter)
        pb_lay.addWidget(self.calib_status)
        self.calib_bar = QProgressBar()
        self.calib_bar.setMinimumHeight(18)
        self.calib_bar.setStyleSheet(
            "QProgressBar{border:1px solid #444;border-radius:4px;background:#222;}"
            "QProgressBar::chunk{background:#3b82f6;border-radius:4px;}"
        )
        pb_lay.addWidget(self.calib_bar)
        self.prog_box = prog_box
        root.addWidget(prog_box)

        params_group = QGroupBox("Параметры калибровки")
        pl = QVBoxLayout(params_group)
        self.params_text = QTextEdit()
        self.params_text.setReadOnly(True)
        self.params_text.setFont(QFont("Consolas", 10))
        self.params_text.setMaximumHeight(200)
        pl.addWidget(self.params_text)
        self.params_group = params_group
        self.params_group.setVisible(False)
        root.addWidget(params_group)

        feeds_group = QGroupBox("Предпросмотр — ректифицированное стерео  "
                                "(горизонтальные линии проверяют эпиполярность)")
        fl = QHBoxLayout(feeds_group)

        self.left_rect = QLabel("Левая ректиф.")
        self.right_rect = QLabel("Правая ректиф.")
        for lbl in (self.left_rect, self.right_rect):
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setMinimumSize(360, 270)
            lbl.setStyleSheet("background:#111; color:#555;")
        fl.addWidget(self.left_rect)
        fl.addWidget(self.right_rect)

        self.feeds_group = feeds_group
        self.feeds_group.setVisible(False)
        root.addWidget(feeds_group, stretch=2)

        save_group = QGroupBox("Сохранение результата")
        sg_lay = QVBoxLayout(save_group)
        sg_lay.setSpacing(6)

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("Имя файла:"))
        self.filename_edit = QLineEdit("stereo_calib_data")
        self.filename_edit.setPlaceholderText("имя без расширения")
        self.filename_edit.setMinimumWidth(200)
        file_row.addWidget(self.filename_edit, stretch=1)
        file_row.addWidget(QLabel(".npz"))
        sg_lay.addLayout(file_row)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Папка:"))
        self.dir_lbl = QLabel(str(Path.home()))
        self.dir_lbl.setStyleSheet("color:#94a3b8; font-size:11px;")
        self.dir_lbl.setWordWrap(True)
        dir_row.addWidget(self.dir_lbl, stretch=1)
        self._save_dir = Path.home()

        browse_btn = QPushButton("Обзор…")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._on_browse)
        dir_row.addWidget(browse_btn)
        sg_lay.addLayout(dir_row)

        btn_row = QHBoxLayout()

        self.recalib_btn = QPushButton("← Перекалибровать")
        self.recalib_btn.setMinimumHeight(44)
        self.recalib_btn.setFont(QFont("Arial", 12))
        self.recalib_btn.clicked.connect(self._on_recalib)
        btn_row.addWidget(self.recalib_btn)

        self.save_btn = QPushButton("Сохранить результат")
        self.save_btn.setMinimumHeight(44)
        self.save_btn.setEnabled(False)
        self.save_btn.setFont(QFont("Arial", 12, QFont.Bold))
        self.save_btn.setStyleSheet(
            "QPushButton{background:#2563eb;color:white;border-radius:6px;}"
            "QPushButton:hover{background:#1d4ed8;}"
            "QPushButton:disabled{background:#555;color:#888;}"
        )
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        self.delete_btn = QPushButton("Удалить снимки")
        self.delete_btn.setMinimumHeight(44)
        self.delete_btn.setEnabled(False)
        self.delete_btn.setFont(QFont("Arial", 12))
        self.delete_btn.setStyleSheet(
            "QPushButton{background:#b45309;color:white;border-radius:6px;}"
            "QPushButton:hover{background:#92400e;}"
            "QPushButton:disabled{background:#555;color:#888;}"
        )
        self.delete_btn.clicked.connect(self._on_delete_photos)
        btn_row.addWidget(self.delete_btn)

        sg_lay.addLayout(btn_row)

        self.save_lbl = QLabel("")
        self.save_lbl.setAlignment(Qt.AlignCenter)
        self.save_lbl.setStyleSheet("color:#22c55e; font-style:italic; font-size:11px;")
        sg_lay.addWidget(self.save_lbl)

        root.addWidget(save_group)

    def start_calibration(self, l_idx: int, r_idx: int, cb: tuple, sq_m: float,
                          selected_pairs=None):
        self.stop()
        self._l_idx = l_idx
        self._r_idx = r_idx
        self._result = None
        self.params_group.setVisible(False)
        self.feeds_group.setVisible(False)
        self.prog_box.setVisible(True)
        self.calib_bar.setValue(0)
        self.calib_status.setText("Инициализация…")
        self.save_lbl.setText("")
        self.save_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)

        self._calib_thread = CalibThread(cb, sq_m, selected_pairs)
        self._calib_thread.progress.connect(self._on_progress)
        self._calib_thread.finished.connect(self._on_finished)
        self._calib_thread.error.connect(self._on_error)
        self._calib_thread.start()

    def stop(self):
        if self._cam_thread:
            self._cam_thread.stop()
            self._cam_thread = None

    def _on_progress(self, msg: str, pct: int):
        self.calib_status.setText(msg)
        self.calib_bar.setValue(pct)

    def _on_finished(self, data: dict):
        self.prog_box.setVisible(False)
        self._result = data
        self._show_params(data)
        self.params_group.setVisible(True)
        self.feeds_group.setVisible(True)
        self.save_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self._start_rectified_preview()

    def _on_error(self, msg: str):
        self.calib_status.setText("ОШИБКА — подробности ниже")
        self.params_text.setPlainText(msg)
        self.params_group.setVisible(True)

    def _on_browse(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Выберите папку для сохранения", str(self._save_dir)
        )
        if directory:
            self._save_dir = Path(directory)
            self.dir_lbl.setText(str(self._save_dir))

    def _on_save(self):
        if self._result is None:
            return

        name = self.filename_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Пустое имя", "Введите имя файла.")
            return

        if name.lower().endswith(".npz"):
            name = name[:-4]

        out_path = self._save_dir / f"{name}.npz"

        if out_path.exists():
            reply = QMessageBox.question(
                self, "Файл существует",
                f"Файл «{out_path.name}» уже существует.\nПерезаписать?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        d = self._result
        try:
            np.savez(
                str(out_path),
                Q=d["Q"],
                mapLx=d["mapLx"], mapLy=d["mapLy"],
                mapRx=d["mapRx"], mapRy=d["mapRy"],
            )
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения", str(e))
            return

        self.save_lbl.setText(f"Сохранено → {out_path}")

        text = self.params_text.toPlainText()
        updated = "\n".join(
            line if not line.startswith("Output saved to:")
            else f"Output saved to: {out_path}"
            for line in text.splitlines()
        )
        self.params_text.setPlainText(updated)

    def _on_delete_photos(self):
        reply = QMessageBox.question(
            self,
            "Удалить снимки",
            "Удалить все снимки из папки images/?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            clear_capture_dirs()
            self.delete_btn.setEnabled(False)
            self.save_lbl.setText(
                self.save_lbl.text() + "  |  Снимки удалены"
                if self.save_lbl.text()
                else "Снимки удалены"
            )

    def _on_recalib(self):
        self.stop()
        self.recalibrate.emit()

    def _show_params(self, d: dict):
        baseline_mm = np.linalg.norm(d["Trns"]) * 1000
        lines = [
            f"RMS reprojection error : {d['rms']:.4f} px",
            f"Valid calibration pairs: {d['valid_pairs']}",
            f"Baseline               : {baseline_mm:.2f} mm",
            "",
            "Left camera matrix:",
            self._fmt_mat(d["mtxL"]),
            "Left distortion coeffs : " + np.array2string(d["distL"].ravel(), precision=5),
            "",
            "Right camera matrix:",
            self._fmt_mat(d["mtxR"]),
            "Right distortion coeffs: " + np.array2string(d["distR"].ravel(), precision=5),
            "",
            "Rotation matrix R:",
            self._fmt_mat(d["Rot"]),
            "Translation vector T (mm):",
            "  " + np.array2string(d["Trns"].ravel() * 1000, precision=2),
            "",
            "Output saved to: (не сохранено)",
        ]
        self.params_text.setPlainText("\n".join(lines))

    @staticmethod
    def _fmt_mat(m: np.ndarray) -> str:
        rows = []
        for r in m:
            rows.append("  [" + "  ".join(f"{v:12.5f}" for v in r) + "]")
        return "\n".join(rows)

    def _start_rectified_preview(self):
        self._cam_thread = DualCamThread(self._l_idx, self._r_idx)
        self._cam_thread.frames_ready.connect(self._on_rect_frames)
        self._cam_thread.camera_error.connect(
            lambda msg: self.calib_status.setText(f"Ошибка камеры: {msg}"))
        self._cam_thread.start()

    def _on_rect_frames(self, fL, fR):
        if self._result is None:
            return
        m = self._result
        rL = cv2.remap(fL, m["mapLx"], m["mapLy"], cv2.INTER_LINEAR)
        rR = cv2.remap(fR, m["mapRx"], m["mapRy"], cv2.INTER_LINEAR)

        h = rL.shape[0]
        for y in range(0, h, 40):
            cv2.line(rL, (0, y), (rL.shape[1], y), (0, 255, 0), 1)
            cv2.line(rR, (0, y), (rR.shape[1], y), (0, 255, 0), 1)

        w = self.left_rect.width()
        hh = self.left_rect.height()
        self.left_rect.setPixmap(bgr_to_pixmap(rL, w, hh))
        self.right_rect.setPixmap(bgr_to_pixmap(rR, w, hh))
