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
import uuid
import re
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QStatusBar, QMessageBox, QLineEdit, QTabWidget,
    QListWidget, QListWidgetItem, QListView, QComboBox, QCheckBox,
    QTextBrowser, QDialog, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QUrl
from PySide6.QtGui import (
    QPixmap, QFont, QFontDatabase, QPainter, QColor, QPen, QIcon, QDesktopServices
)

# ════════════════ F3 Hotkey ════════════════
# Anti-cheat safe (EAC/BattlEye compatible):
# - keyboard: WH_KEYBOARD_LL hook (OS-level, same as Discord/OBS hotkeys)
# - mss: desktop screenshot via BitBlt/DXGI (standard Windows API)
# - NO DLL injection, NO memory reading, NO overlay, NO game process interaction
# The assistant intentionally stays at standard-user integrity. If a game is
# elevated and Windows blocks the hook, the user can choose another hotkey.
#
# sc-trade-companion uses same architecture (JNativeHook + Robot screenshot)
# and has been verified working with EAC.

import ctypes

import keyboard
import subprocess

from app_storage import (
    CONFIG_PATH,
    SCREENSHOT_DIR as USER_SCREENSHOT_DIR,
    atomic_write_json,
    ensure_storage,
    load_json_object,
    migrate_legacy_storage,
)
import history
from upload_contract import (
    APP_VERSION,
    PRIVACY_POLICY_VERSION,
    build_snapshot_items,
    build_snapshot_payload,
    is_valid_device_id,
    is_upload_ready,
    normalize_scm_id,
)
from update_checker import DATA_COLLECTION_URL, check_for_update
from transport_security import normalize_api_base, secure_post_json

# ════════════════ Config ════════════════
# Immutable assets/helpers live with the installation; mutable state does not.
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ensure_storage()
migrate_legacy_storage(Path(_BASE_DIR))
_CONFIG_PATH = str(CONFIG_PATH)
SCREENSHOT_DIR = str(USER_SCREENSHOT_DIR)

_API_DEFAULTS = {
    "hotkey": "f3",
    "api_base": "https://fantiantradinghub.xyz",
    "privacy_agreed": False,
    "privacy_policy_version": "",
    "scm_id": "",
}

# 服务器选项（设置页下拉框）
API_SERVERS = [
    ("正式服务（HTTPS）", "https://fantiantradinghub.xyz"),
    ("本地开发", "http://localhost:4000"),
]

_HOTKEY_RE = re.compile(r"^(?:(?:ctrl|shift|alt)\+){0,3}(?:f(?:[1-9]|1[0-2])|[a-z0-9]|space)$")

def _load_config():
    cfg = dict(_API_DEFAULTS)
    loaded = load_json_object(CONFIG_PATH)
    if loaded:
        hotkey = str(loaded.get("hotkey", "")).lower().strip()
        if _HOTKEY_RE.fullmatch(hotkey):
            cfg["hotkey"] = hotkey
        try:
            cfg["api_base"] = normalize_api_base(loaded.get("api_base"))
        except Exception:
            pass
        cfg["privacy_agreed"] = loaded.get("privacy_agreed") is True
        if isinstance(loaded.get("privacy_policy_version"), str):
            cfg["privacy_policy_version"] = loaded["privacy_policy_version"]
        try:
            cfg["scm_id"] = normalize_scm_id(loaded.get("scm_id"))
        except ValueError:
            cfg["scm_id"] = ""
        if isinstance(loaded.get("device_id"), str):
            cfg["device_id"] = loaded["device_id"]
    return cfg

def _save_config(cfg: dict):
    safe = {
        "hotkey": cfg.get("hotkey", "f3"),
        "api_base": normalize_api_base(cfg.get("api_base", _API_DEFAULTS["api_base"])),
        "privacy_agreed": cfg.get("privacy_agreed") is True,
        "privacy_policy_version": str(cfg.get("privacy_policy_version", "")),
        "scm_id": normalize_scm_id(cfg.get("scm_id")),
        "device_id": cfg.get("device_id", ""),
    }
    atomic_write_json(CONFIG_PATH, safe)

_config = _load_config()
_config.setdefault("privacy_agreed", False)
_config.setdefault("privacy_policy_version", "")
if not is_valid_device_id(_config.get("device_id")):
    _config["device_id"] = str(uuid.uuid4())
# Rewrite only the validated configuration subset on startup.
_save_config(_config)
_current_hotkey = _config.get("hotkey", "f3")

_trigger_event = threading.Event()
_hotkey_handle = None

def _on_hotkey():
    _trigger_event.set()

def _register_hotkey(key: str):
    """Register first, then release the old handle so failure is non-destructive."""
    global _current_hotkey, _hotkey_handle
    if not _HOTKEY_RE.fullmatch(str(key).lower().strip()):
        return False
    try:
        new_handle = keyboard.add_hotkey(key, _on_hotkey)
        old_handle = _hotkey_handle
        _hotkey_handle = new_handle
        _current_hotkey = key
        if old_handle is not None:
            try:
                keyboard.remove_hotkey(old_handle)
            except Exception:
                pass
        return True
    except Exception:
        return False

_PREVIEW_MODE = os.environ.get("FT_DESKTOP_UI_PREVIEW") == "1"
_hotkey_registered = False if _PREVIEW_MODE else _register_hotkey(_current_hotkey)

# ════════════════ 配置 ════════════════
try:
    API_BASE = normalize_api_base(os.environ.get("FT_API", _config["api_base"]))
except Exception:
    API_BASE = _API_DEFAULTS["api_base"]

