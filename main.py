"""
泛天贸易中心 - 数据上传工具
参考 sc-trade-companion / SC-Datarunner-UEX
用法: python main.py

快捷键: F3 = 截图 → OCR → 校验 → 自动提交 → 日志记录
"""
import os
import sys
import time
import threading
import winsound

import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QStatusBar, QMessageBox, QLineEdit, QTabWidget,
    QListWidget, QListWidgetItem, QListView, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QPixmap, QFont, QPainter, QColor, QPen, QIcon

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

# Auto-elevate: if not admin, relaunch as admin
if not ctypes.windll.shell32.IsUserAnAdmin():
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable,
        " ".join(f'"{a}"' if ' ' in a else a for a in sys.argv),
        os.path.dirname(os.path.abspath(__file__)), 1)
    sys.exit(0)

import keyboard
import json as _json
import subprocess

import history

# ════════════════ Config ════════════════
# onefile 打包后 __file__ 指向临时解压目录，配置/截图必须放 exe 旁边
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE_DIR, "ft_upload_config.json")
SCREENSHOT_DIR = os.path.join(_BASE_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

_API_DEFAULTS = {
    "hotkey": "f3",
    # 默认测试服（发给测试人员的包开箱即用；本地开发可在设置里切）
    "api_base": "http://114.55.238.180:3000",
}

# 服务器选项（设置页下拉框）
# 生产服备案待审期间冻结，只提供本地开发 + 测试服
API_SERVERS = [
    ("本地开发", "http://localhost:4000"),
    ("测试服", "http://114.55.238.180:3000"),
]

def _load_config():
    cfg = dict(_API_DEFAULTS)
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(_json.load(f))
        except:
            pass
    return cfg

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
# 提权（UAC）后环境变量丢失，API 地址必须走配置文件
API_BASE = os.environ.get("FT_API", _config.get("api_base", "http://localhost:4000"))

# ── 快门音 ──
# 内存同步播放（SND_MEMORY|SND_SYNC）：异步/文件播放多次后静音的坑全避开。
# 游戏占音频设备导致失败时兜底 MessageBeep(-1) 系统蜂鸣。
_SHUTTER_WAV = None

def _load_shutter_bytes():
    global _SHUTTER_WAV
    if _SHUTTER_WAV is None:
        if getattr(sys, 'frozen', False):
            fp = os.path.join(sys._MEIPASS, "shutter.wav")
        else:
            fp = os.path.join(_BASE_DIR, "shutter.wav")
        try:
            with open(fp, "rb") as f:
                _SHUTTER_WAV = f.read()
        except Exception:
            _SHUTTER_WAV = b""
    return _SHUTTER_WAV

def _thumb_path(shot_path: str) -> str:
    base, ext = os.path.splitext(shot_path)
    return base + "_thumb.png"

def _make_thumbnail(shot_path: str):
    """Generate small thumbnail next to screenshot — log list icons load
    this instead of the full image (11MB decode per entry otherwise)."""
    try:
        pm = QPixmap(shot_path)
        if pm.isNull():
            return
        pm.scaledToWidth(320, Qt.TransformationMode.SmoothTransformation).save(_thumb_path(shot_path))
    except Exception:
        pass

def _trim_working_set():
    """Trim working set — return idle pages to OS after each cycle."""
    try:
        ctypes.windll.kernel32.SetProcessWorkingSetSize(-1, -1, -1)
    except Exception:
        pass

def _play_shutter():
    """Play shutter sound in a daemon thread — sync playback must never
    block the GUI thread (game holding the audio device would freeze it)."""
    def _play():
        wav = _load_shutter_bytes()
        if wav:
            try:
                # 不传 SND_ASYNC 即同步播放；SND_SYNC 常量 3.14 才有，3.12 会 AttributeError
                winsound.PlaySound(wav, winsound.SND_MEMORY)
                return
            except Exception:
                pass
        try:
            winsound.MessageBeep(-1)
        except Exception:
            pass
    threading.Thread(target=_play, daemon=True).start()

# ════════════════ 内嵌 OCR（直接引用 ocr-service 模块） ════════════════
# PyInstaller bundles ocr-service as data; sys._MEIPASS is the temp extract dir
if getattr(sys, 'frozen', False):
    _ocr_service_dir = os.path.join(sys._MEIPASS, "ocr-service")
else:
    _ocr_service_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "sc-trading-hub", "ocr-service")
