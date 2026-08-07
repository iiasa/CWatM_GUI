"""
Menu bar construction for the CWatM GUI main window.

Extracted verbatim from main_window.py: builds the full menu bar (File /
Settings / Tools / RUN CWATM / Configure / Analyse / Help / Info), the menu-bar
group separators and the recent-files handling (listed directly in the File
menu). Mixed into CWatMMainWindow - all state lives on the main window instance.
"""

import os

from PySide6.QtWidgets import QMenuBar, QMenu
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices
from PySide6.QtCore import QUrl, QObject, QEvent

from src.gui.utils.gui_log import get_logger

log = get_logger("menu_builder")


class _KeepMenuOpenFilter(QObject):
    """Event filter that keeps a QMenu **open** after a checkable (tick-box) item is
    clicked, so the ☐→☑ change is visible instead of the menu vanishing. Non-checkable
    items (dialogs, submenus) behave normally."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonRelease and isinstance(obj, QMenu):
            act = obj.actionAt(event.position().toPoint())
            if act is not None and act.isCheckable() and act.isEnabled():
                act.trigger()          # toggle + fire the connected slots
                return True             # consume the event -> the menu stays open
        return False


class MenuBuilderMixin:
    """Menu-bar construction and History menu maintenance for CWatMMainWindow."""

    def create_menu_bar(self, parent_layout):
        """Create menu bar with Info menu, placed below the banner.

        Built as a QMenuBar *widget* added to the layout (rather than the native
        QMainWindow menu bar, which is always pinned to the very top of the window).
        """
        menu_bar = QMenuBar()
        menu_bar.setNativeMenuBar(False)  # keep it in the layout (incl. macOS)

        # File menu (left of Info) — same actions as the Load/Save/Save As buttons.
        # Wrapped in lambdas so the QAction.triggered "checked" bool is not passed
        # as an argument (save_file takes an optional 'new' flag).
        file_menu = menu_bar.addMenu("File")
        load_action = file_menu.addAction("Load .ini")
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(lambda: self.load_file())
        reload_action = file_menu.addAction("Reload")
        reload_action.setShortcut("Ctrl+L")
        reload_action.triggered.connect(lambda: self.reload_file())
        save_action = file_menu.addAction("Save .ini")
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(lambda: self.save_file())
        # Kept referenced so the run controller can grey out Save (but not Save As)
        # while CWatM is running.
        self._save_menu_action = save_action
        save_as_action = file_menu.addAction("Save As")
        save_as_action.setShortcut("Ctrl+Alt+S")
        save_as_action.triggered.connect(lambda: self.save_as_file())
        file_menu.addSeparator()
        workdir_action = file_menu.addAction("Change Working Dir")
        workdir_action.setToolTip(
            "Changes the working directory and executes from here")
        workdir_action.triggered.connect(lambda: self.change_working_dir())
        file_menu.addSeparator()
        # Recent settings files listed directly here (between Change Working Dir and
        # Exit), rebuilt on every open. They are inserted before this exit separator.
        self._file_menu = file_menu
        self._file_menu.setToolTipsVisible(True)
        self._history_actions = []
        self._exit_separator = file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(lambda: self.close())
        file_menu.aboutToShow.connect(self._populate_history_menu)

        # Settings menu (right of File) — same actions as the editor toolbar buttons
        settings_menu = menu_bar.addMenu("Settings")
        self._add_menu_section(settings_menu, "View", first=True)
        compress_action = settings_menu.addAction("Fold All")
        compress_action.setShortcut("Alt+0")
        compress_action.triggered.connect(lambda: self.compress_all_sections())
        expand_action = settings_menu.addAction("Unfold All")
        expand_action.setShortcut("Alt+Shift+0")
        # Pass False so it actually unfolds (the no-arg default notexpand=True does not)
        expand_action.triggered.connect(lambda: self.expand_all_sections(False))
        top_action = settings_menu.addAction("Top")
        top_action.setShortcut("Alt+T")
        top_action.triggered.connect(lambda: self.jump_to_top())
        down_action = settings_menu.addAction("Down")
        down_action.setShortcut("Alt+D")
        down_action.triggered.connect(lambda: self.jump_to_bottom())
        self._add_menu_section(settings_menu, "Find && Replace")
        find_action = settings_menu.addAction("Find")
        find_action.setShortcut("Ctrl+F")
        find_action.triggered.connect(lambda: self.find_text())
        find_next_action = settings_menu.addAction("Find next")
        find_next_action.setShortcut("F3")
        find_next_action.triggered.connect(lambda: self.find_next())
        find_prev_action = settings_menu.addAction("Find previous")
        find_prev_action.setShortcut("Shift+F3")
        find_prev_action.triggered.connect(lambda: self.find_previous())
        replace_action = settings_menu.addAction("Replace")
        replace_action.setShortcut("Ctrl+H")
        replace_action.triggered.connect(lambda: self.replace_text())
        self._add_menu_section(settings_menu, "Edit")
        undo_action = settings_menu.addAction("Undo")
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(lambda: self.text_area.undo())
        redo_action = settings_menu.addAction("Redo")
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(lambda: self.text_area.redo())
        self._add_menu_section(settings_menu, "Bookmarks && Changes")
        toggle_bm_action = settings_menu.addAction("Toggle Bookmark")
        toggle_bm_action.setShortcut("Ctrl+F2")
        toggle_bm_action.triggered.connect(lambda: self.text_area.toggle_bookmark())
        next_bm_action = settings_menu.addAction("Next Bookmark")
        next_bm_action.setShortcut("F2")
        next_bm_action.triggered.connect(lambda: self.text_area.goto_next_bookmark(True))
        prev_bm_action = settings_menu.addAction("Previous Bookmark")
        prev_bm_action.setShortcut("Shift+F2")
        prev_bm_action.triggered.connect(lambda: self.text_area.goto_next_bookmark(False))
        clear_bm_action = settings_menu.addAction("Clear all Bookmarks")
        clear_bm_action.setShortcut("Ctrl+Shift+F2")
        clear_bm_action.triggered.connect(lambda: self.text_area.clear_bookmarks())
        last_change_action = settings_menu.addAction("Goto last change")
        last_change_action.setShortcut("F5")
        last_change_action.setToolTip("Jump to the most recently changed line")
        last_change_action.triggered.connect(lambda: self.text_area.goto_last_change())
        self._add_menu_section(settings_menu, "Check && Compare")
        # One toggle item (F4): runs Check settingsfile when nothing is marked and
        # flips its label to "Clear checking"; when marks are shown it clears them and
        # flips back. The label is re-synced whenever the Settings menu opens.
        check_settings_action = settings_menu.addAction("Check settingsfile")
        check_settings_action.setShortcut("F4")
        check_settings_action.triggered.connect(lambda: self.toggle_check_settings())
        self.check_settings_action = check_settings_action
        self._refresh_check_settings_label()
        settings_menu.aboutToShow.connect(self._refresh_check_settings_label)
        compare_action = settings_menu.addAction("Compare settings")
        compare_action.setToolTip(
            "Show the differences between the current settings file and another one "
            "side by side")
        compare_action.triggered.connect(lambda: self.open_compare_settings())

        # Excel menu (between Settings and Tools) — edit the settings Excel workbook
        excel_menu = menu_bar.addMenu("Excel")
        excel_menu.setToolTipsVisible(True)
        crops_action = excel_menu.addAction("Crops")
        crops_action.setToolTip(
            "Open the 'Crops' sheet of the settings Excel file (Excel_settings_file) "
            "in an editable, colour-preserving table")
        crops_action.triggered.connect(lambda: self.open_excel_sheet("Crops"))
        reservoirs_action = excel_menu.addAction("Reservoirs")
        reservoirs_action.setToolTip(
            "Open the 'Reservoirs' sheet of the settings Excel file "
            "(Excel_settings_file) in an editable, colour-preserving table")
        reservoirs_action.triggered.connect(
            lambda: self.open_excel_sheet("Reservoirs", release_sheet="Reservoirs_downstream"))
        # The Excel menu itself stays open-able; its two items are greyed out while
        # the settings file has no 'Excel_settings_file' key (kept referenced so
        # _update_excel_menu_enabled can toggle them as the text changes).
        self._excel_actions = [crops_action, reservoirs_action]
        self._update_excel_menu_enabled()

        # Tools menu (right of File) — same actions as the side buttons
        tools_menu = menu_bar.addMenu("Tools")
        tools_menu.setToolTipsVisible(True)

        self._add_menu_section(tools_menu, "Basin && Gauges", first=True)
        basin_action = tools_menu.addAction("Show Basin")
        basin_action.setToolTip(
            "Basin viewer on a folium (Leaflet) map in EPSG:4326 - ups.nc/mask "
            "overlays drawn in native lon/lat (no rasterio reprojection, crisp)")
        basin_action.triggered.connect(lambda: self.show_basin())
        set_gauge_action = tools_menu.addAction("Set max Gauge")
        set_gauge_action.setToolTip("Find the point with the largest upstream area in Mask Map")
        set_gauge_action.triggered.connect(lambda: self.set_gauge())
        self._add_menu_section(tools_menu, "Outputs")
        watercycle_action = tools_menu.addAction("Add output Watercycle")
        watercycle_action.setToolTip("Adds an additional output for creating watercycles")
        watercycle_action.triggered.connect(lambda: self.add_output_watercycle())
        outvars_action = tools_menu.addAction("Add output variables")
        outvars_action.setToolTip("Shows a list of possible output variables to select from")
        outvars_action.triggered.connect(lambda: self.add_output_variables())
        self._add_menu_section(tools_menu, "Setup && Data")
        options_action = tools_menu.addAction("Change Options")
        options_action.setToolTip("Display a popup with the settingsfile [Options]")
        options_action.triggered.connect(lambda: self.open_options_window())
        check_action = tools_menu.addAction("Check Data")
        check_action.triggered.connect(lambda: self.open_check_data_window())
        create_pathout_action = tools_menu.addAction("Create PathOut Folder")
        create_pathout_action.triggered.connect(lambda: self.create_pathout_folder())
        self._add_menu_section(tools_menu, "Results && History")
        restore_action = tools_menu.addAction("Restore settingsfile")
        restore_action.setToolTip(
            "Open a CWatM output NetCDF (dis*.nc) and show its stored run metadata")
        restore_action.triggered.connect(lambda: self.restore_settingsfile())
        ledger_action = tools_menu.addAction("Run Ledger")
        ledger_action.setToolTip(
            "Show the log of past runs; reopen their results or reload/compare their settings")
        ledger_action.triggered.connect(lambda: self.open_run_ledger())

        # RUN CWATM menu (right of Tools). Actualize was removed: field changes are
        # auto-applied to the content, and Save/Run flush any pending change first.
        run_menu = menu_bar.addMenu("RUN CWATM")
        run_action = run_menu.addAction("Run CWATM")
        run_action.setShortcut("Ctrl+R")
        run_action.triggered.connect(lambda: self.run_cwatm())
        # Hidden Run: open an independent window that runs CWatM in its own process
        # (does not touch the main run or the main GUI); several can run in parallel.
        hidden_run_action = run_menu.addAction("Hidden Run CWatM")
        hidden_run_action.setToolTip(
            "Open a separate window that runs CWatM in its own process, without "
            "interfering with the main GUI (several can run at once)")
        hidden_run_action.triggered.connect(lambda: self.open_hidden_run())
        run_menu.addSeparator()
        batch_action = run_menu.addAction("Batch Run…")
        batch_action.setToolTip(
            "Run many scenarios from the loaded settings file (base .ini + per-row "
            "key overrides), up to N in parallel")
        batch_action.triggered.connect(lambda: self.open_batch_runner())

        # --- Group divider: end of the "running CWatM" part ---
        self._add_menubar_separator(menu_bar)

        # Analyse menu (analyse results) — its own group
        analyse_menu = menu_bar.addMenu("Analyse")
        analyse_menu.setToolTipsVisible(True)
        open_pathout_action = analyse_menu.addAction("Open PathOut Folder")
        open_pathout_action.setToolTip(
            "Open the resolved PathOut directory in the file explorer")
        open_pathout_action.triggered.connect(lambda: self.open_pathout_folder())
        output_explorer_action = analyse_menu.addAction("Output Explorer")
        output_explorer_action.setToolTip(
            "Browse the PathOut folder; double-click a result to open the matching "
            "viewer (.nc → map, .csv → timeseries, WaterCycle → sunburst)")
        output_explorer_action.triggered.connect(self.open_output_explorer)
        analyse_menu.addSeparator()
        timeseries_action = analyse_menu.addAction("Timeseries")
        timeseries_action.setToolTip("Plot a CWatM result .csv time series (Plotly scatter)")
        timeseries_action.triggered.connect(self.open_timeseries_analysis)
        netcdf_action = analyse_menu.addAction("NetCDF")
        netcdf_action.setToolTip(
            "Show a .nc file on a folium OSM map (EPSG:4326) with an OSM-transparency "
            "slider, colour scale and log scale")
        netcdf_action.triggered.connect(self.open_netcdf_analysis)
        watercycle_action = analyse_menu.addAction("Watercycle")
        watercycle_action.setToolTip(
            "Show the water balance of a WaterCycle_areasum_monthtot.csv as a sunburst")
        watercycle_action.triggered.connect(self.open_watercycle_analysis)
        flowdiagram_action = analyse_menu.addAction("Flow Diagram")
        flowdiagram_action.setToolTip(
            "Show the water balance of a WaterCycle_areasum_monthtot.csv as a Sankey flow diagram")
        flowdiagram_action.triggered.connect(self.open_flowdiagram_analysis)

        # --- Group divider: between "analyse results" and "Help & Info" ---
        self._add_menubar_separator(menu_bar)

        # Configure menu (left of Help). "Write output box" is a checkable tick box;
        # run_cwatm reads the mirrored self._write_output_enabled bool.
        configure_menu = menu_bar.addMenu("Configure")
        configure_menu.setToolTipsVisible(True)  # show action tooltips in the menu

        self._add_menu_section(configure_menu, "Output", first=True)
        set_output_action = configure_menu.addAction("Set output box file…")
        set_output_action.triggered.connect(lambda: self.set_output_box_file())
        # Checkable "Write output box": ☐/☑ box marks it as a tick box.
        self.write_output_action = configure_menu.addAction("Write output box")
        self.write_output_action.setCheckable(True)
        self.write_output_action.setChecked(False)
        self.write_output_action.setToolTip(
            "Writes input to output box to disk, but can slow down a run")
        # Mirror the checkbox into a plain bool so run_cwatm never has to touch the
        # QAction's C++ object (which can outlive-mismatch its Python wrapper).
        self._write_output_enabled = False
        self.write_output_action.toggled.connect(self._on_write_output_toggled)
        self._wire_checkbox_glyph(self.write_output_action, "Write output box")
        # Refresh the tooltip with the current effective output path when opened
        configure_menu.aboutToShow.connect(self._update_output_tooltip)

        # "Run model in separate process" (default ON, persisted): CWatM runs in its
        # own OS process (real Stop, crash isolation - report §3.1). The FUNCTIONALITY
        # is kept (run_controller reads self._run_subprocess_enabled), but the toggle is
        # no longer SHOWN in Configure - the action is created standalone (not added to
        # any menu) so its state still loads/persists and the run path is unchanged.
        # Re-add it to a menu to expose it again.
        _subproc = self._settings.value("run/subprocess", True, type=bool)
        self.run_subprocess_action = QAction("Run model in separate process", self)
        self.run_subprocess_action.setCheckable(True)
        self.run_subprocess_action.setChecked(_subproc)
        self._on_run_subprocess_toggled(_subproc)  # mirror bool (+ glyph text)
        self.run_subprocess_action.toggled.connect(self._on_run_subprocess_toggled)

        self._add_menu_section(configure_menu, "Startup && Model")
        # Checkable "Load previous settings at start" (persisted, default OFF): when
        # ticked, the most recently opened settings file is re-opened automatically on
        # the next startup (handled in cwatm_gui.py main()).
        _load_prev = self._settings.value("startup/load_previous", False, type=bool)
        self.load_previous_action = configure_menu.addAction("Load previous settings at start")
        self.load_previous_action.setCheckable(True)
        self.load_previous_action.setChecked(_load_prev)
        self.load_previous_action.setToolTip(
            "When ticked, the last settings file you had open is loaded again "
            "automatically the next time CWatM GUI starts.")
        self._on_load_previous_toggled(_load_prev)  # persist
        self.load_previous_action.toggled.connect(self._on_load_previous_toggled)
        self._wire_checkbox_glyph(self.load_previous_action,
                                  "Load previous settings at start")

        # Checkable "Use Modflow" (persisted, default OFF): when ON the GUI pre-imports
        # flopy (heavy - pulls the matplotlib stack) so MODFLOW-coupled runs / Check Data
        # are ready; when OFF flopy is never loaded, keeping GUI startup fast.
        _use_modflow = self._settings.value("modflow/enabled", False, type=bool)
        self.use_modflow_action = configure_menu.addAction("Use Modflow")
        self.use_modflow_action.setCheckable(True)
        self.use_modflow_action.setChecked(_use_modflow)
        self.use_modflow_action.setToolTip(
            "Load flopy for MODFLOW coupling. Off = flopy is not loaded (faster start).")
        self._on_use_modflow_toggled(_use_modflow)  # persist + warm if on
        self.use_modflow_action.toggled.connect(self._on_use_modflow_toggled)
        self._wire_checkbox_glyph(self.use_modflow_action, "Use Modflow")

        self._add_menu_section(configure_menu, "Display")
        # Colour mode for the whole GUI (Normal / Dark Mode / Mikhail).
        from src.gui.utils import theme as _theme
        mode_menu = configure_menu.addMenu("Mode")
        mode_menu.setToolTipsVisible(True)
        mode_menu.setToolTip("Colour mode of the whole GUI")
        self._mode_group = QActionGroup(self)
        self._mode_group.setExclusive(True)
        _active = _theme.current_theme()
        for _label, _key in _theme.THEME_CHOICES:
            act = mode_menu.addAction(_label)
            act.setCheckable(True)
            act.setData(_key)
            act.setChecked(_key == _active)
            if _key == "mikhail":
                act.setToolTip("Black background with amber font")
            self._mode_group.addAction(act)
            act.triggered.connect(lambda *_a, k=_key: self._set_theme_mode(k))
        self._mode_menu = mode_menu

        # Show Header: the top banner (CWatM icon + title + interface text + IIASA
        # logo). Off hides the banner and moves everything below up.
        show_header_action = configure_menu.addAction("Show Header")
        show_header_action.setCheckable(True)
        show_header_action.setToolTip("Shows the headline of the CWatM GUI")
        show_header_action.setChecked(
            self._settings.value("display/show_header", True, type=bool))
        show_header_action.toggled.connect(self._on_show_header_toggled)
        self.show_header_action = show_header_action
        self._wire_checkbox_glyph(show_header_action, "Show Header")

        # Global display precision: how many decimals every numeric read-out shows.
        decimals_action = configure_menu.addAction("Show Decimals…")
        decimals_action.setToolTip(
            "Number of decimals shown throughout all displays (default 3)")
        decimals_action.triggered.connect(self.set_show_decimals)
        transparency_action = configure_menu.addAction("Transparency…")
        transparency_action.setToolTip(
            "Initial map transparency (0-100) used by NetCDF and Show Basin")
        transparency_action.triggered.connect(self.set_transparency)

        # Default basemap for the Show Basin map (the EPSG:4326 WMS layers Show
        # Basin offers). Kept in sync with basin_viewer2._B2_PROVIDERS.
        basemap_menu = configure_menu.addMenu("Default openstreet map")
        basemap_menu.setToolTipsVisible(True)
        self._basemap_group = QActionGroup(self)
        self._basemap_group.setExclusive(True)
        _basemaps = [("OSM", "OSM-WMS"), ("Topographic", "TOPO-OSM-WMS"),
                     ("Terrain", "SRTM30-Colored-Hillshade"), ("Dark", "Dark")]
        saved = self._settings.value("basin/default_basemap", "OSM-WMS")
        if saved not in {k for _l, k in _basemaps}:   # migrate an old XYZ key
            saved = "OSM-WMS"
        for _label, _key in _basemaps:
            act = basemap_menu.addAction(_label)
            act.setCheckable(True)
            act.setData(_key)
            act.setChecked(_key == saved)
            self._basemap_group.addAction(act)
            act.triggered.connect(lambda *_a, k=_key: self._set_default_basemap(k))

        # Select animal: the cameo animal that occasionally appears on the live
        # discharge sparkline (exclusive submenu, persisted display/animal).
        from src.gui.widgets.discharge_sparkline import ANIMALS as _ANIMALS
        animal_menu = configure_menu.addMenu("Select animal")
        animal_menu.setToolTip("Animal shown now and then on the live discharge plot")
        self._animal_group = QActionGroup(self)
        self._animal_group.setExclusive(True)
        _sel_animal = self._settings.value("display/animal", "Fish")
        for _name, _emoji in _ANIMALS:
            act = animal_menu.addAction(f"{_emoji}  {_name}")
            act.setCheckable(True)
            act.setData(_name)
            act.setChecked(_name == _sel_animal)
            self._animal_group.addAction(act)
            act.triggered.connect(lambda *_a, n=_name: self._set_animal(n))
        self._animal_menu = animal_menu

        self._add_menu_section(configure_menu, "Editor && Dates")
        # Skill of User (Beginner / Advanced / Expert): how much of the settings
        # file is shown - in sync with the coloured level button next to the editor.
        from src.gui.components.main_window import _EXPERIENCE_LEVELS
        skill_menu = configure_menu.addMenu("Skill of User")
        skill_menu.setToolTipsVisible(True)
        skill_menu.setToolTip(
            "The skill of the user determines how much of the settingsfile is presented")
        self._skill_group = QActionGroup(self)
        self._skill_group.setExclusive(True)
        self._level_menu_actions = {}
        for _lvl in _EXPERIENCE_LEVELS:
            act = skill_menu.addAction(_lvl)
            act.setCheckable(True)
            act.setChecked(_lvl == getattr(self, "_experience_level", "Expert"))
            act.setToolTip(
                "The skill of the user determines how much of the settingsfile is presented")
            self._skill_group.addAction(act)
            act.triggered.connect(lambda *_a, l=_lvl: self.set_experience_level(l))
            self._level_menu_actions[_lvl] = act
        self._skill_menu = skill_menu

        # Web-style date picker (option 3): 📅 button + frameless shadowed popup
        # for Start/Spin/End; unticked = the classic QDateEdit drop-down calendar.
        web_picker_action = configure_menu.addAction("Web-style date picker")
        web_picker_action.setCheckable(True)
        web_picker_action.setToolTip(
            "Pick the Start/Spin/End dates with a modern frameless calendar popup "
            "(📅 button); untick to go back to the classic drop-down calendar")
        web_picker_action.setChecked(
            self._settings.value("display/date_picker_web", True, type=bool))
        web_picker_action.toggled.connect(self._on_web_picker_toggled)
        self.web_picker_action = web_picker_action
        self._wire_checkbox_glyph(web_picker_action, "Web-style date picker")

        # Date timeline (option 4): three-handle Start/Spin/End timeline below
        # the date fields (drag to set; shows the forcing coverage band).
        timeline_action = configure_menu.addAction("Date timeline")
        timeline_action.setCheckable(True)
        timeline_action.setToolTip(
            "Show a draggable Start/Spin/End timeline below the date fields "
            "(the band behind it is the meteo-forcing coverage)")
        timeline_action.setChecked(
            self._settings.value("display/date_timeline", True, type=bool))
        timeline_action.toggled.connect(self._on_date_timeline_toggled)
        self.date_timeline_action = timeline_action
        self._wire_checkbox_glyph(timeline_action, "Date timeline")

        # Checkable "Bookmark Change" (persisted): auto-bookmark a line when it is
        # changed (skipping a line if a bookmark is already 1-2 lines above/below).
        _bm_change = self._settings.value("editor/bookmark_change", False, type=bool)
        self.bookmark_change_action = configure_menu.addAction("Bookmark Change")
        self.bookmark_change_action.setCheckable(True)
        self.bookmark_change_action.setChecked(_bm_change)
        self.bookmark_change_action.setToolTip(
            "Automatically set a bookmark on a line when it is changed (skips a line "
            "if a bookmark is already 1 or 2 lines above/below)")
        self._on_bookmark_change_toggled(_bm_change)  # apply to editor
        self.bookmark_change_action.toggled.connect(self._on_bookmark_change_toggled)
        self._wire_checkbox_glyph(self.bookmark_change_action, "Bookmark Change")

        # Keep the Configure menu open after a tick box is toggled, so the ☐→☑ change
        # is visible instead of the menu closing immediately.
        self._configure_keep_open = _KeepMenuOpenFilter(self)
        configure_menu.installEventFilter(self._configure_keep_open)

        self._add_menu_section(configure_menu, "Run History")
        # Run-history (Run Ledger) storage: general folder + retention.
        history_folder_action = configure_menu.addAction("Run history folder…")
        history_folder_action.setToolTip(
            "Folder where the Run Ledger (log of past runs) is stored")
        history_folder_action.triggered.connect(self.set_history_folder)
        history_retention_action = configure_menu.addAction("Run history retention…")
        history_retention_action.setToolTip(
            "How many days of runs to keep in the Run Ledger (0 = keep forever)")
        history_retention_action.triggered.connect(self.set_history_retention)

        # "CWatM AI" - a clickable menu-bar button (a top-level QAction fires on
        # click instead of opening a dropdown), placed left of Help. Opens the
        # Gemini NotebookLM chat window. Kept referenced so PySide cannot GC it.
        self._cwatm_ai_action = menu_bar.addAction("CWatM AI")
        self._cwatm_ai_action.setToolTip(
            "Ask questions about CWatM, answered by Google NotebookLM (Gemini)")
        self._cwatm_ai_action.triggered.connect(lambda: self.open_cwatm_ai())

        # Help menu — displays the documentation (Markdown)
        help_menu = menu_bar.addMenu("Help")
        help_action = help_menu.addAction("CWatM GUI Documentation")
        help_action.triggered.connect(lambda: self.show_documentation())
        features_action = help_menu.addAction("CWatM GUI Features")
        features_action.triggered.connect(lambda: self.show_features())
        faq_action = help_menu.addAction("FAQ")
        faq_action.setToolTip("Common questions & troubleshooting")
        faq_action.triggered.connect(lambda: self.show_faq())
        homepage_action = help_menu.addAction("CWatM Homepage")
        homepage_action.setToolTip("Open the CWatM homepage in your web browser")
        homepage_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://cwatm.iiasa.ac.at")))

        # Create Info menu and place it on the right side
        info_menu = menu_bar.addMenu("Info")

        # Add action for showing info dialog
        info_action = info_menu.addAction("About CWatM")
        info_action.triggered.connect(self.show_info_dialog)

        # Style the menu bar (theme-aware; re-applied on a mode switch)
        menu_bar.setStyleSheet(self._menu_bar_stylesheet())

        # Insert just below the banner (index 0 = header) regardless of when this
        # is called relative to the content layout.
        parent_layout.insertWidget(1, menu_bar)
        self.menu_bar = menu_bar  # kept so tools can be disabled while CWatM runs
        # Keep Python references to every submenu so PySide cannot garbage-collect a
        # QMenu (and its child QActions) out from under us - the cause of intermittent
        # "Internal C++ object (QAction) already deleted" errors.
        self._menus = [file_menu, settings_menu, excel_menu,
                       tools_menu, run_menu, configure_menu, basemap_menu,
                       self._mode_menu, analyse_menu, help_menu, info_menu]

    def _set_theme_mode(self, key):
        """Configure ▸ Mode: switch the whole GUI to the chosen colour theme,
        persist it and re-style every themed widget live."""
        from PySide6.QtWidgets import QApplication
        from src.gui.utils import theme
        theme.set_theme(key)
        theme.apply_app_theme(QApplication.instance())
        self._retheme()

    def _menu_bar_stylesheet(self):
        """The menu-bar QSS built from the active theme's colours."""
        from src.gui.utils import theme
        return f"""
            QMenuBar {{
                background-color: {theme.c('menubar_bg')};
                color: {theme.c('text')};
                border-bottom: 1px solid {theme.c('menubar_border')};
                padding: 4px;
            }}
            QMenuBar::item {{
                background-color: transparent;
                padding: 4px 8px;
                border-radius: 3px;
            }}
            QMenuBar::item:selected {{
                background-color: {theme.c('menu_sel_bg')};
                color: {theme.c('menu_sel_text')};
            }}
            QMenuBar::item:disabled {{
                color: {theme.c('menubar_sep')};   /* visible divider "|" (not faint grey) */
                padding: 4px 6px;
            }}
        """

    def _add_menubar_separator(self, menu_bar):
        """Add a non-interactive visual divider (a bold vertical bar) between menu-bar
        groups."""
        sep = menu_bar.addAction("│")  # vertical bar
        sep.setEnabled(False)
        _f = sep.font()
        _f.setBold(True)
        sep.setFont(_f)

    def _add_menu_section(self, menu, title, first=False):
        """Add a titled section header inside a QMenu — a bold, disabled (non-clickable)
        label, with a separator above it (except the first). Used instead of
        ``QMenu.addSection()``, whose title text is NOT drawn by every Qt style (the
        native windows11 style renders it as a bare, unlabelled separator). Pass ``&&``
        in ``title`` to show a literal ``&`` (single ``&`` is a mnemonic)."""
        if not first:
            menu.addSeparator()
        header = menu.addAction(title)
        header.setEnabled(False)
        _f = header.font()
        _f.setBold(True)
        header.setFont(_f)
        return header

    def _wire_checkbox_glyph(self, action, label):
        """Prefix a checkable menu item with a ☐ (off) / ☑ (on) box so it is clearly a
        **tick box**, distinct from the dialog '…' items and the '▸' submenus. Sets the
        initial glyph and keeps it in sync on every toggle (in addition to the native
        checkmark). `label` is the plain menu text without the box."""
        def _glyph(checked=None):
            c = action.isChecked() if checked is None else checked
            try:
                action.setText(("☑  " if c else "☐  ") + label)
            except RuntimeError:
                pass   # QAction C++ object gone
        _glyph()
        action.toggled.connect(_glyph)

    def _add_recent_file(self, path):
        """Record a settings file at the top of the recent-files (History) list."""
        if not path:
            return
        path = os.path.abspath(path)
        self._recent_files = [p for p in self._recent_files if os.path.abspath(p) != path]
        self._recent_files.insert(0, path)
        self._recent_files = self._recent_files[:6]
        self._settings.setValue("recent_files", self._recent_files)

    def _populate_history_menu(self):
        """(Re)build the recent-files entries shown directly in the File menu.

        The recent files are inserted before the exit separator so they appear
        as `Change Working Dir | 1. file.ini | 2. file2.ini | ... | Exit`.
        """
        try:
            # Drop the entries added by the previous open.
            for act in self._history_actions:
                self._file_menu.removeAction(act)
            self._history_actions = []
            before = self._exit_separator
            if not self._recent_files:
                a = QAction("(no recent files)", self._file_menu)
                a.setEnabled(False)
                self._file_menu.insertAction(before, a)
                self._history_actions.append(a)
                return
            for i, path in enumerate(self._recent_files, 1):
                act = QAction(f"{i}.  {os.path.basename(path)}", self._file_menu)
                act.setToolTip(path)
                act.triggered.connect(lambda checked=False, p=path: self.load_recent_file(p))
                self._file_menu.insertAction(before, act)
                self._history_actions.append(act)
        except RuntimeError:
            # File menu C++ object transiently gone - nothing to populate
            pass