# ── 资源路径 ──
def _asset_path(name: str) -> str:
    """打包后资源在 sys._MEIPASS，开发时在 exe/脚本旁 assets/ 目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, "assets", name)
    return os.path.join(_BASE_DIR, "assets", name)

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
    _ocr_service_dir = os.environ.get("FT_OCR_SERVICE_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "sc-trading-hub",
        "ocr-service",
    )
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
    finished = Signal(dict)
    error = Signal(str)

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
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, data: dict):
        super().__init__()
        self.data = data

    def run(self):
        try:
            self.finished.emit(secure_post_json(
                API_BASE,
                "/api/upload/snapshot",
                self.data,
                timeout=10,
            ))
        except Exception as e:
            self.error.emit(str(e))


class UpdateCheckWorker(QThread):
    """Fetch the public release record without blocking the UI thread."""
    finished = Signal(str)

    def run(self):
        self.finished.emit(check_for_update(API_BASE, APP_VERSION) or "")


# ════════════════ Toast 通知气泡 ════════════════

class Toast(QWidget):
    """Frameless bottom-right notification bubble, gold theme, auto-dismiss."""
    _active = []

    def __init__(self, title: str, text: str, ok: bool = True):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._accent = "#167C78" if ok else "#B64D4F"
        self.setStyleSheet(f"""
            QLabel#t {{ color: {self._accent}; font-weight: bold; font-size: 13px;
                background: transparent; }}
            QLabel#b {{ color: #14292F; font-size: 12px; background: transparent; }}
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
        p.setBrush(QColor("#FBFDFC"))
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

        heading_row = QHBoxLayout()
        heading = QLabel("本地上传记录")
        heading.setObjectName("sectionTitle")
        heading_row.addWidget(heading)
        heading_row.addStretch()
        clear_button = QPushButton("清除历史与截图")
        clear_button.setObjectName("dangerButton")
        clear_button.clicked.connect(self._clear_history)
        heading_row.addWidget(clear_button)
        layout.addLayout(heading_row)

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
        self.status_label.setStyleSheet("font-weight: bold; color: #167C78;")
        rl.addWidget(self.status_label)

        self.info_label = QLabel("点击左侧日志查看详情")
        self.info_label.setStyleSheet("color: #6E7F83;")
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
            "color: #6E7F83; background: #FBFDFC; border: 1px solid #CFDAD7; border-radius: 12px;")
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
        resolved = history.resolve_screenshot_path(shot)
        full = str(resolved) if resolved else ""
        # 优先用缩略图（小文件，省解码内存）；没有则回退原图
        thumb = _thumb_path(full) if full else ""
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

    def _clear_history(self):
        answer = QMessageBox.question(
            self,
            "清除本地记录",
            "将永久删除本机上传历史、截图和缩略图。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = history.clear_entries()
        self._entries = []
        self.list_widget.clear()
        self.detail_table.setRowCount(0)
        self.status_label.setText("")
        self.info_label.setText(f"已清除 {removed} 条本地记录")
        self.img_label.setPixmap(QPixmap())
        self.img_label.setText("无截图")

    def _show_entry(self, idx: int):
        if idx < 0 or idx >= len(self._entries):
            return
        e = self._entries[idx]
        status_map = {"success": ("提交成功", "#167C78"),
                      "submit_failed": ("提交失败", "#B64D4F"),
                      "check_failed": ("检查未通过", "#B64D4F")}
        name, color = status_map.get(e.get("status", ""), (e.get("status", "未知"), "#6E7F83"))
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
        resolved = history.resolve_screenshot_path(shot)
        full = str(resolved) if resolved else ""
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
    key_captured = Signal(str)

    def __init__(self, current_key: str):
        super().__init__(f"当前: {current_key.upper()}  —  点击后按下新快捷键")
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            QLineEdit { background: #E7EEEC; border: 2px dashed #CFDAD7;
                padding: 12px 24px; font-size: 16px; color: #6E7F83;
                border-radius: 12px; min-height: 50px; }
            QLineEdit:focus { border-color: #167C78; background: #FBFDFC; color: #14292F; }
        """)
        self._capturing = False

    def mousePressEvent(self, event):
        self._capturing = True
        self.setText("按下快捷键...")
        self.setStyleSheet("""
            QLineEdit { background: #FBFDFC; border: 2px solid #167C78;
                padding: 12px 24px; font-size: 16px; color: #167C78;
                border-radius: 12px; min-height: 50px; }
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
                QLineEdit { background: #E7EEEC; border: 2px dashed #167C78;
                    padding: 12px 24px; font-size: 16px; color: #14292F;
                    border-radius: 12px; min-height: 50px; }
            """)
        else:
            self.setText("未识别的按键，请重试")


class SettingsTab(QWidget):
    """Settings tab embedded in main window."""
    hotkey_changed = Signal(str)
    server_changed = Signal(str)
    show_privacy = Signal()

    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QWidget { background: #F2F5F4; }
            QLabel { color: #14292F; font-size: 13px; }
            QLabel#title { font-size: 18px; font-weight: 700; color: #167C78; }
            QLabel#mutedText { color: #6E7F83; }
            QPushButton { background: #FBFDFC; color: #14292F; border: 1px solid #CFDAD7;
                padding: 0 20px; min-height: 36px; border-radius: 12px; font-size: 14px; }
            QPushButton:hover { background: #E7EEEC; border-color: #167C78; }
            QPushButton:focus { border: 2px solid #167C78; }
            QPushButton#saveBtn { background: #167C78; color: #fff; border: none;
                font-weight: 700; padding: 0 28px; min-height: 38px; }
            QPushButton#saveBtn:hover { background: #155F5D; }
            QPushButton#saveBtn:disabled { background: #CFDAD7; color: #6E7F83; }
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
        self.hint_label.setStyleSheet("color: #6E7F83; font-size: 11px;")
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

        layout.addSpacing(12)
        layout.addWidget(QLabel("积分账号与隐私"))

        anonymous_hint = QLabel(
            "使用前必须填写 SCM ID，可为自己账户累计积分；SCM ID 可在网页账户窗口中看到。"
        )
        anonymous_hint.setObjectName("mutedText")
        anonymous_hint.setWordWrap(True)
        layout.addWidget(anonymous_hint)

        account_btn_row = QHBoxLayout()
        account_btn = QPushButton("设置 SCM ID / 隐私")
        account_btn.clicked.connect(lambda: self.show_privacy.emit())
        account_btn_row.addWidget(account_btn)
        account_btn_row.addStretch()
        layout.addLayout(account_btn_row)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self._reset)
        btn_row.addWidget(cancel_btn)
        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("saveBtn")
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setEnabled(False)
        self.server_combo.currentIndexChanged.connect(lambda _index: self.save_btn.setEnabled(True))
        btn_row.addWidget(self.save_btn)
        layout.addLayout(btn_row)

    def _on_key_captured(self, key: str):
        self._captured_key = key
        self.hint_label.setText(f"已捕获: {key.upper()}  —  点击「保存」生效")
        self.save_btn.setEnabled(True)

    def _reset(self):
        self._captured_key = None
        self.capture_widget.setText(f"当前: {_current_hotkey.upper()}  —  点击后按下新快捷键")
        for index in range(self.server_combo.count()):
            if self.server_combo.itemData(index) == _config.get("api_base"):
                self.server_combo.setCurrentIndex(index)
                break
        self.hint_label.setText("未保存的更改已撤销")
        self.save_btn.setEnabled(False)

    def _save(self):
        global _config, _current_hotkey, API_BASE
        saved = []

        # 服务器选择
        try:
            api_base = normalize_api_base(self.server_combo.currentData())
        except Exception as exc:
            QMessageBox.warning(self, "服务器地址不安全", str(exc))
            return
        if api_base and api_base != _config.get("api_base"):
            _config["api_base"] = api_base
            API_BASE = api_base
            self.server_changed.emit(api_base)
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


# ════════════════ 关于 ════════════════
_PRIVACY_HTML = """
<h3 style="color:#167C78;">隐私政策</h3>
<p><b>个人信息处理者：</b>与网站 ICP 备案主体一致，完整名称/姓名在
<a href="https://fantiantradinghub.xyz/privacy">网站隐私政策</a>中实时公示。</p>
<p><b>一、我们收集哪些信息</b></p>
<p>1. 从您按 {hotkey} 主动截取的交易终端画面中识别出的结构化数据（终端、商品、买卖类型、价格和库存）；</p>
<p>2. 桌面助手版本号与本机随机生成的设备标识（仅用于版本兼容、上传限流、重复检测和多来源确认，不用于确认真实身份）；</p>
<p>3. 请求来源 IP（服务安全与滥用防护），以及您填写的 SCM ID。</p>
<p><b>截图说明：</b>截图与上传历史保存在当前 Windows 用户的本地应用数据目录，用于识别和本地回看；截图不会随行情数据上传，您可在日志页一键清除。</p>
<p><b>二、我们如何使用信息</b></p>
<p>1. 符合多来源一致性规则的行情可自动公开，来源不足或异常的数据等待管理员复核；</p>
<p>2. 使用桌面助手必须填写 SCM ID 并同意本政策。SCM ID 仅用于匹配已注册账号并记录积分，不影响审核、限流或封禁。该 ID 由您手动填写，不能证明身份，请勿填写他人的 ID。</p>
<p><b>三、保存期限与安全日志</b></p>
<p>结构化行情、审核记录与必要的来源信息存储于中华人民共和国境内的服务器。设备标识、SCM ID、来源 IP、审核证据及最小化安全日志保存 30 天，随后删除或不可逆匿名化；无法再识别个人的公开行情可作为价格历史长期保留。</p>
<p>安全日志只记录 IP 地址、访问时间、请求路径和响应状态，不得记录请求正文、Cookie、Authorization 或任何密钥。公开行情不会显示设备标识、SCM ID 或来源 IP。</p>
<p><b>四、您的权利与撤回同意</b></p>
<p>您可以在“偏好设置 → 设置 SCM ID / 隐私”中修改 SCM ID 或撤回同意；撤回后工具将停止截图与上传，且不影响撤回前处理的效力。如需查询、复制、更正或删除个人信息，请联系下方渠道，我们将在 15 个工作日内处理。</p>
<p><b>五、未成年人保护</b></p>
<p>未满 14 周岁用户不得使用桌面助手的截图或行情上传功能，并应由监护人联系我们删除已提交的个人信息。</p>
<p><b>六、政策更新</b></p>
<p>若个人信息处理目的、方式或种类发生变化，我们会重新告知并取得您的同意，不以继续使用替代重新同意。本政策版本变化后，桌面助手会要求您再次确认。</p>
<p>联系方式：QQ 群 1083464126</p>
<p style="color:#6E7F83;font-size:11px;">政策版本：2026-08-28</p>
"""

_LICENSES_HTML = """
<h3 style="color:#167C78;">开源许可</h3>
<p>本工具基于以下开源项目构建，特此致谢：</p>
<table cellpadding="4" cellspacing="0" style="border-collapse:collapse;">
<tr><td style="border-bottom:1px solid #CFDAD7;">PySide6 / Qt</td><td style="border-bottom:1px solid #CFDAD7;">LGPL-3.0</td><td style="border-bottom:1px solid #CFDAD7;">界面框架</td></tr>
<tr><td style="border-bottom:1px solid #CFDAD7;">CnOCR</td><td style="border-bottom:1px solid #CFDAD7;">Apache-2.0</td><td style="border-bottom:1px solid #CFDAD7;">文字识别引擎</td></tr>
<tr><td style="border-bottom:1px solid #CFDAD7;">CnStd</td><td style="border-bottom:1px solid #CFDAD7;">Apache-2.0</td><td style="border-bottom:1px solid #CFDAD7;">文本检测</td></tr>
<tr><td style="border-bottom:1px solid #CFDAD7;">RapidOCR</td><td style="border-bottom:1px solid #CFDAD7;">Apache-2.0</td><td style="border-bottom:1px solid #CFDAD7;">OCR 模型（PP-OCRv6）</td></tr>
<tr><td style="border-bottom:1px solid #CFDAD7;">opencv-python</td><td style="border-bottom:1px solid #CFDAD7;">Apache-2.0</td><td style="border-bottom:1px solid #CFDAD7;">图像处理</td></tr>
<tr><td style="border-bottom:1px solid #CFDAD7;">requests</td><td style="border-bottom:1px solid #CFDAD7;">Apache-2.0</td><td style="border-bottom:1px solid #CFDAD7;">HTTP 客户端</td></tr>
<tr><td style="border-bottom:1px solid #CFDAD7;">mss</td><td style="border-bottom:1px solid #CFDAD7;">MIT</td><td style="border-bottom:1px solid #CFDAD7;">屏幕截图</td></tr>
<tr><td style="border-bottom:1px solid #CFDAD7;">keyboard</td><td style="border-bottom:1px solid #CFDAD7;">MIT</td><td style="border-bottom:1px solid #CFDAD7;">全局快捷键</td></tr>
<tr><td style="border-bottom:1px solid #CFDAD7;">ONNX Runtime</td><td style="border-bottom:1px solid #CFDAD7;">MIT</td><td style="border-bottom:1px solid #CFDAD7;">模型推理</td></tr>
<tr><td style="border-bottom:1px solid #CFDAD7;">Pillow</td><td style="border-bottom:1px solid #CFDAD7;">MIT-CMU</td><td style="border-bottom:1px solid #CFDAD7;">图像处理</td></tr>
<tr><td style="border-bottom:1px solid #CFDAD7;">NumPy</td><td style="border-bottom:1px solid #CFDAD7;">BSD-3-Clause</td><td style="border-bottom:1px solid #CFDAD7;">数值计算</td></tr>
<tr><td>PyInstaller</td><td>GPL（bootloader 例外）</td><td>构建期组件，未随程序分发</td></tr>
</table>
<p style="margin-top:10px;"><b>软件许可边界：</b>泛天贸易中心桌面助手自身为专有软件。本工具使用 PySide6 与 Qt 的社区版本，相关库依据
GNU LGPL 第 3 版提供。安装目录中的 Qt/PySide6 动态库保持为独立文件，您可以使用接口兼容的修改版本替换它们，
也可以为调试这些修改进行必要的逆向工程。GNU GPL 第 3 版与 LGPL 第 3 版完整文本随安装包提供。</p>
"""

class AboutTab(QWidget):
    """关于页：logo + 版本 + 隐私政策 + 开源许可。"""

    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QWidget { background: #F2F5F4; }
            QLabel { color: #14292F; }
            QLabel#title { font-size: 18px; font-weight: 700; color: #167C78; }
            QTextBrowser { background: #FBFDFC; color: #14292F; border: 1px solid #CFDAD7;
                border-radius: 12px; padding: 8px; font-size: 12px; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        logo_path = _asset_path("logo.png")
        if os.path.exists(logo_path):
            logo_label = QLabel()
            logo_pix = QPixmap(logo_path)
            if not logo_pix.isNull():
                logo_label.setPixmap(logo_pix.scaledToWidth(180, Qt.TransformationMode.SmoothTransformation))
                logo_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                layout.addWidget(logo_label)

        title = QLabel("泛天贸易中心桌面助手")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)

        version_label = QLabel(f"版本 {APP_VERSION}")
        version_label.setStyleSheet("color: #6E7F83; font-size: 11px;")
        version_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(version_label)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(
            _PRIVACY_HTML.format(hotkey=_current_hotkey.upper()) +
            "<hr style='border:none;border-top:1px solid #CFDAD7;margin:12px 0;'>" +
            _LICENSES_HTML
        )
        layout.addWidget(self.browser, 1)

        contact = QLabel("泛天商会 · QQ 群 1083464126 · fantiantradinghub.xyz")
        contact.setStyleSheet("color: #6E7F83; font-size: 11px;")
        contact.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(contact)


class FirstRunDialog(QDialog):
    """Configure optional points ID and upload consent."""

    def __init__(self, parent=None, require_ready=False):
        super().__init__(parent)
        self.require_ready = require_ready
        self.setWindowTitle("上传与隐私设置 - 泛天贸易中心")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet("""
            QDialog { background: #F2F5F4; }
            QLabel { color: #14292F; font-size: 13px; }
            QLabel#title { font-size: 16px; font-weight: 700; color: #167C78; }
            QLabel#hint { color: #6E7F83; font-size: 11px; }
            QLineEdit { background: #FBFDFC; color: #14292F; border: 1px solid #CFDAD7;
                padding: 6px 8px; border-radius: 12px; font-size: 13px; }
            QLineEdit:focus { border: 2px solid #167C78; }
            QPushButton { background: #FBFDFC; color: #14292F; border: 1px solid #CFDAD7;
                padding: 0 14px; min-height: 36px; border-radius: 12px; font-size: 13px; }
            QPushButton:hover { background: #E7EEEC; border-color: #167C78; }
            QPushButton:focus { border: 2px solid #167C78; }
            QPushButton#confirmBtn { background: #167C78; color: #fff; border: none;
                font-weight: 700; padding: 0 24px; min-height: 38px; }
            QPushButton#confirmBtn:hover { background: #155F5D; }
            QPushButton#confirmBtn:disabled { background: #CFDAD7; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

        title = QLabel("欢迎使用泛天贸易中心桌面助手")
        title.setObjectName("title")
        layout.addWidget(title)

        hint = QLabel("使用前请填写 SCM ID，并阅读和同意隐私政策。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(QLabel("SCM ID（必填）"))
        self.scm_input = QLineEdit()
        self.scm_input.setMaxLength(100)
        self.scm_input.setPlaceholderText("可在网页账户窗口中查看")
        self.scm_input.setText(_config.get("scm_id", ""))
        layout.addWidget(self.scm_input)

        agree_row = QHBoxLayout()
        self.privacy_check = QCheckBox("我已阅读并同意《隐私政策》")
        self.privacy_check.setChecked(
            is_upload_ready(
                _config.get("scm_id"),
                _config.get("privacy_agreed", False),
                _config.get("privacy_policy_version", ""),
            )
        )
        agree_row.addWidget(self.privacy_check)
        agree_row.addStretch()
        layout.addLayout(agree_row)

        policy_row = QHBoxLayout()
        policy_btn = QPushButton("查看隐私政策")
        policy_btn.clicked.connect(self._show_policy)
        policy_row.addWidget(policy_btn)
        policy_row.addStretch()
        layout.addLayout(policy_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.confirm_btn = QPushButton("保存设置")
        self.confirm_btn.setObjectName("confirmBtn")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self._confirm)
        btn_row.addWidget(self.confirm_btn)
        layout.addLayout(btn_row)

        self.privacy_check.stateChanged.connect(lambda _s: self._update_confirm())
        self.scm_input.textChanged.connect(lambda _text: self._update_confirm())
        self._update_confirm()

    def _update_confirm(self):
        if not self.require_ready:
            # Settings mode still permits withdrawing consent or clearing data.
            self.confirm_btn.setEnabled(True)
            return
        self.confirm_btn.setEnabled(
            is_upload_ready(
                self.scm_input.text(),
                self.privacy_check.isChecked(),
                PRIVACY_POLICY_VERSION,
            )
        )

    def _show_policy(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("隐私政策")
        dlg.setFixedSize(520, 480)
        dlg.setStyleSheet("QDialog { background: #F2F5F4; } QTextBrowser { background: #FBFDFC; border: 1px solid #CFDAD7; border-radius: 12px; font-size: 12px; }")
        lay = QVBoxLayout(dlg)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(_PRIVACY_HTML.format(hotkey=_current_hotkey.upper()))
        lay.addWidget(browser)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_row.addWidget(close_btn)
        lay.addLayout(close_row)
        dlg.exec()

    def _confirm(self):
        try:
            scm_id = normalize_scm_id(self.scm_input.text())
        except ValueError as exc:
            QMessageBox.warning(self, "SCM ID 无效", str(exc))
            return
        if self.require_ready and not scm_id:
            QMessageBox.warning(self, "请填写 SCM ID", "SCM ID 可在网页账户窗口中查看。")
            return
        if self.require_ready and not self.privacy_check.isChecked():
            QMessageBox.warning(self, "请同意隐私政策", "同意隐私政策后才能使用桌面助手。")
            return
        _config["scm_id"] = scm_id
        _config["privacy_agreed"] = self.privacy_check.isChecked()
        _config["privacy_policy_version"] = (
            PRIVACY_POLICY_VERSION if self.privacy_check.isChecked() else ""
        )
        _save_config(_config)
        self.accept()


# ════════════════ 主窗口 ════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("泛天贸易中心 - 数据上传")
        self.setMinimumSize(900, 600)

        # 泛天贸易中心网站设计语言：深海蓝品牌栏 + 冷灰白工作区。
        self.setStyleSheet("""
            QMainWindow, QWidget#central { background: #F2F5F4; }
            QLabel { color: #14292F; font-size: 13px; }
            QFrame#brandHeader { background: #14292F; border: none; }
            QLabel#brandEyebrow { color: #B8892F; font-size: 11px; font-weight: 700; }
            QLabel#brandTitle { color: #FBFDFC; font-size: 20px; font-weight: 700; }
            QLabel#brandMeta { color: #AFC0C0; font-size: 11px; }
            QLabel#secureChip { background: #155F5D; color: #F3FBFA; border: 1px solid #5F9F9C;
                border-radius: 12px; padding: 4px 10px; font-size: 11px; font-weight: 700; }
            QFrame#pipelineCard { background: #FBFDFC; border: 1px solid #CFDAD7; border-radius: 12px; }
            QLabel#pipelineStep { color: #6E7F83; border: 1px solid #CFDAD7;
                border-radius: 10px; padding: 7px 12px; font-weight: 600; }
            QLabel#pipelineStep[state="active"] { color: #167C78; background: #DCEBEA; border-color: #167C78; }
            QLabel#pipelineStep[state="done"] { color: #155F5D; background: #E7EEEC; border-color: #9AB9B6; }
            QLabel#pipelineStep[state="error"] { color: #B64D4F; background: #FAEAEA; border-color: #B64D4F; }
            QLabel#pipelineArrow { color: #B8892F; font-size: 16px; }
            QLabel#pipelineMessage { color: #6E7F83; font-size: 11px; }
            QLabel#sectionTitle { color: #14292F; font-size: 17px; font-weight: 700; }
            QLineEdit {
                background: #FBFDFC; color: #14292F; border: 1px solid #CFDAD7;
                padding: 5px 8px; border-radius: 12px; font-size: 12px;
            }
            QComboBox { background: #FBFDFC; color: #14292F; border: 1px solid #CFDAD7;
                border-radius: 12px; padding: 0 10px; min-height: 36px; }
            QComboBox::drop-down { border: none; width: 28px; }
            QCheckBox { color: #14292F; spacing: 8px; }
            QLineEdit:focus, QComboBox:focus { border: 2px solid #167C78; }
            QTableWidget {
                background: #FBFDFC; color: #14292F; gridline-color: #E4EAE8;
                border: 1px solid #CFDAD7; font-size: 12px; border-radius: 12px;
            }
            QTableWidget::item:selected { background: #167C78; color: #fff; }
            QHeaderView::section {
                background: #E7EEEC; color: #14292F; padding: 7px 5px;
                border: none; border-bottom: 1px solid #CFDAD7; font-size: 12px; font-weight: 700;
            }
            QPushButton {
                background: #FBFDFC; color: #14292F; border: 1px solid #CFDAD7;
                padding: 0 16px; min-height: 36px; border-radius: 12px; font-size: 13px;
            }
            QPushButton:hover { background: #E7EEEC; border-color: #167C78; }
            QPushButton:focus { border: 2px solid #167C78; }
            QPushButton:disabled { background: #E4EAE8; color: #6E7F83; border-color: #CFDAD7; }
            QPushButton#dangerButton { color: #B64D4F; border-color: #D9A6A7; }
            QPushButton#dangerButton:hover { background: #FAEAEA; border-color: #B64D4F; }
            QStatusBar { background: #FBFDFC; color: #6E7F83; border-top: 1px solid #CFDAD7; }
            QSplitter::handle { background: #CFDAD7; width: 1px; }
            QListWidget {
                background: #F2F5F4; color: #14292F; border: none; font-size: 11px;
            }
            QListWidget::item { border: 1px solid transparent; border-radius: 12px; padding: 3px; }
            QListWidget::item:selected { background: #DCEBEA; border: 1px solid #167C78; color: #14292F; }
        """)

        central = QWidget()
        central.setObjectName("central")
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        self.setCentralWidget(central)

        header = QFrame()
        header.setObjectName("brandHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 13, 20, 13)
        header_layout.setSpacing(12)
        logo_path = _asset_path("logo.png")
        if os.path.exists(logo_path):
            logo = QLabel()
            logo_pixmap = QPixmap(logo_path)
            if not logo_pixmap.isNull():
                logo.setPixmap(logo_pixmap.scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
                header_layout.addWidget(logo)
        brand_stack = QVBoxLayout()
        brand_stack.setSpacing(1)
        eyebrow = QLabel("FANTIAN TRADING HUB")
        eyebrow.setObjectName("brandEyebrow")
        brand_stack.addWidget(eyebrow)
        brand_title = QLabel("泛天贸易中心桌面助手")
        brand_title.setObjectName("brandTitle")
        brand_stack.addWidget(brand_title)
        brand_meta = QLabel(f"行情采集工作台 · v{APP_VERSION}")
        brand_meta.setObjectName("brandMeta")
        brand_stack.addWidget(brand_meta)
        header_layout.addLayout(brand_stack)
        header_layout.addStretch()
        self.secure_chip = QLabel()
        self.secure_chip.setObjectName("secureChip")
        header_layout.addWidget(self.secure_chip)
        central_layout.addWidget(header)

        pipeline = QFrame()
        pipeline.setObjectName("pipelineCard")
        pipeline_layout = QHBoxLayout(pipeline)
        pipeline_layout.setContentsMargins(16, 10, 16, 10)
        pipeline_layout.setSpacing(9)
        self.pipeline_steps = []
        for index, text in enumerate(("本机截图", "本地识别", "安全上传")):
            step = QLabel(f"0{index + 1}  {text}")
            step.setObjectName("pipelineStep")
            step.setProperty("state", "idle")
            self.pipeline_steps.append(step)
            pipeline_layout.addWidget(step)
            if index < 2:
                arrow = QLabel("→")
                arrow.setObjectName("pipelineArrow")
                pipeline_layout.addWidget(arrow)
        self.pipeline_message = QLabel("数据只在识别完成并通过校验后上传")
        self.pipeline_message.setObjectName("pipelineMessage")
        pipeline_layout.addWidget(self.pipeline_message, 1)
        central_layout.addWidget(pipeline)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background: #F2F5F4; }
            QTabBar::tab { background: #E7EEEC; color: #6E7F83; padding: 10px 24px;
                border: none; border-bottom: 2px solid transparent; font-size: 13px; }
            QTabBar::tab:selected { background: #F2F5F4; color: #167C78;
                border-bottom: 2px solid #167C78; font-weight: 700; }
            QTabBar::tab:hover { color: #14292F; }
            QTabBar::tab:focus { border: 2px solid #167C78; }
        """)
        central_layout.addWidget(self.tabs, 1)

        # ── Tab 0: 日志（首页） ──
        self.log_tab = LogTab()

        # ── Tab 1: 偏好设置 ──
        self.settings_tab = SettingsTab()
        self.settings_tab.hotkey_changed.connect(self._on_hotkey_changed)
        self.settings_tab.server_changed.connect(self._update_security_chip)

        # ── Tab 2: 关于 ──
        self.about_tab = AboutTab()
        self.settings_tab.show_privacy.connect(self._show_account_dialog)

        self.tabs.addTab(self.log_tab, "日志")
        self.tabs.addTab(self.settings_tab, "偏好设置")
        self.tabs.addTab(self.about_tab, "关于")

        # 状态栏
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage(f"就绪  |  按 {_current_hotkey.upper()} 截图")

        # 窗口显示后启动热键轮询
        if not _PREVIEW_MODE:
            QTimer.singleShot(200, self._start_hotkey_timer)
            # Optional background work: a failed release check never affects use.
            QTimer.singleShot(1000, self._check_for_update)
            # 预加载 OCR 模型（后台线程，GUI 无感）
            threading.Thread(target=_preload_ocr, daemon=True).start()

        # 当前数据
        self.current_result = None
        self._current_shot = None
        self._update_security_chip(API_BASE)
        self._set_pipeline("idle", "就绪：等待本机截图")
        if not _hotkey_registered and not _PREVIEW_MODE:
            QTimer.singleShot(0, self._show_hotkey_fallback)

    # ── 偏好设置回调 ────────────────────────

    def _on_hotkey_changed(self, new_key: str):
        self.status.showMessage(f"热键已更新: {new_key.upper()}  |  截图识别")

    def _show_hotkey_fallback(self):
        self.status.showMessage("全局热键不可用 · 请在偏好设置中更换快捷键")
        QMessageBox.information(
            self,
            "全局热键不可用",
            "请在偏好设置中更换快捷键后重试。",
        )

    def _update_security_chip(self, api_base: str):
        if normalize_api_base(api_base).startswith("https://"):
            self.secure_chip.setText("HTTPS · 传输加密")
        else:
            self.secure_chip.setText("LOCAL · 本机开发")

    def _set_pipeline(self, stage: str, message: str, *, error: bool = False):
        stage_index = {"capture": 0, "ocr": 1, "upload": 2}.get(stage, -1)
        for index, label in enumerate(self.pipeline_steps):
            if error and index == stage_index:
                state = "error"
            elif stage_index >= 0 and index < stage_index:
                state = "done"
            elif index == stage_index:
                state = "active"
            elif stage == "done":
                state = "done"
            else:
                state = "idle"
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)
        self.pipeline_message.setText(message)

    def _check_for_update(self):
        self._update_check_worker = UpdateCheckWorker()
        self._update_check_worker.finished.connect(self._show_update_notice)
        self._update_check_worker.start()

    def _show_update_notice(self, version: str):
        if not version:
            return
        answer = QMessageBox.question(
            self,
            "发现新版本",
            f"发现泛天数据上传工具 v{version}，是否前往数据采集页查看更新方式？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(DATA_COLLECTION_URL))

    # ── OCR 处理 ──────────────────────────

    def _process_shot(self, file_path: str):
        self._current_shot = file_path
        self.status.showMessage("OCR 识别中...")
        self._set_pipeline("ocr", "截图仅在本机进入 OCR 识别")

        self.worker = OcrWorker(file_path)
        self.worker.finished.connect(self.on_ocr_done)
        self.worker.error.connect(self.on_ocr_error)
        self.worker.start()

    def on_ocr_done(self, result: dict):
        if not result.get("ok"):
            self._set_pipeline("ocr", "本地识别失败，未上传任何行情", error=True)
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
            self._set_pipeline("upload", "校验通过，正在通过安全连接上传")
            self.do_submit()
        else:
            self._set_pipeline("ocr", "本地校验未通过，已阻止上传", error=True)
            self.status.showMessage("检查未通过，未提交")
            shown = reasons[:3]
            extra = f"（共{len(reasons)}个问题）" if len(reasons) > 3 else ""
            Toast("提交失败", "\n".join(shown) + extra, ok=False).show_at_corner()
            self._log_outcome("check_failed", "; ".join(reasons))

    def on_ocr_error(self, err_msg: str):
        self._set_pipeline("ocr", "OCR 服务不可用，已阻止上传", error=True)
        self.status.showMessage(f"OCR 服务不可用: {err_msg}")
        Toast("提交失败", f"OCR 服务不可用: {err_msg}", ok=False).show_at_corner()
        self._log_outcome("check_failed", f"OCR 服务不可用: {err_msg}")

    # ── 提交 ─────────────────────────────

    def do_submit(self):
        """Auto-submit current OCR result. Called after validate_result passes."""
        if not self.current_result:
            return
        # Explicit consent is required whether or not points metadata is present.
        if not is_upload_ready(
            _config.get("scm_id"),
            _config.get("privacy_agreed", False),
            _config.get("privacy_policy_version", ""),
        ):
            self._set_pipeline("upload", "未同意隐私政策，已阻止上传", error=True)
            self.status.showMessage("未同意隐私政策，已阻止上传")
            Toast("已阻止上传", "请先设置 SCM ID 并同意隐私政策", ok=False).show_at_corner()
            return

        self.status.showMessage("提交中...")
        self.worker2 = SubmitWorker(build_snapshot_payload(
            self.current_result,
            _config.get("scm_id", ""),
            _config.get("device_id", ""),
        ))
        self.worker2.finished.connect(self.on_submit_done)
        self.worker2.error.connect(self.on_submit_error)
        self.worker2.start()

    def on_submit_done(self, resp: dict):
        if resp.get("ok"):
            self._set_pipeline("done", "安全上传完成，本地记录已更新")
            n = resp.get("upserted", 0)
            promoted = resp.get("promoted", 0)
            pending = resp.get("pending", 0)
            if isinstance(promoted, int) and promoted > 0 and isinstance(pending, int) and pending > 0:
                result_detail = f"已接收 {n} 条：{promoted} 条已公开，{pending} 条待审核"
            elif isinstance(promoted, int) and promoted > 0:
                result_detail = f"已接收 {n} 条，已通过一致性校验并公开"
            else:
                result_detail = f"已接收 {n} 条，等待管理员审核"
            points = resp.get("points") if isinstance(resp.get("points"), dict) else {}
            credited = points.get("credited", 0)
            if isinstance(credited, int) and credited > 0:
                total = points.get("total")
                points_detail = f"本次 +{credited} 积分"
                if isinstance(total, int):
                    points_detail += f"，本月共 {total} 积分"
            elif points.get("note"):
                points_detail = str(points["note"])
            elif points.get("capped"):
                points_detail = "今日积分已达上限"
            elif points.get("duplicates"):
                points_detail = "重复数据不计积分"
            else:
                points_detail = "本次未增加积分"
            self.status.showMessage(f"处理完成: {n} 条")
            toast_detail = result_detail + f"\n{points_detail}"
            Toast("上传处理完成", toast_detail).show_at_corner()
            self._log_outcome("success", toast_detail.replace("\n", "；"))
        else:
            self._set_pipeline("upload", "服务器未接受本次数据", error=True)
            self.status.showMessage("提交失败")
            Toast("提交失败", resp.get("error", "未知错误"), ok=False).show_at_corner()
            self._log_outcome("submit_failed", resp.get("error", "未知错误"))

    def on_submit_error(self, err_msg: str):
        self._set_pipeline("upload", "安全上传失败，请检查网络后重试", error=True)
        self.status.showMessage("提交失败（网络错误）")
        Toast("提交失败", f"网络错误: {err_msg}", ok=False).show_at_corner()
        self._log_outcome("submit_failed", f"网络错误: {err_msg}")

    # ── 日志记录 ──────────────────────────

    def _log_outcome(self, status: str, detail: str):
        # 每轮结束 2 秒后修剪工作集（把推理峰值内存还给 OS，学 Mem Reduct）
        QTimer.singleShot(2000, _trim_working_set)
        items = []
        if self.current_result:
            items = build_snapshot_items(self.current_result)
        shot = f"screenshots/{Path(self._current_shot).name}" if self._current_shot else ""
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

    def _show_account_dialog(self, require_ready=False):
        FirstRunDialog(self, require_ready=require_ready).exec()

    def _maybe_show_first_run(self):
        """Show privacy settings on first run."""
        if not is_upload_ready(
            _config.get("scm_id"),
            _config.get("privacy_agreed", False),
            _config.get("privacy_policy_version", ""),
        ):
            self._set_pipeline("capture", "请先设置 SCM ID 并同意隐私政策", error=True)
            FirstRunDialog(self, require_ready=True).exec()
            if is_upload_ready(
                _config.get("scm_id"),
                _config.get("privacy_agreed", False),
                _config.get("privacy_policy_version", ""),
            ):
                self._set_pipeline("idle", "设置已保存，等待本机截图")
                self.status.showMessage(f"就绪  |  按 {_current_hotkey.upper()} 截图")

    def _do_screenshot(self):
        """Capture screen via child process (GDI capture leaks ~20MB heap per
        shot in-process; a short-lived child returns it all to the OS)."""
        # Consent gates capture/upload; SCM ID remains optional points metadata.
        if not is_upload_ready(
            _config.get("scm_id"),
            _config.get("privacy_agreed", False),
            _config.get("privacy_policy_version", ""),
        ):
            self.status.showMessage("请先设置 SCM ID 并同意隐私政策")
            Toast("暂不可用", "请先设置 SCM ID 并同意隐私政策", ok=False).show_at_corner()
            self._show_account_dialog(require_ready=True)
            if is_upload_ready(
                _config.get("scm_id"),
                _config.get("privacy_agreed", False),
                _config.get("privacy_policy_version", ""),
            ):
                self._set_pipeline("idle", "设置已保存，请再次按快捷键截图")
                self.status.showMessage(f"设置已保存  |  按 {_current_hotkey.upper()} 截图")
            return
        _play_shutter()
        self._set_pipeline("capture", "正在截取本机画面")
        file_name = time.strftime("sc_shot_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8] + ".png"
        path = os.path.join(SCREENSHOT_DIR, file_name)
        if getattr(sys, 'frozen', False):
            cap_cmd = [os.path.join(os.path.dirname(sys.executable), "FT-Capture.exe"), path]
        else:
            cap_cmd = [sys.executable, os.path.join(_BASE_DIR, "capture_main.py"), path]
        try:
            subprocess.run(cap_cmd, timeout=10)
        except Exception:
            pass
        if not os.path.exists(path):
            self._set_pipeline("capture", "截图失败，未进入识别流程", error=True)
            self.status.showMessage("截图失败")
            return
        _make_thumbnail(path)
        self._process_shot(path)

    def closeEvent(self, event):
        event.accept()

# ════════════════ 入口 ════════════════
def _configure_application_font(app: QApplication):
    """Prefer the website font, with a guaranteed Windows Chinese fallback."""
    families = set(QFontDatabase.families())
    for font_path in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc"):
        if not ({"Noto Sans SC", "Microsoft YaHei UI", "Microsoft YaHei"} & families):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id >= 0:
                families.update(QFontDatabase.applicationFontFamilies(font_id))
    family = next(
        (name for name in ("Noto Sans SC", "Microsoft YaHei UI", "Microsoft YaHei") if name in families),
        app.font().family(),
    )
    font = QFont(family, 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("泛天贸易中心")
    logo_path = _asset_path("logo.png")
    if os.path.exists(logo_path):
        app.setWindowIcon(QIcon(logo_path))
    _configure_application_font(app)

    window = MainWindow()
    window.show()
    # First-run privacy prompt; capture/upload remains blocked until consent.
    if not _PREVIEW_MODE:
        QTimer.singleShot(0, window._maybe_show_first_run)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