if _ocr_service_dir not in sys.path:
    sys.path.insert(0, _ocr_service_dir)
from server import run_ocr, parse_kiosk, get_ocr, validate_result  # CnOCR, lazy-load on first call

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
            # 释放推理期间的大块内存（截图缓冲/中间数组）
            import gc
            del img_bytes, lines
            gc.collect()
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


# ════════════════ Toast 通知气泡 ════════════════

class Toast(QWidget):
    """Frameless bottom-right notification bubble, gold theme, auto-dismiss."""
    _active = []

    def __init__(self, title: str, text: str, ok: bool = True):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._accent = "#c9a94e" if ok else "#d9534f"
        self.setStyleSheet(f"""
            QLabel#t {{ color: {self._accent}; font-weight: bold; font-size: 13px;
                background: transparent; }}
            QLabel#b {{ color: #2d2318; font-size: 12px; background: transparent; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(4)
        t = QLabel(title)
        t.setObjectName("t")
        b = QLabel(text)
        b.setObjectName("b")
        outer.addWidget(t)
        outer.addWidget(b)
        # 成功 3s，失败 5s 自动消失
        QTimer.singleShot(3000 if ok else 5000, self.close)

    def paintEvent(self, event):
        """Draw gold-bordered rounded box (QSS background unreliable on bare QWidget)."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#faf7f0"))
        p.setPen(QPen(QColor(self._accent), 2))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)

    def show_at_corner(self):
        """Show at screen bottom-right, stacking above any active toasts."""
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.width() - 20
        y = screen.bottom() - self.height() - 20
        for w in Toast._active:
            y -= w.height() + 8
        self.move(x, y)
        Toast._active.append(self)
        self.show()

    def closeEvent(self, event):
        if self in Toast._active:
            Toast._active.remove(self)
        super().closeEvent(event)


# ════════════════ 日志页 ════════════════

