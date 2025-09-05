"""
Basin Viewer - Pure PySide6 Implementation
==========================================

A comprehensive basin data visualization tool using Qt's native rendering capabilities.
Displays NetCDF basin data with interactive zoom, pan, and overlay features.

Features:
- Native Qt painting (no matplotlib dependency)
- Mouse wheel and button zoom controls
- Click and drag panning
- UPS data visualization with viridis-like colormap
- Semi-transparent mask overlay in green
- Coordinate display on click
- Keyboard shortcuts
- Clean axis frame without gridlines

Author: CWatM GUI Team
"""

import os
import sys
import numpy as np
import xarray as xr
import rasterio
import configparser
import re
from typing import Optional, Tuple, Union

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QScrollArea, QWidget, QApplication
)
from PySide6.QtCore import Qt, QPoint, Signal, QRect
from PySide6.QtGui import (
    QPainter, QWheelEvent, QKeyEvent, QMouseEvent, 
    QColor, QBrush, QPen, QFont, QPixmap, QImage, QIcon
)

import cwatm.run_cwatm as run_cwatm


class BasinCanvas(QWidget):
    """
    Custom Qt widget for rendering basin data with native QPainter.
    Handles all drawing operations, user interactions, and coordinate calculations.
    """
    
    # Signals
    coordinate_clicked = Signal(float, float, float, object)  # lat, lon, basin_val, mask_val
    zoom_changed = Signal(float)  # zoom_factor
    
    def __init__(self, basin_data: np.ndarray, lats: np.ndarray, lons: np.ndarray, 
                 mask_data: Optional[np.ndarray] = None, parent=None):
        """
        Initialize the basin canvas widget.
        
        Args:
            basin_data: 2D numpy array with basin/UPS data
            lats: 1D numpy array with latitude coordinates
            lons: 1D numpy array with longitude coordinates  
            mask_data: Optional 2D numpy array with mask data
            parent: Parent widget
        """
        super().__init__(parent)
        
        # Store data
        self.basin_data = basin_data
        self.lats = lats
        self.lons = lons
        self.mask_data = mask_data
        
        # Calculate data properties
        self.data_height, self.data_width = basin_data.shape
        self.lat_min, self.lat_max = float(np.min(lats)), float(np.max(lats))
        self.lon_min, self.lon_max = float(np.min(lons)), float(np.max(lons))
        
        # Normalize basin data for color mapping
        self.data_min = np.nanmin(basin_data)
        self.data_max = np.nanmax(basin_data)
        self.data_range = self.data_max - self.data_min if self.data_max > self.data_min else 1.0
        
        # Display settings - always show both UPS and mask
        self.show_ups = True
        self.show_mask = True
        
        # Zoom and pan settings
        self.zoom_factor = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 20.0
        
        # Mouse interaction
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.drag_start = None
        self.is_dragging = False
        
        # Initialize widget size
        self._setup_initial_size()
        
    def _setup_initial_size(self):
        """Setup initial widget size based on data dimensions."""
        # Calculate initial scale to fit nicely
        initial_scale = min(800 / self.data_width, 600 / self.data_height, 3.0)
        self.zoom_factor = max(initial_scale, self.min_zoom)
        
        # Set widget size
        width = int(self.data_width * self.zoom_factor)
        height = int(self.data_height * self.zoom_factor)
        
        self.setMinimumSize(50, 50)
        self.setMaximumSize(int(self.data_width * self.max_zoom), 
                          int(self.data_height * self.max_zoom))
        self.resize(width, height)
        
    # === Display Control Methods ===
    
    def toggle_mask(self, show: bool):  
        """Toggle mask overlay display."""
        self.show_mask = show
        self._cached_image = None  # Force image recreation
        self.update()
        
    def set_mask_data(self, mask_data: Optional[np.ndarray]):
        """Update mask data and refresh display."""
        self.mask_data = mask_data
        self._cached_image = None  # Force image recreation
        self.update()
        
    def set_zoom(self, zoom_factor: float):
        """Set zoom factor and resize widget."""
        zoom_factor = max(self.min_zoom, min(zoom_factor, self.max_zoom))
        if zoom_factor != self.zoom_factor:
            self.zoom_factor = zoom_factor
            
            new_width = max(50, int(self.data_width * zoom_factor))
            new_height = max(50, int(self.data_height * zoom_factor))
            
            self.resize(new_width, new_height)
            # No need to recreate image, just repaint at new size
            self.update()
            self.zoom_changed.emit(zoom_factor)
            
    def zoom_in(self):
        """Zoom in by 25%."""
        self.set_zoom(self.zoom_factor * 1.25)
        
    def zoom_out(self):
        """Zoom out by 20%."""
        self.set_zoom(self.zoom_factor * 0.8)
        
    # === Event Handlers ===
    
    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel for zooming."""
        # Get mouse position for zoom center
        mouse_pos = event.position().toPoint()
        
        # Store old size for centering calculation
        old_size = self.size()
        old_zoom = self.zoom_factor
        
        # Apply zoom
        delta = event.angleDelta().y()
        if delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()
            
        # If zoom changed, adjust scroll position to keep mouse position centered
        if self.zoom_factor != old_zoom:
            # Find the scroll area (should be immediate parent)
            parent = self.parent()
            scroll_area = None
            
            if isinstance(parent, QScrollArea):
                scroll_area = parent
            else:
                # Look in parent hierarchy
                while parent:
                    if hasattr(parent, 'scroll_area'):
                        scroll_area = parent.scroll_area
                        break
                    parent = parent.parent()
            
            if scroll_area:
                # Calculate zoom ratio
                zoom_ratio = self.zoom_factor / old_zoom
                
                # Get current scroll position
                h_scroll = scroll_area.horizontalScrollBar()
                v_scroll = scroll_area.verticalScrollBar()
                
                # Calculate new scroll position to keep mouse position centered
                new_h = int((h_scroll.value() + mouse_pos.x()) * zoom_ratio - mouse_pos.x())
                new_v = int((v_scroll.value() + mouse_pos.y()) * zoom_ratio - mouse_pos.y())
                
                # Apply new scroll positions with bounds
                h_scroll.setValue(max(0, min(new_h, h_scroll.maximum())))
                v_scroll.setValue(max(0, min(new_v, v_scroll.maximum())))
                
        event.accept()
        
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press for drag start."""
        if event.button() == Qt.LeftButton:
            self.drag_start = event.pos()
            self.is_dragging = False
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for panning."""
        if event.buttons() & Qt.LeftButton and self.drag_start:
            distance = (event.pos() - self.drag_start).manhattanLength()
            if distance > 5:
                if not self.is_dragging:
                    self.is_dragging = True
                    self.setCursor(Qt.ClosedHandCursor)
                
                # Calculate pan delta and emit to parent for scroll area handling
                delta = event.pos() - self.drag_start
                self.drag_start = event.pos()  # Update for next move
                
                # Find scroll area for panning
                parent = self.parent()
                scroll_area = None
                
                if isinstance(parent, QScrollArea):
                    scroll_area = parent
                else:
                    # Look in parent hierarchy
                    while parent:
                        if hasattr(parent, 'scroll_area'):
                            scroll_area = parent.scroll_area
                            break
                        parent = parent.parent()
                
                if scroll_area:
                    h_scroll = scroll_area.horizontalScrollBar()
                    v_scroll = scroll_area.verticalScrollBar()
                    
                    # Pan by updating scroll bar values (negative for natural feel)
                    new_h = h_scroll.value() - delta.x()
                    new_v = v_scroll.value() - delta.y()
                    
                    # Apply with bounds checking
                    h_scroll.setValue(max(0, min(new_h, h_scroll.maximum())))
                    v_scroll.setValue(max(0, min(new_v, v_scroll.maximum())))
                    
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release for click detection."""
        if event.button() == Qt.LeftButton:
            if not self.is_dragging and self.drag_start:
                # This was a click, emit coordinates
                self._emit_coordinates(event.pos())
            
            self.is_dragging = False
            self.drag_start = None
            self.setCursor(Qt.ArrowCursor)
            
        super().mouseReleaseEvent(event)
        
    # === Painting ===
    
    def paintEvent(self, event):
        """Main paint event - renders image-based maps like mask_viewer."""
        painter = QPainter(self)
        
        try:
            # Create and display the composite image
            if not hasattr(self, '_cached_image') or self._cached_image is None:
                self._create_composite_image()
            
            if hasattr(self, '_cached_image') and self._cached_image:
                # Scale image to current widget size with nearest neighbor for sharp pixels
                scaled_image = self._cached_image.scaled(
                    self.size(), Qt.KeepAspectRatio, Qt.FastTransformation
                )
                
                # Center the image
                x = (self.width() - scaled_image.width()) // 2
                y = (self.height() - scaled_image.height()) // 2
                
                painter.drawImage(x, y, scaled_image)
                
            # Draw axis frame on top
            self._draw_axis_frame(painter)
            
        except Exception as e:
            self._draw_error(painter, str(e))
            
        painter.end()
        
    def _create_composite_image(self):
        """Create composite image from basin and mask data like mask_viewer."""
        try:
            height, width = self.basin_data.shape
            
            # Create RGBA image (with alpha channel for transparency)
            rgba_array = np.zeros((height, width, 4), dtype=np.uint8)

            # Fill basin/UPS data if enabled
            if self.show_ups:
                # Create discrete 8-class classification for UPS data
                valid_mask = ~np.isnan(self.basin_data)
                
                if self.data_range > 0:
                    # Apply logarithmic normalization for better visual distribution
                    # Add small offset to avoid log(0) issues
                    log_min = np.log10(self.data_min + 1e-10)
                    log_max = np.log10(self.data_max + 1e-10)
                    log_data = np.log10(self.basin_data + 1e-10)
                    
                    # Normalize logarithmic values to 0-1 range
                    if log_max > log_min:
                        normalized_data = (log_data - log_min) / (log_max - log_min)
                    else:
                        normalized_data = np.zeros_like(log_data)
                    
                    # Create 8 discrete classes
                    class_indices = np.floor(normalized_data * 7.999).astype(int)  # 0-7 classes
                    class_indices = np.clip(class_indices, 0, 7)
                    
                    # Define 8 discrete blue colors from light to dark
                    blue_colors = np.array([
                        [173, 216, 230],  # Very light blue
                        [135, 206, 235],  # Light blue  
                        [100, 149, 237],  # Cornflower blue
                        [70, 130, 180],   # Steel blue
                        [30, 144, 255],   # Dodger blue
                        [0, 100, 200],    # Medium blue
                        [0, 70, 160],     # Dark blue
                        [0, 40, 120]      # Very dark blue
                    ], dtype=np.uint8)
                    
                    # Vectorized color assignment
                    rgba_array[valid_mask, :3] = blue_colors[class_indices[valid_mask]]
                    rgba_array[valid_mask, 3] = 100  # Alpha channel
                    
                    # Transparent for invalid values
                    rgba_array[~valid_mask] = [255, 255, 255, 0]


            else:
                # All transparent when UPS is hidden
                rgba_array[:, :, 3] = 0

            # Add mask overlay if enabled - vectorized operation
            if self.show_mask and self.mask_data is not None:
                rgba_array[:, :, 3] = np.where(rgba_array[:, :, 3] == 0,0,(np.where(self.mask_data ==1, 255,128)))

            # Create QImage from array
            self._cached_image = QImage(
                rgba_array.data, width, height, width * 4, QImage.Format_RGBA8888
            )
            
        except Exception as e:
            print(f"Error creating composite image: {str(e)}", file=sys.stderr)
            self._cached_image = None
                    
    def _draw_axis_frame(self, painter: QPainter):
        """Draw clean axis frame with corner ticks."""
        rect = self.rect()
        
        # Main frame - dark gray
        frame_pen = QPen(QColor(64, 64, 64), 1)
        painter.setPen(frame_pen)
        
        # Draw rectangle frame
        painter.drawRect(0, 0, rect.width() - 1, rect.height() - 1)
        
        # Corner tick marks - lighter gray
        tick_pen = QPen(QColor(96, 96, 96), 1)
        painter.setPen(tick_pen)
        
        tick_size = 6
        
        # Bottom-left corner
        painter.drawLine(0, rect.height() - tick_size, 0, rect.height() - 1)
        painter.drawLine(0, rect.height() - 1, tick_size, rect.height() - 1)
        
        # Bottom-right corner  
        painter.drawLine(rect.width() - tick_size, rect.height() - 1, 
                        rect.width() - 1, rect.height() - 1)
        
        # Top-left corner
        painter.drawLine(0, 0, tick_size, 0)
        painter.drawLine(0, 0, 0, tick_size)
        
        # Top-right corner
        painter.drawLine(rect.width() - tick_size, 0, rect.width() - 1, 0)
        painter.drawLine(rect.width() - 1, 0, rect.width() - 1, tick_size)
        
    def _draw_error(self, painter: QPainter, error_msg: str):
        """Draw error message when rendering fails."""
        painter.fillRect(self.rect(), QColor(255, 200, 200))
        painter.setPen(QColor(200, 0, 0))
        font = QFont("Arial", 12, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, f"Render Error:\n{error_msg}")
        

    # === Coordinate Calculations ===
    
    def _emit_coordinates(self, pos: QPoint):
        """Calculate and emit geographic coordinates for clicked position."""
        try:
            lat, lon, basin_val, mask_val = self._get_coordinates_at_position(pos)
            if lat is not None:
                self.coordinate_clicked.emit(lat, lon, basin_val, mask_val)
        except Exception as e:
            print(f"Error getting coordinates: {e}", file=sys.stderr)
            
    def _get_coordinates_at_position(self, pos: QPoint) -> Tuple[Optional[float], Optional[float], Optional[float], Union[float, str]]:
        """Convert widget position to geographic coordinates and data values."""
        rect = self.rect()
        
        # Convert widget coordinates to data indices
        rel_x = pos.x() / rect.width()
        rel_y = pos.y() / rect.height()
        
        data_j = int(rel_x * self.data_width)
        data_i = int(rel_y * self.data_height)
        
        # Clamp to valid ranges
        data_i = max(0, min(data_i, self.data_height - 1))
        data_j = max(0, min(data_j, self.data_width - 1))
        
        # Calculate geographic coordinates
        lon = self.lon_min + rel_x * (self.lon_max - self.lon_min)
        lat = self.lat_max - rel_y * (self.lat_max - self.lat_min)  # Flip Y axis
        
        # Get data values
        basin_val = self.basin_data[data_i, data_j]
        mask_val = self.mask_data[data_i, data_j] if self.mask_data is not None else "N/A"
        
        return lat, lon, basin_val, mask_val


