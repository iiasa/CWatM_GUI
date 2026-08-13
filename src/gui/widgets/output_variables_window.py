"""Tools ▸ Add output variables - a picker of the CWatM output variables that fit the
loaded settings file.

Lists every ``[Array]`` variable from ``cwatm/metaNetcdf.xml`` (the data variables
that can be written as output), **filtered to the ones that fit the current
[OPTIONS]** (e.g. no glacier variables when ``includeGlaciers = False``, no modflow
output when ``modflow_coupling = False``, no small-lake output when
``useSmallLakes = False``).

The ~580 variables are **grouped by topic** (``_GROUPS`` / ``group_of`` - snow, meteo,
evaporation, soil, groundwater, lakes, routing, demand, crops, balance totals, static
maps, and *Other*), alphabetical inside each group, the header carrying the group's
count and hiding itself when a filter empties it. The **filter box searches the unit,
long name and description too**, not only the variable name ("evapo" finds
``actualET``).

A variable the settings file **already writes** is marked **``✓``, bold and green**,
with its output keys and line numbers in the tooltip (``_file_vars`` /
``_refresh_marks``); the **"Only variables already in the settings file"** tick turns
the picker into an overview of the file's outputs. There is deliberately **no Refresh
button**: the marks are re-read whenever the window is activated, and the list itself
is rebuilt only when a gating option really changed (``_current_signature`` /
``changeEvent``).

An **array variable** (``actualET`` is allocated per land cover) is invalid as an
output without an index, so those are marked ``[index]`` and both click styles **ask
which one, by name** - "1 - grassland", "0,2 - top soil layer, irrPaddy" - from
``src/gui/utils/var_dims.py``, the same table Check settingsfile uses to flag a wrong
index (``_pick_index`` for a left-click, an index submenu under the time step for a
right-click, ``QInputDialog`` for the open-ended per-crop ones). By
default only the ``priority="high"`` (recommended) variables are shown - 116 of the 580
in the shipped xml; the checkable **Load all Variable** toggle above the filter box
switches to every fitting variable. *Should a future ``metaNetcdf.xml`` ship without
``priority`` flags that view would be empty, so the picker falls back to the full list
and says so in the status line (``_priority_missing``).* Whatever the settings file
already writes is listed in **either** view. Each item's tooltip shows ``unit:`` and
``Dimension:`` (the metaNetcdf ``dim``).

**Left-clicking** a variable pastes its name at the settings editor's cursor position -
but only when the cursor sits on an **output line** (a key like ``OUT_TSS_Daily`` /
``OUT_MAP_MonthAvg``); otherwise it complains and inserts nothing. Comma separators
are added automatically so the line stays a valid comma list.

**Right-clicking** a variable needs no cursor position: a menu offers
**Timeseries (TSS)** (the ten time steps plus an **upstream calculation** submenu -
``AreaSum`` / ``AreaAvg``, each with its seven time steps) and **Map (MAP)** (the
same ten time steps, no area aggregation - CWatM silently ignores an AreaSum/AreaAvg
map key). Every entry carries a tooltip explaining the time step and showing the line it
produces. Choosing one builds ``OUT_<TSS|MAP>_<selection>`` and either appends the
variable to that key's existing line or creates ``<key> = <variable>`` at the end of
the ``[OUTPUT]`` section.

**Picking a variable a second time removes it again** (both click styles, via
``_remove_output``) - and when it was the only variable on that output line, the
**whole line is deleted**, so a line the right-click menu just created disappears
completely.

Non-modal, themed like the other secondary windows; geometry key ``output_variables``.
"""

import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QInputDialog,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QTextCursor, QFont, QCursor, QColor

from src.gui.utils import theme
from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils.gui_log import get_logger
from src.gui.utils import meta_netcdf
from src.gui.utils import var_dims

log = get_logger("output_variables_window")

# When a feature's [OPTIONS] switch is OFF, its output variables are not produced, so
# hide any variable whose name contains one of these (lower-case) substrings. Keyed by
# the option name (read from the flat settings lookup, so it works wherever the switch
# lives). Mirrors the enable guards in cwatm/ (read-only). Deliberately conservative -
# only clear-cut feature families are gated, so common variables are never hidden.
_FEATURE_VAR_PATTERNS = {
    'includeglaciers':            ['glacier'],
    'modflow_coupling':           ['modflow'],
    'usesmalllakes':              ['smalllake', 'smallwaterbody', 'smallevap'],
    'includewaterbodies':         ['lake', 'reservoir', 'waterbody', 'wetland', 'outlake'],
    'includewaterdemand':         ['demand', 'abstraction', 'withdrawal', 'domestic',
                                   'industry', 'livestock', 'unmet'],
    'includerunoffconcentration': ['runoff_conc', 'runoffconc'],
    'calc_environflow':           ['environ', 'envflow'],
}

