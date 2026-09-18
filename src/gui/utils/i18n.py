"""Language of the GUI chrome: menus, menu items, buttons, labels and tooltips.

Preferences ▸ Display ▸ **Language** (persisted ``display/language``, default English).

The English texts stay in the code, and the translations live in **one table**,
``translations/ui_strings_languages.csv`` (columns ``No, English`` and one column per
language; a further language is one more column plus an entry in ``LANGUAGES`` /
``_COLUMNS``). No widget
calls a translate function. Instead an application-wide event filter swaps the text of

* every **QAction** (menu items, menu titles, menu-section headers) when it is added
  to a widget or changed (``ActionAdded`` / ``ActionChanged``), so a relabel such as
  *Check settingsfile* → *Clear checking* is caught at once;
* every **button and label** when it is polished (before the first layout) and before
  every repaint, so a later ``setText`` (RUN CWatM → STOP CWatM) never reaches the screen
  in English;
* every **tooltip** at the moment it is shown (``ToolTip``). The stored tooltip is
  never changed, only the text on screen.

So a new UI string is translated by adding a CSV row. A text with ``{…}`` placeholders
is a template: ``Run '{name}'`` matches ``Run 'scenario 1'``, and the captured values
are translated too when they are catalog words (``cell`` → ``Zelle``, ``3 rows`` →
``3 Zeilen``).

English costs nothing: the filter is installed only while another language is active.
The original text is kept on each object (dynamic property ``_i18n_source``), so the
language switches **live, in both directions**.
"""

import csv
import os
import re
import sys

from src.gui.utils.gui_log import get_logger

log = get_logger("i18n")

# (name shown in Preferences, code). Each language names itself.
LANGUAGES = [
    ("English", "en"), ("Deutsch", "de"), ("Italiano", "it"), ("Magyar", "hu"),
    ("Română", "ro"), ("Srpski", "sr"), ("Hrvatski", "hr"), ("Slovenčina", "sk"),
    ("Български", "bg"), ("Čeština", "cs"), ("Українська", "uk"),
]
DEFAULT = "en"
_SETTINGS_KEY = "display/language"
_CSV_NAME = "ui_strings_languages.csv"
# language code -> CSV column
_COLUMNS = {
    "de": "German", "it": "Italian", "hu": "Hungarian", "ro": "Romanian",
    "sr": "Serbian", "hr": "Croatian", "sk": "Slovak", "bg": "Bulgarian",
    "cs": "Czech", "uk": "Ukrainian",
}

_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_NUMBER_PREFIX = re.compile(r"(\d[\d,.]*) (.+)", re.S)
_LETTER = re.compile(r"[A-Za-z]")


# ------------------------------------------------------------------ catalog (no Qt)

def _compile(template):
    """(literal length, regex, {placeholder: group}) for a ``{…}`` template, or None
    when the template has no literal letters (it would match anything)."""
    parts, groups, literal, pos = [], {}, "", 0
    for m in _PLACEHOLDER.finditer(template):
        lit = template[pos:m.start()]
        parts.append(re.escape(lit))
        literal += lit
        name = m.group(0)
        if name in groups:                       # repeated placeholder: same value
            parts.append(f"(?P={groups[name]})")
        else:
            groups[name] = f"g{len(groups)}"
            # greedy: '{span} {where}' on '3 columns left' must give '3 columns'
            parts.append(f"(?P<{groups[name]}>.+)")
        pos = m.end()
    tail = template[pos:]
    parts.append(re.escape(tail))
    literal += tail
    if not _LETTER.search(literal):
        return None
    return len(literal), re.compile("".join(parts), re.S), groups


