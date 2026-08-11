"""
泛天贸易中心 - 数据上传工具
参考 sc-trade-companion / SC-Datarunner-UEX
用法: python main.py

快捷键: F3 = 截图并识别
"""
import os
import sys
import time
import threading
import tempfile
import ctypes
from ctypes import wintypes
from PIL import ImageGrab

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

# ════════════════ 内嵌 OCR（直接引用 ocr-service 模块） ════════════════
_ocr_service_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "sc-trading-hub", "ocr-service")
if _ocr_service_dir not in sys.path:
    sys.path.insert(0, _ocr_service_dir)
from server import run_ocr, parse_kiosk, get_ocr  # CnOCR, lazy-load on first call

def _preload_ocr():
    """Preload OCR model in background thread so first F3 is fast."""
    try:
        get_ocr()  # trigger model loading
    except:
        pass


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
                img_bytes = f.read()
            lines, img_h = run_ocr(img_bytes)
            result = parse_kiosk(lines, img_h)
            self.finished.emit(result)
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


# ════════════════ 主窗口 ════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("泛天贸易中心 - 数据上传")
        self.setMinimumSize(900, 600)
        self.setAcceptDrops(True)

        # 泛天贸易中心配色 — 与网站保持一致
        self.setStyleSheet("""
            QMainWindow, QWidget#central { background: #faf7f0; }
            QLabel { color: #2d2318; font-size: 13px; }
            QLabel#title { color: #2d2318; font-size: 13px; }
            QLineEdit, QComboBox {
                background: #ffffff; color: #2d2318; border: 1px solid #e4dcc8;
                padding: 4px 6px; border-radius: 4px; font-size: 12px;
            }
            QLineEdit:focus, QComboBox:focus { border-color: #c9a94e; }
            QTableWidget {
                background: #ffffff; color: #2d2318; gridline-color: #f0ebe0;
                border: 1px solid #e4dcc8; font-size: 12px;
                border-radius: 4px;
            }
            QTableWidget::item:selected { background: #c9a94e; color: #fff; }
            QHeaderView::section {
                background: #f5f0e5; color: #2d2318; padding: 5px 4px;
                border: none; border-bottom: 1px solid #e4dcc8; font-size: 12px; font-weight: bold;
            }
            QPushButton {
                background: #ffffff; color: #2d2318; border: 1px solid #e4dcc8;
                padding: 6px 16px; border-radius: 4px; font-size: 13px;
            }
            QPushButton:hover { background: #f5f0e5; border-color: #c9a94e; }
            QPushButton:disabled { background: #f0ebe0; color: #8a8070; border-color: #e4dcc8; }
            QPushButton#submitBtn { background: #c9a94e; color: #ffffff; border: none; font-size: 14px; padding: 7px 28px; font-weight: bold; }
            QPushButton#submitBtn:hover { background: #b8983d; }
            QStatusBar { background: #faf7f0; color: #8a8070; border-top: 1px solid #e4dcc8; }
            QProgressBar {
                border: none; background: #f0ebe0; height: 3px;
                text-align: center; color: transparent; border-radius: 1px;
            }
            QProgressBar::chunk { background: #c9a94e; border-radius: 1px; }
            QSplitter::handle { background: #e4dcc8; width: 1px; }
            QFrame#dropZone {
                border: 2px dashed #e4dcc8; border-radius: 8px;
                background: #ffffff; min-height: 200px;
            }
            QFrame#dropZone:hover { border-color: #c9a94e; background: #faf7f0; }
            QCheckBox { color: #2d2318; }
            QCheckBox::indicator { width: 16px; height: 16px; }
        """)

        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 10, 15, 10)

        # 标题
        title_row = QHBoxLayout()
        self.logo_label = QLabel("泛天")
        self.logo_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #c9a94e; font-family: serif;")
        title_row.addWidget(self.logo_label)
        self.subtitle_label = QLabel("数据上传工具")
        self.subtitle_label.setStyleSheet("font-size: 11px; color: #8a8070; padding-top: 8px;")
        title_row.addWidget(self.subtitle_label)
        title_row.addStretch()
        layout.addLayout(title_row)

        # Gold shimmer line
        gold_line = QFrame()
        gold_line.setFixedHeight(2)
        gold_line.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #c9a94e, stop:0.3 #d4b85e, stop:0.5 #c9a94e, stop:0.7 #d4b85e, stop:1 #c9a94e); border: none;")
        layout.addWidget(gold_line)

        # 提示文字
        self.title_label = QLabel("拖入截图或 Ctrl+V 粘贴  |  F3 一键截图识别")
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
        self.preview_label.setStyleSheet("color: #8a8070; font-size: 14px;")
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
        # 货箱规格暂时禁用
        # self.table = QTableWidget(0, 6)
        # self.table.setHorizontalHeaderLabels(["商品名", "库存等级", "SCU", "单价", "最大库存", "货箱规格"])
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

        # 窗口显示后注册全局热键（需要有效的窗口句柄）
        QTimer.singleShot(200, self._register_hotkey)

        # 预加载 OCR 模型（后台线程，GUI 无感）
        threading.Thread(target=_preload_ocr, daemon=True).start()

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

            # 货箱规格 — 暂时禁用，精度不够
            # box = item.get("boxSizes")
            # if isinstance(box, list) and box:
            #     box_text = " / ".join(str(b) for b in box)
            # elif box:
            #     box_text = str(box)
            # else:
            #     box_text = ""
            # self.table.setItem(i, 5, QTableWidgetItem(box_text))

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
        ocr_items = self.current_result.get("items", [])
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
                # "boxSizes": ocr_items[i].get("boxSizes") if i < len(ocr_items) else None,  # 暂时禁用
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
    def _register_hotkey(self):
        """Register global hotkey via Windows API. Try F3 first, fallback F4."""
        self._hotkey_id = 1
        hwnd = int(self.winId())
        for vk, label in [(0x72, "F3"), (0x73, "F4")]:
            ok = ctypes.windll.user32.RegisterHotKey(hwnd, self._hotkey_id, 0, vk)
            if ok:
                self.status.showMessage(f"热键 {label} 已就绪")
                return
        self.status.showMessage("热键注册失败，请用拖拽或 Ctrl+V")

    def nativeEvent(self, eventType, message):
        """Catch WM_HOTKEY (0x0312) from Windows."""
        # message is a ctypes pointer to MSG struct
        try:
            ptr = int(message)
            if ptr:
                msg = ctypes.cast(ptr, ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == 0x0312:  # WM_HOTKEY
                    self._on_f3()
                    return True, 0
        except:
            pass
        return False, 0

    def _on_f3(self):
        """F3: capture screen and OCR."""
        tmp = os.path.join(tempfile.gettempdir(), f"sc_f3_{int(time.time())}.png")
        ImageGrab.grab().save(tmp, "PNG")
        self.process_file(tmp)

    def closeEvent(self, event):
        event.accept()

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