# --------------------------------------------------------------- output types
# The time steps offered by the right-click menu, in menu order. Mirrors CWatM's
# output grammar (cwatm/management_modules/globals.py: outputTypTss /
# outputTypMap / outputTypTss2 - read-only) so the picker can never write a key
# CWatM rejects. TotalEnd is MAP-ONLY (outputTypTss has no 'totalend'): it is
# listed for TSS as well, but disabled, so the reason is visible instead of the
# item silently missing.
_TIME_TYPES = ('Daily', 'MonthAvg', 'MonthTot', 'MonthEnd',
               'AnnualAvg', 'AnnualTot', 'AnnualEnd',
               'TotalAvg', 'TotalTot', 'TotalEnd')
_TSS_ONLY_INVALID = ('TotalEnd',)          # valid for OUT_MAP_…, not for OUT_TSS_…

# Upstream-catchment aggregation - timeseries only (OUT_TSS_AreaSum_… /
# OUT_TSS_AreaAvg_…; CWatM silently ignores an AreaSum/AreaAvg map key). Total*
# is not offered here, matching CWatM's usual usage. Picked in two steps: first
# the aggregation (AreaSum / AreaAvg), then the time step.
_AREA_TIME_TYPES = ('Daily', 'MonthAvg', 'MonthTot', 'MonthEnd',
                    'AnnualAvg', 'AnnualTot', 'AnnualEnd')
_AREA_AGGS = ('AreaSum', 'AreaAvg')
_AREA_TYPES = tuple(f"{agg}_{t}" for t in _AREA_TIME_TYPES for agg in _AREA_AGGS)

# --------------------------------------------------------------------- grouping
# 580 variables alphabetically is a long scroll, so the list is grouped by topic.
# First match wins, so the order matters (the specific families come before the
# broad ones); anything unmatched lands in "Other". A heuristic over the variable
# names - metaNetcdf.xml carries no category of its own.
# A pattern is a lower-case **substring**, or an **exact** name when written "=name"
# (needed for the short ones: "g" or "w1" as a substring would swallow the list).
_GROUPS = (
    ("Snow, ice & frost",      ('snow', 'ice', 'frost', 'swe', 'glacier', 'kfrost',
                                'tempmelt', 'tempsnow', 'seasonalsnow')),
    ("Meteo & radiation",      ('prec', 'rain', 'tavg', '=temp', '=tempht', '=meteo',
                                '=co2', 'albedo', 'radiation', 'lapserate', 'wind',
                                '=z_0', '=z_h', '=con_e', '=tadd', '=ts_add',
                                '=tstart', '=thermali')),
    ("Evaporation & transpiration", ('evap', 'transp', 'actualet', 'totalet', 'etref',
                                     'ewref', 'potet', 'e0', 'kc', 'intercept',
                                     'addtoevapotrans', 'ef_vmf', 'cropgroupnumber')),
    ("Soil & infiltration",    ('soil', 'theta', 'perc', 'infiltr', 'topwater',
                                'caprise', 'prefflow', 'rootdepth', 'adjroot',
                                'arnobeta', 'storcap', '=w1', '=w2', '=w3', '=depth',
                                '=sum_w1', '=sum_w2', '=sum_w3',
                                'totavlwater', 'kunsat', 'conlimit', 'alphadepletion',
                                'maxtopwater', 'mintopwater')),
    ("Groundwater & MODFLOW",  ('gw', 'groundwater', 'baseflow', 'modflow', 'modf',
                                'pumping', 'head', 'specificyield', 'recession',
                                'aquifer', 'leakage', 'capillar', 'storgroundwater',
                                'allowedpumping', 'relaxgw')),
    ("Lakes & reservoirs",     ('lake', 'reservoir', 'res_', 'resvolume', 'resstorage',
                                'resid', 'resyear', 'waterbody', 'outlake', 'floodlimit',
                                'normlimit', 'adjust_normal', 'reslakeoutflow',
                                'minqc', 'normqc', 'nondmgqc')),
    ("Routing & discharge",    ('discharge', 'chan', 'runoff', 'dis_', 'sideflow',
                                'uparea', 'ldd', 'travel', 'waterlevel', 'riverbed',
                                'inflow', 'qin', 'maxdischarge', 'avgdischarge',
                                'mq90', 'dirup', 'dirdown', 'downstruct', 'downdist',
                                'envflow', 'watertemperature', 'invchan')),
    ("Water demand & abstraction", ('demand', 'abstract', 'withdrawal', 'consumption',
                                    'domestic', 'industry', 'livestock', 'irrig',
                                    'unmet', 'desal', 'efficiency', 'wwt', 'sewer',
                                    'humanuse', 'humanconsumption', 'natureuse',
                                    'returnflow', 'returnfraction', 'canal', 'lift_',
                                    'command_areas', 'allocation_zone', 'segment',
                                    'urbanleak', 'pitlatrin', 'maskdomestic',
                                    'maskindustry', 'relaxsw', 'minimum_irrigation',
                                    'waterabstract', 'pot_', 'act_')),
    ("Crops & land cover",     ('crop', 'irr', 'paddy', 'fallow', 'yield', 'fracveg',
                                'fracallcover', 'landcover', 'activatedcrops',
                                'availablearableland', 'monthcounter', 'ky',
                                'generalcrop', 'weighted_kc')),
    ("Water balance totals",   ('sum_', 'sumed_', 'total', 'tws', 'pretotalsto',
                                'gridcell_storage', 'rws', 'wb_')),
    ("Grid & static maps",     ('cellarea', 'celllength', 'dem', 'lat', 'mtom3',
                                'm3tom', 'invcellarea', 'mask', 'catchment',
                                'adminsegments', 'compress', 'decompress',
                                'elevationstd', '=beta', '=g', '=mmf', '=stability',
                                '=smooth_time_steps', '=maxtax', '=lw_max')),
)
_OTHER_GROUP = "Other"
_GROUP_ORDER = tuple(name for name, _ in _GROUPS) + (_OTHER_GROUP,)