class Catalog:
    """English → one target language. Pure logic, no Qt."""

    _CACHE_MAX = 4096

    def __init__(self, pairs):
        self._exact = {}
        self._reverse = {}
        patterns = []
        for en, target in pairs:
            if not en or not target:
                continue
            if _PLACEHOLDER.search(en):
                compiled = _compile(en)
                if compiled:
                    patterns.append(compiled + (target,))
            else:
                self._exact.setdefault(en, target)
                self._reverse.setdefault(target, en)
        # most specific first: 'Paste into this {kind}' before 'Paste {span} {where}'
        patterns.sort(key=lambda p: -p[0])
        self._patterns = patterns
        self._cache = {}

    def __len__(self):
        return len(self._exact) + len(self._patterns)

    def translate(self, text):
        """The translation of ``text``, or ``text`` itself when there is none."""
        if not text:
            return text
        hit = self._cache.get(text)
        if hit is None:
            hit = self._lookup(text)
            if len(self._cache) >= self._CACHE_MAX:
                self._cache.clear()
            self._cache[text] = hit
        return hit

    def english_of(self, text):
        """The English source of an already translated text (a text copied from one
        widget onto another), or None. An English key is never reversed."""
        if text in self._exact:
            return None
        return self._reverse.get(text)

    def _lookup(self, text):
        exact = self._exact.get(text)
        if exact is not None:
            return exact
        if text.endswith(":") and text[:-1] in self._exact:     # 'Language:' rows
            return self._exact[text[:-1]] + ":"
        for _literal, regex, groups, target in self._patterns:
            m = regex.fullmatch(text)
            if m:
                values = {name: self._value(m.group(g)) for name, g in groups.items()}
                return _PLACEHOLDER.sub(lambda p: values.get(p.group(0), p.group(0)),
                                        target)
        return text

    def _value(self, value):
        """A captured placeholder value: translated only when it is a catalog word,
        optionally after a count ('3 rows')."""
        exact = self._exact.get(value)
        if exact is not None:
            return exact
        m = _NUMBER_PREFIX.fullmatch(value)
        if m and m.group(2) in self._exact:
            return f"{m.group(1)} {self._exact[m.group(2)]}"
        return value


def csv_path():
    """The translation table - next to the source tree, or in ``_internal`` frozen."""
    if getattr(sys, "frozen", False):
        bases = [getattr(sys, "_MEIPASS", ""), os.path.dirname(sys.executable)]
    else:
        bases = [os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))]
    candidates = [os.path.join(b, "translations", _CSV_NAME) for b in bases if b]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return candidates[0]


def load_catalog(language, path=None):
    """The Catalog for ``language`` read from the CSV; None if it cannot be read."""
    column = _COLUMNS.get(language)
    if column is None:
        return None
    path = path or csv_path()
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = csv.DictReader(fh)
            return Catalog((r.get("English", ""), r.get(column, "")) for r in rows)
    except Exception:
        log.warning("cannot read the translation table %s", path, exc_info=True)
        return None


# -------------------------------------------------------------------- Qt side

_language = DEFAULT
_catalog = None          # loaded on first need, kept for reverse lookups afterwards
_translator = None
_SOURCE = "_i18n_source"
_SHOWN = "_i18n_shown"


def current_language():
    return _language


def saved_language():
    from PySide6.QtCore import QSettings
    code = QSettings("IIASA", "CWatM_GUI").value(_SETTINGS_KEY, DEFAULT)
    return code if code in {c for _n, c in LANGUAGES} else DEFAULT


def _strip_mnemonic(text):
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def _render(source, mnemonic):
    """What to display for an English ``source`` in the current language."""
    if _language == DEFAULT or _catalog is None or not source:
        return source
    key = _strip_mnemonic(source) if mnemonic else source
    out = _catalog.translate(key)
    if out == key:
        return source
    return out.replace("&", "&&") if mnemonic else out


def tr(text):
    """Explicit translation, for the few texts the filter does not reach (items of a
    list widget)."""
    return _render(text, mnemonic=False)


def _source_of(text, mnemonic):
    if _catalog is None or not text:
        return text
    key = _strip_mnemonic(text) if mnemonic else text
    english = _catalog.english_of(key)
    if english is None:
        return text
    return english.replace("&", "&&") if mnemonic else english


def _retext(obj, get, put, mnemonic):
    """Show ``obj``'s text in the current language, remembering the English source.

    ``_i18n_shown`` is what was last put on screen here: a different current text
    means the code set a new (English) text since, which becomes the new source."""
    current = get()
    shown = obj.property(_SHOWN)
    if current == shown:
        source = obj.property(_SOURCE)
        if source is None:
            source = current
    else:
        if not current and shown is None:
            return
        source = _source_of(current, mnemonic)
        obj.setProperty(_SOURCE, source)
    new = _render(source, mnemonic)
    if new != current:
        put(new)
    if new != shown:
        obj.setProperty(_SHOWN, new)


