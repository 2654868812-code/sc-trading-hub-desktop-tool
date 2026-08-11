"""
泛天贸易中心 - 数据上传工具
参考 sc-trade-companion / SC-Datarunner-UEX
用法: python main.py  (需先启动 OCR 服务: cd ../ocr-service && python server.py)
"""
import json
import os
import sys
import time
import threading
from pathlib import Path
from io import BytesIO

import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QSplitter, QStatusBar, QMessageBox, QComboBox,
    QCheckBox, QLineEdit, QFrame, QStyle, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QPixmap, QImage, QDragEnterEvent, QDropEvent, QFont, QPalette, QColor

# ════════════════ 配置 ════════════════
API_BASE = os.environ.get("FT_API", "http://localhost:4000")
OCR_URL = os.environ.get("FT_OCR", "http://127.0.0.1:8765/parse")

# Star Citizen 截图路径
SC_DIRS = [
    os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Roberts Space Industries", "StarCitizen", "LIVE", "ScreenShots"),
    os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Roberts Space Industries", "StarCitizen", "LIVE", "ScreenShots"),
]


# ════════════════ OCR Worker ════════════════
class OcrWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path

    def run(self):
        try:
            with open(self.file_path, "rb") as f:
                resp = requests.post(OCR_URL, files={"file": f}, timeout=60)
            self.finished.emit(resp.json())
        except Exception as e:
            self.error.emit(str(e))


class SubmitWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, data: dict):
        super().__init__()
        self.data = data

    def run(self):
        try:
            resp = requests.post(f"{API_BASE}/api/upload/snapshot", json=self.data, timeout=10)
            self.finished.emit(resp.json())
        except Exception as e:
            self.error.emit(str(e))


# ════════════════ 文件监控线程 ════════════════
class ScreenshotWatcher(QThread):
    new_file = pyqtSignal(str)

    def __init__(self, watch_dir: str):
        super().__init__()
        self.watch_dir = watch_dir
        self.running = True

    def run(self):
        if not os.path.isdir(self.watch_dir):
            return
        seen = set(os.listdir(self.watch_dir))
        while self.running:
            try:
                current = set(os.listdir(self.watch_dir))
                for f in sorted(current - seen):
                    fpath = os.path.join(self.watch_dir, f)
                    time.sleep(0.3)
                    if os.path.isfile(fpath):
                        self.new_file.emit(fpath)
                seen = current
            except:
                pass
            time.sleep(2)

    def stop(self):
        self.running = False


