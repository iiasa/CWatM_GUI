#!/usr/bin/env python3
"""
Entry point of CWatM_model.exe - the lightweight child process the GUI spawns
(via QProcess) for every model run: real Stop (kill), crash isolation, fresh
interpreter state, and no Qt imports so it starts fast.

Usage:  CWatM_model.exe <settings.ini> [cwatm flags]
        python cwatm_model.py <settings.ini> [cwatm flags]

All the logic lives in src/gui/utils/cwatm_model_runner.py (see there for the
stdout marker protocol the GUI parses); the second EXE is built by
cwatm_gui_dir.spec. From source the GUI spawns "python cwatm_gui.py --run-cwatm"
instead, which dispatches to the same runner.
"""

import os
import sys

if __name__ == "__main__":
    _root = os.path.dirname(os.path.abspath(__file__))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from src.gui.utils.cwatm_model_runner import main
    sys.exit(main(sys.argv[1:]))
