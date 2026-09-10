"""
Preferences window for the CWatM GUI.

Opened from **Configure ▸ Preferences…** (Ctrl+,) or the **⋮** button in the
right corner of the menu bar. Every GUI setting that used to be an item in the
Configure menu lives here, grouped into the same five categories: a category
list on the left, one page of controls on the right, OK / Cancel / Apply below.

Edits are **buffered** - nothing takes effect until *Apply* or *OK*; *Cancel*
discards whatever has not been applied yet. Applying always goes through the
main window's own handlers (``_on_*_toggled``, ``_set_theme_mode``,
``set_experience_level``, ``run_ledger.set_*``), so this window is a second
*face* on the existing behaviour and never a second implementation of it - the
persisted QSettings keys and the live effects are unchanged.

Built fresh on every open, so it picks up the active colour theme (the usual
rule for the secondary windows).
"""

import os

from PySide6.QtWidgets import (QDialog, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QStackedWidget,
                               QCheckBox, QComboBox, QFontComboBox, QSpinBox,
                               QLineEdit, QPushButton, QDialogButtonBox, QFileDialog,
                               QSizePolicy)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont

from src.gui.utils import theme, display_format, run_ledger
from src.gui.utils.gui_log import get_logger
from src.gui.utils.window_geometry import scaled_default_size

log = get_logger("preferences")

# Category pages, in list order.
CATEGORIES = ["Output", "Startup & Model", "Display", "Editor & Dates", "Run History"]

# Default OpenStreetMap basemap for Show Basin - the EPSG:4326 WMS layers of
# basin_viewer2 (kept in sync with its _B2_PROVIDERS).
BASEMAPS = [("OSM", "OSM-WMS"), ("Topographic", "TOPO-OSM-WMS"),
            ("Terrain", "SRTM30-Colored-Hillshade"), ("Dark", "Dark")]


def _saved_basemap(settings):
    """The persisted default basemap, migrating an old (XYZ) key to OSM-WMS."""
    saved = settings.value("basin/default_basemap", "OSM-WMS")
    return saved if saved in {k for _l, k in BASEMAPS} else "OSM-WMS"


