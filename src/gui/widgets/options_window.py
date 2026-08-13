"""
Options Window for CWatM GUI
Manages boolean options from the [Options] section of configuration files
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QCheckBox, QPushButton, QScrollArea, QWidget, QFrame,
                             QLineEdit, QInputDialog, QMessageBox)
from PySide6.QtCore import Qt
import re

from src.gui.utils import theme
from src.gui.utils import option_help
from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils.gui_log import get_logger

log = get_logger("options_window")


class OptionsWindow(GeometryMemoryMixin, QDialog):
    """Window for managing boolean options from [Options] section"""

    def __init__(self, parent=None, config_content=None):
        super().__init__(parent)
        self.config_content = config_content
        self.parent_window = parent
        self.checkboxes = {}  # Dictionary to store checkboxes by option name
        self.options_data = {}  # Dictionary to store parsed options
        self._initial = {}    # option -> value as the file had it (changed marks)
        self._rows = {}       # option -> the row's widgets, for filtering
        self._marks = {}      # option -> the "changed" dot label
        self._group_headers = []   # (title, QLabel) - hidden when the group is empty

        self.setWindowTitle("Change Options")     # same name as the menu item
        # Non-modal: each tick is applied to the settings content at once, so there
        # is nothing to accept - and the editor stays readable while deciding.
        self.setModal(False)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("options"):
            self.resize(640, 620)
            self.move(150, 100)

        self.init_ui()
        self.parse_options_section()
        self._initial = dict(self.options_data)
        self.create_option_checkboxes()
        
    def init_ui(self):
        """Initialize the user interface"""
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Title label with modern styling
        title_label = QLabel("Configuration Options")
        if theme.is_dark():
            _title_color, _title_border = theme.c('accent'), theme.c('border')
        else:  # classic blue gradient title + underline
            _title_color = ("qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                            "stop:0 #2980b9, stop:1 #3498db)")
            _title_border = ("qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                             "stop:0 #74b9ff, stop:1 #0984e3)")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-weight: 700;
                font-size: 24px;
                color: {_title_color};
                padding: 15px 0px 20px 0px;
                border-bottom: 3px solid {_title_border};
                margin-bottom: 10px;
            }}
        """)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Subtitle with modern styling
        subtitle_label = QLabel("Boolean options from the [Options] section:")
        subtitle_label.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-size: 14px;
                color: {theme.c('text_gray')};
                font-weight: 400;
                margin: 0px 0px 15px 0px;
                line-height: 1.4;
            }}
        """)
        main_layout.addWidget(subtitle_label)

        # Find a switch among the forty-odd in a real settings file, and see at a
        # glance what this session changed.
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter options…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.filter_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {theme.c('field_bg')}; "
            f"color: {theme.c('field_text')}; border: 1px solid "
            f"{theme.c('field_border')}; border-radius: 6px; padding: 5px 8px; "
            "font-size: 13px; }")
        self.changed_only = QCheckBox("Changed only")
        self.changed_only.setToolTip("Show only the options changed in this session")
        self.changed_only.setStyleSheet(
            f"QCheckBox {{ color: {theme.c('text')}; font-size: 12px; }}")
        self.changed_only.toggled.connect(self._apply_filter)
        filter_row.addWidget(self.filter_edit, 1)
        filter_row.addWidget(self.changed_only)
        main_layout.addLayout(filter_row)

        # Scrollable area for options with modern styling
        scroll_area = QScrollArea()
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {theme.c('border')};
                border-radius: 12px;
                background-color: {theme.c('panel_bg')};
            }}
            QScrollBar:vertical {{
                background-color: {theme.c('surface_bg')};
                width: 10px;
                border-radius: 5px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #74b9ff, stop:1 #0984e3);
                border-radius: 5px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #81c3ff, stop:1 #0d7bd6);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
            }}
        """)
        
        scroll_widget = QWidget()
        # Object-name selector, not a property-only sheet: a bare
        # "background-color: …;" cascades to every child - and to the **tooltips** of
        # those children, which is how an option's tooltip kept the panel's white
        # background instead of the reversed colours from Preferences ▸ Display.
        scroll_widget.setObjectName("optionsScrollBody")
        scroll_widget.setStyleSheet(
            f"QWidget#optionsScrollBody {{ background-color: {theme.c('panel_bg')}; "
            "border-radius: 12px; }")
        self.scroll_layout = QVBoxLayout(scroll_widget)
        self.scroll_layout.setSpacing(1)  # Much closer spacing
        self.scroll_layout.setContentsMargins(15, 15, 15, 15)
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        main_layout.addWidget(scroll_area)

        button_style = f"""
            QPushButton {{
                font-family: 'Segoe UI', sans-serif; font-size: 12px;
                font-weight: 600; color: white; border: none; border-radius: 6px;
                padding: 6px 16px; min-height: 24px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #5dade2, stop:1 #3498db); }}
            QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #85c1e9, stop:1 #5dade2); }}
            QPushButton:disabled {{ background: #bdc3c7; color: #ecf0f1; }}
        """
        self.add_button = QPushButton("Add option…")
        self.add_button.setToolTip(
            "Add a switch CWatM understands that this settings file does not define "
            "yet (it is written to [OPTIONS] as False)")
        self.add_button.setStyleSheet(button_style)
        self.add_button.clicked.connect(self._add_option)
        self.revert_button = QPushButton("Revert all")
        self.revert_button.setToolTip(
            "Put every option back to the value the file had when this window opened")
        self.revert_button.setStyleSheet(button_style)
        self.revert_button.setEnabled(False)
        self.revert_button.clicked.connect(self._revert_all)
        self.close_button = QPushButton("Close")
        self.close_button.setStyleSheet(button_style)
        self.close_button.clicked.connect(self.close)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(self.add_button)
        btn_row.addWidget(self.revert_button)
        btn_row.addStretch()
        btn_row.addWidget(self.close_button)
        main_layout.addLayout(btn_row)

        self.setLayout(main_layout)
    
    def parse_options_section(self):
        """Parse the [Options] section from configuration content"""
        if not self.config_content:
            return
        
        lines = self.config_content.split('\n')
        in_options_section = False
        
        for line in lines:
            line = line.strip()
            
            # Check if we're entering the [Options] section
            if line.lower() == '[options]':
                in_options_section = True
                continue
            
            # Check if we're entering a different section
            if line.startswith('[') and line.endswith(']') and line.lower() != '[options]':
                in_options_section = False
                continue
            
            # Parse options within the [Options] section
            if in_options_section and line and not line.startswith('#'):
                # Look for key = value pairs
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    # An inline comment is part of the line, not of the value:
                    # "includeGlaciers = False   # no OGGM data yet" used to fail the
                    # boolean test below, so that switch never appeared in the window
                    # at all.
                    value = re.split(r"[#;]", value, 1)[0].strip()

                    # Check if value is boolean (True/False case insensitive)
                    if value.lower() in ['true', 'false']:
                        self.options_data[key] = value.lower() == 'true'
    
    def _info_badge(self, tip):
        """A small circled **i** carrying ``tip``; None when there is nothing to say.

        Drawn with a border-radius label rather than a glyph, so the circle looks the
        same in every font and follows the colour theme."""
        if not tip:
            return None
        badge = QLabel("i")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(16, 16)
        badge.setCursor(Qt.WhatsThisCursor)
        badge.setToolTip(tip)
        # Selected by **object name**, not by `QLabel`: a tooltip is itself a QLabel
        # (QTipLabel), so a bare `QLabel { … }` rule on this widget also paints its
        # tooltip - which is why the badge's own colours showed up instead of the
        # reversed ones from Preferences ▸ Display ▸ Tooltip reverse.
        badge.setObjectName("optionInfoBadge")
        badge.setStyleSheet(f"""
            QLabel#optionInfoBadge {{
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                font-weight: 700;
                color: {theme.c('accent')};
                border: 1px solid {theme.c('accent')};
                border-radius: 8px;
                background-color: {theme.c('surface_bg')};
            }}
            QLabel#optionInfoBadge:hover {{
                color: white;
                background-color: {theme.c('accent')};
            }}
        """)
        return badge

    def create_option_checkboxes(self):
        """Create checkboxes for each boolean option"""
        if not self.options_data:
            # No boolean options found
            no_options_frame = QFrame()
            no_options_frame.setStyleSheet("""
                QFrame {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #ffeaa7, stop:1 #fdcb6e);
                    border: none;
                    border-radius: 12px;
                    padding: 25px;
                    margin: 15px;
                }
            """)
            
            no_options_layout = QVBoxLayout(no_options_frame)
            no_options_label = QLabel("No boolean options found")
            no_options_label.setStyleSheet("""
                QLabel {
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 16px;
                    font-weight: 700;
                    color: #2d3436;
                    text-align: center;
                }
            """)
            no_options_label.setAlignment(Qt.AlignCenter)
            
            info_label = QLabel("The [Options] section does not contain any True/False settings.")
            info_label.setStyleSheet("""
                QLabel {
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 13px;
                    color: #636e72;
                    font-weight: 400;
                    text-align: center;
                    margin-top: 8px;
                }
            """)
            info_label.setAlignment(Qt.AlignCenter)
            
            no_options_layout.addWidget(no_options_label)
            no_options_layout.addWidget(info_label)
            
            self.scroll_layout.addWidget(no_options_frame)
            return
        
        # Grouped by topic (option_help.GROUPS): related switches are scattered
        # through the settings file, but people think about them by subject. Within a
        # group the file's own order is kept; unknown options land in "Other".
        order = [t for t, _n in option_help.GROUPS] + ["Other"]
        by_group = {}
        for name, value in self.options_data.items():
            by_group.setdefault(option_help.group_of(name), []).append((name, value))

        for title in order:
            members = by_group.get(title)
            if not members:
                continue
            header = QLabel(title)
            header.setStyleSheet(f"""
                QLabel {{
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 12px;
                    font-weight: 700;
                    color: {theme.c('text_muted')};
                    padding: 10px 2px 2px 2px;
                    border-bottom: 1px solid {theme.c('border')};
                }}
            """)
            self.scroll_layout.addWidget(header)
            self._group_headers.append((title, header))
            self._build_rows(members)

        # Add stretch to push all options to top
        self.scroll_layout.addStretch()

    def _build_rows(self, members):
        """One row per option: [changed dot] [checkbox] [name] [ⓘ]."""
        for option_name, option_value in members:
            option_layout = QHBoxLayout()
            option_layout.setContentsMargins(5, 2, 5, 2)  # Minimal margins
            option_layout.setSpacing(1)  # Compact spacing
            
            # Create checkbox with custom styling
            checkbox = QCheckBox()
            checkbox.setChecked(option_value)
            checkbox.stateChanged.connect(lambda state, name=option_name: self.on_checkbox_changed(name, state))
            checkbox.setStyleSheet(f"""
                QCheckBox {{
                    spacing: 12px;
                    font-size: 14px;
                    font-family: 'Segoe UI', sans-serif;
                    color: {theme.c('text')};
                    padding: 8px;
                    border-radius: 6px;
                }}
                QCheckBox:hover {{
                    background-color: {theme.c('surface_bg')};
                }}
                QCheckBox::indicator {{
                    width: 20px;
                    height: 20px;
                    border-radius: 6px;
                    border: 2px solid {theme.c('border')};
                    background-color: {theme.c('field_bg')};
                }}
                QCheckBox::indicator:hover {{
                    border-color: {theme.c('btn_hover_border')};
                }}
                QCheckBox::indicator:checked {{
                    border-color: #00b894;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #00b894, stop:1 #00a085);
                    image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iOSIgdmlld0JveD0iMCAwIDEyIDkiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxwYXRoIGQ9Ik0xIDQuNUw0LjUgOEwxMSAxIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPgo8L3N2Zz4K);
                }}
                QCheckBox::indicator:checked:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #17a085, stop:1 #008a75);
                }}
            """)
            
            # Create label with improved styling
            label = QLabel(option_name)
            label.setStyleSheet(f"""
                QLabel {{
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 14px;
                    font-weight: 600;
                    color: {theme.c('text')};
                }}
            """)
            
            # A dot in front of the rows changed in this session (the row numbers it
            # replaces said nothing) - "Changed only" filters on the same state.
            mark = QLabel("●")
            mark.setFixedWidth(14)
            mark.setAlignment(Qt.AlignCenter)
            mark.setStyleSheet(f"QLabel {{ color: {theme.c('accent')}; "
                               "font-size: 11px; }")
            mark.setToolTip("Changed since this window was opened")
            mark.setVisible(False)

            option_layout.addWidget(mark)
            option_layout.addWidget(checkbox)
            option_layout.addWidget(label)
            # What this switch does, and what True/False mean (option_help.py): behind
            # a small ⓘ badge rather than on the row itself, so the explanation only
            # appears when it is asked for - hovering an option to tick it should not
            # pop a paragraph of text.
            info = self._info_badge(option_help.text(option_name))
            if info is not None:
                option_layout.addWidget(info)
            option_layout.addStretch()  # Push content to left

            self.scroll_layout.addLayout(option_layout)
            self.checkboxes[option_name] = checkbox
            self._marks[option_name] = mark
            self._rows[option_name] = [mark, checkbox, label] + (
                [info] if info is not None else [])

    # --------------------------------------------------- filter / marks / revert
    def _apply_filter(self):
        """Hide the rows (and the group headers left empty) that do not match the
        filter text or the "Changed only" tick."""
        needle = self.filter_edit.text().strip().lower()
        only_changed = self.changed_only.isChecked()
        visible_groups = set()
        for name, widgets in self._rows.items():
            show = (not needle or needle in name.lower()) and (
                not only_changed or self._is_changed(name))
            for widget in widgets:
                widget.setVisible(show)
            if show:
                visible_groups.add(option_help.group_of(name))
        for title, header in self._group_headers:
            header.setVisible(title in visible_groups)

    def _is_changed(self, option_name):
        return (self.options_data.get(option_name)
                != self._initial.get(option_name))

    def _refresh_marks(self):
        changed = 0
        for name, mark in self._marks.items():
            is_changed = self._is_changed(name)
            changed += 1 if is_changed else 0
            try:
                mark.setVisible(is_changed and mark.parent() is not None)
            except RuntimeError:
                log.debug("_refresh_marks: ignored", exc_info=True)
        self.revert_button.setEnabled(changed > 0)
        self.revert_button.setText(
            f"Revert all ({changed})" if changed else "Revert all")
        if self.changed_only.isChecked():
            self._apply_filter()

    def _revert_all(self):
        """Every option back to what the file had when this window opened."""
        changed = [n for n in self._marks if self._is_changed(n)]
        if not changed:
            return
        for name in changed:
            box = self.checkboxes.get(name)
            if box is not None:
                box.setChecked(bool(self._initial.get(name)))   # drives the writes
        self._refresh_marks()

    def _add_option(self):
        """Add a switch CWatM understands that this file does not define yet."""
        missing = [n for n in option_help.KNOWN
                   if n.lower() not in {k.lower() for k in self.options_data}]
        if not missing:
            QMessageBox.information(
                self, "Add option",
                "This settings file already defines every option the GUI knows about.")
            return
        name, ok = QInputDialog.getItem(
            self, "Add option",
            "Add to [OPTIONS] (as False - tick it afterwards):", missing, 0, False)
        if not ok or not name:
            return
        content = self._insert_option(name)
        if content is None:
            QMessageBox.warning(
                self, "Add option",
                "This settings file has no [OPTIONS] section to add it to.")
            return
        self.config_content = content
        self._push_to_editor()
        # Rebuild so the new switch appears in its group, in file order.
        self.options_data[name] = False
        self._initial.setdefault(name, False)
        self._rebuild()

    def _insert_option(self, name):
        """``name = False`` at the end of [OPTIONS]; None when there is no such
        section."""
        lines = (self.config_content or "").split("\n")
        start = None
        for i, line in enumerate(lines):
            if line.strip().lower() == "[options]":
                start = i
                break
        if start is None:
            return None
        end = len(lines)
        for i in range(start + 1, len(lines)):
            s = lines[i].strip()
            if s.startswith("[") and s.endswith("]"):
                end = i
                break
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1                       # keep the blank line before the next section
        lines.insert(end, f"{name} = False")
        return "\n".join(lines)

    def _rebuild(self):
        """Re-create the rows (after adding an option)."""
        self.checkboxes.clear()
        self._marks.clear()
        self._rows.clear()
        self._group_headers.clear()
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget() is not None:
                        sub.widget().deleteLater()
        self.create_option_checkboxes()
        self._refresh_marks()
        self._apply_filter()

    def on_checkbox_changed(self, option_name, state):
        """Handle checkbox state changes and update configuration immediately"""
        # Update the configuration content immediately
        self.update_single_option(option_name, state == 2)  # 2 = Qt.Checked
        self.options_data[option_name] = state == 2
        self._push_to_editor()
        self._refresh_marks()

    def _push_to_editor(self):
        """Send the changed content to the main window's editor.

        Through ``set_content_preserving``, so a tick is **one undo step** (Ctrl+Z in
        the editor takes it back) and folding/scroll survive - the old path wrote the
        content straight back and could not be undone at all."""
        mw = self.parent_window
        if not mw:
            return
        try:
            if hasattr(mw, "text_display"):
                mw.text_display.set_original_content(self.config_content)
            editor = getattr(mw, "text_area", None)
            if editor is not None and hasattr(editor, "set_content_preserving"):
                editor.set_content_preserving(self.config_content)
            elif hasattr(mw, "parse_file"):      # older path, kept as a fallback
                mw.parse_file(expand_all=False, load=False,
                              content=self.config_content)
            if hasattr(mw, "on_field_changed"):
                mw.on_field_changed()
        except Exception:
            log.debug("pushing options to the editor failed", exc_info=True)
    
    
    @staticmethod
    def _rewrite_value(line, key, new_value):
        """``key = <new_value>`` with the line's own indentation **and whatever
        followed the value** kept.

        The old version rebuilt the line as ``key = True`` and silently dropped a
        trailing comment - ``includeGlaciers = False   # no OGGM data yet`` lost its
        note the moment the box was ticked."""
        indent = line[:len(line) - len(line.lstrip())]
        after = line.split("=", 1)[1] if "=" in line else ""
        match = re.match(r"^([^#;]*)(.*)$", after)      # value part, then any comment
        comment = match.group(2) if match else ""
        if comment and not comment[:1].isspace():
            comment = "   " + comment
        return f"{indent}{key} = {new_value}{comment}"

    def update_configuration(self):
        """Update the configuration content with new checkbox values"""
        if not self.config_content:
            return
        
        lines = self.config_content.split('\n')
        updated_lines = []
        in_options_section = False
        
        for line in lines:
            original_line = line
            line_stripped = line.strip()
            
            # Check if we're entering the [Options] section
            if line_stripped.lower() == '[options]':
                in_options_section = True
                updated_lines.append(original_line)
                continue
            
            # Check if we're entering a different section
            if line_stripped.startswith('[') and line_stripped.endswith(']') and line_stripped.lower() != '[options]':
                in_options_section = False
                updated_lines.append(original_line)
                continue
            
            # Update options within the [Options] section
            if in_options_section and line_stripped and not line_stripped.startswith('#'):
                if '=' in line_stripped:
                    key, value = line_stripped.split('=', 1)
                    key = key.strip()
                    
                    if key in self.checkboxes:
                        updated_lines.append(self._rewrite_value(
                            original_line, key,
                            "True" if self.checkboxes[key].isChecked() else "False"))
                        continue
            
            # Keep original line if not modified
            updated_lines.append(original_line)
        
        # Update the configuration content
        self.config_content = '\n'.join(updated_lines)
    
    def update_single_option(self, option_name, is_checked):
        """Update a single option in the configuration content"""
        if not self.config_content:
            return
        
        lines = self.config_content.split('\n')
        updated_lines = []
        in_options_section = False
        
        for line in lines:
            original_line = line
            line_stripped = line.strip()
            
            # Check if we're entering the [Options] section
            if line_stripped.lower() == '[options]':
                in_options_section = True
                updated_lines.append(original_line)
                continue
            
            # Check if we're entering a different section
            if line_stripped.startswith('[') and line_stripped.endswith(']') and line_stripped.lower() != '[options]':
                in_options_section = False
                updated_lines.append(original_line)
                continue
            
            # Update the specific option within the [Options] section
            if in_options_section and line_stripped and not line_stripped.startswith('#'):
                if '=' in line_stripped:
                    key, value = line_stripped.split('=', 1)
                    key = key.strip()

                    if key == option_name:
                        updated_lines.append(self._rewrite_value(
                            original_line, key, "True" if is_checked else "False"))
                        continue
            
            # Keep original line if not modified
            updated_lines.append(original_line)
        
        # Update the configuration content
        self.config_content = '\n'.join(updated_lines)
