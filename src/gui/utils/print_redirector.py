"""stdout/stderr -> GUI output box redirection.

``cwatm_gui.py`` installs one instance for ``sys.stdout`` and one for
``sys.stderr`` before the main window is shown, so everything the model and the
GUI print lands in the CWatM output box (stderr in dark red). The subprocess run
worker relies on this too: it forwards the child's output one write per line to
``sys.stdout``/``sys.stderr`` so it behaves exactly like an in-process print
(see ``cwatm_process_worker.py``).
"""

from PySide6.QtCore import QObject, Signal

from src.gui.utils.warning_filters import LineSuppressor


class PrintRedirector(QObject):
    """Redirect print output to GUI"""
    text_written = Signal(str, bool)  # text, is_error

    def __init__(self, is_error=False):
        super().__init__()
        self.is_error = is_error
        # Keeps the rasterio x numpy 2.5 shape deprecation out of the output box
        # even if it is raised in-process (basin viewer, Check Data, the mask
        # generation, the in-process run worker) with the warnings filter somehow
        # bypassed - see warning_filters.py.
        self._suppress = LineSuppressor()

    def write(self, text):
        if self._suppress(text):
            return
        # NOTE: whitespace-only writes (including a bare "\n") are dropped on
        # purpose - the output box does its own line handling, and the \r
        # progress-line overwrite depends on not being fed empty appends.
        # Do not "fix" this without testing a live run.
        if text.strip():  # Only emit non-empty text
            self.text_written.emit(text, self.is_error)

    def flush(self):
        pass
