"""Global colour theme ("Mode") for the whole GUI.

Three modes, selectable via Configure ▸ Mode (persisted in QSettings
``display/theme``):

- **Normal**  - the classic light look; token values ARE the colours that used
  to be hardcoded all over the GUI, so Normal renders pixel-identical to the
  pre-theme version (no app-level stylesheet / palette override at all).
- **Dark Mode** - dark gray panels, light text, blue accent.
- **Mikhail** - black background with amber font (CRT terminal style).

Design: every colour the main window / editor / gutter / clock / output box
needs is a semantic token in ``_THEMES``; widgets build their stylesheets from
``c(token)`` and the main window re-applies them on a switch
(``CWatMMainWindow._retheme``). For Dark/Mikhail an application-wide QPalette +
Fusion style + a small QSS handles everything that is not explicitly styled
(menus, dialogs, message boxes, scroll bars); Normal restores the platform
style and default palette.

Keep this module light (PySide6 only) - it is imported at startup.
"""

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette

_SETTINGS_KEY = "display/theme"

# (menu label, key) in menu order
THEME_CHOICES = [("Normal", "normal"), ("Dark Mode", "dark"), ("Mikhail", "mikhail")]

_THEMES = {
    # ------------------------------------------------------------- Normal
    # Token values = the previously hardcoded colours (do not change them,
    # Normal must look exactly like the GUI always did).
    "normal": dict(
        window_bg="#f0f0f0", panel_bg="#ffffff",
        surface_bg="#f8f9fa", border="#e1e5e9",
        text="#2c3e50", text_muted="#333333", text_gray="gray",
        accent="#0066CC",
        menubar_bg="#f8f9fa", menubar_border="#e1e5e9", menubar_sep="#495057",
        menu_sel_bg="#0066CC", menu_sel_text="white",
        field_bg="#f5f5f5", field_border="#cccccc", field_text="#000000",
        btn_top="#ffffff", btn_bottom="#f1f3f4", btn_border="#e1e5e9",
        btn_text="#2c3e50",
        btn_hover_top="#f8f9fa", btn_hover_bottom="#e9ecef", btn_hover_border="#74b9ff",
        btn_press_top="#e9ecef", btn_press_bottom="#dee2e6", btn_press_border="#0984e3",
        dirty_bg="#add8e6", dirty_border="#87ceeb",
        dirty_hover="#87ceeb", dirty_press="#6bb6ff",
        editor_bg="#ffffff", editor_text="#2c3e50",
        editor_border="#e1e5e9", editor_focus_border="#74b9ff",
        sel_bg="#74b9ff", sel_text="white",
        gutter_bg="#f1f3f4", gutter_num="#95a5a6",
        fold_marker="#2c80d3", bookmark="#e67e22",
        ini_comment="darkgray", ini_true="blue", ini_false="red",
        changed_line="#dcecff", duplicate_line="#ff8f8f", error_line="#ffd9d9",
        filler_line="#e0e0e0", diff_line="#ffe1c2", current_diff_line="#ffb877",
        out_bg="#f5f5f5", out_border="#cccccc", out_text="#333333",
        out_error="darkred",
        ok_color="green", link_color="blue", warn_color="red",
        hint_color="#0066CC",
        clock_accent="#0066CC", clock_text="#2c3e50",
    ),
    # ---------------------------------------------------------------- Dark
    "dark": dict(
        window_bg="#232629", panel_bg="#2b2f33",
        surface_bg="#26292d", border="#3a3f44",
        text="#e8eaed", text_muted="#b8bcc2", text_gray="#9aa0a6",
        accent="#4da3ff",
        menubar_bg="#1e2124", menubar_border="#3a3f44", menubar_sep="#b8bcc2",
        menu_sel_bg="#4da3ff", menu_sel_text="#101214",
        field_bg="#1e2124", field_border="#3a3f44", field_text="#e8eaed",
        btn_top="#3a3f44", btn_bottom="#2f3337", btn_border="#4a5056",
        btn_text="#e8eaed",
        btn_hover_top="#454b51", btn_hover_bottom="#3a3f44", btn_hover_border="#4da3ff",
        btn_press_top="#2f3337", btn_press_bottom="#26292c", btn_press_border="#2f7fd6",
        dirty_bg="#2a5674", dirty_border="#3d7ba6",
        dirty_hover="#336a90", dirty_press="#3d7ba6",
        editor_bg="#1e2124", editor_text="#dcdfe4",
        editor_border="#3a3f44", editor_focus_border="#4da3ff",
        sel_bg="#264f78", sel_text="#e8eaed",
        gutter_bg="#2b2f33", gutter_num="#7a8085",
        fold_marker="#4da3ff", bookmark="#e67e22",
        ini_comment="#8a9199", ini_true="#6cb6ff", ini_false="#ff7b72",
        changed_line="#1f3a5f", duplicate_line="#8a2626", error_line="#5a2323",
        filler_line="#3a3a3a", diff_line="#7d5a2b", current_diff_line="#c08333",
        out_bg="#16181a", out_border="#3a3f44", out_text="#d0d4d8",
        out_error="#ff6b60",
        ok_color="#4ec46a", link_color="#6cb6ff", warn_color="#ff6b60",
        hint_color="#4da3ff",
        clock_accent="#4da3ff", clock_text="#e8eaed",
    ),
    # ------------------------------------------------------------- Mikhail
    # Black background, amber font (classic amber-phosphor CRT).
    "mikhail": dict(
        window_bg="#000000", panel_bg="#0a0800",
        surface_bg="#0d0a00", border="#4d3800",
        text="#ffb000", text_muted="#cc8c00", text_gray="#8a6a00",
        accent="#ffb000",
        menubar_bg="#000000", menubar_border="#4d3800", menubar_sep="#ffb000",
        menu_sel_bg="#ffb000", menu_sel_text="#000000",
        field_bg="#0d0a00", field_border="#4d3800", field_text="#ffb000",
        btn_top="#1a1400", btn_bottom="#0d0a00", btn_border="#664c00",
        btn_text="#ffb000",
        btn_hover_top="#261e00", btn_hover_bottom="#1a1400", btn_hover_border="#ffb000",
        btn_press_top="#0d0a00", btn_press_bottom="#050400", btn_press_border="#cc8c00",
        dirty_bg="#332800", dirty_border="#997300",
        dirty_hover="#403200", dirty_press="#4d3c00",
        editor_bg="#000000", editor_text="#ffb000",
        editor_border="#4d3800", editor_focus_border="#ffb000",
        sel_bg="#664c00", sel_text="#ffe08a",
        gutter_bg="#0d0a00", gutter_num="#8a6a00",
        fold_marker="#ffd24d", bookmark="#ff8c00",
        ini_comment="#8a6a00", ini_true="#ffd24d", ini_false="#ff6a00",
        changed_line="#2e2400", duplicate_line="#6b1e00", error_line="#3d1400",
        filler_line="#2a2a10", diff_line="#6e4a10", current_diff_line="#946313",
        out_bg="#000000", out_border="#4d3800", out_text="#ffb000",
        out_error="#ff5533",
        ok_color="#ffd24d", link_color="#ffd24d", warn_color="#ff6a00",
        hint_color="#ffb000",
        clock_accent="#ffb000", clock_text="#ffb000",
    ),
}

