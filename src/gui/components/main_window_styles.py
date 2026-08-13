"""Stylesheet builders for the main window's own widgets.

Every colour comes from `theme.c(token)` (the theme-token rule), so a Mode switch only
has to re-run these through `main_window._retheme()`. Split out of `main_window.py`
because they are pure presentation: each method returns a QSS string (or applies one),
and none of them touches model or file state.

Mixed into `CWatMMainWindow`. `_LEVEL_COLORS` lives here because `_level_button_style`
is its only reader (`main_window` keeps `_LEVEL_ALLOWED`/`_EXPERIENCE_LEVELS`, which
drive behaviour rather than appearance).
"""

from src.gui.utils import theme
from src.gui.utils.gui_log import get_logger

log = get_logger("main_window_styles")

# Level button background (RGB; drawn at 50% transparency).
_LEVEL_COLORS = {
    "Beginner": "144, 238, 144",   # light green
    "Advanced": "173, 216, 230",   # light blue
    "Expert":   "180, 180, 180",   # gray
}


class MainWindowStyleMixin:
    """The main window's stylesheet builders (see the module docstring)."""

    def _left_panel_style(self):
        return f"""
            QWidget {{
                background-color: {theme.c('panel_bg')};
                border-radius: 12px;
                margin: 6px 8px 8px 8px;
                margin-top: 1px;
                padding: 5px 8px 8px 8px;
            }}
        """

    def _right_panel_style(self):
        # Scoped to the object name - a bare "QWidget {…}" would cascade into the
        # editor's scroll bars (see create_right_panel).
        return f"""
            QWidget#rightPanel {{
                background-color: {theme.c('panel_bg')};
                border-radius: 12px;
                margin: 8px;
                padding: 15px;
            }}
        """

    def _field_style(self):
        return (f"QLineEdit {{ background-color: {theme.c('field_bg')}; "
                f"color: {theme.c('field_text')}; }}")

    def _output_box_style(self):
        return f"""
            QPlainTextEdit {{
                background-color: {theme.c('out_bg')};
                border: 1px solid {theme.c('out_border')};
                padding: 0px;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: {self._cwatm_font_size}px;
                color: {theme.c('out_text')};
            }}
            QScrollBar:vertical {{
                background-color: {theme.c('surface_bg')};
                width: 16px;
                border-radius: 6px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {theme.c('accent')};
                border-radius: 6px;
                min-height: 28px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {theme.c('menu_sel_bg')};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar:horizontal {{
                background-color: {theme.c('surface_bg')};
                height: 16px;
                border-radius: 6px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {theme.c('accent')};
                border-radius: 6px;
                min-width: 28px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {theme.c('menu_sel_bg')};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
        """

    def _editor_font_css(self):
        """The QSS font-family list for the settings editor: the family chosen in
        Preferences ▸ Display ▸ Font first, then the built-in monospace fallback
        chain (which is all there is while nothing has been chosen, so an untouched
        installation renders exactly as before)."""
        chain = "'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Consolas', monospace"
        fam = getattr(self, "_editor_font_family", "")
        return f"'{fam}', {chain}" if fam else chain

    def _editor_style(self):
        return f"""
            QPlainTextEdit {{
                background-color: {theme.c('editor_bg')};
                border: 2px solid {theme.c('editor_border')};
                border-radius: 12px;
                padding: 16px;
                font-family: {self._editor_font_css()};
                font-size: {self._editor_font_size}px;
                line-height: 1.5;
                color: {theme.c('editor_text')};
                selection-background-color: {theme.c('sel_bg')};
                selection-color: {theme.c('sel_text')};
            }}
            QPlainTextEdit:focus {{
                border-color: {theme.c('editor_focus_border')};
            }}
            QScrollBar:vertical {{
                background-color: {theme.c('surface_bg')};
                width: 16px;
                border-radius: 6px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {theme.c('accent')};
                border-radius: 6px;
                min-height: 28px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {theme.c('menu_sel_bg')};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """

    def _level_button_style(self):
        """Stylesheet for the level button: the level's colour at 50% opacity."""
        rgb = _LEVEL_COLORS.get(self._experience_level, "200, 200, 200")
        return f"""
            QPushButton {{
                background-color: rgba({rgb}, 0.5);
                border: 1px solid {theme.c('btn_border')};
                border-radius: 5px;
                color: {theme.c('btn_text')};
                font-weight: 600;
                font-size: 11px;
                padding: 2px 8px;
                min-height: 16px;
            }}
            QPushButton:hover {{ background-color: rgba({rgb}, 0.7);
                                 border-color: {theme.c('btn_hover_border')}; }}
            QPushButton:pressed {{ background-color: rgba({rgb}, 0.85);
                                   border-color: {theme.c('btn_press_border')}; }}
        """

    def _apply_level_button_style(self):
        btn = getattr(self, "level_button", None)
        if btn is not None:
            try:
                btn.setStyleSheet(self._level_button_style())
            except RuntimeError:
                log.debug("_apply_level_button_style: ignored", exc_info=True)

    def _run_button_idle_style(self):
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_top')}, stop:1 {theme.c('btn_bottom')});
                border: 2px solid {theme.c('btn_border')};
                border-radius: 8px;
                color: {theme.c('btn_text')};
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_hover_top')}, stop:1 {theme.c('btn_hover_bottom')});
                border-color: {theme.c('btn_hover_border')};
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_press_top')}, stop:1 {theme.c('btn_press_bottom')});
                border-color: {theme.c('btn_press_border')};
            }}
        """

    def _build_modern_button_style(self):
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_top')}, stop:1 {theme.c('btn_bottom')});
                border: 1px solid {theme.c('btn_border')};
                border-radius: 5px;
                color: {theme.c('btn_text')};
                font-weight: 600;
                font-size: 11px;
                padding: 2px 8px;
                min-height: 16px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_hover_top')}, stop:1 {theme.c('btn_hover_bottom')});
                border-color: {theme.c('btn_hover_border')};
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_press_top')}, stop:1 {theme.c('btn_press_bottom')});
                border-color: {theme.c('btn_press_border')};
            }}
            QPushButton:disabled {{
                background: {theme.c('surface_bg')};
                border: 1px solid {theme.c('border')};
                color: {theme.c('text_gray')};
            }}
        """

    def _build_save_dirty_style(self):
        return f"""
            QPushButton {{
                background-color: {theme.c('dirty_bg')};
                border: 1px solid {theme.c('dirty_border')};
                border-radius: 5px;
                color: {theme.c('btn_text')};
                font-weight: 600;
                font-size: 11px;
                padding: 2px 8px;
                min-height: 16px;
            }}
            QPushButton:hover {{ background-color: {theme.c('dirty_hover')};
                                 border-color: {theme.c('dirty_border')}; }}
            QPushButton:pressed {{ background-color: {theme.c('dirty_press')};
                                   border-color: {theme.c('dirty_border')}; }}
            QPushButton:disabled {{ background-color: {theme.c('surface_bg')};
                                    border: 1px solid {theme.c('border')};
                                    color: {theme.c('text_gray')}; }}
        """

    def _apply_filename_state(self):
        """Re-apply the filename/Title label colours for the remembered state
        (none / loaded / saveas / error) using the active theme."""
        st = getattr(self, "_filename_state", "none")
        colors = {"loaded": theme.c("ok_color"), "saveas": theme.c("link_color"),
                  "error": theme.c("warn_color")}
        # margin/padding 0 overrides the left panel's bare "QWidget {margin/padding}"
        # cascade, keeping "Working directory:" tight under the "Loaded:" line.
        _tight = " margin: 0px; padding: 0px;"
        if st == "none":
            self.filename_label.setStyleSheet(
                f"color: {theme.c('text_gray')}; font-style: italic;" + _tight)
            if getattr(self, "title_label", None) is not None:
                self.title_label.setStyleSheet(_tight)
        else:
            style = f"color: {colors[st]}; font-weight: bold;" + _tight
            self.filename_label.setStyleSheet(style)
            if st != "error" and getattr(self, "title_label", None) is not None:
                self.title_label.setStyleSheet(style)
        # The Working-directory line stays neutral in every state, 2 px under
        # the Loaded line
        if getattr(self, "workdir_label", None) is not None:
            self.workdir_label.setStyleSheet(
                f"color: {theme.c('text_gray')}; "
                "margin: 2px 0px 0px 0px; padding: 0px;")

    def _apply_gauges_field_color(self):
        """Colour the Gauges box text by the remembered gauge-in-mask result
        (True = all inside, False = outside, None = unknown)."""
        gres = getattr(self, "_gauges_state", None)
        color = {True: theme.c("link_color"), False: theme.c("warn_color")}.get(
            gres, theme.c("field_text"))
        self.gauges_field.setStyleSheet(
            f"QLineEdit {{ background-color: {theme.c('field_bg')}; color: {color}; }}")