def _show_tooltip(obj, event):
    """Show the translated tooltip instead of Qt's; False lets Qt handle the event
    (nothing to translate, or a widget that builds its tooltip itself)."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtWidgets import QAbstractItemView, QMenu, QToolTip, QWidget
    rect = QRect()
    if isinstance(obj, QMenu):
        action = obj.actionAt(event.pos())
        if action is None or not obj.toolTipsVisible():
            return False
        tip = action.toolTip()
        if tip == _strip_mnemonic(action.text()):     # no explicit tooltip set
            return False
        rect = obj.actionGeometry(action)
    elif isinstance(obj.parent(), QAbstractItemView) and obj.parent().viewport() is obj:
        view = obj.parent()
        index = view.indexAt(event.pos())
        if not index.isValid():
            return False
        tip = index.data(Qt.ToolTipRole)
        rect = view.visualRect(index)
    elif isinstance(obj, QWidget):
        tip = obj.toolTip()
    else:
        return False
    if not isinstance(tip, str) or not tip:
        return False
    text = _render(tip, mnemonic=False)
    if text == tip:
        return False
    QToolTip.showText(event.globalPos(), text, obj, rect)
    return True


def _make_translator():
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QAbstractButton, QLabel

    paint, polish = QEvent.Type.Paint, QEvent.Type.Polish
    added, changed = QEvent.Type.ActionAdded, QEvent.Type.ActionChanged
    tooltip = QEvent.Type.ToolTip

    class _Translator(QObject):
        def eventFilter(self, obj, event):
            kind = event.type()
            try:
                if kind == paint or kind == polish:
                    if isinstance(obj, QAbstractButton):
                        _retext(obj, obj.text, obj.setText, True)
                    elif isinstance(obj, QLabel) and obj.objectName() != "qtooltip_label":
                        _retext(obj, obj.text, obj.setText, False)
                elif kind == added or kind == changed:
                    action = event.action()
                    if action is not None:
                        _retext(action, action.text, action.setText, True)
                elif kind == tooltip:
                    return _show_tooltip(obj, event)
            except RuntimeError:
                log.debug("i18n: object deleted during translation", exc_info=True)
            except Exception:
                log.debug("i18n: event filter failed", exc_info=True)
            return False

    return _Translator()


def retranslate_all():
    """Put every existing button, label and action into the current language."""
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.allWidgets():
        try:
            if isinstance(widget, QAbstractButton):
                _retext(widget, widget.text, widget.setText, True)
            elif isinstance(widget, QLabel) and widget.objectName() != "qtooltip_label":
                _retext(widget, widget.text, widget.setText, False)
            for action in widget.actions():
                _retext(action, action.text, action.setText, True)
        except RuntimeError:
            log.debug("retranslate_all: widget deleted", exc_info=True)


def _activate(code):
    """Make ``code`` the active language: (un)install the filter, retranslate."""
    global _language, _catalog, _translator
    from PySide6.QtWidgets import QApplication
    if code != DEFAULT:
        catalog = load_catalog(code)
        if catalog is None:
            code = DEFAULT
        else:
            _catalog = catalog
    _language = code
    app = QApplication.instance()
    if app is None:
        return
    if code != DEFAULT and _translator is None:
        _translator = _make_translator()
        app.installEventFilter(_translator)
    retranslate_all()
    if code == DEFAULT and _translator is not None:
        app.removeEventFilter(_translator)
        _translator = None


def install():
    """Startup: activate the saved language, before any window is built."""
    code = saved_language()
    if code != DEFAULT:
        _activate(code)


def set_language(code):
    """Preferences ▸ Display ▸ Language: switch live and remember it."""
    from PySide6.QtCore import QSettings
    if code not in {c for _n, c in LANGUAGES}:
        code = DEFAULT
    settings = QSettings("IIASA", "CWatM_GUI")
    settings.setValue(_SETTINGS_KEY, code)
    settings.sync()
    if code != _language:
        _activate(code)
