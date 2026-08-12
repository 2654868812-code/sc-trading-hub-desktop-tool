# -*- mode: python ; coding: utf-8 -*-

import os

# SPECPATH is the directory containing this .spec file (provided by PyInstaller)
_spec_dir = SPECPATH
_ocr_dir = os.path.join(_spec_dir, '..', 'sc-trading-hub', 'ocr-service')
_ocr_dir = os.path.normpath(_ocr_dir)

a = Analysis(
    ['main.py'],
    pathex=[_ocr_dir],
    binaries=[],
    datas=[
        (os.path.join(_ocr_dir, 'server.py'), 'ocr-service'),
        (os.path.join(_ocr_dir, 'oneocr.py'), 'ocr-service'),
        # Commodity/location lookup tables for spellcheck
        (os.path.join(_ocr_dir, '..', 'src', 'lib', 'commodity-zh.ts'), 'ocr-service'),
        (os.path.join(_ocr_dir, '..', 'src', 'lib', 'location-zh.ts'), 'ocr-service'),
    ],
    hiddenimports=['server', 'oneocr', 'cnocr', 'mss', 'keyboard'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FT-DataUpload',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    uac_admin=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