class BasinWindow(QDialog):
    """
    Main basin visualization window with controls and display area.
    Provides a complete interface for viewing and interacting with basin data.
    """
    
    def __init__(self, basin_data: np.ndarray, lats: np.ndarray, lons: np.ndarray,
                 title: str = "Basin Display", mask_data: Optional[np.ndarray] = None, 
                 settings_file: Optional[str] = None, parent=None):
        """
        Initialize the basin visualization window.
        
        Args:
            basin_data: 2D numpy array with basin/UPS data
            lats: 1D numpy array with latitude coordinates
            lons: 1D numpy array with longitude coordinates
            title: Window title
            mask_data: Optional 2D numpy array with mask data
            settings_file: Path to CWatM settings file for mask creation
            parent: Parent widget
        """
        super().__init__(parent)
        
        # Store data and setup window
        self.basin_data = basin_data
        self.lats = lats
        self.lons = lons
        self.mask_data = mask_data
        self.settings_file = settings_file
        
        self.setWindowTitle(f"🗺️ {title}")
        self.setModal(False)
        self.resize(950, 650)  # Slightly larger for buttons
        
        # Set window flags to NOT show in taskbar but have min/max/close buttons
        self.setWindowFlags(Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        
        # Set CWatM icon
        try:
            icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'assets', 'cwatm.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception as e:
            print(f"Warning: Could not load CWatM icon: {e}", file=sys.stderr)
        
        # Window styling
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f8f9fa, stop:1 #e9ecef);
            }
        """)
        
        # Control variables - always display both UPS and mask
        self.show_ups = True
        self.show_mask = True
        
        # Setup UI components
        self._setup_ui()
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Force initial display
        QApplication.processEvents()
        self.basin_canvas.update()
        
    def _setup_ui(self):
        """Setup the complete user interface."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)
        
        # Title header
        self._create_title_header(main_layout)
        
        # Main display area with scroll
        self._create_display_area(main_layout)
        
        # Coordinate info label
        self._create_info_label(main_layout)
        
        # Control buttons
        self._create_control_buttons(main_layout)
        
    def _create_title_header(self, layout: QVBoxLayout):
        """Create the title header."""
        title_text = self.windowTitle().replace('🗺️ ', '')
        title_label = QLabel(f"Basin Visualization: {title_text}")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 18px;
                font-weight: 700;
                color: #2c3e50;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ffffff, stop:1 #f8f9fa);
                border: 2px solid #e9ecef;
                border-radius: 10px;
                padding: 12px 20px;
            }
        """)
        layout.addWidget(title_label)
        
    def _create_display_area(self, layout: QVBoxLayout):
        """Create the scrollable display area with basin canvas as scrollable content."""
        # Create QScrollArea as the primary scrollable container
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)  # Manual sizing for zoom control
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setMinimumSize(580, 420)
        
        # Configure scroll bar policies - show when needed
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Style the scroll area and scroll bars
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #ffffff;
                border: 2px solid #dee2e6;
                border-radius: 8px;
                margin: 4px;
            }
            QScrollBar:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border: 1px solid #dee2e6;
                border-radius: 6px;
                width: 18px;
            }
            QScrollBar:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border: 1px solid #dee2e6;
                border-radius: 6px;
                height: 18px;
            }
            QScrollBar::handle:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3498db, stop:1 #2980b9);
                border-radius: 5px;
                min-height: 30px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3498db, stop:1 #2980b9);
                border-radius: 5px;
                min-width: 30px;
                margin: 2px;
            }
            QScrollBar::handle:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #5dade2, stop:1 #3498db);
            }
            QScrollBar::add-line, QScrollBar::sub-line {
                border: none;
                background: transparent;
            }
        """)
        
        # Create the basin canvas as the scrollable widget content
        self.basin_canvas = BasinCanvas(self.basin_data, self.lats, self.lons, self.mask_data)
        self.basin_canvas.setStyleSheet("""
            BasinCanvas {
                background-color: white;
                border: 1px solid #e9ecef;
                margin: 2px;
            }
        """)
        
        # Connect canvas coordinate click signal
        self.basin_canvas.coordinate_clicked.connect(self._on_coordinate_clicked)
        
        # Set basin canvas as the widget inside scroll area
        self.scroll_area.setWidget(self.basin_canvas)
        
        # Add scroll area to main layout
        layout.addWidget(self.scroll_area)
        
    def _create_info_label(self, layout: QVBoxLayout):
        """Create the coordinate information display label."""
        self.info_label = QLabel("Click on the image to see coordinates and values")
        self.info_label.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', 'Consolas', monospace;
                font-size: 12px;
                font-weight: 500;
                color: #2c3e50;
                padding: 12px 16px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border: 2px solid #dee2e6;
                border-radius: 8px;
                min-height: 20px;
            }
        """)
        layout.addWidget(self.info_label)
        
    def _create_control_buttons(self, layout: QVBoxLayout):
        """Create the control button layout."""
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.setContentsMargins(8, 8, 8, 8)
        
        # Standard button style for toggles
        toggle_style = """
            QPushButton {
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                font-weight: 500;
                color: white;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #87ceeb, stop:1 #5dade2);
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                min-width: 70px;
                min-height: 28px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #add8e6, stop:1 #87ceeb);
                box-shadow: 0 2px 6px rgba(135, 206, 235, 0.3);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #5dade2, stop:1 #3498db);
            }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #b0c4de, stop:1 #778899);
            }
            QPushButton:disabled {
                background: #d3d3d3;
                color: #a9a9a9;
            }
        """
        
        # Show Mask toggle button
        self.mask_button = QPushButton("Hide Mask")
        self.mask_button.setCheckable(True)
        self.mask_button.setChecked(True)
        self.mask_button.clicked.connect(self._toggle_mask)
        self.mask_button.setStyleSheet(toggle_style)
        
        if self.mask_data is None:
            self.mask_button.setEnabled(False)
            self.mask_button.setText("Mask (N/A)")
            
        button_layout.addWidget(self.mask_button)
        
        # Create new mask button
        self.create_mask_button = QPushButton("Create new Mask")
        self.create_mask_button.clicked.connect(self._create_new_mask)
        self.create_mask_button.setStyleSheet(toggle_style)
        button_layout.addWidget(self.create_mask_button)
        
        # Use coordinates button - initially disabled
        self.use_coords_button = QPushButton("Use Coordinates")
        self.use_coords_button.clicked.connect(self._use_coordinates)
        self.use_coords_button.setStyleSheet(toggle_style)
        self.use_coords_button.setEnabled(False)  # Disabled until mask is created successfully
        button_layout.addWidget(self.use_coords_button)
        
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
    # === Event Handlers ===
    
    def _toggle_mask(self):
        """Toggle mask overlay display."""
        self.show_mask = self.mask_button.isChecked()
        self.mask_button.setText("Hide Mask" if self.show_mask else "Show Mask")
        self.basin_canvas.toggle_mask(self.show_mask)
        
    def _use_coordinates(self):
        """Put the lon lat coordinates into maskmap_field in the main GUI."""
        if hasattr(self, 'last_clicked_lat') and hasattr(self, 'last_clicked_lon'):
            try:
                # Format coordinates to 4 decimal places
                coord_string = f"{self.last_clicked_lon:.4f} {self.last_clicked_lat:.4f}"
                
                # Try to access the main window's maskmap field
                # This assumes the main window has a maskmap_field attribute
                app = QApplication.instance()
                if app:
                    for widget in app.allWidgets():
                        if hasattr(widget, 'maskmap_field'):
                            widget.maskmap_field.setText(coord_string)
                            # Coordinates updated successfully
                            return
                
                print("Could not find MaskMap field in main GUI", file=sys.stderr)
                
            except Exception as e:
                print(f"Error updating MaskMap field: {str(e)}", file=sys.stderr)
        else:
            print("No coordinates available - create a mask first", file=sys.stderr)
        
    def _create_new_mask(self):
        """Create new mask using current clicked coordinates."""
        if hasattr(self, 'last_clicked_lat') and hasattr(self, 'last_clicked_lon'):
            try:
                # Import here to avoid circular imports
                import cwatm.run_cwatm as run_cwatm
                import configparser
                import tempfile
                
                # Creating new mask at specified coordinates
                
                # Check if we have settings file
                if not hasattr(self, 'settings_file') or not self.settings_file:
                    print("No settings file available for mask creation", file=sys.stderr)
                    return
                
                # Read and modify settings file
                config = configparser.ConfigParser()
                config.optionxform = str
                config.read(self.settings_file)
                
                # Update MaskMap with coordinates - format as "lon lat" with 4 decimal places
                coord_string = f"{self.last_clicked_lon:.4f} {self.last_clicked_lat:.4f}"
                if config.has_section('MASK_OUTLET'):
                    config.set('MASK_OUTLET', 'MaskMap', coord_string)
                else:
                    config.add_section('MASK_OUTLET')
                    config.set('MASK_OUTLET', 'MaskMap', coord_string)
                
                # Update Gauges with coordinates as well
                if config.has_section('MASK_OUTLET'):
                    config.set('MASK_OUTLET', 'Gauges', coord_string)
                else:
                    config.set('MASK_OUTLET', 'Gauges', coord_string)
                
                # Create temporary settings file in same directory as original
                import os
                original_dir = os.path.dirname(self.settings_file)
                temp_filename = f"temp_mask_{os.getpid()}.ini"
                temp_settings_path = os.path.join(original_dir, temp_filename)
                
                with open(temp_settings_path, 'w') as temp_file:
                    config.write(temp_file)
                
                # Temporary settings file created and coordinates updated
                
                # Call CWatM mainwarm function with temporary settings file
                result = run_cwatm.mainwarm(temp_settings_path, ["-vgm"], [])
                
                if result and len(result) > 0:
                    # Update mask data with new result
                    new_mask = result[0].data
                    new_mask = np.where(new_mask != 1, 0, 1)
                    
                    if new_mask.shape != self.basin_data.shape:
                        # Handle different sized masks by placing them correctly
                        x = result[1]
                        y = result[2]
                        maskbig = np.zeros(self.basin_data.shape)
                        maskbig[y:y + new_mask.shape[0], x:x + new_mask.shape[1]] = new_mask
                        self.mask_data = maskbig
                    else:
                        self.mask_data = new_mask
                    
                    # Update canvas with new mask data
                    self.basin_canvas.set_mask_data(self.mask_data)
                    # New mask created successfully
                    
                    # Enable mask button if it was disabled
                    if not self.mask_button.isEnabled():
                        self.mask_button.setEnabled(True)
                        self.mask_button.setText("Hide Mask")
                        self.mask_button.setChecked(True)
                        self.show_mask = True
                    
                    # Force refresh of the composite image display
                    self.basin_canvas._cached_image = None
                    self.basin_canvas.update()
                    
                    # Enable "Use Coordinates" button after successful mask creation
                    self.use_coords_button.setEnabled(True)
                    
                    # Enable mask button if it was disabled
                    if not self.mask_button.isEnabled():
                        self.mask_button.setEnabled(True)
                        self.mask_button.setText("Hide Mask")
                        self.mask_button.setChecked(True)
                        self.show_mask = True
                    
                else:
                    print("Failed to create new mask - no result from CWatM", file=sys.stderr)
                
                # Delete temporary file completely
                try:
                    import os
                    if os.path.exists(temp_settings_path):
                        os.remove(temp_settings_path)
                        # Temporary file deleted successfully
                except Exception as cleanup_error:
                    print(f"Warning: Could not delete temporary file {temp_settings_path}: {cleanup_error}", file=sys.stderr)
                    
            except Exception as e:
                print(f"Error creating new mask: {str(e)}", file=sys.stderr)
        else:
            print("No coordinates available - click on the map first", file=sys.stderr)
    
    def _on_coordinate_clicked(self, lat: float, lon: float, basin_val: float, mask_val):
        """Handle coordinate click from canvas."""
        try:
            # Store coordinates for mask creation
            self.last_clicked_lat = lat
            self.last_clicked_lon = lon
            
            # Format basin value
            if basin_val is not None and np.isnan(basin_val):
                basin_str = "No Data"
            elif basin_val is not None:
                basin_str = f"{basin_val:.1f}"
            else:
                basin_str = "N/A"

            if mask_val == 1:
                mask = "True"
            else:
                mask = "False"
                
            # Update info label
            info_text = f"Lat: {lat:.3f}°, Lon: {lon:.3f}° | Basin area: {basin_str} km2 | Mask: {mask}"
            self.info_label.setText(info_text)
            
        except Exception as e:
            print(f"Error handling coordinate click: {e}", file=sys.stderr)
            self.info_label.setText("Error getting coordinates")
            
    def wheelEvent(self, event: QWheelEvent):
        """Forward wheel events to canvas for zoom functionality."""
        if hasattr(self, 'basin_canvas') and self.basin_canvas:
            self.basin_canvas.wheelEvent(event)
        else:
            super().wheelEvent(event)
        
    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard shortcuts."""
        key = event.key()
        
        if key == Qt.Key_M and self.mask_data is not None:
            self.mask_button.setChecked(not self.mask_button.isChecked())
            self._toggle_mask()
        elif key == Qt.Key_U:
            self.ups_button.setChecked(not self.ups_button.isChecked())
            self._toggle_ups()
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.basin_canvas.zoom_in()
        elif key == Qt.Key_Minus:
            self.basin_canvas.zoom_out()
        elif key == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class BasinViewer:
    """
    Main basin viewer class for loading and displaying NetCDF basin data.
    Handles configuration parsing, data loading, and window management.
    """
    
    def __init__(self, config_content: Optional[str] = None):
        """
        Initialize the basin viewer.
        
        Args:
            config_content: INI configuration file content as string
        """
        self.config_content = config_content
        self.basin_window = None
        
    def show_basin(self, settings_file: str, parent=None):
        """
        Load and display basin data from NetCDF file.
        
        Args:
            settings_file: Path to the CWatM settings file
            parent: Parent window for the basin dialog
        """
        try:
            # Store settings file path for mask creation
            self.settings_file = settings_file
            # Find UPS file path
            ups_path = self._find_ups_path()
            if not ups_path:
                print("No UPS path found in configuration", file=sys.stderr)
                return
                
            # Resolve placeholders and validate path
            resolved_path = self._resolve_placeholders(ups_path)
            if not resolved_path or not os.path.exists(resolved_path):
                print(f"Basin file not found: {resolved_path}", file=sys.stderr)
                return
                
            # Load NetCDF data
            basin_data, lats, lons = self._load_netcdf_data(resolved_path)
            if basin_data is None:
                return
                
            # Load mask data if available
            mask_data = self._load_mask_data(self.settings_file,basin_data.shape)
            
            # Create and show window
            title = f"Basin: {os.path.basename(resolved_path)}"
            self.basin_window = BasinWindow(basin_data, lats, lons, title, mask_data, settings_file, parent)
            self.basin_window.show()
            
        except Exception as e:
            print(f"Error loading basin data: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            
    def _find_ups_path(self) -> Optional[str]:
        """Find UPS file path from TOPOP.ldd configuration."""
        if not self.config_content:
            return None
            
        try:
            config = configparser.ConfigParser()
            config.read_string(self.config_content)
            
            if config.has_section("TOPOP") and config.has_option("TOPOP", "ldd"):
                ldd_path = config.get("TOPOP", "ldd")
                # Replace filename with ups.nc
                directory = os.path.dirname(ldd_path)
                return os.path.join(directory, "ups.nc")
            else:
                print("Warning: ldd not found in [TOPOP] section", file=sys.stderr)
                return None
                
        except Exception as e:
            print(f"Error finding UPS path: {e}", file=sys.stderr)
            return None
            
    def _find_mask_path(self) -> Optional[str]:
        """Find mask file path from configuration."""
        if not self.config_content:
            return None
            
        try:
            config = configparser.ConfigParser()
            config.read_string(self.config_content)
            
            # Search for MaskMap in all sections
            for section_name in config.sections():
                for key, value in config.items(section_name):
                    if key.lower() == 'maskmap':
                        return value
            return None
            
        except Exception as e:
            print(f"Error finding mask path: {e}", file=sys.stderr)
            return None
            
    def _resolve_placeholders(self, path: str) -> str:
        """Resolve $(section:key) placeholders in file paths."""
        if not path or '$' not in path or not self.config_content:
            return path
            
        try:
            config = configparser.ConfigParser()
            config.read_string(self.config_content)
            
            # Resolve placeholders iteratively (up to 10 iterations)
            for _ in range(10):
                placeholders = re.findall(r'\$\(([^)]+)\)', path)

                if not placeholders:
                    break
                    
                for placeholder in placeholders:
                    parts = placeholder.split(":")
                    if len(parts) >= 2:
                        section_name, key_name = parts[0], parts[1]
                        if config.has_section(section_name) and config.has_option(section_name, key_name):
                            value = config.get(section_name, key_name)
                            path = path.replace(f'$({placeholder})', value)
                    else:
                        # Try FILE_PATHS section
                        key_name = parts[0]
                        if config.has_section("FILE_PATHS") and config.has_option("FILE_PATHS", key_name):
                            value = config.get("FILE_PATHS", key_name)
                            path = path.replace(f'$({placeholder})', value)
                            
            return path
            
        except Exception as e:
            print(f"Error resolving placeholders: {e}", file=sys.stderr)
            return path
            
    def _load_netcdf_data(self, file_path: str) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """Load basin data from NetCDF file."""
        try:
            ds = xr.open_dataset(file_path)
            
            # Find data variable
            data_vars = [var for var in ds.data_vars.keys()]
            coord_vars = [var for var in ds.coords.keys()]
            
            if data_vars:
                basin_data = ds[data_vars[0]]
            else:
                # Fallback to first suitable variable
                suitable_var = None
                for var in ds.variables.keys():
                    if var not in coord_vars and len(ds[var].dims) >= 2:
                        suitable_var = var
                        break
                        
                if suitable_var:
                    basin_data = ds[suitable_var]
                else:
                    print("No suitable data variable found", file=sys.stderr)
                    ds.close()
                    return None, None, None
                    
            # Find coordinate variables
            lat_var = lon_var = None
            lat_names = ['lat', 'latitude', 'y', 'LAT', 'LATITUDE', 'Y']
            lon_names = ['lon', 'longitude', 'x', 'LON', 'LONGITUDE', 'X']
            
            for name in lat_names:
                if name in ds.coords or name in ds.variables:
                    lat_var = name
                    break
                    
            for name in lon_names:
                if name in ds.coords or name in ds.variables:
                    lon_var = name
                    break
                    
            if not lat_var or not lon_var:
                # Use dimensions as fallback
                dims = list(basin_data.dims)
                if len(dims) >= 2:
                    lat_var, lon_var = dims[-2], dims[-1]
                else:
                    print("Cannot determine coordinate system", file=sys.stderr)
                    ds.close()
                    return None, None, None
                    
            # Extract data
            lats = ds[lat_var].values
            lons = ds[lon_var].values
            
            # Handle extra dimensions
            if basin_data.ndim > 2:
                basin_data = basin_data.isel({dim: 0 for dim in basin_data.dims 
                                           if dim not in [lat_var, lon_var]})
                                           
            basin_array = basin_data.values
            ds.close()
            
            return basin_array, lats, lons
            
        except Exception as e:
            print(f"Error loading NetCDF data: {e}", file=sys.stderr)
            return None, None, None
            
    def _load_mask_data(self, settings_file: str, upsshape):
        """Load mask data if available."""
        try:
            mask_path = self._find_mask_path()
            if not mask_path:
                return None
                
            coord = mask_path.split()
            if len(coord) < 2:
                # File path - load with rasterio
                resolved_path = self._resolve_placeholders(mask_path)
                if resolved_path and os.path.exists(resolved_path):
                    with rasterio.open(resolved_path) as src:
                        mask = src.read(1)
                    return np.where(mask > 1, 0, 1)
                else:
                    print(f"Mask file not found: {resolved_path}", file=sys.stderr)
                    return None
            else:
                # Coordinate-based - use CWatM method
                mask_result = run_cwatm.mainwarm(settings_file, ["-vgm"], [])
                if mask_result:
                    mask_data = mask_result[0].data
                    mask_data = np.where(mask_data != 1, 0, 1)
                    if mask_data.shape != upsshape:
                        x = mask_result[1]
                        y = mask_result[2]
                        maskbig = np.zeros(upsshape)
                        maskbig[y:y + mask_data.shape[0], x:x + mask_data.shape[1]] = mask_data
                        mask_data = maskbig
                        return mask_data


                return None
                
        except Exception as e:
            print(f"Error loading mask data: {e}", file=sys.stderr)
            return None


# === Module Exports ===
__all__ = ['BasinViewer', 'BasinWindow', 'BasinCanvas']