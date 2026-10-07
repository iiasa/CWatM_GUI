"""CWatM Academy - a guided, ten-level introduction to the GUI (see
``src/gui/utils/academy_content.py`` for the curriculum and
``src/gui/utils/academy_progress.py`` for the persisted progress).

Always styled in the Mikhail amber-on-black palette (``theme.theme_colors
('mikhail')``), regardless of the app's own active Mode - CWatM Academy has its
own fixed look rather than following Normal/Dark/Mikhail, the same way the
saturated RUN/Compare buttons elsewhere are deliberately theme-independent.

Three pages in a QStackedWidget: a welcome page (the ``academy_welcome.png``
artwork + New/Continue) shown every time the window opens, Level 1's
interactive outlet-picker map (``academy_outlet_map.py``), and the level
browser for everything else. Non-modal, ``GeometryMemoryMixin`` + ``QDialog``
like the other secondary windows (NetCDF / Watercycle / CWatM AI); opened via
the module-level ``open_academy()`` singleton-reuse function from the "CWatM
Academy" menu-bar button, and optionally auto-opened at startup when
Preferences ▸ CWatM Academy ▸ Enable CWatM Academy is on (see
``main_window.open_academy`` / ``cwatm_gui._maybe_open_academy``).

Progress is a local QSettings value per machine - or, while Preferences ▸ CWatM
Academy ▸ Link CWatM Academy to your login is on and the user is logged in, the
list stored in the CWatM account's profile, where every finished level also
earns points (see academy_progress). Either way the welcome page offers
"Continue" / "Start Over"; ``refresh_progress`` re-reads it when the login
changes.

Level 2 is a second interactive walkthrough, not a text lesson, and - like
Level 1 - ends with a graded Field Test, not just teaching content (see the
academy_guide module docstring for the teaching-guide -> mission briefing ->
Field Test -> celebration shape both levels follow). Its "Start walkthrough"
button (see _show_level/_on_complete_clicked) hides this window and hands
off to a **teaching** TorusGuideBubble (_start_level2_tour) that runs the
run-period fields in two passes - first the real PathOut/StepStart/SpinUp/
StepEnd lines *in the settings file* (academy_guide.settings_line_point -
the same settings-editor-line target Level 1's outlet map uses for
MaskMap/Gauges), purely to explain what each means, then the *left panel*
where those same values are mirrored and actually edited (the PathOut box,
gated on a real folder existing there, and the date fields/timeline). See
_start_level2_tour for why editing only works from the left-panel pass
(main_window._live_content() rebuilds PathOut/MaskMap/Gauges from those
boxes, so a direct edit to the settings-file line alone would never satisfy
the PathOut gate).

Finishing that teaching tour shows the mission briefing
(academy_guide.show_mission_briefing), then a **second**, separate
TorusGuideBubble tour for the Field Test itself (_start_level2_field_test):
configure the mission's exact run (February 2005, one-month spin-up -
_level2_dates_match_mission, gated), launch it with RUN CWATM (gated on
those same dates *and* the run finishing - _level2_mission_run_complete),
then open the Analyse menu to confirm the result in Watercycle (gated on
_watercycle_opened). Both tours use the same per-step *gating* mechanism
(TorusGuideBubble's optional third tuple element) so a step can't be
clicked past until its real-world condition is actually true. Finishing
either level's Field Test celebrates with a centred TorusPrompt
(academy_guide.show_level_celebration) before returning to the level
browser.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QTextBrowser, QFrame, QStackedWidget, QMessageBox,
)
from PySide6.QtCore import Qt, QDate, QPoint, QSize, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap

from src.gui.utils import theme
from src.gui.utils.assets import asset_path
from src.gui.utils.academy_content import LEVELS, LEVEL_COUNT, level_by_id
from src.gui.utils import academy_progress as progress
from src.gui.widgets.academy_outlet_map import OutletMapWidget
from src.gui.utils.window_geometry import GeometryMemoryMixin, scaled_default_size
from src.gui.utils.gui_log import get_logger

log = get_logger("academy_window")

# Fixed Mikhail palette - not theme.c(), which follows the app's live Mode.
_C = theme.theme_colors("mikhail")

# From this level on the Academy needs a CWatM account login (_needs_login).
LOGIN_LEVEL = 4

_PAGE_WELCOME = 0
_PAGE_BROWSER = 1
_PAGE_MAP = 2

# Level 2's Field Test mission: run February 2015 with a one-month spin-up
# (StepStart -> SpinUp is the spin-up month, SpinUp -> StepEnd is the
# scored period - see CLAUDE.md's Check-settingsfile date-ordering note,
# StepStart <= SpinUp <= StepEnd) - see _level2_dates_match_mission. Stored
# as the exact settings-file strings (DD/MM/YYYY), not QDate, because the
# gate reads the editor text directly (academy_guide.read_settings_value),
# not the left-panel date widgets - see that method's docstring for why.
_LEVEL2_MISSION_START_STR = "01/01/2015"
_LEVEL2_MISSION_SPIN_STR = "01/02/2015"
_LEVEL2_MISSION_END_STR = "28/02/2015"


def open_academy(parent=None):
    """Open (or reuse) the CWatM Academy window, always landing on its welcome
    page - the intro/choice screen is meant to show every time the button is
    clicked, not only on first use."""
    win = getattr(parent, "_academy_window", None)
    try:
        if win is not None and win.isVisible():
            win.raise_()
            win.activateWindow()
            win.show_welcome()
            return win
    except RuntimeError:
        win = None  # C++ object gone
    win = AcademyWindow(parent)
    if parent is not None:
        parent._academy_window = win
    win.show()
    win.raise_()
    win.activateWindow()
    return win


class AcademyWindow(GeometryMemoryMixin, QDialog):
    """Welcome page + level browser/lesson pane for CWatM Academy."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mw = parent
        self.setWindowTitle("CWatM Academy")
        try:
            self.setWindowIcon(QIcon())  # inherits the app icon; no extra asset needed
        except Exception:
            log.debug("setWindowIcon: ignored", exc_info=True)

        self._build_ui()
        self._apply_style()
        if not self._init_geometry_memory("academy"):
            self.resize(*scaled_default_size(self, 860, 620))
        self.show_welcome()

    # ------------------------------------------------------------------ layout

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.stack.addWidget(self._build_welcome_page())
        self.stack.addWidget(self._build_browser_page())
        self.outlet_map = OutletMapWidget(main_window=self.mw)
        self.outlet_map.outlet_picked.connect(self._on_outlet_picked)
        self.stack.addWidget(self.outlet_map)

    def _build_welcome_page(self):
        page = QFrame()
        page.setObjectName("acadWelcome")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(14)
        lay.addStretch(1)

        art = QLabel()
        art.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(asset_path("academy_welcome.png"))
        if not pixmap.isNull():
            # Device-pixel-ratio aware, like the Mikhail banner logo fix - a
            # plain logical-pixel-sized QPixmap gets stretched across MORE
            # physical pixels on a scaled (HiDPI) display and reads as
            # out-of-focus no matter how good the source is.
            box = 700
            dpr = self.devicePixelRatioF()
            scaled = pixmap.scaled(
                round(box * dpr), round(box * dpr),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            art.setPixmap(scaled)
        else:
            art.setText("CWatM Academy")
            art.setObjectName("acadHead")
        lay.addWidget(art, 0, Qt.AlignHCenter)

        self.welcome_status = QLabel()
        self.welcome_status.setObjectName("acadWelcomeStatus")
        self.welcome_status.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.welcome_status)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.start_over_button = QPushButton("Start Over")
        self.start_over_button.setObjectName("acadSecondary")
        self.start_over_button.clicked.connect(self._on_start_over_clicked)
        btn_row.addWidget(self.start_over_button)
        self.continue_button = QPushButton()
        self.continue_button.setObjectName("acadComplete")
        self.continue_button.clicked.connect(self._on_continue_clicked)
        btn_row.addWidget(self.continue_button)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
        lay.addStretch(1)
        return page

    def _build_browser_page(self):
        page = QFrame()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(14, 14, 14, 12)
        outer.setSpacing(10)

        head = QLabel("CWatM Academy")
        head.setObjectName("acadHead")
        outer.addWidget(head)
        sub = QLabel("A ten-level guided tour of the CWatM GUI.")
        sub.setObjectName("acadSub")
        outer.addWidget(sub)

        body = QHBoxLayout()
        body.setSpacing(12)
        outer.addLayout(body, 1)

        # Left: the level list, one row per level, a check mark once completed.
        self.level_list = QListWidget()
        self.level_list.setObjectName("acadLevels")
        self.level_list.setFixedWidth(230)
        self.level_list.currentRowChanged.connect(self._on_row_changed)
        body.addWidget(self.level_list)

        # Right: the lesson panel for the selected level.
        panel = QFrame()
        panel.setObjectName("acadPanel")
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(16, 14, 16, 14)
        panel_lay.setSpacing(8)

        self.lesson_title = QLabel()
        self.lesson_title.setObjectName("acadLessonTitle")
        panel_lay.addWidget(self.lesson_title)

        self.lesson_badge = QLabel()
        self.lesson_badge.setObjectName("acadBadge")
        panel_lay.addWidget(self.lesson_badge)

        self.lesson_body = QTextBrowser()
        self.lesson_body.setObjectName("acadBody")
        self.lesson_body.setOpenExternalLinks(False)
        panel_lay.addWidget(self.lesson_body, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.complete_button = QPushButton()
        self.complete_button.setObjectName("acadComplete")
        self.complete_button.clicked.connect(self._on_complete_clicked)
        btn_row.addWidget(self.complete_button)
        panel_lay.addLayout(btn_row)

        body.addWidget(panel, 1)

        self._populate_level_list()
        return page

    def _populate_level_list(self):
        self.level_list.blockSignals(True)
        self.level_list.clear()
        done = progress.completed_levels()
        for lvl in LEVELS:
            mark = "✓" if lvl["id"] in done else str(lvl["id"])
            item = QListWidgetItem(f"{mark}   {lvl['title']}")
            item.setData(Qt.UserRole, lvl["id"])
            item.setSizeHint(QSize(0, 34))
            self.level_list.addItem(item)
        self.level_list.blockSignals(False)

    # --------------------------------------------------------------- welcome

    def show_welcome(self):
        """(Re)show the welcome page - just two plain options, no explanatory
        text: 'New here' for a first visit, 'Choose a level' (opens the level
        list, pre-selected on wherever progress left off) for a returning
        learner."""
        done = progress.completed_levels()
        if done:
            self.welcome_status.setText("Choose a level")
            self.continue_button.setText("Continue")
            self.start_over_button.setVisible(True)
        else:
            self.welcome_status.setText("New here")
            self.continue_button.setText("Begin")
            self.start_over_button.setVisible(False)
        self.stack.setCurrentIndex(_PAGE_WELCOME)

    def refresh_progress(self):
        """The progress source changed (login, logout, Preferences ▸ CWatM Academy ▸
        Link to your login, or the server's answer to a finished level): re-read it
        on the page that shows it. Level 1's map page is left alone."""
        page = self.stack.currentIndex()
        if page == _PAGE_WELCOME:
            self.show_welcome()
        elif page == _PAGE_BROWSER:
            level_id = getattr(self, "_current_level_id", None)
            # a refresh (e.g. the login just arrived) re-shows the level quietly
            self._refreshing = True
            try:
                self._populate_level_list()
                self.go_to_level(level_id or progress.current_level())
            finally:
                self._refreshing = False

    def _on_continue_clicked(self):
        self._enter_academy(reset_first=False)

    def _on_start_over_clicked(self):
        self._enter_academy(reset_first=True)

    def _enter_academy(self, reset_first):
        first_visit_before = progress.is_first_visit()
        if reset_first:
            progress.reset()
        # Entering Academy for the very first time - or explicitly starting
        # over - also switches the settings editor to the simplified Beginner
        # view; a learner wants that too.
        if (first_visit_before or reset_first) and self.mw is not None:
            try:
                self.mw.set_experience_level("Beginner")
            except Exception:
                log.debug("set_experience_level(Beginner): ignored", exc_info=True)
        self._populate_level_list()
        # Level 1 is the interactive outlet-picker map, not a text lesson - only
        # reachable this way (Begin / Continue landing on it), not by clicking
        # back to "1" in the level list once it's done (see _show_level).
        if progress.current_level() == 1 and 1 not in progress.completed_levels():
            if self.mw is not None and not self.mw.file_manager.has_file_loaded():
                self._show_load_settings_prompt()
                return
            self.outlet_map.reset()
            self.stack.setCurrentIndex(_PAGE_MAP)
            return
        self.go_to_level(progress.current_level())
        self.stack.setCurrentIndex(_PAGE_BROWSER)

    def _replay_level1(self):
        """Level 1 again: the outlet-picker map (needs a loaded settings file, like
        the first time). Picking an outlet saves it and returns to the browser."""
        if self.mw is not None and not self.mw.file_manager.has_file_loaded():
            self._show_load_settings_prompt()
            return
        self.outlet_map.reset()
        self.stack.setCurrentIndex(_PAGE_MAP)

    def _show_load_settings_prompt(self):
        """Level 1's actual first step: there is nothing to pick an outlet
        ON until a settings file is loaded. Hide this window (so it doesn't
        sit on top of the main GUI a file needs to be dragged onto) and show
        a big, centred, halo'd Torus prompt over it instead, asking for one -
        loadable by dropping it either on the main window behind the prompt,
        or directly on the prompt itself (it's always-on-top, so a drop aimed
        at the editor can easily land on it instead), or via File > Load .ini.
        Poll until any settings file is loaded, then the same prompt walks
        through 'Settings file loaded' -> 'Loading Earth...' before the map
        appears (see _check_settings_loaded/_show_loading_earth_message/
        _finish_load_prompt) - not an instant cut."""
        try:
            self.hide()
        except Exception:
            log.debug("_show_load_settings_prompt: could not hide Academy window",
                      exc_info=True)
        # Re-entering this gate (e.g. Begin clicked again with still nothing
        # loaded) would otherwise leave a previous poll timer orphaned and
        # still ticking in the background.
        if getattr(self, "_load_poll_timer", None) is not None:
            self._load_poll_timer.stop()
        from src.gui.widgets.academy_guide import TorusPrompt
        self._load_prompt = TorusPrompt(
            "Drag in a settings file from the<br><b>CWatM-Earth-30min</b> "
            "repository to begin")
        # The prompt sits always-on-top and centred, so a drop aimed at the
        # editor underneath can easily land on it instead - wire it to the
        # exact same load path a drop on the editor itself uses
        # (tab_manager.py: editor.fileDropped.connect(self.load_recent_file)).
        self._load_prompt.fileDropped.connect(self.mw.load_recent_file)
        self._load_prompt.start()
        self._load_poll_timer = QTimer(self)
        self._load_poll_timer.setInterval(400)
        self._load_poll_timer.timeout.connect(self._check_settings_loaded)
        self._load_poll_timer.start()

    def _check_settings_loaded(self):
        """A file just became loaded (however it happened) - a short beat
        of its own before the map appears, rather than an instant cut:
        'Settings file loaded', then 'Loading Earth...', then the map."""
        if self.mw is None or not self.mw.file_manager.has_file_loaded():
            return
        self._load_poll_timer.stop()
        self._load_prompt.set_text("Settings file loaded")
        QTimer.singleShot(900, self._show_loading_earth_message)

    def _show_loading_earth_message(self):
        if self._load_prompt is not None:
            self._load_prompt.set_text("Loading Earth...")
        QTimer.singleShot(900, self._finish_load_prompt)

    def _finish_load_prompt(self):
        if self._load_prompt is not None:
            self._load_prompt.close()
        self.show()
        self.raise_()
        self.activateWindow()
        self.outlet_map.reset()
        self.stack.setCurrentIndex(_PAGE_MAP)

    def _on_outlet_picked(self, lon, lat):
        """Level 1's map exercise confirmed a point: save it, mark Level 1
        complete, and move into the text-lesson browser for Level 2 onward."""
        progress.set_outlet(lon, lat)
        progress.mark_complete(1)
        self._populate_level_list()
        self.go_to_level(progress.current_level())
        self.stack.setCurrentIndex(_PAGE_BROWSER)

    # -------------------------------------------------------------- navigation

    def go_to_level(self, level_id):
        """Select ``level_id`` in the list and show its lesson."""
        for row in range(self.level_list.count()):
            if self.level_list.item(row).data(Qt.UserRole) == level_id:
                self.level_list.setCurrentRow(row)
                return
        if self.level_list.count():
            self.level_list.setCurrentRow(0)

    def _on_row_changed(self, row):
        if row < 0:
            return
        level_id = self.level_list.item(row).data(Qt.UserRole)
        self._show_level(level_id)
        # the learner picked (or arrived at) a locked level: say why, offer the login
        if self._needs_login(level_id) and not getattr(self, "_refreshing", False):
            QTimer.singleShot(0, self._explain_login_needed)

    def _needs_login(self, level_id):
        """Level LOGIN_LEVEL and above need a CWatM account login - the same rule
        (and the same check) as the Advanced / Expert skill levels."""
        if level_id < LOGIN_LEVEL or self.mw is None:
            return False
        unlocked = getattr(self.mw, "levels_unlocked", None)
        return unlocked is not None and not unlocked()

    def _academy_question(self, title, text):
        """A Yes/No box in the Academy's own look. It must style itself completely:
        as a child of this window it inherits the window's ``QDialog`` background
        (black), while its text colour would come from the app palette - black in
        Normal mode, i.e. black on black."""
        c = _C
        box = QMessageBox(QMessageBox.Question, title, text,
                          QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.Yes)
        box.setStyleSheet(f"""
            QMessageBox {{ background-color: {c['window_bg']}; }}
            QMessageBox QLabel {{ color: {c['text']}; background: transparent; }}
            QMessageBox QPushButton {{
                background-color: {c['panel_bg']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 5px;
                padding: 5px 18px; min-width: 60px;
            }}
            QMessageBox QPushButton:default {{ border-color: {c['accent']}; }}
            QMessageBox QPushButton:hover {{
                background-color: {c['menu_sel_bg']}; color: {c['menu_sel_text']};
            }}
        """)
        return box.exec() == QMessageBox.Yes

    def _explain_login_needed(self):
        answer = self._academy_question(
            "CWatM Academy",
            f"From Level {LOGIN_LEVEL} on, CWatM Academy needs a login.\n\n"
            "Log in to your CWatM account (or register - it is free) to continue. "
            "Your progress is then kept in your account and every finished level "
            "earns points.\n\nLog in now?")
        if answer:
            try:
                self.mw.open_account()
            except Exception:
                log.debug("open_account from the Academy failed", exc_info=True)

    def _show_level(self, level_id):
        lvl = level_by_id(level_id)
        if lvl is None:
            return
        self._current_level_id = level_id
        self.lesson_title.setText(f"Level {lvl['id']}: {lvl['title']}")
        self.lesson_badge.setText(f"Badge: {lvl['badge']}")
        bullets = "".join(f"<li>{t}</li>" for t in lvl["teaches"])
        self.lesson_body.setHtml(  # html-safe: lesson texts are constants in this module
            f"<p>{lvl['summary']}</p>"
            f"<p><b>You'll use:</b></p><ul>{bullets}</ul>"
            f"<p><i>Try it: {lvl['menu_hint']}</i></p>"
        )
        done = progress.completed_levels()
        already = level_id in done
        # The current (lowest unfinished) level can be marked, and a completed one
        # stays available - to do it again; a level cannot be skipped ahead of.
        unlocked = already or level_id <= progress.current_level()
        self.complete_button.setEnabled(unlocked)
        if self._needs_login(level_id):
            # clickable: it explains the lock and offers the login again
            self.complete_button.setEnabled(True)
            self.complete_button.setText("Log in to continue")
        elif already and level_id in (1, 2):
            # the interactive levels (outlet map, walkthrough) can be replayed
            self.complete_button.setText("Completed ✓ - do it again")
        elif already:
            self.complete_button.setText("Completed ✓ - next level")
        elif level_id == 2:
            # Level 2 is a guided walkthrough over the real GUI, not a
            # "read this, then tick it off" level - see _start_level2_tour.
            self.complete_button.setText("Start walkthrough")
        else:
            self.complete_button.setText("Mark level complete")

    def _on_complete_clicked(self):
        level_id = getattr(self, "_current_level_id", None)
        if level_id is None:
            return
        if self._needs_login(level_id):
            self._explain_login_needed()
            return
        if level_id in progress.completed_levels():
            # a completed level stays available (its points are paid only once)
            if level_id == 1:
                self._replay_level1()
            elif level_id == 2:
                self._start_level2_tour()
            else:
                self.go_to_level(min(level_id + 1, LEVEL_COUNT))
            return
        if level_id == 2:
            self._start_level2_tour()
            return
        if progress.mark_complete(level_id):
            self._populate_level_list()
            next_level = progress.current_level()
            self.go_to_level(next_level)
            if level_id == LEVEL_COUNT:
                self.lesson_badge.setText(
                    f"Badge: {level_by_id(level_id)['badge']} — CWatM Academy complete!")

    # ------------------------------------------------------------ level 2 tour

    def _start_level2_tour(self):
        """Level 2's "Start walkthrough": hide this window (mirroring
        academy_outlet_map._show_written_lines) and hand off to a
        TorusGuideBubble for the **teaching** pass only - the graded Field
        Test is a separate tour started afterward (see
        _on_level2_teaching_finished/_start_level2_field_test), the same
        teaching-guide -> mission briefing -> Field Test -> celebration
        shape Level 1 follows.

        This teaching pass goes through the run in two passes of its own.
        First, purely to explain what each one means, it walks the real
        PathOut/StepStart/SpinUp/StepEnd lines *in the settings file*
        (academy_guide.settings_line_point, the same helper Level 1 uses
        for MaskMap/Gauges). Then it comes back to the *left panel* - where
        those same four values are mirrored - and shows where they're
        actually edited: the PathOut box (gated on a real folder existing
        there, via _pathout_folder_ready) and the date fields/timeline.
        Editing only works from the left panel here, not by typing on the
        settings-file line directly: main_window._live_content(), which the
        PathOut gate reads through, rebuilds the file's PathOut/MaskMap/
        Gauges entries from the **left-panel boxes**, overwriting whatever
        the editor's own PathOut line says - so a direct edit to that line
        wouldn't move the "ready" gate at all, only editing the box does."""
        if self.mw is None:
            # No main window to point at - fall back to the plain
            # mark-complete path so the learner isn't stuck.
            if progress.mark_complete(2):
                self._populate_level_list()
                self.go_to_level(progress.current_level())
            return
        try:
            self.hide()
        except Exception:
            log.debug("_start_level2_tour: could not hide Academy window", exc_info=True)
        try:
            self.mw.raise_()
            self.mw.activateWindow()
        except Exception:
            log.debug("_start_level2_tour: could not raise main window", exc_info=True)
        from src.gui.widgets.academy_guide import TorusGuideBubble, settings_line_point
        self._level2_guide = TorusGuideBubble()
        self._level2_guide.finished.connect(self._on_level2_teaching_finished)
        steps = [
            (settings_line_point(self.mw, "PathOut"),
             "This is <b>PathOut</b> in the settings file - the folder "
             "CWatM writes its results into.",
             (self._pathout_folder_ready, "Folder not found yet …",
              "✓ Folder found", False)),
            (settings_line_point(self.mw, "StepStart"),
             "<b>StepStart</b> - the first day the run simulates."),
            (settings_line_point(self.mw, "SpinUp"),
             "<b>SpinUp</b> - the date the model has finished \"warming "
             "up\" by. Everything before it primes the model's state; the "
             "run is only really scored from here on."),
            (settings_line_point(self.mw, "StepEnd"),
             "<b>StepEnd</b> - the last day the run simulates."),
            (self._widget_point(lambda: getattr(self.mw, "pathout_field", None),
                                 from_right=True),
             "PathOut is mirrored here on the left too - this is where "
             "it's actually edited. Create a folder on disk, then type or "
             "browse to its path in this box.",
             (self._pathout_folder_ready,
              "Folder not found yet …", "✓ Folder found")),
            (self._date_area_point(),
             "The three dates are mirrored here as well - drag the "
             "timeline's handles below the date fields, or edit each date "
             "box directly, to change them."),
        ]
        self._level2_guide.start(steps)

    def _on_level2_teaching_finished(self):
        """The teaching tour's last "Got it!" - show the "will you accept
        this mission" briefing for Level 2's Field Test before the graded
        check itself (_start_level2_field_test), rather than jumping
        straight into it."""
        from src.gui.widgets.academy_guide import show_mission_briefing
        self._level2_mission_prompt = show_mission_briefing(
            2, self._start_level2_field_test)

    def _start_level2_field_test(self):
        """Level 2's Field Test: a second, separate TorusGuideBubble tour -
        configure the exact run the mission specifies (gated on
        _level2_dates_match_mission), launch it (gated on
        _level2_mission_run_complete - the same dates, *and* a finished
        run), then open Watercycle to confirm the result (gated on
        _watercycle_opened, unchanged from the teaching-pass version of
        this step)."""
        if self.mw is None:
            return
        self._level2_seen_running = False
        # Cleared here so a stale reference from an earlier Watercycle visit
        # this session can't satisfy _watercycle_opened() instantly.
        self.mw._last_watercycle_window = None
        from src.gui.widgets.academy_guide import TorusGuideBubble, settings_line_point
        self._level2_field_test_guide = TorusGuideBubble()
        self._level2_field_test_guide.finished.connect(self._on_level2_tour_finished)
        steps = [
            (settings_line_point(self.mw, "StepStart"),
             "<b>Mission:</b> configure this run for <b>February 2015</b> "
             "with a one-month spin-up - edit it right here in the "
             "settings file. Set StepStart to 01/01/2015, SpinUp to "
             "01/02/2015, and StepEnd to 28/02/2015, <b>then save</b> "
             "(Ctrl+S or the Save button) - RUN CWATM only ever uses "
             "what's saved to disk, never an unsaved edit.",
             (self._level2_dates_match_mission,
              "Awaiting mission parameters …",
              "✓ Parameters locked in and saved")),
            (self._widget_point(lambda: getattr(self.mw, "run_cwatm_button", None),
                                 from_right=True),
             "Launch the mission run - click <b>RUN CWATM</b>.",
             (self._level2_mission_run_complete,
              "Standing by …", "✓ Mission run complete")),
            (self._corner_point(),
             "Debrief: open <b>Analyse ▸ Watercycle</b>, then pick "
             "the <b>WaterCycle</b> result csv from your PathOut folder - "
             "the file dialog already starts there - to confirm the "
             "mission's results.",
             (self._watercycle_opened,
              "Waiting for you to open it …", "✓ Watercycle opened")),
        ]
        self._level2_field_test_guide.start(steps)

    def _corner_point(self):
        """A zero-arg TorusGuideBubble target pinned near the screen's
        top-left corner, forced to open to its right (see
        TorusGuideBubble._reposition's ``forced_side``) - used for the
        Analyse/Watercycle step specifically, whose real target (the
        Analyse menu) triggers a *native* file-open dialog right after, and
        Qt centres that dialog on the main window. A bubble positioned at
        the menu itself (the usual _menu_point target) ends up sitting
        directly on top of that centred dialog once it opens - confirmed
        live: the dialog's file list was unusable behind it. Parking the
        bubble in a corner keeps it clear of wherever that dialog lands,
        at the cost of no longer pointing precisely at the menu entry -
        acceptable here since the step's own text already names it by menu
        path."""
        def _target():
            screen = QGuiApplication.primaryScreen()
            geo = screen.availableGeometry() if screen is not None else None
            if geo is None:
                return None
            return QPoint(geo.left() + 20, geo.top() + 80), "right"
        return _target

    def _level2_dates_match_mission(self):
        """Level 2's Field Test date gate: StepStart/SpinUp/StepEnd in the
        *settings file itself* (academy_guide.read_settings_value) exactly
        match the mission (February 2015, one-month spin-up) - AND the file
        has no unsaved changes. Checking the live editor text (not the
        left-panel date widgets - see read_settings_value's docstring) is
        what lets an edit made directly on the settings-file line register
        at all; requiring ``not main_window._is_dirty`` on top of that is
        what makes the gate trustworthy: RUN CWATM only ever runs the file
        as saved on disk (run_controller.run_cwatm reads
        file_manager.get_current_file_path(), never the unsaved editor
        buffer), so dates that merely *look* right in the editor but were
        never saved would otherwise pass this gate while the actual run
        used stale values underneath - the gate would be lying."""
        if self.mw is None:
            return False
        if getattr(self.mw, "_is_dirty", True):
            return False
        try:
            from src.gui.widgets.academy_guide import read_settings_value
            return (read_settings_value(self.mw, "StepStart") == _LEVEL2_MISSION_START_STR
                    and read_settings_value(self.mw, "SpinUp") == _LEVEL2_MISSION_SPIN_STR
                    and read_settings_value(self.mw, "StepEnd") == _LEVEL2_MISSION_END_STR)
        except Exception:
            log.debug("_level2_dates_match_mission: ignored", exc_info=True)
            return False

    def _level2_mission_run_complete(self):
        """Level 2's RUN CWATM Field-Test gate: the mission's exact dates
        AND a run that finished while they were set - not just any run.
        Short-circuits on the date check, so a run started with the wrong
        dates is never even considered (_level2_run_finished's own
        ``_level2_seen_running`` latch is only armed while the dates
        already match)."""
        return self._level2_dates_match_mission() and self._level2_run_finished()

    def _watercycle_opened(self):
        """Level 2's Field-Test debrief gate: the level isn't done until
        the learner has actually looked at their own run's water balance,
        not just been told where to find it. True once Analyse ▸
        Watercycle (analysis_watercycle.open_watercycle) has successfully
        opened a WaterCycle window - it stores that window on
        ``main_window._last_watercycle_window`` right before showing it
        (only reached once a real file was picked; a cancelled file dialog
        never gets there), which _start_level2_field_test clears before
        this step can be reached, so a window left over from an earlier
        Watercycle visit this session can't satisfy the gate on its own."""
        if self.mw is None:
            return False
        return getattr(self.mw, "_last_watercycle_window", None) is not None

    def _date_area_point(self):
        """A zero-arg TorusGuideBubble target: the left panel's date
        timeline if it's on screen (Preferences ▸ Editor & Dates ▸ Date
        timeline, on by default - the "slider" the run-period dates are
        also edited from), else the StepStart date field itself."""
        def _getter():
            dm = getattr(self.mw, "date_manager", None) if self.mw is not None else None
            if dm is None:
                return None
            timeline = getattr(dm, "timeline", None)
            if timeline is not None and timeline.isVisible():
                return timeline
            return getattr(dm, "start_date_edit", None)
        return self._widget_point(_getter, from_right=True)

    def _widget_point(self, getter, from_right=False):
        """A zero-arg TorusGuideBubble target: the global, vertically
        centred point of whatever widget ``getter()`` currently returns -
        re-evaluated lazily each time the step is shown, same reasoning as
        academy_guide.settings_line_point.

        ``from_right`` anchors on the widget's right edge instead of its
        left, AND tells TorusGuideBubble._reposition to always open on that
        right side (returning ``(point, "right")``, not a bare point) -
        every left-panel widget this points at (RUN CWATM, the PathOut box,
        the date timeline) sits near the main window's own left edge, so
        the bubble should always open into the space beyond it, never back
        over the widget itself.

        That forced side matters for more than just a narrow button like
        RUN CWATM: TorusGuideBubble's own "is there room" heuristic only
        looks at the target x-coordinate against the screen's left edge, so
        for a *wide* widget (the PathOut box, the date timeline - each
        spanning most of the left panel) anchored on its own right edge,
        that heuristic reads "plenty of room to the left" and opens the
        bubble there - directly on top of the widget, since the widget
        itself occupies exactly that space between its left and right
        edges. Forcing "right" here means the bubble always opens past the
        widget's right edge instead, regardless of what the raw
        x-coordinate would otherwise suggest."""
        def _target():
            try:
                w = getter()
            except Exception:
                return None
            if w is None or not w.isVisible():
                return None
            try:
                if from_right:
                    return w.mapToGlobal(QPoint(w.width(), w.height() // 2)), "right"
                return w.mapToGlobal(QPoint(0, w.height() // 2))
            except Exception:
                return None
        return _target

    def _menu_point(self, menu_text):
        """A zero-arg TorusGuideBubble target: the global centre of the
        top-level menu-bar entry titled ``menu_text`` (e.g. "Analyse") - the
        action inside it (Watercycle) has no stable screen position while
        its submenu is closed, so this points at the menu itself.

        ``self.mw.menu_bar`` - not the QWidget-builtin, always-empty
        ``self.mw.menuBar()`` - since menu_builder.create_menu_bar builds a
        plain QMenuBar *widget* added to the window's own layout (so it can
        sit below the banner) rather than installing it as the native
        QMainWindow menu bar; menu_builder keeps a reference on
        ``self.menu_bar`` for exactly this kind of later lookup."""
        def _target():
            if self.mw is None:
                return None
            try:
                bar = getattr(self.mw, "menu_bar", None)
                if bar is None:
                    return None
                for action in bar.actions():
                    if action.text().replace("&", "") == menu_text:
                        rect = bar.actionGeometry(action)
                        if rect.isNull():
                            return None
                        return bar.mapToGlobal(rect.center())
            except Exception:
                log.debug("_menu_point failed", exc_info=True)
            return None
        return _target

    def _pathout_folder_ready(self):
        """Level 2's PathOut-step gate: the field's value, placeholders
        resolved, points at a directory that actually exists on disk (see
        main_window._resolved_pathout_dir)."""
        if self.mw is None:
            return False
        try:
            return bool(self.mw._resolved_pathout_dir())
        except Exception:
            log.debug("_pathout_folder_ready: ignored", exc_info=True)
            return False

    def _level2_run_finished(self):
        """Level 2's RUN CWATM-step gate: true once a run that was actually
        started while this step was showing has finished (success, error or
        Stop all converge on run_controller's "ready" state - see
        run_controller.set_cwatm_button_ready_state). Guarded by
        ``_level2_seen_running`` so a run already finished from *before* the
        walkthrough started doesn't satisfy the gate instantly."""
        if self.mw is None:
            return False
        state = getattr(self.mw, "_run_btn_state", "idle")
        if state == "running":
            self._level2_seen_running = True
            return False
        return bool(state == "ready" and getattr(self, "_level2_seen_running", False))

    def _on_level2_tour_finished(self):
        """The Torus guide's last "Got it!" - celebrate with a big centred
        TorusPrompt (academy_guide.show_level_celebration, the same look
        every level's completion uses) before bringing the Academy window
        back and marking Level 2 complete."""
        from src.gui.widgets.academy_guide import show_level_celebration
        self._level2_celebration = show_level_celebration(2, self._finish_level2_tour)

    def _finish_level2_tour(self):
        try:
            self.show()
            self.raise_()
            self.activateWindow()
        except Exception:
            log.debug("_finish_level2_tour: could not restore Academy window",
                      exc_info=True)
        if progress.mark_complete(2):
            self._populate_level_list()
            self.go_to_level(progress.current_level())
        self.stack.setCurrentIndex(_PAGE_BROWSER)

    # ----------------------------------------------------------------- theme

    def _apply_style(self):
        """Fixed Mikhail-amber styling - see the module docstring for why this
        does not follow theme.c()/the app's active Mode."""
        c = _C
        self.setStyleSheet(f"""
            QDialog, QFrame#acadWelcome {{
                background-color: {c['window_bg']};
            }}
            QLabel#acadWelcomeStatus {{
                color: {c['text']};
                font-size: 13px;
            }}
            QLabel#acadHead {{
                color: {c['accent']};
                font-size: 20px;
                font-weight: 700;
            }}
            QLabel#acadSub {{
                color: {c['text_muted']};
            }}
            QListWidget#acadLevels {{
                background-color: {c['panel_bg']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                padding: 4px;
                color: {c['text']};
                outline: none;
            }}
            QListWidget#acadLevels::item {{
                padding-left: 8px;
                border-radius: 4px;
            }}
            QListWidget#acadLevels::item:selected {{
                background-color: {c['menu_sel_bg']};
                color: {c['menu_sel_text']};
            }}
            QFrame#acadPanel {{
                background-color: {c['panel_bg']};
                border: 1px solid {c['border']};
                border-radius: 12px;
            }}
            QLabel#acadLessonTitle {{
                color: {c['accent']};
                font-size: 16px;
                font-weight: 700;
            }}
            QLabel#acadTag {{
                color: {c['accent']};
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#acadBadge {{
                color: {c['text_muted']};
                font-style: italic;
            }}
            QLabel#acadExplain {{
                color: {c['text']};
                font-size: 17px;
                line-height: 135%;
            }}
            QTextBrowser#acadBody {{
                background-color: {c['editor_bg']};
                color: {c['editor_text']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 6px;
            }}
            QPushButton#acadComplete {{
                background-color: {c['btn_top']};
                color: {c['btn_text']};
                border: 1px solid {c['btn_border']};
                border-radius: 4px;
                padding: 6px 14px;
            }}
            QPushButton#acadComplete:hover {{
                background-color: {c['btn_hover_top']};
            }}
            QPushButton#acadComplete:disabled {{
                color: {c['text_gray']};
                border-color: {c['border']};
            }}
            QPushButton#acadSecondary {{
                background-color: {c['panel_bg']};
                color: {c['text_muted']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 6px 14px;
            }}
            QPushButton#acadSecondary:hover {{
                background-color: {c['btn_hover_top']};
                color: {c['text']};
            }}
        """)