def group_of(varname):
    """The topic group a variable is listed under (see ``_GROUPS``)."""
    low = (varname or "").lower()
    for name, patterns in _GROUPS:
        for p in patterns:
            if p[:1] == '=':
                if low == p[1:]:
                    return name
            elif p in low:
                return name
    return _OTHER_GROUP


_AREA_LABEL = "upstream calculation"
_AREA_AGG_TOOLTIPS = {
    'AreaSum': "Sums up all values of the upstream catchment",
    'AreaAvg': "Averages all values over the upstream catchment",
}

_TYPE_TOOLTIPS = {
    'Daily':     "Daily values",
    'MonthAvg':  "Monthly averages",
    'MonthTot':  "Monthly sums",
    'MonthEnd':  "Value at the end of the month",
    'AnnualAvg': "Yearly averages",
    'AnnualTot': "Yearly sums",
    'AnnualEnd': "Value at the end of a year",
    'TotalAvg':  "Total average over the whole period from split date till end date",
    'TotalTot':  "Total sum over the whole period from split date till end date",
    'TotalEnd':  "Last value at the end of the run",
    _AREA_LABEL: "Sums up (or averages) all values for the upstream catchment",
}

# AreaSum_Daily -> "Daily values summing up all upstream cells"
# AreaAvg_Daily -> "Daily values averaging over all upstream cells"
_TYPE_TOOLTIPS.update({
    a: "%s %s all upstream cells" % (
        _TYPE_TOOLTIPS[a.split('_', 1)[1]],
        "summing up" if a.startswith('AreaSum') else "averaging over")
    for a in _AREA_TYPES
})


def open_output_variables(main_window):
    """Open (or re-open) the Add output variables picker for ``main_window``."""
    win = OutputVariablesWindow(main_window)
    win.show()
    win.raise_()
    win.activateWindow()
    return win


