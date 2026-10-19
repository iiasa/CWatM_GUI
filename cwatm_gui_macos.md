# Running the CWatM GUI on macOS (source run)

The installer/exe are Windows-only. On a Mac the GUI runs from source; the code paths
that differ from Windows are already portable (`open_path` uses `open`, the log and run
journal live in `~/Library/Application Support/CWatM_GUI`, caches in
`~/Library/Caches/cwatm_gui`).

```bash
python3 -m venv venv2 && . venv2/bin/activate
pip install -r requirements.txt
./gui.sh                 # or: ./gui.sh settings.ini
./gui.sh --check         # lists python, PySide6 and the key packages
```

- Use Python 3.12 if possible; if a pinned wheel is missing for your Python or for
  Apple Silicon, relax that one pin and install with `--only-binary=:all:`.
- `gui.sh` skips the Linux workarounds (X11, software GL, `LD_PRELOAD`) on macOS.
- The model run starts `python -u cwatm_model.py <ini>` as a child process, as on Linux.
- Not available on macOS: Create batch produces a Windows `.bat`; the Edge/Chrome login
  of CWatM AI looks for browsers in Windows locations only.
- **Status: untested on a real Mac** - the changes were made from a Linux session.
  Please report anything that breaks, with `~/Library/Application Support/CWatM_GUI/gui.log`.
