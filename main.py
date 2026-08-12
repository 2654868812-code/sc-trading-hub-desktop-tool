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
import winsound

import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QStatusBar, QMessageBox, QComboBox,
    QCheckBox, QLineEdit, QFrame, QProgressBar, QTabWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QFont

# ════════════════ F3 Hotkey ════════════════
# Anti-cheat safe (EAC/BattlEye compatible):
# - keyboard: WH_KEYBOARD_LL hook (OS-level, same as Discord/OBS hotkeys)
# - mss: desktop screenshot via BitBlt/DXGI (standard Windows API)
# - NO DLL injection, NO memory reading, NO overlay, NO game process interaction
# Admin elevation only needed for UIPI bypass when game runs elevated.
#
# sc-trade-companion uses same architecture (JNativeHook + Robot screenshot)
# and has been verified working with EAC.

import ctypes
import mss

# Auto-elevate: if not admin, relaunch as admin
if not ctypes.windll.shell32.IsUserAnAdmin():
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable,
        " ".join(f'"{a}"' if ' ' in a else a for a in sys.argv),
        os.path.dirname(os.path.abspath(__file__)), 1)
    sys.exit(0)

import keyboard
import json as _json

# ════════════════ Config ════════════════
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ft_upload_config.json")

def _load_config():
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                return _json.load(f)
        except:
            pass
    return {"hotkey": "f3"}

def _save_config(cfg: dict):
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        _json.dump(cfg, f, indent=2, ensure_ascii=False)

_config = _load_config()
_current_hotkey = _config.get("hotkey", "f3")

_trigger_event = threading.Event()

def _on_hotkey():
    _trigger_event.set()

def _register_hotkey(key: str):
    """Register global hotkey via keyboard library. Returns True on success."""
    global _current_hotkey
    try:
        keyboard.remove_all_hotkeys()
    except:
        pass
    try:
        keyboard.add_hotkey(key, _on_hotkey)
        _current_hotkey = key
        return True
    except Exception:
        return False

_register_hotkey(_current_hotkey)

# ════════════════ 配置 ════════════════
API_BASE = os.environ.get("FT_API", "http://localhost:4000")

# ════════════════ 内嵌 OCR（直接引用 ocr-service 模块） ════════════════
# PyInstaller bundles ocr-service as data; sys._MEIPASS is the temp extract dir
if getattr(sys, 'frozen', False):
    _ocr_service_dir = os.path.join(sys._MEIPASS, "ocr-service")
else:
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


# ════════════════ 设置窗口 ════════════════

class HotkeyCaptureWidget(QLineEdit):
    """Read-only line edit that captures next key press as hotkey binding."""
    key_captured = pyqtSignal(str)

    def __init__(self, current_key: str):
        super().__init__(f"当前: {current_key.upper()}  —  点击后按下新快捷键")
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            QLineEdit { background: #f5f0e5; border: 2px dashed #e4dcc8;
                padding: 12px 24px; font-size: 16px; color: #8a8070;
                border-radius: 4px; min-height: 50px; }
            QLineEdit:focus { border-color: #c9a94e; background: #fff; color: #2d2318; }
        """)
        self._capturing = False

    def mousePressEvent(self, event):
        self._capturing = True
        self.setText("按下快捷键...")
        self.setStyleSheet("""
            QLineEdit { background: #fff; border: 2px solid #c9a94e;
                padding: 12px 24px; font-size: 16px; color: #c9a94e;
                border-radius: 4px; min-height: 50px; }
        """)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if not self._capturing:
            return super().keyPressEvent(event)
        parts = []
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")
        key = event.key()
        key_name = ""
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
            key_name = f"f{key - Qt.Key.Key_F1 + 1}"
        elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            key_name = chr(key).lower()
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            key_name = chr(key)
        elif key == Qt.Key.Key_Space:
            key_name = "space"
        if key_name:
            parts.append(key_name)
        if parts and key_name:  # must have a non-modifier key
            captured = "+".join(parts)
            self._capturing = False
            self.setText(f"已捕获: {captured.upper()}")
            self.key_captured.emit(captured)
            self.setStyleSheet("""
                QLineEdit { background: #f5f0e5; border: 2px dashed #c9a94e;
                    padding: 12px 24px; font-size: 16px; color: #2d2318;
                    border-radius: 4px; min-height: 50px; }
            """)
        else:
            self.setText("未识别的按键，请重试")


class SettingsTab(QWidget):
    """Settings tab embedded in main window."""
    hotkey_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QWidget { background: #faf7f0; }
            QLabel { color: #2d2318; font-size: 13px; }
            QLabel#title { font-size: 18px; font-weight: bold; color: #c9a94e; font-family: serif; }
            QPushButton { background: #ffffff; color: #2d2318; border: 1px solid #e4dcc8;
                padding: 8px 20px; border-radius: 4px; font-size: 14px; }
            QPushButton:hover { background: #f5f0e5; border-color: #c9a94e; }
            QPushButton#saveBtn { background: #c9a94e; color: #fff; border: none;
                font-weight: bold; padding: 8px 28px; }
            QPushButton#saveBtn:hover { background: #b8983d; }
        """)
        self._captured_key = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        title = QLabel("偏好设置")
        title.setObjectName("title")
        layout.addWidget(title)

        layout.addSpacing(6)
        layout.addWidget(QLabel("截图快捷键"))

        self.capture_widget = HotkeyCaptureWidget(_current_hotkey)
        self.capture_widget.key_captured.connect(self._on_key_captured)
        layout.addWidget(self.capture_widget)

        self.hint_label = QLabel("")
        self.hint_label.setStyleSheet("color: #8a8070; font-size: 11px;")
        layout.addWidget(self.hint_label)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(cancel_btn)
        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("saveBtn")
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setEnabled(False)
        btn_row.addWidget(self.save_btn)
        layout.addLayout(btn_row)

    def _on_key_captured(self, key: str):
        self._captured_key = key
        self.hint_label.setText(f"已捕获: {key.upper()}  —  点击「保存」生效")
        self.save_btn.setEnabled(True)

    def _save(self):
        if not self._captured_key:
            return
        if _register_hotkey(self._captured_key):
            global _config, _current_hotkey
            _config["hotkey"] = self._captured_key
            _save_config(_config)
            _current_hotkey = self._captured_key
            self.hotkey_changed.emit(self._captured_key)
            self.capture_widget.setText(f"当前: {self._captured_key.upper()}  —  点击后按下新快捷键")
            self.hint_label.setText("已保存 ✓")
            self.save_btn.setEnabled(False)
            self._captured_key = None
        else:
            QMessageBox.warning(self, "注册失败", f"无法注册热键: {self._captured_key}，请尝试其他按键")


