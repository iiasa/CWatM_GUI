"""Import every module under src/gui, then construct the main window offscreen.

An ImportError in a window nobody opened during testing (Restore settingsfile, the
Excel editor, the Flow Diagram, ...) is invisible until a user clicks that menu item.
Importing all of them turns that into a CI failure.

Needs the runtime dependencies installed and a Qt platform plugin; run it with
``QT_QPA_PLATFORM=offscreen`` on a headless machine:

    python tools/import_all.py
"""

import importlib
import os
import pathlib
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CWATM_GUI_NO_MAXIMIZE", "1")
sys.path.insert(0, os.getcwd())


def modules():
    for path in sorted(pathlib.Path("src/gui").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield ".".join(path.with_suffix("").parts)


def main():
    from PySide6.QtWidgets import QApplication
    app = QApplication([])          # some modules touch Qt at import time
    assert app is not None

    ok, failed = 0, []
    for name in modules():
        try:
            importlib.import_module(name)
            ok += 1
        except Exception:
            failed.append(name)
            traceback.print_exc()

    print(f"imported {ok} module(s), {len(failed)} failed")
    if failed:
        print("FAILED: " + ", ".join(failed), file=sys.stderr)
        return 1

    from src.gui.components.main_window import CWatMMainWindow
    window = CWatMMainWindow()
    window.show()
    print("main window constructed and shown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