_current = "normal"
# Original platform style/palette, captured on the first non-normal apply so
# switching back to Normal restores the exact startup look.
_orig_style_name = None
_orig_palette = None


def current_theme():
    """The active theme key ('normal' / 'dark' / 'mikhail')."""
    return _current


def is_dark():
    return _current != "normal"


def c(token):
    """Colour string for ``token`` in the active theme."""
    return _THEMES[_current][token]


def qcolor(token):
    """QColor for ``token`` in the active theme."""
    return QColor(c(token))


def load_saved_theme():
    """Read the persisted theme key from QSettings (default 'normal')."""
    global _current
    key = QSettings("IIASA", "CWatM_GUI").value(_SETTINGS_KEY, "normal")
    _current = key if key in _THEMES else "normal"
    return _current


def set_theme(key):
    """Make ``key`` the active theme and persist it immediately, so the next GUI
    launch restores it (Configure ▸ Mode is remembered across sessions)."""
    global _current
    if key not in _THEMES:
        key = "normal"
    _current = key
    s = QSettings("IIASA", "CWatM_GUI")
    s.setValue(_SETTINGS_KEY, key)
    s.sync()  # flush to the registry now (do not rely on deferred auto-sync)


# ------------------------------------------------------------------ Plotly
# Helpers for the Analyse windows (Timeseries / NetCDF), whose figures are
# rendered as HTML in a QtWebEngine view and must match the active theme.

