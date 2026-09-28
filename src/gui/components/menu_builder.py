"""
Menu bar construction for the CWatM GUI main window.

Extracted verbatim from main_window.py: builds the full menu bar (File /
Settings / Tools / RUN CWATM / Configure / Analyse / Help / Info), the menu-bar
group separators, the ⋮ Preferences button in the right corner and the
recent-files handling (listed directly in the File menu). Mixed into
CWatMMainWindow - all state lives on the main window instance.
"""

import os

from PySide6.QtWidgets import QMenuBar, QToolButton, QWidget, QHBoxLayout
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtCore import Qt, QUrl

from src.gui.utils.gui_log import get_logger

log = get_logger("menu_builder")


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
        # Last item: colour the lines that differ from the neighbouring TAB, in
        # place (a toggle - F8 again removes the colouring, and the item relabels
        # itself "Uncompare Tab" while the marks are shown).
        compare_tab_action = settings_menu.addAction("Compare Tab")
        compare_tab_action.setShortcut("F8")
        compare_tab_action.setToolTip("Compares a tab with the neighbor one")
        compare_tab_action.triggered.connect(lambda: self.toggle_compare_tab())
        self.compare_tab_action = compare_tab_action
        self._refresh_compare_tab_label()
        settings_menu.aboutToShow.connect(self._refresh_compare_tab_label)

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
        # First under Outputs: the folder the outputs go into has to exist before a
        # run - CWatM does not create it.
        create_pathout_action = tools_menu.addAction("Create PathOut Folder")
        create_pathout_action.setToolTip(
            "Create the output folder (PathOut, placeholders resolved) if it is missing")
        create_pathout_action.triggered.connect(lambda: self.create_pathout_folder())
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
        # The settings Excel workbook (this was the whole "Excel" menu before).
        workbook_action = tools_menu.addAction("Excel Crops/Reservoirs")
        workbook_action.setToolTip(
            "Open the settings Excel file (Excel_settings_file) in an editable, "
            "colour-preserving table - all its sheets (Crops, Reservoirs, "
            "Reservoirs_downstream, ...) on tabs below the table")
        workbook_action.triggered.connect(lambda: self.open_excel_workbook())
        # Greyed out while the settings file has no 'Excel_settings_file' key (kept
        # referenced so _update_excel_menu_enabled can toggle it as the text changes).
        self._excel_actions = [workbook_action]
        self._update_excel_menu_enabled()
        check_action = tools_menu.addAction("Check Data")
        check_action.triggered.connect(lambda: self.open_check_data_window())
        # (No "Results & History" section any more: the Journal of Runs moved to the
        # RUN CWATM menu, and Restore settingsfile belongs with the other setup tools.)
        restore_action = tools_menu.addAction("Restore settingsfile")
        restore_action.setToolTip(
            "Open a CWatM output NetCDF (dis*.nc) and show its stored run metadata")
        restore_action.triggered.connect(lambda: self.restore_settingsfile())

        # RUN CWATM menu (right of Tools). Actualize was removed: field changes are
        # auto-applied to the content, and Save/Run flush any pending change first.
        run_menu = menu_bar.addMenu("RUN CWATM")
        run_action = run_menu.addAction("Run CWATM")
        run_action.setShortcut("Ctrl+R")
        run_action.triggered.connect(lambda: self.run_cwatm())
        # The history of what has been run - next to the actions that produce it
        # (this was Tools > Run Ledger).
        ledger_action = run_menu.addAction("Journal of Runs")
        ledger_action.setToolTip(
            "Show the journal of past runs; reopen their results or reload/compare "
            "their settings")
        ledger_action.triggered.connect(lambda: self.open_run_ledger())
        # Windowed Run: open an independent window that runs CWatM in its own process
        # (does not touch the main run or the main GUI); several can run in parallel.
        hidden_run_action = run_menu.addAction("Windowed Run CWatM")
        hidden_run_action.setToolTip("Run CWatM in a separate window")
        hidden_run_action.triggered.connect(lambda: self.open_hidden_run())
        run_menu.addSeparator()
        batch_action = run_menu.addAction("Batch Run…")
        batch_action.setToolTip(
            "Run many scenarios from the loaded settings file (base .ini + per-row "
            "key overrides), up to N in parallel")
        batch_action.triggered.connect(lambda: self.open_batch_runner())
        run_menu.addSeparator()
        create_batch_action = run_menu.addAction("Create batch")
        create_batch_action.setToolTip(
            "Creates a Windows batch file to run CWatM without the GUI")
        create_batch_action.triggered.connect(lambda: self.create_run_batch_file())

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
        # Own name: the Tools menu has an "Add output Watercycle" action in the same
        # scope, and both are registered for the Beginner level below.
        analyse_watercycle_action = analyse_menu.addAction("Watercycle")
        analyse_watercycle_action.setToolTip(
            "Show the water balance of a WaterCycle_areasum_monthtot.csv as a sunburst")
        analyse_watercycle_action.triggered.connect(self.open_watercycle_analysis)
        flowdiagram_action = analyse_menu.addAction("Flow Diagram")
        flowdiagram_action.setToolTip(
            "Show the water balance of a WaterCycle_areasum_monthtot.csv as a Sankey flow diagram")
        flowdiagram_action.triggered.connect(self.open_flowdiagram_analysis)

        # --- Group divider: between "analyse results" and "Help & Info" ---
        self._add_menubar_separator(menu_bar)

        # Configure menu (left of Help). Every GUI setting now lives in the
        # Preferences window (categorised pages + OK/Cancel/Apply); the menu holds
        # the single item that opens it - as does the ⋮ button in the menu bar's
        # right corner.
        configure_menu = menu_bar.addMenu("Configure")
        configure_menu.setToolTipsVisible(True)  # show action tooltips in the menu
        prefs_action = configure_menu.addAction("Preferences…")
        prefs_action.setShortcut("Ctrl+,")
        prefs_action.setToolTip(
            "All GUI settings - output, startup, display, editor, run history")
        prefs_action.triggered.connect(lambda: self.open_preferences())
        self._preferences_action = prefs_action

        self._init_configure_state()

        # "CWatM Academy" - a clickable menu-bar button (same pattern as CWatM AI
        # below), placed left of it. Opens the ten-level guided tour. Kept
        # referenced so PySide cannot GC it.
        self._academy_action = menu_bar.addAction("CWatM Academy")
        self._academy_action.setToolTip(
            "A guided, ten-level introduction to the CWatM GUI")
        self._academy_action.triggered.connect(lambda: self.open_academy())

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
        privacy_action = help_menu.addAction("CWatM account privacy")
        privacy_action.setToolTip(
            "What the optional CWatM account stores, and how to export or delete it")
        privacy_action.triggered.connect(lambda: self.show_account_privacy())
        homepage_action = help_menu.addAction("CWatM Homepage")
        homepage_action.setToolTip("Open the CWatM homepage in your web browser")
        homepage_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://cwatm.iiasa.ac.at")))

        # Create Info menu and place it on the right side
        info_menu = menu_bar.addMenu("Info")

        # Add action for showing info dialog
        info_action = info_menu.addAction("About CWatM")
        info_action.triggered.connect(self.show_info_dialog)
        # The CWatM account leaderboard - shown only while logged in (account_ui.py
        # toggles it with the login state).
        self._leaderboard_action = info_menu.addAction("Leaderboard")
        self._leaderboard_action.setToolTip(
            "Ranking of the CWatM account users who share their points")
        self._leaderboard_action.triggered.connect(lambda: self.open_leaderboard())
        self._leaderboard_action.setVisible(False)
        info_menu.setToolTipsVisible(True)

        # "⋮" in the menu bar's right corner - a second way into Preferences
        # (the familiar overflow/settings affordance). Kept referenced so PySide
        # cannot garbage-collect it.
        prefs_button = QToolButton()
        prefs_button.setText("⋮")
        prefs_button.setToolTip("Preferences")
        prefs_button.setAutoRaise(True)
        prefs_button.setCursor(Qt.PointingHandCursor)
        prefs_button.clicked.connect(lambda: self.open_preferences())
        self._preferences_button = prefs_button
        # The corner holds one widget: the CWatM account button (account_ui.py -
        # "Log in" / "<user> · <points> pt") left of the ⋮ button.
        corner = QWidget()
        corner_lay = QHBoxLayout(corner)
        corner_lay.setContentsMargins(0, 0, 0, 0)
        corner_lay.setSpacing(2)
        corner_lay.addWidget(self._create_account_button())
        corner_lay.addWidget(prefs_button)
        menu_bar.setCornerWidget(corner, Qt.TopRightCorner)
        self._menu_corner = corner

        # Style the menu bar (theme-aware; re-applied on a mode switch)
        menu_bar.setStyleSheet(self._menu_bar_stylesheet())

        # Insert just below the banner (index 0 = header) regardless of when this
        # is called relative to the content layout.
        parent_layout.insertWidget(1, menu_bar)
        self.menu_bar = menu_bar  # kept so tools can be disabled while CWatM runs
        # Keep Python references to every submenu so PySide cannot garbage-collect a
        # QMenu (and its child QActions) out from under us - the cause of intermittent
        # "Internal C++ object (QAction) already deleted" errors.
        self._menus = [file_menu, settings_menu,
                       tools_menu, run_menu, configure_menu,
                       analyse_menu, help_menu, info_menu]
        # Entries a **Beginner** does not see (Skill of user). The level restricts the
        # settings sections shown in the editor; the same idea applied to the menus -
        # everything a beginner has no use for yet, and could set up wrongly, is out of
        # the way. Advanced and Expert see everything.
        # Analyse ▸ Watercycle is the one exception: CWatM Academy's Level 2 (Running
        # CWatM) sends a Beginner there directly to read their own run's water
        # balance, so it stays visible at every level - Tools ▸ Add output
        # Watercycle (a setup/config action, not part of that lesson) still hides.
        self._beginner_hidden_actions = [
            watercycle_action, options_action, workbook_action, check_action,
            restore_action, ledger_action,                      # Tools
            hidden_run_action, batch_action,                    # RUN CWATM
            flowdiagram_action,                                 # Analyse
        ]
        # Entries only an **Expert** sees. Compare Tab works on the settings-file
        # tabs, and those are Expert-only themselves (Preferences ▸ Use Tabs ×
        # Expert), so the menu item follows them - a Beginner/Advanced has no tab
        # bar for it to act on. Create batch (running CWatM entirely outside the
        # GUI) is an Expert-level power tool the same way.
        self._expert_only_actions = [compare_tab_action,        # Settings
                                      create_batch_action]       # RUN CWATM
        self._apply_menu_level()

    def _init_configure_state(self):
        """Restore the persisted Preferences settings that need an action at
        startup.

        The settings themselves are edited in the Preferences window
        (``preferences_window.py``); this only re-establishes their effect on the
        freshly built GUI. The rest is already restored where it is used - the
        banner, date picker and timeline in ``create_gui``, decimals/transparency
        in ``__init__``, the sparkline animal in ``discharge_sparkline``.

        Two settings keep a standalone ``QAction`` (not in any menu) because other
        code reads ``.isChecked()`` on them: **Write output box** (run_controller)
        and **Run model in separate process** (default ON, deliberately not exposed
        in the UI - add it to a Preferences page to expose it again).
        """
        # Write output box - off at every start (it is not persisted)
        self.write_output_action = QAction("Write output box", self)
        self.write_output_action.setCheckable(True)
        self.write_output_action.setChecked(False)
        # Mirror the state into a plain bool so run_cwatm never has to touch the
        # QAction's C++ object (which can outlive-mismatch its Python wrapper).
        self._write_output_enabled = False
        self.write_output_action.toggled.connect(self._on_write_output_toggled)

        # Run model in separate process: own OS process (real Stop, crash
        # isolation - report §3.1).
        _subproc = self._settings.value("run/subprocess", True, type=bool)
        self.run_subprocess_action = QAction("Run model in separate process", self)
        self.run_subprocess_action.setCheckable(True)
        self.run_subprocess_action.setChecked(_subproc)
        self._on_run_subprocess_toggled(_subproc)  # mirror bool + persist
        self.run_subprocess_action.toggled.connect(self._on_run_subprocess_toggled)

        # Load previous settings at start (read by cwatm_gui.py main())
        self._on_load_previous_toggled(
            self._settings.value("startup/load_previous", False, type=bool))
        # Use Modflow: pre-warm flopy in the background when on (heavy import)
        self._on_use_modflow_toggled(
            self._settings.value("modflow/enabled", False, type=bool))
        # Bookmark Change: auto-bookmark changed lines - apply to the editor
        self._on_bookmark_change_toggled(
            self._settings.value("editor/bookmark_change", False, type=bool))
        # Tooltip reverse: the app-wide QToolTip rule (no-op when off)
        self._apply_tooltip_style()

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
            /* the ⋮ Preferences button in the right corner (a narrow, tall glyph -
               a slightly larger font and symmetric padding keep the hover box square).
               The size is in **pt**, not px: a pixel font-size leaves the widget's
               QFont with pointSize() == -1, and a QToolButton is one of the widgets
               Qt's style asks for a *point* size - that is where the console warning
               "QFont::setPointSize: Point size <= 0 (-1)" comes from. */
            QMenuBar QToolButton {{
                background-color: transparent;
                color: {theme.c('text')};
                border: none;
                border-radius: 3px;
                padding: 0px 9px;
                font-size: 13pt;
                font-weight: bold;
            }}
            QMenuBar QToolButton:hover {{
                background-color: {theme.c('menu_sel_bg')};
                color: {theme.c('menu_sel_text')};
            }}
            /* the CWatM account button left of the ⋮ - menu-item sized text, not the
               large ⋮ glyph (pt, for the same reason as above) */
            QMenuBar QToolButton#accountButton {{
                font-size: 9pt;
                font-weight: normal;
                color: {theme.c('accent')};
                padding: 2px 8px;
            }}
            QMenuBar QToolButton#accountButton:hover {{
                color: {theme.c('menu_sel_text')};
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
        # Remembered so _apply_menu_level can hide a header whose whole section is
        # hidden (Beginner) instead of leaving a title with nothing under it.
        if not hasattr(self, "_section_headers"):
            self._section_headers = []
        self._section_headers.append(header)
        return header

    def _apply_menu_level(self):
        """Show or hide the menu entries that depend on the **Skill of user**.

        A Beginner sees only what a first model run needs; everything registered in
        ``_beginner_hidden_actions`` (scenario runs, the Excel workbook, Check Data,
        the Run Ledger, the water-balance analyses, …) is hidden - the same idea as
        the settings sections the level hides in the editor. Advanced and Expert see
        those. ``_expert_only_actions`` goes the other way: **Expert alone** sees
        them (Settings ▸ Compare Tab, which needs the Expert-only tab bar). Called
        when the menus are built and from ``set_experience_level``."""
        level = getattr(self, "_experience_level", "Expert")
        beginner = level == "Beginner"
        for action in getattr(self, "_beginner_hidden_actions", []):
            try:
                action.setVisible(not beginner)
            except RuntimeError:          # QAction deleted on the C++ side
                log.debug("level: action already gone", exc_info=True)
        for action in getattr(self, "_expert_only_actions", []):
            try:
                # Disabled as well as hidden: an invisible QAction can still fire
                # its shortcut, and F8 must do nothing for a Beginner/Advanced.
                action.setVisible(level == "Expert")
                action.setEnabled(level == "Expert")
            except RuntimeError:
                log.debug("level: expert-only action already gone", exc_info=True)
        # A section title with nothing left under it is noise - hide it too.
        headers = set(getattr(self, "_section_headers", []))
        if not headers:
            return
        for menu in getattr(self, "_menus", []):
            try:
                actions = menu.actions()
            except RuntimeError:
                continue
            header, items = None, []
            for action in actions:
                if action in headers:
                    self._set_header_visible(header, items)
                    header, items = action, []
                elif not action.isSeparator():
                    items.append(action)
            self._set_header_visible(header, items)

    @staticmethod
    def _set_header_visible(header, items):
        if header is None:
            return
        try:
            header.setVisible(any(a.isVisible() for a in items) if items else True)
        except RuntimeError:
            log.debug("_set_header_visible: ignored", exc_info=True)

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
            log.debug("_populate_history_menu: ignored", exc_info=True)

