from pathlib import Path

import cv2
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QGridLayout, QFrame, QCheckBox,
)

from config import CAPTURE_DIR
from utils import bgr_to_pixmap


class PhotoSelectionPage(QWidget):
    """Screen 2.5 — review captured pairs, tick/untick before calibration."""
    proceed = pyqtSignal(list)
    go_back = pyqtSignal()

    THUMB_W = 218
    THUMB_H = 163

    def __init__(self):
        super().__init__()
        self._pairs: list = []
        self._checkboxes: list = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(14, 14, 14, 14)

        title = QLabel("Выбор снимков для калибровки")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        toolbar = QHBoxLayout()

        self.count_lbl = QLabel("Выбрано: 0 / 0")
        self.count_lbl.setStyleSheet("font-size:12px; color:#94a3b8;")
        toolbar.addWidget(self.count_lbl)
        toolbar.addStretch()

        sel_btn = QPushButton("Выбрать все")
        sel_btn.setFixedHeight(30)
        sel_btn.clicked.connect(self._select_all)
        toolbar.addWidget(sel_btn)

        desel_btn = QPushButton("Снять все")
        desel_btn.setFixedHeight(30)
        desel_btn.clicked.connect(self._deselect_all)
        toolbar.addWidget(desel_btn)

        root.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea{border:1px solid #333; border-radius:4px;}")

        self.grid_widget = QWidget()
        self.grid_widget.setStyleSheet("background:#12121f;")
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)

        self.scroll.setWidget(self.grid_widget)
        root.addWidget(self.scroll, stretch=1)

        btn_row = QHBoxLayout()

        self.back_btn = QPushButton("← Назад")
        self.back_btn.setMinimumHeight(44)
        self.back_btn.clicked.connect(self.go_back.emit)
        btn_row.addWidget(self.back_btn)

        self.proceed_btn = QPushButton("Начать калибровку  ▶")
        self.proceed_btn.setEnabled(False)
        self.proceed_btn.setMinimumHeight(44)
        self.proceed_btn.setFont(QFont("Arial", 13, QFont.Bold))
        self.proceed_btn.setStyleSheet(
            "QPushButton{background:#16a34a;color:white;border-radius:6px;}"
            "QPushButton:hover{background:#15803d;}"
            "QPushButton:disabled{background:#555;color:#888;}"
        )
        self.proceed_btn.clicked.connect(self._on_proceed)
        btn_row.addWidget(self.proceed_btn)

        root.addLayout(btn_row)

    def load_images(self):
        """Reload left/right pairs from CAPTURE_DIR and rebuild the grid."""
        self._checkboxes.clear()
        self._pairs.clear()
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        left_dir = CAPTURE_DIR / "left"
        right_dir = CAPTURE_DIR / "right"

        def _sorted(d):
            try:
                return sorted(d.glob("*.jpg"), key=lambda p: int(p.stem.split("_")[1]))
            except Exception:
                return sorted(d.glob("*.jpg"))

        lefts = _sorted(left_dir) if left_dir.exists() else []
        rights = _sorted(right_dir) if right_dir.exists() else []
        self._pairs = list(zip(lefts, rights))

        COLS = 2
        for i, (lp, rp) in enumerate(self._pairs):
            cell = self._make_pair_cell(i, lp, rp)
            self.grid_layout.addWidget(cell, i // COLS, i % COLS)

        if len(self._pairs) % COLS:
            spacer = QWidget()
            spacer.setStyleSheet("background:transparent;")
            row = len(self._pairs) // COLS
            self.grid_layout.addWidget(spacer, row, 1)

        self._update_count()

    def _make_pair_cell(self, idx: int, left_path: Path, right_path: Path) -> QFrame:
        cell = QFrame()
        cell.setFrameShape(QFrame.StyledPanel)
        cell.setStyleSheet(
            "QFrame{background:#1e1e2e; border:1px solid #2d2d44; border-radius:6px;}"
        )
        lay = QVBoxLayout(cell)
        lay.setSpacing(6)
        lay.setContentsMargins(8, 8, 8, 8)

        cb = QCheckBox(f"  Пара {idx + 1}")
        cb.setChecked(True)
        cb.setFont(QFont("Arial", 10, QFont.Bold))
        cb.setStyleSheet("QCheckBox{color:#e2e8f0;} QCheckBox::indicator{width:16px;height:16px;}")
        cb.stateChanged.connect(self._on_check_changed)
        self._checkboxes.append(cb)
        lay.addWidget(cb)

        imgs_row = QHBoxLayout()
        imgs_row.setSpacing(6)

        for path, side_lbl in ((left_path, "Левая"), (right_path, "Правая")):
            col = QVBoxLayout()
            col.setSpacing(2)

            img_lbl = QLabel()
            img_lbl.setFixedSize(self.THUMB_W, self.THUMB_H)
            img_lbl.setAlignment(Qt.AlignCenter)
            img_lbl.setStyleSheet("background:#0d0d1a; border:1px solid #2d2d44; border-radius:3px;")

            frame = cv2.imread(str(path))
            if frame is not None:
                img_lbl.setPixmap(bgr_to_pixmap(frame, self.THUMB_W, self.THUMB_H))
            else:
                img_lbl.setText("Не удалось\nзагрузить")
                img_lbl.setStyleSheet("color:#666; background:#0d0d1a;")

            side_label = QLabel(side_lbl)
            side_label.setAlignment(Qt.AlignCenter)
            side_label.setStyleSheet("color:#64748b; font-size:10px;")

            col.addWidget(img_lbl)
            col.addWidget(side_label)
            imgs_row.addLayout(col)

        lay.addLayout(imgs_row)
        return cell

    def _on_check_changed(self):
        for i, cb in enumerate(self._checkboxes):
            cell = self.grid_layout.itemAt(i).widget() if i < self.grid_layout.count() else None
            if cell:
                if cb.isChecked():
                    cell.setStyleSheet(
                        "QFrame{background:#1e1e2e; border:1px solid #2d2d44; border-radius:6px;}"
                    )
                else:
                    cell.setStyleSheet(
                        "QFrame{background:#141420; border:1px solid #1a1a2a; border-radius:6px;}"
                    )
        self._update_count()

    def _select_all(self):
        for cb in self._checkboxes:
            cb.setChecked(True)

    def _deselect_all(self):
        for cb in self._checkboxes:
            cb.setChecked(False)

    def _update_count(self):
        n = sum(1 for cb in self._checkboxes if cb.isChecked())
        total = len(self._checkboxes)
        self.count_lbl.setText(f"Выбрано: {n} / {total}")
        self.proceed_btn.setEnabled(n >= 4)
        if 0 < n < 4:
            self.count_lbl.setStyleSheet("font-size:12px; color:#f87171;")
            self.count_lbl.setText(f"Выбрано: {n} / {total}  (нужно минимум 4)")
        else:
            self.count_lbl.setStyleSheet("font-size:12px; color:#94a3b8;")

    def _on_proceed(self):
        selected = [
            (str(lp), str(rp))
            for (lp, rp), cb in zip(self._pairs, self._checkboxes)
            if cb.isChecked()
        ]
        self.proceed.emit(selected)