# ════════════════ 主窗口 ════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("泛天贸易中心 - 数据上传")
        self.setMinimumSize(900, 600)
        self.setAcceptDrops(True)

        # 暗色主题
        self.setStyleSheet("""
            QMainWindow, QWidget#central { background: #1a1a2e; }
            QLabel { color: #ccc; font-size: 13px; }
            QLabel#title { color: #fff; font-size: 14px; font-weight: bold; }
            QLineEdit, QComboBox {
                background: #2a2a3e; color: #fff; border: 1px solid #444;
                padding: 4px; border-radius: 3px; font-size: 12px;
            }
            QTableWidget {
                background: #2a2a3e; color: #fff; gridline-color: #333;
                border: 1px solid #333; font-size: 12px;
            }
            QTableWidget::item:selected { background: #4a90d9; }
            QHeaderView::section {
                background: #333; color: #ccc; padding: 4px;
                border: none; font-size: 12px;
            }
            QPushButton {
                background: #4a90d9; color: #fff; border: none;
                padding: 8px 20px; border-radius: 4px; font-size: 13px;
            }
            QPushButton:hover { background: #5aa0e9; }
            QPushButton:disabled { background: #444; color: #888; }
            QPushButton#submitBtn { background: #27ae60; font-size: 14px; padding: 8px 30px; }
            QPushButton#submitBtn:hover { background: #2ecc71; }
            QStatusBar { background: #111; color: #888; }
            QProgressBar {
                border: none; background: #2a2a3e; height: 4px;
                text-align: center; color: transparent;
            }
            QProgressBar::chunk { background: #4a90d9; }
            QSplitter::handle { background: #333; width: 1px; }
            QFrame#dropZone {
                border: 2px dashed #555; border-radius: 8px;
                background: #14142a; min-height: 200px;
            }
            QFrame#dropZone:hover { border-color: #4a90d9; }
            QCheckBox { color: #ccc; }
            QCheckBox::indicator { width: 18px; height: 18px; }
        """)

        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 10, 15, 10)

        # 标题栏
        self.title_label = QLabel("拖入截图或 Ctrl+V 粘贴  |  监控: 未找到截图文件夹")
        self.title_label.setObjectName("title")
        layout.addWidget(self.title_label)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # 主区域：左侧截图预览 + 右侧结果表格
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        # 左侧 — 截图预览
        self.drop_zone = QFrame(objectName="dropZone")
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label = QLabel("拖入截图\n或 Ctrl+V 粘贴")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("color: #666; font-size: 14px;")
        drop_layout.addWidget(self.preview_label)
        splitter.addWidget(self.drop_zone)

        # 右侧 — 结果 + 操作
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(8)

        # 终端信息
        self.terminal_label = QLabel("")
        self.terminal_label.setStyleSheet("font-weight: bold; color: #4a90d9;")
        right_layout.addWidget(self.terminal_label)

        self.tx_label = QLabel("")
        right_layout.addWidget(self.tx_label)

        # 表格
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["商品名", "库存等级", "SCU", "单价", "最大库存"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 5):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        right_layout.addWidget(self.table, 1)

        # 操作按钮
        btn_row = QHBoxLayout()
        self.select_file_btn = QPushButton("选择文件")
        self.select_file_btn.clicked.connect(self.select_file)
        btn_row.addWidget(self.select_file_btn)
        btn_row.addStretch()
        self.submit_btn = QPushButton("提交到泛天")
        self.submit_btn.setObjectName("submitBtn")
        self.submit_btn.setEnabled(False)
        self.submit_btn.clicked.connect(self.do_submit)
        btn_row.addWidget(self.submit_btn)
        right_layout.addLayout(btn_row)

        splitter.addWidget(right_panel)
        splitter.setSizes([380, 500])

        # 状态栏
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("就绪")

        # 文件夹监控
        self.watcher = None
        self._start_watcher()

        # 当前数据
        self.current_image = None
        self.current_result = None

    # ── 拖拽 & 粘贴 ────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                self.process_file(path)
            return

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_V and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            if mime.hasImage():
                img = mime.imageData()
                if img:
                    tmp = os.path.join(os.environ["TEMP"], f"sc_paste_{int(time.time())}.png")
                    img.save(tmp, "PNG")
                    self.process_file(tmp)

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择截图", "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All (*.*)")
        if path:
            self.process_file(path)

    # ── OCR 处理 ──────────────────────────

    def process_file(self, file_path: str):
        # 预览
        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            self.status.showMessage(f"无法加载: {file_path}")
            return
        scaled = pixmap.scaledToWidth(360, Qt.TransformationMode.SmoothTransformation)
        self.preview_label.setPixmap(scaled)
        self.current_image = file_path

        # OCR
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.showMessage("OCR 识别中...")
        self.submit_btn.setEnabled(False)

        self.worker = OcrWorker(file_path)
        self.worker.finished.connect(self.on_ocr_done)
        self.worker.error.connect(self.on_ocr_error)
        self.worker.start()

    def on_ocr_done(self, result: dict):
        self.progress.setVisible(False)
        if not result.get("ok"):
            self.status.showMessage(f"OCR 失败: {result.get('error', 'unknown')}")
            return

        self.current_result = result
        items = result.get("items", [])
        terminal = result.get("terminal", "未知")
        tx = result.get("transactionType", "未知")
        tx_cn = "买入" if tx == "buy" else "卖出"

        self.terminal_label.setText(f"终端: {terminal}")
        self.tx_label.setText(f"类型: {tx_cn}  |  {len(items)} 条商品")
        self.status.showMessage(f"识别完成: {terminal} {tx_cn} {len(items)}条")

        # 填表
        self.table.setRowCount(len(items))
        INVENTORY_LEVELS = ["库存已满", "库存已空", "高", "中", "低", "非常低", "无货", ""]
        for i, item in enumerate(items):
            # 商品名
            name_edit = QLineEdit(item.get("commodityName", ""))
            self.table.setCellWidget(i, 0, name_edit)

            # 库存等级
            inv_combo = QComboBox()
            inv_combo.addItems(INVENTORY_LEVELS)
            inv_combo.setCurrentText(item.get("inventoryLevel") or "")
            self.table.setCellWidget(i, 1, inv_combo)

            # SCU
            scu_val = item.get("scu")
            self.table.setItem(i, 2, QTableWidgetItem(str(scu_val) if scu_val else ""))

            # 价格
            price_val = item.get("price")
            self.table.setItem(i, 3, QTableWidgetItem(str(price_val) if price_val else ""))

            # 最大库存
            chk = QCheckBox()
            chk.setChecked(item.get("isMaxStock", False))
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(i, 4, chk_widget)

        self.submit_btn.setEnabled(True)

    def on_ocr_error(self, err_msg: str):
        self.progress.setVisible(False)
        self.status.showMessage(f"OCR 服务不可用: {err_msg}")

    # ── 提交 ─────────────────────────────

    def do_submit(self):
        if not self.current_result:
            return

        # 从表格读最新数据
        items = []
        for i in range(self.table.rowCount()):
            name_widget = self.table.cellWidget(i, 0)
            inv_widget = self.table.cellWidget(i, 1)
            chk_widget = self.table.cellWidget(i, 4)
            name = name_widget.text() if isinstance(name_widget, QLineEdit) else ""
            inv = inv_widget.currentText() if isinstance(inv_widget, QComboBox) else ""
            is_max = False
            if chk_widget:
                chk = chk_widget.findChild(QCheckBox)
                if chk:
                    is_max = chk.isChecked()

            items.append({
                "commodityName": name,
                "transactionType": self.current_result.get("transactionType", "buy"),
                "inventoryLevel": inv or None,
                "scu": self._parse_int(self.table.item(i, 2)),
                "price": self._parse_float(self.table.item(i, 3)),
                "isMaxStock": is_max,
            })

        self.submit_btn.setEnabled(False)
        self.status.showMessage("提交中...")
        self.worker2 = SubmitWorker({
            "terminal": self.current_result.get("terminal", ""),
            "items": items,
        })
        self.worker2.finished.connect(self.on_submit_done)
        self.worker2.error.connect(self.on_submit_error)
        self.worker2.start()

    def on_submit_done(self, resp: dict):
        self.submit_btn.setEnabled(True)
        if resp.get("ok"):
            QMessageBox.information(self, "成功", f"已提交 {resp.get('upserted', 0)} 条数据")
            self.status.showMessage(f"提交成功: {resp.get('upserted', 0)} 条")
        else:
            QMessageBox.warning(self, "失败", resp.get("error", "未知错误"))

    def on_submit_error(self, err_msg: str):
        self.submit_btn.setEnabled(True)
        QMessageBox.critical(self, "网络错误", err_msg)

    def _parse_int(self, item):
        if not item or not item.text():
            return None
        try:
            return int(item.text().replace(",", ""))
        except ValueError:
            return None

    def _parse_float(self, item):
        if not item or not item.text():
            return None
        try:
            return float(item.text().replace(",", ""))
        except ValueError:
            return None

    # ── 文件夹监控 ────────────────────────
    def _start_watcher(self):
        for d in SC_DIRS:
            if os.path.isdir(d):
                self.watcher = ScreenshotWatcher(d)
                self.watcher.new_file.connect(self.process_file)
                self.watcher.start()
                self.title_label.setText(f"拖入截图或 Ctrl+V 粘贴  |  监控: {d}")
                return
        self.title_label.setText("拖入截图或 Ctrl+V 粘贴  |  未找到 SC 截图文件夹")


# ════════════════ 入口 ════════════════
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("泛天贸易中心")
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()

    # 支持命令行传图
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        window.process_file(sys.argv[1])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
