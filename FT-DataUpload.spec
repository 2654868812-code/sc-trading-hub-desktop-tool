# -*- mode: python ; coding: utf-8 -*-

import os

import cnocr
from PyInstaller.utils.hooks import collect_data_files

# SPECPATH is the directory containing this .spec file (provided by PyInstaller)
_spec_dir = SPECPATH
_ocr_dir = os.path.join(_spec_dir, '..', 'sc-trading-hub', 'ocr-service')
_ocr_dir = os.path.normpath(_ocr_dir)
_cnocr_pkg = os.path.dirname(cnocr.__file__)

a = Analysis(
    ['main.py'],
    pathex=[_ocr_dir],
    binaries=[],
    datas=[
        (os.path.join(_ocr_dir, 'server.py'), 'ocr-service'),
        # 快门音
        (os.path.join(_spec_dir, 'shutter.wav'), '.'),
        # Logo（关于页 + 窗口图标）
        (os.path.join(_spec_dir, 'assets', 'logo.png'), 'assets'),
        # Commodity/location lookup tables for spellcheck
        (os.path.join(_ocr_dir, '..', 'src', 'lib', 'commodity-zh.ts'), 'ocr-service'),
        (os.path.join(_ocr_dir, '..', 'src', 'lib', 'location-zh.ts'), 'ocr-service'),
        # CnOCR / CnSTD models — bundled so testers need no download.
        # PyInstaller copies CONTENTS of src into dest — dest must include
        # the version/ppocr path levels that cnocr/cnstd resolve at runtime.
        (os.path.join(os.environ['APPDATA'], 'cnocr', '2.3'), os.path.join('cnocr', '2.3')),
        (os.path.join(os.environ['APPDATA'], 'cnstd', '1.2', 'ppocr'), os.path.join('cnstd', '1.2', 'ppocr')),
        # Rec vocab files — cnocr loads them relative to its package dir
        # (consts.py: CN_VOCAB_FP); missing vocab = garbled recognition
        (os.path.join(_cnocr_pkg, 'label_cn.txt'), 'cnocr'),
        (os.path.join(_cnocr_pkg, 'label_number.txt'), 'cnocr'),
        # Package data files (yaml configs, vocab, etc.) — sweeps everything
        # cnocr/cnstd/rapidocr ship inside their packages
        *collect_data_files('cnocr'),
        *collect_data_files('cnstd'),
        *collect_data_files('rapidocr'),
    ],
    hiddenimports=['server', 'cnocr', 'mss', 'keyboard'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # PaddleOCR fallback in server.py is dead code for the exe (CnOCR always
    # present) — its dependency chain drags in tensorflow/polars (~2GB).
    # NOTE: torch/torchvision must stay — cnocr imports torch unconditionally
    # (cn_ocr.py); excluding it breaks `import torch.hub` and silently falls
    # back to the low-accuracy OneOCR engine. scipy must stay too — cnstd
    # imports it at package level (utils/metrics.py).
    excludes=['tensorflow', 'paddle', 'paddleocr', 'paddlex',
              'modelscope', 'polars', 'pyarrow', 'altair'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FT-DataUpload',
    icon=os.path.join(_spec_dir, 'assets', 'logo.ico'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    # The GUI handles only user-owned screenshots and network requests. Running
    # the entire application elevated turns replaceable bundled files into an
    # administrator-code execution path, so it must remain a standard-user app.
    uac_admin=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FT-DataUpload',
)

# ── 截图子进程 exe（不提权） ──
# mss/GDI 截图每帧残留 ~20MB 堆内存不归还，独立短命进程截完即退、内存归 OS
a_capture = Analysis(
    ['capture_main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['mss'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz_capture = PYZ(a_capture.pure)

exe_capture = EXE(
    pyz_capture,
    a_capture.scripts,
    [],
    exclude_binaries=True,
    name='FT-Capture',
    icon=os.path.join(_spec_dir, 'assets', 'logo.ico'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    uac_admin=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll_capture = COLLECT(
    exe_capture,
    a_capture.binaries,
    a_capture.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FT-Capture',
)
