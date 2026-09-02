# FT-DataUpload Private Build Audit Guide

This private archive records proprietary application source and build inputs
for internal audit and reproducibility. It is not LGPL corresponding source,
is not referenced by public release metadata, and must not be uploaded to the
public release directory. The application uses the dynamically
linked PySide6 and Qt community libraries under GNU LGPL version 3. See
`COPYING.LESSER`, `COPYING`, `QT-LGPL-SOURCE.md`, and
`THIRD-PARTY-NOTICES.md`.

## Supported build environment

- Windows 10 or Windows 11, x86-64
- Python 3.12
- The sibling website source tree at `../sc-trading-hub`
- The exact Python versions in `requirements.txt`
- Inno Setup 6 or 7 for compiling the Windows installer

The source archive preserves the two repository directories needed by the
PyInstaller specification:

```text
FT-DataUpload-source/
  sc-trading-hub-desktop-tool/
  sc-trading-hub/
```

## Build

From `sc-trading-hub-desktop-tool` in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe build_release.py
.\.venv\Scripts\python.exe build_installer.py
```

CnOCR and CnSTD model files must be downloaded through their documented model
installation flow before running PyInstaller. `FT-DataUpload.spec` reads those
models from the current Windows user's application-data directory and includes
the exact website OCR helper and lookup tables referenced by the specification.

The release build keeps the portable binary archive for local use and writes
the proprietary audit archive under `release/private/`. `build_installer.py` compiles the public
Windows x64 installer. Verify the installer and source hashes recorded in
`release-info.json` before publication. Keep the source archive with its
matching installer so each historical build remains reproducible and auditable.

The installer requests administrator privileges, offers a custom installation
directory, and defaults to `{autopf}\FT-DataUpload`. It always creates a Start
Menu shortcut and offers a desktop shortcut. On uninstall, local configuration,
history, and screenshots are retained unless the user explicitly chooses to
delete `%LOCALAPPDATA%\FantianTradingHub\DesktopAssistant`.

If an executable is Authenticode-signed, sign both executables before running
`build_release.py --skip-build`; changing a binary after hashing invalidates the
release metadata.
