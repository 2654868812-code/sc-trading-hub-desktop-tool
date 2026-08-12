"""Create Windows .lnk shortcut with Ctrl+Alt+F3 hotkey for screenshot trigger."""
import os
import sys

def create_shortcut():
    import pythoncom
    from win32com.client import Dispatch

    shortcut_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "FT-Trigger.lnk")
    python_exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    work_dir = os.path.dirname(os.path.abspath(__file__))

    shell = Dispatch("WScript.Shell")
    lnk = shell.CreateShortcut(shortcut_path)
    lnk.TargetPath = python_exe
    lnk.Arguments = "main.py --trigger"
    lnk.WorkingDirectory = work_dir
    lnk.Hotkey = "Ctrl+Alt+F3"
    lnk.WindowStyle = 7  # Minimized
    # Use the exe icon if available
    icon = os.path.join(work_dir, "dist", "FT-DataUpload.exe")
    if os.path.exists(icon):
        lnk.IconLocation = f"{icon},0"
    lnk.Save()

    print(f"Shortcut created: {shortcut_path}")
    print(f"Hotkey: Ctrl+Alt+F3")
    print(f"Press Ctrl+Alt+F3 in-game to trigger screenshot OCR.")

if __name__ == "__main__":
    create_shortcut()