class OutputVariablesWindow(GeometryMemoryMixin, QDialog):
    """Alphabetical, option-filtered picker of CWatM output variables."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self._main = main_window
        self._priority_missing = False   # set by _available_varnames
        self.setWindowTitle("Add output variables")
        self.setModal(False)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("output_variables"):
            self.resize(340, 620)
        self._set_window_icon()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        intro = QLabel(
            "Click a variable to insert it at the cursor in the settings editor.\n"
            "Right-click it to pick the output type instead.\n"
            "✓ = already written by this settings file (click again to take it out);"
            "  [index] = an array variable, you are asked which one.")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            f"font-family: 'Segoe UI', sans-serif; font-size: 11px; "
            f"color: {theme.c('text_muted')};")
        layout.addWidget(intro)

        # Toggle above the filter box: default OFF = only priority="high" variables;
        # ON = every fitting variable (priority ignored).
        self.load_all_button = QPushButton("Load all Variable")
        self.load_all_button.setCheckable(True)
        self.load_all_button.setToolTip(
            "Off: show only the high-priority (recommended) output variables.\n"
            "On: show every output variable that fits the current options.")
        self.load_all_button.setStyleSheet(self._blue_button_style())
        self.load_all_button.toggled.connect(self._on_load_all_toggled)
        layout.addWidget(self.load_all_button)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter name, unit or description…")
        self.filter_edit.setToolTip(
            "Searches the variable name AND its unit, long name and description - "
            "'evapo' finds actualET")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setStyleSheet(
            f"QLineEdit {{ background: {theme.c('field_bg')}; "
            f"border: 1px solid {theme.c('field_border')}; border-radius: 5px; "
            f"padding: 4px 6px; color: {theme.c('field_text')}; }}")
        self.filter_edit.textChanged.connect(lambda _t: self._apply_filter())
        layout.addWidget(self.filter_edit)

        # Show only what the settings file already writes - the picker doubles as an
        # overview of the file's outputs.
        self.in_file_only = QCheckBox("Only variables already in the settings file")
        self.in_file_only.setStyleSheet(
            f"color: {theme.c('text')}; font-size: 11px;")
        self.in_file_only.toggled.connect(lambda _c: self._apply_filter())
        layout.addWidget(self.in_file_only)

        self.list = QListWidget()
        self.list.setStyleSheet(
            f"QListWidget {{ background: {theme.c('editor_bg')}; "
            f"border: 1px solid {theme.c('editor_border')}; border-radius: 6px; "
            f"color: {theme.c('editor_text')}; font-family: 'Consolas','Monaco',monospace; "
            f"font-size: 13px; }}"
            f"QListWidget::item:selected {{ background: {theme.c('sel_bg')}; "
            f"color: {theme.c('sel_text')}; }}")
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"font-family: 'Segoe UI', sans-serif; font-size: 12px; "
            f"color: {theme.c('text_muted')};")
        layout.addWidget(self.status)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.setStyleSheet(self._blue_button_style())
        self.close_button.clicked.connect(self.close)
        btn_row.addWidget(self.close_button)
        layout.addLayout(btn_row)

        self.setStyleSheet(f"QDialog {{ background-color: {theme.c('window_bg')}; }}")
        self._rebuild()

    # ---------------------------------------------------------------- build list
    def _settings_content(self):
        try:
            return self._main.text_area.toPlainText()
        except Exception:
            return ""

    def _flat_options(self, content):
        """Flat {key lower: raw value} across ALL sections (later wins), so a switch is
        found wherever it lives (CWatM reads these by key name from its flat dicts)."""
        opts = {}
        cur = ""
        for line in content.split('\n'):
            s = line.strip()
            if not s or s[0] in '#;':
                continue
            if s[0] == '[':
                continue
            eq = s.find('=')
            if eq <= 0:
                continue
            opts[s[:eq].strip().lower()] = s[eq + 1:].strip()
        return opts

    @staticmethod
    def _is_on(opts, name):
        return opts.get(name.lower(), "").strip().lower() in ('true', '1', 'yes', 'on')

    def _available_varnames(self):
        """Every [Array] variable minus the ones whose gating feature is off. Limited to
        priority="high" unless the "Load all Variable" toggle is on."""
        high_only = not self.load_all_button.isChecked()
        names = list(meta_netcdf.output_varnames(high_only=high_only))
        # The shipped cwatm/metaNetcdf.xml carries NO priority="…" attribute at all,
        # so the high-priority view would be empty. We must not add the flag there
        # (cwatm/ is read-only), so fall back to the full list and say why in the
        # status line. Once metaNetcdf.xml gains priority="high" entries this
        # branch stops firing by itself.
        self._priority_missing = high_only and not names
        if self._priority_missing:
            names = list(meta_netcdf.output_varnames(high_only=False))
        opts = self._flat_options(self._settings_content())
        # Collect the substrings to hide (features that are not enabled).
        hide = []
        for opt_name, patterns in _FEATURE_VAR_PATTERNS.items():
            if not self._is_on(opts, opt_name):
                hide.extend(patterns)
        if hide:
            names = [n for n in names
                     if not any(p in n.lower() for p in hide)]
        # Whatever the settings file already writes is ALWAYS listed, whichever view
        # is active - a variable that is in the file but hidden (not high-priority, or
        # its feature switched off) could otherwise neither be seen nor clicked off.
        known = set(meta_netcdf.all_varnames())
        names = list(names) + [n for n in self._file_vars() if n in known]
        # Alphabetical, case-insensitive, de-duplicated.
        return sorted(set(names), key=str.lower)

    def _on_load_all_toggled(self, checked):
        self.load_all_button.setText(
            "Load high priority Variables" if checked else "Load all Variable")
        self._rebuild()

    # ------------------------------------------------ what the file already writes
    def _file_vars(self):
        """``{base varname: [(key, line number, token as written)]}`` for every
        ``OUT_TSS_…`` / ``OUT_MAP_…`` value in the settings file - what the list marks
        with a ✓. The index is stripped for the lookup (``actualET[1]`` -> key
        ``actualET``) but kept in the token, so the tooltip can show it."""
        found = {}
        for row, line in enumerate(self._settings_content().split('\n')):
            s = line.strip()
            if not s or s[0] in '#;[':
                continue
            eq = s.find('=')
            if eq <= 0:
                continue
            key = s[:eq].strip()
            low = key.lower()
            if not (low.startswith('out_tss_') or low.startswith('out_map_')):
                continue
            for token in s[eq + 1:].split(','):
                token = token.strip()
                if not token or token.lower() == 'none':
                    continue
                base = token.split('[')[0].strip()
                found.setdefault(base, []).append((key, row + 1, token))
        return found

    def _item_tooltip(self, name, entries):
        """Tooltip of one variable: metadata, the index it needs, and where it is
        already used."""
        tip = name
        meta = meta_netcdf.get_meta(name)
        if meta:
            unit, long_name, desc = meta
            tip += f"\nunit: {unit}"
            tip += f"\nDimension: {meta_netcdf.dim_of(name)}"
            if long_name or desc:
                tip += f"\n{long_name or desc}"
        if var_dims.needs_index(name):
            tip += f"\n\nneeds an index: {var_dims.hint_of(name)}"
        if entries:
            where = ", ".join(f"{k} (line {row})" for k, row, _t in entries[:6])
            tip += f"\n\nalready in the settings file: {where}"
            if len(entries) > 6:
                tip += f", +{len(entries) - 6} more"
            tip += "\nClick it again to take it out."
        return tip

    def _make_item(self, name, entries):
        """One variable row: ``✓`` when the settings file already writes it, ``[index]``
        when it is an array variable that needs one."""
        marked = bool(entries)
        text = ("✓ " if marked else "   ") + name
        if var_dims.needs_index(name):
            text += "  [index]"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, name)
        item.setToolTip(self._item_tooltip(name, entries))
        if marked:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setForeground(QColor(theme.c('ok_color')))
        return item

    @staticmethod
    def _haystack(name):
        """What the filter searches: the name plus unit / long name / description, so
        'evapo' finds actualET."""
        parts = [name]
        meta = meta_netcdf.get_meta(name)
        if meta:
            parts.extend(str(p) for p in meta if p)
        return " ".join(parts).lower()

    def _add_group_header(self, title, count):
        item = QListWidgetItem(f"{title}  ({count})")
        item.setFlags(Qt.NoItemFlags)          # a label, not a choice
        item.setData(Qt.UserRole, None)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QColor(theme.c('text_muted')))
        item.setBackground(QColor(theme.c('surface_bg')))
        self.list.addItem(item)

    def _rebuild(self):
        names = self._available_varnames()
        self._all_names = names
        self._haystacks = {n: self._haystack(n) for n in names}
        entries_by_var = self._file_vars()
        self._options_signature = self._current_signature()
        grouped = {}
        for n in names:
            grouped.setdefault(group_of(n), []).append(n)
        self.list.clear()
        for title in _GROUP_ORDER:
            group_names = grouped.get(title)
            if not group_names:
                continue
            self._add_group_header(title, len(group_names))
            for n in sorted(group_names, key=str.lower):
                self.list.addItem(self._make_item(n, entries_by_var.get(n)))
        self._apply_filter()
        note = f"{len(names)} output variable(s) fit the current options."
        if getattr(self, "_priority_missing", False):
            note += ("  metaNetcdf.xml has no priority=\"high\" flags yet, "
                     "so all of them are listed.")
        self._status(note)

    def _refresh_marks(self):
        """Re-apply the ✓ / bold / tooltip after the settings file changed - much
        cheaper than a rebuild, and it keeps the scroll position and the filter."""
        entries_by_var = self._file_vars()
        for i in range(self.list.count()):
            item = self.list.item(i)
            name = item.data(Qt.UserRole)
            if not name:
                continue
            entries = entries_by_var.get(name)
            marked = bool(entries)
            item.setText(("✓ " if marked else "   ") + name
                         + ("  [index]" if var_dims.needs_index(name) else ""))
            font = item.font()
            font.setBold(marked)
            item.setFont(font)
            item.setForeground(QColor(theme.c('ok_color') if marked
                                      else theme.c('editor_text')))
            item.setToolTip(self._item_tooltip(name, entries))
        if self.in_file_only.isChecked():
            self._apply_filter()

    def _current_signature(self):
        """The gating [OPTIONS] values the list was built from - so a re-activated
        window can tell "the options changed, rebuild" from "nothing to do"."""
        opts = self._flat_options(self._settings_content())
        return tuple(opts.get(name, "") for name in sorted(_FEATURE_VAR_PATTERNS))

    def changeEvent(self, event):
        """Coming back to the window: re-read the settings file. The ✓ marks are
        always refreshed (cheap, keeps the scroll position); the list itself is only
        rebuilt when a gating option actually changed - that is what the removed
        Refresh button used to be for."""
        super().changeEvent(event)
        if not hasattr(self, "list"):          # still being built
            return
        if event.type() == event.Type.ActivationChange and self.isActiveWindow():
            try:
                if self._current_signature() != getattr(self, "_options_signature", None):
                    self._rebuild()
                else:
                    self._refresh_marks()
            except Exception:
                log.debug("refresh on activation failed", exc_info=True)

    def _apply_filter(self):
        """Hide what does not match the filter text / the 'only in the file' tick, and
        hide a group header whose whole group went with it."""
        text = self.filter_edit.text().strip().lower()
        only_in_file = self.in_file_only.isChecked()
        header = None
        shown_in_group = 0
        shown = 0
        for i in range(self.list.count()):
            item = self.list.item(i)
            name = item.data(Qt.UserRole)
            if not name:                       # group header
                if header is not None:
                    header.setHidden(shown_in_group == 0)
                header, shown_in_group = item, 0
                continue
            hide = bool(text) and text not in self._haystacks.get(name, name.lower())
            if not hide and only_in_file and "✓" not in item.text():
                hide = True
            item.setHidden(hide)
            if not hide:
                shown_in_group += 1
                shown += 1
        if header is not None:
            header.setHidden(shown_in_group == 0)
        if text or only_in_file:
            self._status(f"{shown} of {len(self._all_names)} variable(s) shown.")

    # ------------------------------------------------------- right-click menu
    def _on_context_menu(self, pos):
        """Right-click a variable: choose timeseries or map plus a time step, and
        the variable is added to that output key - the key is created under
        [OUTPUT] when the settings file does not have it yet. No cursor position
        needed (unlike the left-click insert)."""
        item = self.list.itemAt(pos)
        if item is None:
            return
        varname = item.data(Qt.UserRole)
        if not varname:                    # a group header
            return

        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        tss = menu.addMenu("Timeseries (TSS)")
        tss.setToolTipsVisible(True)
        tss.menuAction().setToolTip(
            f"Write '{varname}' as a time series (OUT_TSS_…) at the gauge points")
        for t in _TIME_TYPES:
            self._add_type_action(tss, varname, "TSS", t)
        # Two more levels: the aggregation first, then its time step.
        area = tss.addMenu(_AREA_LABEL)
        area.setToolTipsVisible(True)
        area.menuAction().setToolTip(_TYPE_TOOLTIPS[_AREA_LABEL])
        for agg in _AREA_AGGS:
            sub = area.addMenu(agg)
            sub.setToolTipsVisible(True)
            sub.menuAction().setToolTip(_AREA_AGG_TOOLTIPS[agg])
            for t in _AREA_TIME_TYPES:
                self._add_type_action(sub, varname, "TSS", f"{agg}_{t}", label=t)

        maps = menu.addMenu("Map (MAP)")
        maps.setToolTipsVisible(True)
        maps.menuAction().setToolTip(
            f"Write '{varname}' as a NetCDF map (OUT_MAP_…)")
        for t in _TIME_TYPES:
            self._add_type_action(maps, varname, "MAP", t)

        menu.exec(self.list.viewport().mapToGlobal(pos))

    def _add_type_action(self, menu, varname, kind, type_name, label=None):
        """One time-step entry: tooltip = what it means plus the line it will
        produce. kind is 'TSS' or 'MAP'. ``label`` overrides the menu text - the
        upstream-calculation entries show only their time step ("MonthTot"), the
        aggregation being their parent submenu (AreaSum/AreaAvg)."""
        key = f"OUT_{kind}_{type_name}"
        tip = _TYPE_TOOLTIPS.get(type_name, "")
        options = var_dims.index_options(varname)
        if options and not (kind == "TSS" and type_name in _TSS_ONLY_INVALID):
            # An array variable: the time step becomes a submenu of its valid indices,
            # named ("1 - grassland"), so the user never has to guess the number.
            sub = menu.addMenu(label or type_name)
            sub.setToolTipsVisible(True)
            sub.menuAction().setToolTip(f"{tip}\n{var_dims.hint_of(varname)}")
            for suffix, item_label, item_tip in options:
                act = sub.addAction(item_label)
                act.setToolTip(item_tip if suffix is None
                               else f"{item_tip}\n→  {key} = {varname}{suffix}")
                act.triggered.connect(
                    lambda checked=False, v=varname, s=suffix, k=key:
                    self._add_indexed(v, s, k))
            return sub.menuAction()
        act = menu.addAction(label or type_name)
        if kind == "TSS" and type_name in _TSS_ONLY_INVALID:
            # Offered but not selectable - CWatM's TSS grammar has no such type,
            # and it would be silently dropped / raise Error 130 at run start.
            act.setEnabled(False)
            act.setToolTip(
                f"{tip}\nNot available for timeseries (CWatM's outputTypTss has no "
                f"{type_name}) - use Map (MAP) ▸ {type_name}.")
            return act
        act.setToolTip(f"{tip}\n→  {key} = {varname}")
        act.triggered.connect(
            lambda checked=False, v=varname, k=key: self._add_output(v, k))
        return act

    # ------------------------------------------------- add to / create the key
    def _ask_index(self, varname):
        """The 'other crop number…' entry: ask for the index. Returns '[7]' or None."""
        value, ok = QInputDialog.getInt(
            self, "Crop index",
            f"Crop number for '{varname}'\n(the crop list comes from the settings "
            "Excel sheet):", 0, 0, 999, 1)
        return f"[{value}]" if ok else None

    def _add_indexed(self, varname, suffix, key):
        """Right-click on an array variable: add ``varname[index]`` to ``key``."""
        if suffix is None:
            suffix = self._ask_index(varname)
            if suffix is None:
                return
        self._add_output(varname + suffix, key)

    def _add_output(self, varname, key):
        """Add ``varname`` to the ``key`` output line: append it to the existing
        line's comma list, or create ``key = varname`` at the end of [OUTPUT]."""
        editor = getattr(self._main, "text_area", None)
        if editor is None:
            return
        lines = editor.toPlainText().split('\n')
        row = self._find_key_row(lines, key)
        if row is not None:
            line = lines[row]
            eq = line.find('=')
            tokens = [t.strip() for t in line[eq + 1:].split(',') if t.strip()]
            if varname in tokens:
                # Second pick of the same variable = undo the first one (and take
                # the whole line with it when nothing else is written to that key).
                self._status(self._remove_output(varname, row), 'muted')
                return
            if not tokens or [t.lower() for t in tokens] == ['none']:
                # An empty value / a leading 'None' means "output off" in CWatM -
                # replace it instead of appending behind it.
                lines[row] = line[:eq + 1] + ' ' + varname
            else:
                lines[row] = line.rstrip() + ', ' + varname
            note = f"Added '{varname}' to {key} (line {row + 1})."
        else:
            row = self._insert_output_line(lines, f"{key} = {varname}")
            note = f"Created '{key} = {varname}' (line {row + 1})."
        # One undoable step; keeps folding and the scroll position (never
        # setPlainText, which would clear the undo stack).
        editor.set_content_preserving('\n'.join(lines))
        self._goto_row(editor, row)
        self._refresh_marks()
        self._status(note, 'ok')

    def _remove_output(self, varname, row):
        """Take ``varname`` off the output line at ``row``. When it was the last
        variable there the **whole line is deleted** - an ``OUT_… =`` line without
        a value is dead weight (and a line created by the right-click menu should
        disappear again when the variable is de-selected). Returns a status note."""
        editor = self._main.text_area
        lines = editor.toPlainText().split('\n')
        line = lines[row]
        eq = line.find('=')
        key_disp = line[:eq].strip()
        rest = [t.strip() for t in line[eq + 1:].split(',')
                if t.strip() and t.strip() != varname]
        if rest:
            lines[row] = line[:eq + 1] + ' ' + ', '.join(rest)
            note = f"Removed '{varname}' from {key_disp}."
        else:
            del lines[row]
            note = f"Removed '{varname}' - the empty {key_disp} line was deleted."
        editor.set_content_preserving('\n'.join(lines))
        self._goto_row(editor, min(row, editor.document().blockCount() - 1))
        self._refresh_marks()
        return note

    @staticmethod
    def _find_key_row(lines, key):
        """Row of the (uncommented) line defining ``key``, or None. A hit inside
        [OUTPUT] wins - CWatM collects out_* keys per section, and that is where
        new keys are created."""
        want = key.lower()
        in_output = False
        first = None
        for i, line in enumerate(lines):
            s = line.strip()
            if not s or s[0] in '#;':
                continue
            if s[0] == '[':
                in_output = s.lower().startswith('[output]')
                continue
            eq = s.find('=')
            if eq <= 0 or s[:eq].strip().lower() != want:
                continue
            if in_output:
                return i
            if first is None:
                first = i
        return first

    @staticmethod
    def _insert_output_line(lines, new_line):
        """Put ``new_line`` after the last entry of the [OUTPUT] section (creating
        the section at the end of the file if there is none). Mutates ``lines``
        and returns the row it was written to."""
        out_start = None
        for i, line in enumerate(lines):
            if line.strip().lower() == '[output]':
                out_start = i
                break
        if out_start is None:
            while lines and not lines[-1].strip():
                lines.pop()
            lines.extend(['', '[OUTPUT]', new_line])
            return len(lines) - 1
        insert_at = len(lines)
        for j in range(out_start + 1, len(lines)):
            s = lines[j].strip()
            if s.startswith('[') and s.endswith(']'):
                insert_at = j
                break
        while insert_at - 1 > out_start and not lines[insert_at - 1].strip():
            insert_at -= 1
        lines.insert(insert_at, new_line)
        return insert_at

    @staticmethod
    def _goto_row(editor, row):
        """Put the editor cursor on ``row`` and make it visible (unfolding its
        section if the line is hidden)."""
        block = editor.document().findBlockByNumber(row)
        if not block.isValid():
            return
        editor.setTextCursor(QTextCursor(block))
        try:
            editor.reveal_cursor()
        except Exception:
            log.debug("reveal_cursor failed", exc_info=True)
        editor.ensureCursorVisible()

    # ---------------------------------------------------------------- insert
    def _on_item_clicked(self, item):
        if item is None:
            return
        varname = item.data(Qt.UserRole)
        if varname:                        # not a group header
            self._insert(varname)

    def _insert(self, varname):
        editor = getattr(self._main, "text_area", None)
        if editor is None:
            return
        cur = editor.textCursor()
        block_text = cur.block().text()
        s = block_text.strip()
        eq = s.find('=')
        key = s[:eq].strip().lower() if eq > 0 else ""
        # Only OUT_TSS_… / OUT_MAP_… lines take a variable list (OUT_…_Dir takes a path).
        if not (key.startswith('out_tss_') or key.startswith('out_map_')):
            self._status(
                "⚠  Put the cursor on an output line (OUT_TSS_… / OUT_MAP_…) first - "
                "nothing was inserted. (Right-click a variable to pick the output "
                "type instead - no cursor needed.)", 'warn')
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.beep()
            except Exception:
                log.debug("_insert: ignored", exc_info=True)
            return
        key_disp = s[:eq].strip()
        # Toggle: if the variable is already in this output line's value list, a second
        # click removes it (and the line itself once it holds nothing else); otherwise
        # it is inserted at the cursor. An array variable matches on its **base** name,
        # so a click takes 'actualET[1]' out again.
        eq_full = block_text.find('=')
        present = [t.strip() for t in block_text[eq_full + 1:].split(',') if t.strip()]
        same = [t for t in present if t.split('[')[0].strip() == varname]
        if same:
            self._status(self._remove_output(same[0], cur.blockNumber()), 'muted')
            return
        # An array variable is invalid without an index (actualET -> actualET[1]), so
        # ask which one - by name, at the mouse, instead of writing a line CWatM
        # rejects.
        if var_dims.needs_index(varname):
            suffix = self._pick_index(varname)
            if suffix is None:
                return
            varname += suffix
        # Smart insert at the cursor: keep the line a valid comma list.
        pos = cur.positionInBlock()
        before, after = block_text[:pos], block_text[pos:]
        ins = varname
        lb = before.rstrip()
        if lb and lb[-1] not in ',=':
            ins = ', ' + ins
        ra = after.lstrip()
        if ra and ra[0] != ',':
            ins = ins + ', '
        cur.insertText(ins)
        editor.setTextCursor(cur)
        self._refresh_marks()
        self._status(f"Inserted '{varname}' into {key_disp}.", 'ok')

    def _pick_index(self, varname):
        """Small menu at the mouse with the variable's valid indices, named
        ("1 - grassland"). Returns '[1]' / '[0][2]', or None when dismissed."""
        options = var_dims.index_options(varname)
        if not options:
            return ""
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        title = menu.addAction(var_dims.hint_of(varname))
        title.setEnabled(False)
        menu.addSeparator()
        actions = {}
        for suffix, label, tip in options:
            act = menu.addAction(label)
            act.setToolTip(tip)
            actions[act] = suffix
        chosen = menu.exec(QCursor.pos())
        if chosen is None or chosen not in actions:
            return None
        suffix = actions[chosen]
        return self._ask_index(varname) if suffix is None else suffix

    # ---------------------------------------------------------------- misc
    def _status(self, text, kind='muted'):
        """Set the status line under the list. kind: 'muted' | 'ok' | 'warn'."""
        color = {'ok': theme.c('ok_color'),
                 'warn': theme.c('warn_color')}.get(kind, theme.c('text_muted'))
        self.status.setText(text)
        self.status.setStyleSheet(
            f"font-family: 'Segoe UI', sans-serif; font-size: 12px; "
            f"font-weight: {'bold' if kind == 'warn' else 'normal'}; "
            f"color: {color};")

    def _set_window_icon(self):
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(__file__))))
            icon_path = os.path.join(root, "assets", "cwatm.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            log.debug("_set_window_icon: ignored", exc_info=True)

    @staticmethod
    def _blue_button_style():
        """Branded blue button (white-on-colour, theme-independent) — matches the
        NetCDF viewer's buttons."""
        return """
            QPushButton { font-family: 'Segoe UI', sans-serif; font-size: 12px;
                font-weight: 500; color: white; border: none; border-radius: 6px;
                padding: 5px 14px; min-height: 22px;
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #5dade2, stop:1 #3498db); }
            QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #85c1e9, stop:1 #5dade2); }
            QPushButton:checked { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #2e86c1, stop:1 #21618c); }
            QPushButton:disabled { background: #d3d3d3; color: #a9a9a9; }
        """

    @staticmethod
    def _button_style():
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_top')}, stop:1 {theme.c('btn_bottom')});
                border: 1px solid {theme.c('btn_border')}; border-radius: 5px;
                color: {theme.c('btn_text')}; font-weight: 600; font-size: 11px;
                padding: 4px 12px; min-height: 18px;
            }}
            QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme.c('btn_hover_top')}, stop:1 {theme.c('btn_hover_bottom')});
                border-color: {theme.c('btn_hover_border')}; }}
        """
