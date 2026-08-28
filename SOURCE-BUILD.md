# FT-DataUpload Corresponding Source and Build Guide

This archive is the corresponding source for the binary release with the same
version number. The application is distributed under GNU GPL version 3; see
`COPYING`.

## Supported build environment

- Windows 10 or Windows 11, x86-64
- Python 3.12
- The sibling website source tree at `../sc-trading-hub`
- The exact Python versions in `requirements.txt`

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
```

CnOCR and CnSTD model files must be downloaded through their documented model
installation flow before running PyInstaller. `FT-DataUpload.spec` reads those
models from the current Windows user's application-data directory and includes
the exact website OCR helper and lookup tables referenced by the specification.

The build produces the binary archive, the corresponding-source archive,
SHA-256 files for both, and one `release-info.json`. Verify both hashes before
publication. The two archives must be offered together in the same QQ group
file area without charging extra for or restricting access to the source.

If an executable is Authenticode-signed, sign both executables before running
`build_release.py --skip-build`; changing a binary after hashing invalidates the
release metadata.
