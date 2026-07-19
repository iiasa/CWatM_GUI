"""
Date management for CWatM GUI.

Handles date validation and date widget management for the main window.
Provides functionality for creating date input widgets and validating
chronological order constraints.
"""

from PySide6.QtWidgets import QDateEdit, QLabel, QHBoxLayout
from PySide6.QtCore import QDate, Qt


class DateManager:
    """Manages date input fields and validation.
    
    This class handles the creation and management of date input widgets
    for the CWatM GUI, including start date, spin-up date, and end date.
    Provides validation to ensure proper chronological ordering.
    
    Attributes
    ----------
    start_date_edit : QDateEdit or None
        Date input widget for simulation start date
    spin_date_edit : QDateEdit or None
        Date input widget for spin-up completion date
    end_date_edit : QDateEdit or None
        Date input widget for simulation end date
    """
    
    def __init__(self):
        """Initialize the date manager.
        
        Sets up empty references to date input widgets that will be
        created later by create_date_widgets().
        """
        self.start_date_edit = None
        self.spin_date_edit = None
        self.end_date_edit = None
        
    def create_date_widgets(self, parent_layout):
        """Create and setup date input widgets.
        
        Creates three date input widgets (start, spin, end) with calendar
        popups and validation callbacks. Widgets are styled and connected
        to validation methods.
        
        Parameters
        ----------
        parent_layout : QLayout
            The parent layout to add the date widgets to
        """
        date_layout = QHBoxLayout()
        
        # Start Date
        date_label = QLabel("Start Date:")
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setDate(QDate.currentDate())
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setMinimumWidth(150)
        self.start_date_edit.setMinimumHeight(30)
        self.start_date_edit.dateChanged.connect(self.validate_dates)
        date_layout.addWidget(date_label)
        date_layout.addWidget(self.start_date_edit)

        # Spin Date
        spin_date_label = QLabel("Spin Date:")
        self.spin_date_edit = QDateEdit()
        self.spin_date_edit.setDate(QDate.currentDate().addDays(0))
        self.spin_date_edit.setCalendarPopup(True)
        self.spin_date_edit.setMinimumWidth(150)
        self.spin_date_edit.setMinimumHeight(30)
        self.spin_date_edit.dateChanged.connect(self.validate_dates)
        date_layout.addWidget(spin_date_label)
        date_layout.addWidget(self.spin_date_edit)
        
        # End Date
        end_date_label = QLabel("End Date:")
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setDate(QDate.currentDate().addDays(0))
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setMinimumWidth(150)
        self.end_date_edit.setMinimumHeight(30)
        self.end_date_edit.dateChanged.connect(self.validate_dates)
        date_layout.addWidget(end_date_label)
        date_layout.addWidget(self.end_date_edit)

        date_layout.addStretch()
        parent_layout.addLayout(date_layout)
        self.retheme()

    def retheme(self):
        """(Re-)apply the theme's field colours to the three date widgets."""
        from src.gui.utils import theme
        style = (f"QDateEdit {{ background-color: {theme.c('field_bg')}; "
                 f"color: {theme.c('field_text')}; }}")
        for w in (self.start_date_edit, self.spin_date_edit, self.end_date_edit):
            if w is not None:
                w.setStyleSheet(style)
        
    def validate_dates(self):
        """Ensure chronological order of dates"""
        if not all([self.start_date_edit, self.spin_date_edit, self.end_date_edit]):
            return
            
        start_date = self.start_date_edit.date()
        spin_date = self.spin_date_edit.date()
        end_date = self.end_date_edit.date()
        
        # Ensure spin_date is not earlier than start_date
        if spin_date < start_date:
            self.spin_date_edit.setDate(start_date)
            
        # Ensure end_date is not earlier than spin_date
        spin_date = self.spin_date_edit.date()  # Get updated spin_date
        if end_date < spin_date:
            self.end_date_edit.setDate(spin_date)
    
    def _resolve_date_value(self, value, config_parser, start_date_obj):
        """Resolve a StepStart/SpinUp/StepEnd value to a QDate.

        In CWatM settings, SpinUp and StepEnd may be given either as a date or as a
        plain integer. The integer is a timestep number counted from StepStart, which
        is timestep 1 (see datetoInt in cwatm/management_modules/timestep.py). So an
        integer N corresponds to the date StepStart + (N - 1) days. Returns None if
        the value is neither a date nor an integer (or no start date is available to
        offset from).
        """
        if not value:
            return None

        # First try a real date string (dd/mm/yyyy, yyyy-mm-dd, ...)
        date_obj = config_parser.parse_date_value(value)
        if date_obj:
            return date_obj

        # Otherwise treat it as an integer offset of timesteps from StepStart
        try:
            n = int(float(str(value).strip()))
        except (ValueError, TypeError):
            return None
        if start_date_obj is None:
            return None
        return start_date_obj.addDays(n - 1)

    def set_dates_from_config(self, date_values, config_parser):
        """Update date fields from parsed configuration values"""
        if not all([self.start_date_edit, self.spin_date_edit, self.end_date_edit]):
            return

        step_start = date_values.get('stepstart')
        spin_up = date_values.get('spinup')
        step_end = date_values.get('stepend')

        start_date_obj = None
        if step_start:
            start_date_obj = config_parser.parse_date_value(step_start)
            if start_date_obj:
                self.start_date_edit.setDate(start_date_obj)

        if spin_up:
            spin_date_obj = self._resolve_date_value(spin_up, config_parser, start_date_obj)
            if spin_date_obj:
                self.spin_date_edit.setDate(spin_date_obj)
            elif start_date_obj:
                # If SpinUp is neither a valid date nor an integer, use StepStart date
                self.spin_date_edit.setDate(start_date_obj)

        if step_end:
            end_date_obj = self._resolve_date_value(step_end, config_parser, start_date_obj)
            if end_date_obj:
                self.end_date_edit.setDate(end_date_obj)
            elif start_date_obj:
                # If StepEnd is neither a valid date nor an integer, fall back to StepStart
                self.end_date_edit.setDate(start_date_obj)
    
    def get_current_dates(self):
        """Get current date values from widgets"""
        if not all([self.start_date_edit, self.spin_date_edit, self.end_date_edit]):
            return None, None, None
            
        return (
            self.start_date_edit.date(),
            self.spin_date_edit.date(), 
            self.end_date_edit.date()
        )
    
    def dates_changed_from_config(self, current_config_dates):
        """Check if current widget dates differ from config file dates"""
        start_date, spin_date, end_date = self.get_current_dates()
        if not all([start_date, spin_date, end_date]):
            return False
            
        start_date_str = start_date.toString("dd/MM/yyyy")
        spin_date_str = spin_date.toString("dd/MM/yyyy")
        end_date_str = end_date.toString("dd/MM/yyyy")
        
        return (current_config_dates.get('stepstart') != start_date_str or 
                current_config_dates.get('spinup') != spin_date_str or 
                current_config_dates.get('stepend') != end_date_str)