def plotly_template():
    """Plotly built-in template name for the active theme."""
    return "plotly_white" if not is_dark() else "plotly_dark"


def plotly_layout_overrides():
    """Extra fig.update_layout(...) kwargs for the active theme (empty for
    Normal). Apply AFTER the figure's own update_layout so the axis dicts merge
    with (not replace) settings like scaleanchor."""
    if not is_dark():
        return {}
    grid = "#3a3f44" if _current == "dark" else "#332800"
    return dict(
        paper_bgcolor=c("panel_bg"), plot_bgcolor=c("editor_bg"),
        font=dict(color=c("text")),
        xaxis=dict(gridcolor=grid, zerolinecolor=grid),
        yaxis=dict(gridcolor=grid, zerolinecolor=grid),
    )


def plotly_legend_bg():
    """Semi-transparent legend background matching the active theme."""
    return "rgba(255,255,255,0.6)" if not is_dark() else "rgba(0,0,0,0.5)"


def themed_plot_page(html):
    """Inject a page-background style into a ``fig.to_html`` page so the area
    around the plot matches the theme (no-op for Normal)."""
    if not is_dark():
        return html
    style = f"<style>body {{ background-color: {c('panel_bg')}; margin: 0; }}</style>"
    return html.replace("<head>", "<head>" + style, 1)


def _dark_palette():
    """QPalette from the active (dark/mikhail) theme tokens."""
    p = QPalette()
    window = QColor(c("window_bg"))
    base = QColor(c("editor_bg"))
    text = QColor(c("text"))
    button = QColor(c("btn_bottom"))
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        p.setColor(group, QPalette.Window, window)
        p.setColor(group, QPalette.WindowText, text)
        p.setColor(group, QPalette.Base, base)
        p.setColor(group, QPalette.AlternateBase, QColor(c("panel_bg")))
        p.setColor(group, QPalette.Text, text)
        p.setColor(group, QPalette.Button, button)
        p.setColor(group, QPalette.ButtonText, text)
        p.setColor(group, QPalette.ToolTipBase, QColor(c("panel_bg")))
        p.setColor(group, QPalette.ToolTipText, text)
        p.setColor(group, QPalette.Highlight, QColor(c("sel_bg")))
        p.setColor(group, QPalette.HighlightedText, QColor(c("sel_text")))
        p.setColor(group, QPalette.PlaceholderText, QColor(c("text_gray")))
        p.setColor(group, QPalette.Link, QColor(c("link_color")))
    dis = QColor(c("text_gray"))
    p.setColor(QPalette.Disabled, QPalette.WindowText, dis)
    p.setColor(QPalette.Disabled, QPalette.Text, dis)
    p.setColor(QPalette.Disabled, QPalette.ButtonText, dis)
    return p


def _app_stylesheet():
    """Small app-wide QSS for the pieces the palette does not fully cover."""
    return f"""
        QMenu {{
            background-color: {c('panel_bg')};
            color: {c('text')};
            border: 1px solid {c('menubar_border')};
        }}
        QMenu::item:selected {{
            background-color: {c('menu_sel_bg')};
            color: {c('menu_sel_text')};
        }}
        QMenu::separator {{
            background: {c('menubar_border')};
            height: 1px;
            margin: 4px 8px;
        }}
        QToolTip {{
            background-color: {c('panel_bg')};
            color: {c('text')};
            border: 1px solid {c('menubar_border')};
        }}
    """


def apply_app_theme(app):
    """Apply the active theme application-wide.

    Dark/Mikhail: Fusion style (the native Windows style ignores much of the
    palette) + theme palette + QSS. Normal: restore the original platform
    style, default palette and no stylesheet."""
    global _orig_style_name, _orig_palette
    if _orig_style_name is None:
        _orig_style_name = app.style().objectName()
        _orig_palette = QPalette(app.palette())
    if is_dark():
        app.setStyle("Fusion")
        app.setPalette(_dark_palette())
        app.setStyleSheet(_app_stylesheet())
    else:
        app.setStyle(_orig_style_name)
        app.setPalette(_orig_palette)
        app.setStyleSheet("")
