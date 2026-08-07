"""Third-party warnings the GUI silences - one definition, applied by every
entry point (GUI process and model child process) plus a last-resort filter on
the child's output stream, so the message can never reach a user's output box.

Currently one entry: rasterio 1.5.0 sets .shape on the array it returns from
EVERY read (its Cython _io.pyx: `out.shape = out.shape[1:]` squeezes the band
axis of `read(1)`), which numpy 2.5 deprecated:

    DeprecationWarning: Setting the shape on a NumPy array has been deprecated
    in NumPy 2.5. As an alternative, you can create a new view using np.reshape
    (with copy=False if needed).

Because it is raised from C code, Python attributes it to whatever *Python* line
called read() - usually cwatm/management_modules/data_handling.py:317 / :654 -
so it reads like a CWatM problem although nothing on our side triggers it and
there is nothing the user can do about it. It is cosmetic: read(1) still returns
the correct 2-D array. rasterio 1.5.0 is the newest release and still has it;
delete this module (and its three call sites) once a fixed rasterio ships.

Matched by MESSAGE TEXT, because neither the category nor the reported module
identifies it.
"""

import os
import warnings

#: Message prefix of the rasterio x numpy 2.5 deprecation. Doubles as a
#: filterwarnings regex and as a PYTHONWARNINGS literal prefix, so it must stay
#: free of ':' and of regex metacharacters.
RASTERIO_SHAPE_MESSAGE = "Setting the shape on a NumPy array has been deprecated"

#: PYTHONWARNINGS entry ("action:message:category:module:lineno") exported to
#: child processes so the suppression is active from interpreter start-up,
#: before any of our code runs - this also covers a child built from an OLDER
#: build that has no filter of its own. (A frozen child ignores the environment;
#: for those the in-code apply() below and _drop_line() are what count.)
PYTHONWARNINGS_ENTRY = "ignore:%s:DeprecationWarning" % RASTERIO_SHAPE_MESSAGE


def apply(export_env=True):
    """Install the filter in this process and (by default) export it to any
    child process through PYTHONWARNINGS. Call as early as possible - before
    numpy/rasterio/cwatm are imported."""
    warnings.filterwarnings("ignore", category=DeprecationWarning,
                           message=RASTERIO_SHAPE_MESSAGE)
    if export_env:
        export_to_environment(os.environ)


def export_to_environment(env):
    """Append our PYTHONWARNINGS entry to `env` (os.environ or any dict-like),
    keeping whatever the user already set there. Returns the new value."""
    parts = [p for p in env.get("PYTHONWARNINGS", "").split(",") if p.strip()]
    if PYTHONWARNINGS_ENTRY not in parts:
        parts.append(PYTHONWARNINGS_ENTRY)
    value = ",".join(parts)
    env["PYTHONWARNINGS"] = value
    return value


# --------------------------------------------------------- output-stream guard
# The warning prints as two message lines plus (source builds only) an echo of
# the offending source line:
#     ...data_handling.py:317: DeprecationWarning: Setting the shape on a ...
#     As an alternative, you can create a new view using np.reshape (with ...)
#       mapnp = nf2.read(1)
# A child process we did not start ourselves - e.g. a CWatM_model.exe left over
# from an older build in _internal/, which has neither the filter nor (frozen)
# the PYTHONWARNINGS export - can still print it. _drop_line() lets the parent
# throw those lines away on the way to the output box.

_CONTINUATION = "As an alternative, you can create a new view using np.reshape"


class LineSuppressor:
    """Stateful filter over one stream: True = drop this chunk.

    Fed either one line at a time (cwatm_process_worker forwards the child's
    output that way) or one whole warning in a single write (warnings.warn
    formats all its lines into one file.write, so an in-process warning is
    dropped by the first test alone). The follow-up states only ever swallow a
    line that really looks like the rest of THIS warning, so indented model
    output right after it survives."""

    _IDLE, _EXPECT_CONTINUATION, _EXPECT_SOURCE_ECHO = 0, 1, 2

    def __init__(self):
        self._state = self._IDLE

    def __call__(self, chunk):
        text = chunk.lstrip("\r \t")
        if "DeprecationWarning: " + RASTERIO_SHAPE_MESSAGE in text:
            self._state = self._EXPECT_CONTINUATION
            return True
        state, self._state = self._state, self._IDLE
        if state == self._EXPECT_CONTINUATION and text.startswith(_CONTINUATION):
            self._state = self._EXPECT_SOURCE_ECHO
            return True
        if state == self._EXPECT_SOURCE_ECHO and chunk[:1] in (" ", "\t") and chunk.strip():
            return True                      # "  mapnp = nf2.read(1)"
        return False