# ════════════════ 主窗口 ════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("泛天贸易中心 - 数据上传")
        self.setMinimumSize(900, 600)

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

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background: #faf7f0; }
            QTabBar::tab { background: #f5f0e5; color: #8a8070; padding: 8px 24px;
                border: none; border-bottom: 2px solid transparent; font-size: 13px; }
            QTabBar::tab:selected { background: #faf7f0; color: #c9a94e;
                border-bottom: 2px solid #c9a94e; font-weight: bold; }
            QTabBar::tab:hover { color: #2d2318; }
        """)
        self.setCentralWidget(self.tabs)

        # ── Tab 0: 数据上传 ──
        upload_tab = QWidget(objectName="central")
        layout = QVBoxLayout(upload_tab)
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
        hotkey_display = _current_hotkey.upper()
        self.title_label = QLabel(f"按 {hotkey_display} 截图识别  |  全屏截取自动 OCR")
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
        hotkey_display = _current_hotkey.upper()
        self.preview_label = QLabel(f"按 {hotkey_display} 截图\n自动 OCR 识别")
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
        self.table.setHorizontalHeaderLabels(["商品名", "库存等级", "当前库存", "单价", "最大库存"])
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
        btn_row.addStretch()
        self.submit_btn = QPushButton("提交到泛天")
        self.submit_btn.setObjectName("submitBtn")
        self.submit_btn.setEnabled(False)
        self.submit_btn.clicked.connect(self.do_submit)
        btn_row.addWidget(self.submit_btn)
        right_layout.addLayout(btn_row)

        splitter.addWidget(right_panel)
        splitter.setSizes([380, 500])

        # ── Tab 1: 偏好设置 ──
        self.settings_tab = SettingsTab()
        self.settings_tab.hotkey_changed.connect(self._on_hotkey_changed)

        # Add tabs
        self.tabs.addTab(upload_tab, "数据上传")
        self.tabs.addTab(self.settings_tab, "偏好设置")

        # 状态栏
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage(f"就绪  |  按 {_current_hotkey.upper()} 截图")

        # 窗口显示后启动热键轮询
        QTimer.singleShot(200, self._start_hotkey_timer)

        # 预加载 OCR 模型（后台线程，GUI 无感）
        threading.Thread(target=_preload_ocr, daemon=True).start()

        # 当前数据
        self.current_image = None
        self.current_result = None

    # ── 偏好设置回调 ────────────────────────

    def _on_hotkey_changed(self, new_key: str):
        hd = new_key.upper()
        self.title_label.setText(f"按 {hd} 截图识别  |  全屏截取自动 OCR")
        self.preview_label.setText(f"按 {hd} 截图\n自动 OCR 识别")
        self.status.showMessage(f"热键已更新: {hd}  |  截图识别")

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
        INVENTORY_LEVELS = ["库存已满", "库存已空", "库存将满", "库存充足", "库存中等", "库存偏少", "库存极低", ""]
        for i, item in enumerate(items):
            # 商品名
            name_edit = QLineEdit(item.get("commodityName", ""))
            self.table.setCellWidget(i, 0, name_edit)

            # 库存等级
            inv_combo = QComboBox()
            inv_combo.addItems(INVENTORY_LEVELS)
            inv_combo.setCurrentText(item.get("inventoryLevel") or "")
            self.table.setCellWidget(i, 1, inv_combo)

            # SCU / 当前库存
            scu_val = item.get("scu")
            self.table.setItem(i, 2, QTableWidgetItem(str(scu_val) if scu_val is not None else ""))

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

    # ── 全局热键 ──────────────────────────
    def _start_hotkey_timer(self):
        """Qt timer polls _trigger_event (set by keyboard hotkey thread)."""
        self._hotkey_timer = QTimer()
        self._hotkey_timer.timeout.connect(self._check_hotkey)
        self._hotkey_timer.start(50)

    def _check_hotkey(self):
        if _trigger_event.is_set():
            _trigger_event.clear()
            self._do_screenshot()

    def _do_screenshot(self):
        """Capture screen via mss (works with DirectX games) and OCR."""
        # Camera shutter sound: two-tone click
        winsound.Beep(1200, 40)
        winsound.Beep(600, 60)
        tmp = os.path.join(tempfile.gettempdir(), f"sc_shot_{int(time.time())}.png")
        with mss.mss() as sct:
            sct.shot(output=tmp)
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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