class LogTab(QWidget):
    """Left: screenshot thumbnail list. Right: submission detail."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # 左侧 — 缩略图日志列表
        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListView.ViewMode.IconMode)
        self.list_widget.setIconSize(QSize(170, 96))
        self.list_widget.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_widget.setSpacing(10)
        self.list_widget.setWordWrap(True)
        self.list_widget.itemClicked.connect(self._on_clicked)
        splitter.addWidget(self.list_widget)

        # 右侧 — 详情
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setSpacing(8)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-weight: bold; color: #c9a94e;")
        rl.addWidget(self.status_label)

        self.info_label = QLabel("点击左侧日志查看详情")
        self.info_label.setStyleSheet("color: #8a8070;")
        rl.addWidget(self.info_label)

        self.detail_table = QTableWidget(0, 5)
        self.detail_table.setHorizontalHeaderLabels(["商品名", "库存等级", "当前库存", "单价", "最大库存"])
        self.detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.detail_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 5):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        rl.addWidget(self.detail_table, 1)

        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setMinimumHeight(160)
        self.img_label.setStyleSheet(
            "color: #8a8070; background: #ffffff; border: 1px solid #e4dcc8; border-radius: 4px;")
        rl.addWidget(self.img_label, 1)

        splitter.addWidget(right)
        splitter.setSizes([430, 620])

        self._entries = history.load_entries()
        for e in self._entries:
            self.list_widget.addItem(self._make_item(e))
        if self._entries:
            self.list_widget.setCurrentRow(0)
            self._show_entry(0)

    def _make_item(self, e: dict) -> QListWidgetItem:
        shot = e.get("screenshot", "")
        full = os.path.join(_BASE_DIR, shot) if not os.path.isabs(shot) else shot
        # 优先用缩略图（小文件，省解码内存）；没有则回退原图
        thumb = _thumb_path(full)
        icon_src = thumb if os.path.exists(thumb) else full
        icon = QIcon(icon_src) if os.path.exists(icon_src) else QIcon()
        label = f"{e.get('time','')}\n{e.get('terminal','')}"
        item = QListWidgetItem(icon, label)
        item.setToolTip(e.get("detail", ""))
        return item

    def add_entry(self, entry: dict):
        """Persist new entry and insert at top of list (capped)."""
        self._entries = history.append_entry(entry)
        self.list_widget.insertItem(0, self._make_item(entry))
        while self.list_widget.count() > history.MAX_ENTRIES:
            self.list_widget.takeItem(self.list_widget.count() - 1)
        self.list_widget.setCurrentRow(0)
        self._show_entry(0)

    def _on_clicked(self, item):
        self._show_entry(self.list_widget.row(item))

    def _show_entry(self, idx: int):
        if idx < 0 or idx >= len(self._entries):
            return
        e = self._entries[idx]
        status_map = {"success": ("提交成功", "#c9a94e"),
                      "submit_failed": ("提交失败", "#d9534f"),
                      "check_failed": ("检查未通过", "#d9534f")}
        name, color = status_map.get(e.get("status", ""), (e.get("status", "未知"), "#8a8070"))
        self.status_label.setStyleSheet(f"font-weight: bold; color: {color};")
        self.status_label.setText(f"{name}  |  {e.get('detail','')}")

        tx = e.get("transactionType", "")
        tx_cn = "买入" if tx == "buy" else ("卖出" if tx == "sell" else tx)
        self.info_label.setText(f"{e.get('time','')}  |  终端: {e.get('terminal','')}  |  {tx_cn}")

        items = e.get("items", [])
        self.detail_table.setRowCount(len(items))
        for i, it in enumerate(items):
            self.detail_table.setItem(i, 0, QTableWidgetItem(it.get("commodityName", "")))
            self.detail_table.setItem(i, 1, QTableWidgetItem(it.get("inventoryLevel") or ""))
            scu = it.get("scu")
            self.detail_table.setItem(i, 2, QTableWidgetItem(str(scu) if scu is not None else ""))
            price = it.get("price")
            self.detail_table.setItem(i, 3, QTableWidgetItem(str(price) if price is not None else ""))
            self.detail_table.setItem(i, 4, QTableWidgetItem("✓" if it.get("isMaxStock") else ""))

        shot = e.get("screenshot", "")
        full = os.path.join(_BASE_DIR, shot) if not os.path.isabs(shot) else shot
        if full and os.path.exists(full):
            pm = QPixmap(full)
            if not pm.isNull():
                self.img_label.setPixmap(pm.scaledToWidth(560, Qt.TransformationMode.SmoothTransformation))
                return
        self.img_label.setPixmap(QPixmap())
        self.img_label.setText("无截图")


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

        layout.addSpacing(12)
        layout.addWidget(QLabel("数据提交服务器"))

        self.server_combo = QComboBox()
        current_api = _config.get("api_base", _API_DEFAULTS["api_base"])
        for label, url in API_SERVERS:
            self.server_combo.addItem(f"{label}（{url}）", url)
        for i in range(self.server_combo.count()):
            if self.server_combo.itemData(i) == current_api:
                self.server_combo.setCurrentIndex(i)
                break
        layout.addWidget(self.server_combo)

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
        global _config, _current_hotkey, API_BASE
        saved = []

        # 服务器选择
        api_base = self.server_combo.currentData()
        if api_base and api_base != _config.get("api_base"):
            _config["api_base"] = api_base
            API_BASE = api_base
            saved.append("服务器已切换")
        elif api_base == _config.get("api_base"):
            saved.append("服务器未变")

        # 快捷键（仅捕获了新键时）
        if self._captured_key:
            if _register_hotkey(self._captured_key):
                _config["hotkey"] = self._captured_key
                _current_hotkey = self._captured_key
                self.hotkey_changed.emit(self._captured_key)
                self.capture_widget.setText(f"当前: {self._captured_key.upper()}  —  点击后按下新快捷键")
                saved.append("热键已更新")
                self._captured_key = None
            else:
                QMessageBox.warning(self, "注册失败", f"无法注册热键: {self._captured_key}，请尝试其他按键")
                return

        _save_config(_config)
        self.hint_label.setText("  ".join(saved) + " ✓")
        self.save_btn.setEnabled(False)


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
            QLineEdit {
                background: #ffffff; color: #2d2318; border: 1px solid #e4dcc8;
                padding: 4px 6px; border-radius: 4px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #c9a94e; }
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
            QStatusBar { background: #faf7f0; color: #8a8070; border-top: 1px solid #e4dcc8; }
            QSplitter::handle { background: #e4dcc8; width: 1px; }
            QListWidget {
                background: #faf7f0; color: #2d2318; border: none;
                font-size: 11px;
            }
            QListWidget::item { border: 1px solid transparent; border-radius: 4px; padding: 2px; }
            QListWidget::item:selected { background: #f5f0e5; border: 1px solid #c9a94e; color: #2d2318; }
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

        # ── Tab 0: 日志（首页） ──
        self.log_tab = LogTab()

        # ── Tab 1: 偏好设置 ──
        self.settings_tab = SettingsTab()
        self.settings_tab.hotkey_changed.connect(self._on_hotkey_changed)

        self.tabs.addTab(self.log_tab, "日志")
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
        self.current_result = None
        self._current_shot = None

    # ── 偏好设置回调 ────────────────────────

    def _on_hotkey_changed(self, new_key: str):
        self.status.showMessage(f"热键已更新: {new_key.upper()}  |  截图识别")

    # ── OCR 处理 ──────────────────────────

    def _process_shot(self, file_path: str):
        self._current_shot = file_path
        self.status.showMessage("OCR 识别中...")

        self.worker = OcrWorker(file_path)
        self.worker.finished.connect(self.on_ocr_done)
        self.worker.error.connect(self.on_ocr_error)
        self.worker.start()

    def on_ocr_done(self, result: dict):
        if not result.get("ok"):
            self.status.showMessage(f"OCR 失败: {result.get('error', 'unknown')}")
            Toast("提交失败", f"OCR 失败: {result.get('error', 'unknown')}", ok=False).show_at_corner()
            self._log_outcome("check_failed", f"OCR 失败: {result.get('error', 'unknown')}")
            return

        self.current_result = result
        items = result.get("items", [])
        terminal = result.get("terminal", "未知")
        tx = result.get("transactionType", "未知")
        tx_cn = "买入" if tx == "buy" else ("卖出" if tx == "sell" else "未知")
        self.status.showMessage(f"识别完成: {terminal} {tx_cn} {len(items)}条")

        # 校验 → 自动提交
        ok, reasons = validate_result(result)
        if ok:
            self.status.showMessage("检查通过，自动提交中...")
            self.do_submit()
        else:
            self.status.showMessage("检查未通过，未提交")
            shown = reasons[:3]
            extra = f"（共{len(reasons)}个问题）" if len(reasons) > 3 else ""
            Toast("提交失败", "\n".join(shown) + extra, ok=False).show_at_corner()
            self._log_outcome("check_failed", "; ".join(reasons))

    def on_ocr_error(self, err_msg: str):
        self.status.showMessage(f"OCR 服务不可用: {err_msg}")
        Toast("提交失败", f"OCR 服务不可用: {err_msg}", ok=False).show_at_corner()
        self._log_outcome("check_failed", f"OCR 服务不可用: {err_msg}")

    # ── 提交 ─────────────────────────────

    def do_submit(self):
        """Auto-submit current OCR result. Called after validate_result passes."""
        if not self.current_result:
            return
        tx = self.current_result.get("transactionType", "buy")
        items = [{
            "commodityName": it.get("commodityName", ""),
            "transactionType": tx,
            "inventoryLevel": it.get("inventoryLevel") or None,
            "scu": it.get("scu"),
            "price": it.get("price"),
            "isMaxStock": it.get("isMaxStock", False),
        } for it in self.current_result.get("items", [])]

        self.status.showMessage("提交中...")
        self.worker2 = SubmitWorker({
            "terminal": self.current_result.get("terminal", ""),
            "items": items,
        })
        self.worker2.finished.connect(self.on_submit_done)
        self.worker2.error.connect(self.on_submit_error)
        self.worker2.start()

    def on_submit_done(self, resp: dict):
        if resp.get("ok"):
            n = resp.get("upserted", 0)
            self.status.showMessage(f"提交成功: {n} 条")
            Toast("提交成功", f"已提交 {n} 条数据").show_at_corner()
            self._log_outcome("success", f"已提交 {n} 条")
        else:
            self.status.showMessage("提交失败")
            Toast("提交失败", resp.get("error", "未知错误"), ok=False).show_at_corner()
            self._log_outcome("submit_failed", resp.get("error", "未知错误"))

    def on_submit_error(self, err_msg: str):
        self.status.showMessage("提交失败（网络错误）")
        Toast("提交失败", f"网络错误: {err_msg}", ok=False).show_at_corner()
        self._log_outcome("submit_failed", f"网络错误: {err_msg}")

    # ── 日志记录 ──────────────────────────

    def _log_outcome(self, status: str, detail: str):
        # 每轮结束 2 秒后修剪工作集（把推理峰值内存还给 OS，学 Mem Reduct）
        QTimer.singleShot(2000, _trim_working_set)
        items = []
        if self.current_result:
            tx = self.current_result.get("transactionType", "buy")
            items = [{
                "commodityName": it.get("commodityName", ""),
                "transactionType": tx,
                "inventoryLevel": it.get("inventoryLevel") or None,
                "scu": it.get("scu"),
                "price": it.get("price"),
                "isMaxStock": it.get("isMaxStock", False),
            } for it in self.current_result.get("items", [])]
        shot = os.path.relpath(self._current_shot, _BASE_DIR) if self._current_shot else ""
        entry = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": status,
            "terminal": (self.current_result or {}).get("terminal", ""),
            "transactionType": (self.current_result or {}).get("transactionType", ""),
            "detail": detail,
            "items": items,
            "screenshot": shot.replace("\\", "/"),
        }
        self.log_tab.add_entry(entry)

    # ── 全局热键 ──────────────────────────
    def _start_hotkey_timer(self):
        """Qt timer polls _trigger_event (set by keyboard hotkey thread)."""
        self._hotkey_timer = QTimer()
        self._hotkey_timer.timeout.connect(self._check_hotkey)
        self._hotkey_timer.start(50)

    def _check_hotkey(self):
        if _trigger_event.is_set():
            _trigger_event.clear()
            # OCR/提交进行中忽略连按（否则截到动画帧，解析必失败）
            if hasattr(self, "worker") and self.worker.isRunning():
                return
            if hasattr(self, "worker2") and self.worker2.isRunning():
                return
            self._do_screenshot()

    def _do_screenshot(self):
        """Capture screen via child process (GDI capture leaks ~20MB heap per
        shot in-process; a short-lived child returns it all to the OS)."""
        _play_shutter()
        path = os.path.join(SCREENSHOT_DIR, time.strftime("sc_shot_%Y%m%d_%H%M%S.png"))
        if getattr(sys, 'frozen', False):
            cap_cmd = [os.path.join(os.path.dirname(sys.executable), "FT-Capture.exe"), path]
        else:
            cap_cmd = [sys.executable, os.path.join(_BASE_DIR, "capture_main.py"), path]
        try:
            subprocess.run(cap_cmd, timeout=10)
        except Exception:
            pass
        if not os.path.exists(path):
            self.status.showMessage("截图失败")
            return
        _make_thumbnail(path)
        self._process_shot(path)

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
