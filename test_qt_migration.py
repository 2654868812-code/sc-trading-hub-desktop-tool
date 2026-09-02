"""Runtime smoke test for the supported Qt binding."""

import os
import subprocess
import sys
import tempfile
import traceback


def test_desktop_ui_starts_without_pyqt6():
    """The packaged UI must depend only on the LGPL Qt for Python binding."""
    probe = r'''
import importlib.abc
import sys

class RejectPyQt6(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PyQt6" or fullname.startswith("PyQt6."):
            raise ModuleNotFoundError("PyQt6 is intentionally unavailable")
        return None

sys.meta_path.insert(0, RejectPyQt6())

from PySide6.QtWidgets import QApplication
import main

app = QApplication.instance() or QApplication([])
about = main.AboutTab()
about.show()
app.processEvents()
assert about.isVisible()
print(about.findChild(main.QTextBrowser).toPlainText())
about.close()
'''
    with tempfile.TemporaryDirectory() as local_app_data:
        environment = dict(os.environ)
        environment.update({
            "FT_DESKTOP_UI_PREVIEW": "1",
            "LOCALAPPDATA": local_app_data,
            "QT_QPA_PLATFORM": "offscreen",
        })
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=os.path.dirname(__file__),
            env=environment,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PySide6" in result.stdout
    assert "LGPL-3.0" in result.stdout
    assert "专有软件" in result.stdout
    assert "本工具整体依据 GNU GPL" not in result.stdout


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}:")
                traceback.print_exc()
    print(f"{failed} failed")
    sys.exit(1 if failed else 0)