class PreferencesWindow(QDialog):
    """The categorised Preferences dialog (see the module docstring)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.mw = parent                      # the CWatMMainWindow
        self.setWindowTitle("Preferences")
        self.setModal(True)
        self.resize(*scaled_default_size(self, 780, 540))

        self._build_ui()
        self._applied = self._read_state()    # what the app currently has
        self._to_widgets(self._applied)
        self._apply_style()

    # ------------------------------------------------------------------ layout

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 12)
        outer.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(12)
        outer.addLayout(body, 1)

        # Left: the category list. The row height comes from an explicit size hint,
        # NOT from QSS `::item { padding }` - Fusion (the style Dark/Mikhail switch
        # to) does not fold that padding into the item's size hint, so the rows
        # overlapped in those modes. Derived from the font so it follows the DPI.
        self.cat_list = QListWidget()
        self.cat_list.setObjectName("prefCats")
        self.cat_list.setFixedWidth(180)
        self.cat_list.setSpacing(2)
        row_h = self.cat_list.fontMetrics().height() + 14
        for name in CATEGORIES:
            item = QListWidgetItem(name)
            item.setSizeHint(QSize(0, row_h))
            self.cat_list.addItem(item)
        body.addWidget(self.cat_list)

        # Right: one stacked page per category, inside a framed panel
        panel = QFrame()
        panel.setObjectName("prefPanel")
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        panel_lay.addWidget(self.pages)
        body.addWidget(panel, 1)

        self.pages.addWidget(self._page_output())
        self.pages.addWidget(self._page_startup())
        self.pages.addWidget(self._page_display())
        self.pages.addWidget(self._page_editor())
        self.pages.addWidget(self._page_history())

        self.cat_list.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.cat_list.setCurrentRow(0)

        # Bottom: OK / Cancel / Apply
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        self.buttons.accepted.connect(self._on_ok)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        outer.addWidget(self.buttons)

    # --------------------------------------------------------- page helpers

    def _page(self, title, subtitle=""):
        """An empty page with its heading; returns (widget, content layout)."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(9)
        head = QLabel(title)
        head.setObjectName("prefHead")
        lay.addWidget(head)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("prefSub")
            sub.setWordWrap(True)
            lay.addWidget(sub)
        lay.addSpacing(4)
        return page, lay

    def _check(self, layout, text, tip=""):
        box = QCheckBox(text)
        if tip:
            box.setToolTip(tip)
        layout.addWidget(box)
        return box

    def _row(self, layout, label, widget, tip=""):
        """A 'Label:  [widget]' row with the labels of a page lined up."""
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setMinimumWidth(200)
        if tip:
            lbl.setToolTip(tip)
            widget.setToolTip(tip)
        row.addWidget(lbl)
        row.addWidget(widget)
        row.addStretch(1)
        layout.addLayout(row)
        return widget

    def _path_row(self, layout, label, on_browse, tip="", placeholder=""):
        """A 'Label: [line edit] [Browse…]' row; on_browse returns a path or ''."""
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setMinimumWidth(200)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn = QPushButton("Browse…")
        btn.setFixedWidth(90)
        if tip:
            lbl.setToolTip(tip)
            edit.setToolTip(tip)

        def _browse():
            picked = on_browse(edit.text())
            if picked:
                edit.setText(picked)

        btn.clicked.connect(_browse)
        row.addWidget(lbl)
        row.addWidget(edit, 1)
        row.addWidget(btn)
        layout.addLayout(row)
        return edit

    # ---------------------------------------------------------------- pages

    def _page_output(self):
        page, lay = self._page(
            "Output",
            "Where the content of the CWatM output box is written to, and whether "
            "it is written at all.")
        self.ed_output_file = self._path_row(
            lay, "Output box file:", self._browse_output_file,
            tip="Custom file the output box is appended to. Leave empty to use "
                "the default <PathOut>/cwatm_out.txt.",
            placeholder=self._default_output_file_hint())
        self.cb_write_output = self._check(
            lay, "Write output box to that file",
            "Writes input to output box to disk, but can slow down a run")
        lay.addStretch(1)
        return page

    def _page_startup(self):
        page, lay = self._page(
            "Startup & Model",
            "What happens when the GUI starts, and which model libraries are loaded.")
        self.cb_load_previous = self._check(
            lay, "Load previous settings at start",
            "When ticked, the last settings file you had open is loaded again "
            "automatically the next time CWatM GUI starts.")
        self.cb_use_modflow = self._check(
            lay, "Use Modflow",
            "Load flopy for MODFLOW coupling. Off = flopy is not loaded (faster start).")
        lay.addStretch(1)
        return page

    def _page_display(self):
        page, lay = self._page(
            "Display",
            "Colours, the banner, the settings-file font, and the defaults the map "
            "and number displays open with.")
        self.cmb_theme = QComboBox()
        for label, key in theme.THEME_CHOICES:
            self.cmb_theme.addItem(label, key)
        self._row(lay, "Mode:", self.cmb_theme,
                  "Colour mode of the whole GUI")
        self.cb_show_header = self._check(
            lay, "Show Header", "Shows the headline of the CWatM GUI")

        # Settings-editor font. The family list is filtered to the monospaced
        # fonts (a settings file is read in columns, and the line-number gutter
        # assumes fixed-width digits); the family the editor currently renders
        # with is inserted if the filter does not offer it.
        self.cmb_font = QFontComboBox()
        self.cmb_font.setFontFilters(QFontComboBox.MonospacedFonts)
        self.cmb_font.setMinimumWidth(220)
        self._row(lay, "Font of settingsfile:", self.cmb_font,
                  "Font the settings file is displayed with (monospaced fonts)")

        self.sp_font_size = QSpinBox()
        self.sp_font_size.setRange(6, 32)
        self.sp_font_size.setSuffix(" px")
        self._row(lay, "Font size of settingsfile:", self.sp_font_size,
                  "Size the settings file is displayed with - the same setting as "
                  "the Font+ / Font- buttons above the settings file")

        self.sp_decimals = QSpinBox()
        self.sp_decimals.setRange(0, 12)
        self._row(lay, "Show decimals:", self.sp_decimals,
                  "Number of decimals shown throughout all displays (default 3)")

        self.sp_transparency = QSpinBox()
        self.sp_transparency.setRange(0, 100)
        self.sp_transparency.setSuffix(" %")
        self._row(lay, "Initial map transparency:", self.sp_transparency,
                  "Initial map transparency used by NetCDF and Show Basin.\n"
                  "0 = OSM hidden (only the data); 100 = OSM fully visible "
                  "(data 50% on top)")

        self.cmb_basemap = QComboBox()
        for label, key in BASEMAPS:
            self.cmb_basemap.addItem(label, key)
        self._row(lay, "Default openstreet map:", self.cmb_basemap,
                  "Basemap Show Basin opens with")

        from src.gui.widgets.discharge_sparkline import ANIMALS
        self.cmb_animal = QComboBox()
        for name, emoji in ANIMALS:
            self.cmb_animal.addItem(f"{emoji}  {name}", name)
        self._row(lay, "Select animal:", self.cmb_animal,
                  "Animal shown now and then on the live discharge plot")
        self.cb_tooltip_reverse = self._check(
            lay, "Tooltip reverse",
            "Show tooltips with the text and background colours swapped "
            "(light on dark instead of dark on light)")
        lay.addStretch(1)
        return page

    def _page_editor(self):
        page, lay = self._page(
            "Editor & Dates",
            "How much of the settings file is shown, and how the dates are picked.")
        from src.gui.components.main_window import _EXPERIENCE_LEVELS
        self.cmb_level = QComboBox()
        for lvl in _EXPERIENCE_LEVELS:
            self.cmb_level.addItem(lvl, lvl)
        self._row(lay, "Skill of user:", self.cmb_level,
                  "The skill of the user determines how much of the settingsfile "
                  "is presented")
        self.cb_web_picker = self._check(
            lay, "Web-style date picker",
            "Pick the Start/Spin/End dates with a modern frameless calendar popup "
            "(📅 button); untick to go back to the classic drop-down calendar")
        self.cb_timeline = self._check(
            lay, "Date timeline",
            "Show a draggable Start/Spin/End timeline below the date fields "
            "(the band behind it is the meteo-forcing coverage)")
        self.cb_bookmark_change = self._check(
            lay, "Bookmark Change",
            "Automatically set a bookmark on a line when it is changed (skips a "
            "line if a bookmark is already 1 or 2 lines above/below)")
        self.cb_use_tabs = self._check(
            lay, "Use Tabs",
            "Show the tab bar above the settings file, so several settings files "
            "can be open at once (right-click a tab for Delete Tab / Copy Tab / "
            "Run CWatM).\nShown in the Expert skill level only; open tabs keep "
            "their content while the bar is hidden.")
        lay.addStretch(1)
        return page

    def _page_history(self):
        page, lay = self._page(
            "Run History",
            "Where the Run Ledger (the log of past runs) is stored and how long "
            "it is kept.")
        self.ed_history_folder = self._path_row(
            lay, "Run history folder:", self._browse_history_folder,
            tip="Folder where the Run Ledger (log of past runs) is stored")
        self.sp_retention = QSpinBox()
        self.sp_retention.setRange(0, 100000)
        self.sp_retention.setSuffix(" days")
        self.sp_retention.setSpecialValueText("keep forever")
        self._row(lay, "Run history retention:", self.sp_retention,
                  "How many days of runs to keep in the Run Ledger (0 = keep forever)")
        lay.addStretch(1)
        return page

    # -------------------------------------------------------------- browsing

    def _default_output_file_hint(self):
        try:
            return self.mw._default_output_file()
        except Exception:
            return "cwatm_out.txt"

    def _browse_output_file(self, current):
        path, _ = QFileDialog.getSaveFileName(
            self, "Set output box file", current or self._default_output_file_hint(),
            "Text files (*.txt);;All files (*)")
        return path

    def _browse_history_folder(self, current):
        return QFileDialog.getExistingDirectory(
            self, "Choose the run-history folder", current or run_ledger.history_dir())

    # ----------------------------------------------------------- state <-> UI

    def _read_state(self):
        """The settings as they currently are in the running app."""
        mw = self.mw
        s = mw._settings
        return {
            "output_file": mw._output_file_override or "",
            "write_output": bool(mw.write_output_action.isChecked()),
            "load_previous": s.value("startup/load_previous", False, type=bool),
            "use_modflow": s.value("modflow/enabled", False, type=bool),
            "theme": theme.current_theme(),
            "show_header": s.value("display/show_header", True, type=bool),
            # The editor font: the family actually rendered (the persisted choice,
            # else what the built-in chain resolved to) and the size the Font+ /
            # Font- buttons keep - both read live, so the box always opens on what
            # the editor shows right now.
            "editor_font": mw.editor_font_family(),
            "editor_font_size": mw._editor_font_size,
            "decimals": display_format.get_decimals(),
            "transparency": display_format.get_transparency(),
            "basemap": _saved_basemap(s),
            "animal": s.value("display/animal", "Fish"),
            "tooltip_reverse": s.value("display/tooltip_reverse", False, type=bool),
            "level": getattr(mw, "_experience_level", "Expert"),
            "web_picker": s.value("display/date_picker_web", True, type=bool),
            "date_timeline": s.value("display/date_timeline", True, type=bool),
            "bookmark_change": s.value("editor/bookmark_change", False, type=bool),
            "use_tabs": s.value("editor/use_tabs", True, type=bool),
            "history_folder": run_ledger.history_dir(),
            "history_retention": run_ledger.retention_days(),
        }

    def _to_widgets(self, st):
        """Fill the controls from a state dict."""
        self.ed_output_file.setText(st["output_file"])
        self.cb_write_output.setChecked(st["write_output"])
        self.cb_load_previous.setChecked(st["load_previous"])
        self.cb_use_modflow.setChecked(st["use_modflow"])
        self._select_data(self.cmb_theme, st["theme"])
        self.cb_show_header.setChecked(st["show_header"])
        self._select_font(st["editor_font"])
        self.sp_font_size.setValue(st["editor_font_size"])
        self.sp_decimals.setValue(st["decimals"])
        self.sp_transparency.setValue(st["transparency"])
        self._select_data(self.cmb_basemap, st["basemap"])
        self._select_data(self.cmb_animal, st["animal"])
        self.cb_tooltip_reverse.setChecked(st["tooltip_reverse"])
        self._select_data(self.cmb_level, st["level"])
        self.cb_web_picker.setChecked(st["web_picker"])
        self.cb_timeline.setChecked(st["date_timeline"])
        self.cb_bookmark_change.setChecked(st["bookmark_change"])
        self.cb_use_tabs.setChecked(st["use_tabs"])
        self.ed_history_folder.setText(st["history_folder"])
        self.sp_retention.setValue(st["history_retention"])

    def _from_widgets(self):
        """Read the state the user has dialled in."""
        return {
            "output_file": self.ed_output_file.text().strip(),
            "write_output": self.cb_write_output.isChecked(),
            "load_previous": self.cb_load_previous.isChecked(),
            "use_modflow": self.cb_use_modflow.isChecked(),
            "theme": self.cmb_theme.currentData(),
            "show_header": self.cb_show_header.isChecked(),
            "editor_font": self.cmb_font.currentFont().family(),
            "editor_font_size": self.sp_font_size.value(),
            "decimals": self.sp_decimals.value(),
            "transparency": self.sp_transparency.value(),
            "basemap": self.cmb_basemap.currentData(),
            "animal": self.cmb_animal.currentData(),
            "tooltip_reverse": self.cb_tooltip_reverse.isChecked(),
            "level": self.cmb_level.currentData(),
            "web_picker": self.cb_web_picker.isChecked(),
            "date_timeline": self.cb_timeline.isChecked(),
            "bookmark_change": self.cb_bookmark_change.isChecked(),
            "use_tabs": self.cb_use_tabs.isChecked(),
            "history_folder": self.ed_history_folder.text().strip(),
            "history_retention": self.sp_retention.value(),
        }

    @staticmethod
    def _select_data(combo, value):
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _select_font(self, family):
        """Show `family` in the font box, adding it if the monospaced filter does
        not list it (a chosen proportional font, or a family Qt classifies
        differently) - otherwise the box would silently show a different font than
        the editor uses and Apply would then change it."""
        if not family:
            return
        if self.cmb_font.findText(family) < 0:
            self.cmb_font.insertItem(0, family)
        self.cmb_font.setCurrentFont(QFont(family))

    # -------------------------------------------------------------- applying

    def _on_ok(self):
        self._apply()
        self.accept()

    def _apply(self):
        """Push everything the user changed since the last apply into the app.

        Only the *changed* keys are pushed, so applying twice does not re-fire
        handlers (a theme re-apply, a flopy warm-up) for untouched settings.
        """
        new = self._from_widgets()
        changed = {k: v for k, v in new.items() if v != self._applied.get(k)}
        if not changed:
            return
        mw = self.mw
        for key, value in changed.items():
            try:
                self._apply_one(mw, key, value)
            except Exception:
                log.warning("applying preference %s failed", key, exc_info=True)
        self._applied = new
        try:
            mw.status_bar.showMessage(
                f"Preferences: {len(changed)} setting(s) applied")
        except Exception:
            log.debug("_apply: ignored", exc_info=True)

    def _apply_one(self, mw, key, value):
        """Apply one setting through the main window's existing handler."""
        if key == "output_file":
            mw._output_file_override = value or None
        elif key == "write_output":
            # QAction: run_controller reads .isChecked(); toggling mirrors the bool
            mw.write_output_action.setChecked(value)
        elif key == "load_previous":
            mw._on_load_previous_toggled(value)
        elif key == "use_modflow":
            mw._on_use_modflow_toggled(value)
        elif key == "theme":
            mw._set_theme_mode(value)
            self._apply_style()          # follow the new theme while open
        elif key == "show_header":
            mw._on_show_header_toggled(value)
        elif key == "editor_font":
            mw.set_editor_font_family(value)
        elif key == "editor_font_size":
            mw._set_editor_font_size(value)      # same handler as Font+ / Font-
        elif key == "tooltip_reverse":
            mw._on_tooltip_reverse_toggled(value)
        elif key == "decimals":
            display_format.set_decimals(value)
            mw._settings.setValue("display/decimals", display_format.get_decimals())
        elif key == "transparency":
            display_format.set_transparency(value)
            mw._settings.setValue("display/transparency",
                                  display_format.get_transparency())
        elif key == "basemap":
            mw._set_default_basemap(value)
        elif key == "animal":
            mw._set_animal(value)
        elif key == "level":
            mw.set_experience_level(value)
        elif key == "web_picker":
            mw._on_web_picker_toggled(value)
        elif key == "date_timeline":
            mw._on_date_timeline_toggled(value)
        elif key == "bookmark_change":
            mw._on_bookmark_change_toggled(value)
        elif key == "use_tabs":
            mw._on_use_tabs_toggled(value)
        elif key == "history_folder":
            if value and os.path.isdir(value):
                run_ledger.set_history_dir(value)
        elif key == "history_retention":
            run_ledger.set_retention_days(value)

    # ----------------------------------------------------------------- theme

    def _apply_style(self):
        """Theme the dialog chrome. Only the pieces that are not already covered
        by the app palette are styled, so Normal keeps its native look."""
        self.setStyleSheet(f"""
            QListWidget#prefCats {{
                background-color: {theme.c('panel_bg')};
                border: 1px solid {theme.c('border')};
                border-radius: 6px;
                padding: 4px;
                color: {theme.c('text')};
                outline: none;
            }}
            QListWidget#prefCats::item {{
                /* horizontal inset only - the row HEIGHT is the item's size hint
                   (Fusion ignores vertical ::item padding, rows would overlap) */
                padding-left: 10px;
                padding-right: 10px;
                border-radius: 4px;
            }}
            QListWidget#prefCats::item:selected {{
                background-color: {theme.c('menu_sel_bg')};
                color: {theme.c('menu_sel_text')};
            }}
            QFrame#prefPanel {{
                background-color: {theme.c('panel_bg')};
                border: 1px solid {theme.c('border')};
                border-radius: 6px;
            }}
            QLabel#prefHead {{
                color: {theme.c('accent')};
                font-size: 16px;
                font-weight: 700;
                padding-bottom: 2px;
            }}
            QLabel#prefSub {{
                color: {theme.c('text_gray')};
            }}
        """)


def open_preferences(parent):
    """Open the Preferences dialog (modal) on top of the main window."""
    dlg = PreferencesWindow(parent)
    dlg.exec()
    return dlg
