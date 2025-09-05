"""
Basin viewer using xarray for loading NetCDF files with latitude and longitude
"""

import os
import sys
import numpy as np
import xarray as xr
import rasterio
# Native Qt approach - no longer need matplotlib or PIL
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QCheckBox, QWidget
from PySide6.QtCore import Qt, QPoint, QRect, Signal
from PySide6.QtGui import QPixmap, QImage, QPainter, QWheelEvent, QKeyEvent, QMouseEvent, QColor, QBrush, QPen
import configparser
from io import StringIO
import re

import cwatm.run_cwatm as run_cwatm


class BasinImageWidget(QWidget):
    """Custom widget for displaying basin data with Qt native painting"""
    
    # Signal emitted when widget is clicked with coordinate data
    clicked = Signal(float, float, float, object)  # lat, lon, basin_val, mask_val
    
    def __init__(self, basin_data, lats, lons, mask_data=None, parent=None):
        super().__init__(parent)
        self.basin_data = basin_data
        self.lats = lats  
        self.lons = lons
        self.mask_data = mask_data
        
        # Display controls
        self.show_ups = True
        self.show_mask = True
        
        # Coordinate ranges
        self.lat_min, self.lat_max = float(np.min(lats)), float(np.max(lats))
        self.lon_min, self.lon_max = float(np.min(lons)), float(np.max(lons))
        
        # Set size based on data
        height, width = basin_data.shape
        self.base_width = width
        self.base_height = height
        self.data_width = width
        self.data_height = height
        
        # Zoom settings
        self.zoom_factor = 1.0
        self.min_zoom = 0.25
        self.max_zoom = 8.0
        
        # Set initial size - scale to fit nicely in window
        initial_scale = min(600 / width, 450 / height, 2.0)
        self.zoom_factor = max(initial_scale, self.min_zoom)
        initial_width = int(width * self.zoom_factor)
        initial_height = int(height * self.zoom_factor)
        
        self.setMinimumSize(int(width * self.min_zoom), int(height * self.min_zoom))
        self.setMaximumSize(int(width * self.max_zoom), int(height * self.max_zoom))
        self.resize(initial_width, initial_height)
        
        # Enable mouse tracking for coordinates
        self.setMouseTracking(True)
        
        # Mouse handling variables
        self.click_start_pos = None
        self.panning = False
        self.last_pan_point = QPoint()
        
        # Enable focus for keyboard events
        self.setFocusPolicy(Qt.StrongFocus)
        
    def toggle_ups(self, show):
        """Toggle UPS data display"""
        self.show_ups = show
        self.update()  # Trigger repaint
        
    def toggle_mask(self, show):
        """Toggle mask overlay display"""  
        self.show_mask = show
        self.update()  # Trigger repaint
        
    def wheelEvent(self, event):
        """Handle mouse wheel for zooming"""
        delta = event.angleDelta().y()
        zoom_in = delta > 0
        
        # Calculate new zoom factor
        if zoom_in:
            new_zoom = min(self.zoom_factor * 1.2, self.max_zoom)
        else:
            new_zoom = max(self.zoom_factor / 1.2, self.min_zoom)
            
        if new_zoom != self.zoom_factor:
            self.zoom_factor = new_zoom
            
            # Resize widget based on new zoom
            new_width = int(self.data_width * self.zoom_factor)
            new_height = int(self.data_height * self.zoom_factor)
            self.resize(new_width, new_height)
            
        # Accept the event so parent doesn't handle it
        event.accept()
        
    def paintEvent(self, event):
        """Paint the basin data and overlays using QPainter with axis lines but no grid"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)  # Disable for pixel-perfect rendering
        
        # Get widget dimensions
        widget_rect = self.rect()
        data_height, data_width = self.basin_data.shape
        
        # Fill background with white
        painter.fillRect(widget_rect, QColor(255, 255, 255))
        
        # Calculate scaling based on current zoom
        scale_x = widget_rect.width() / data_width
        scale_y = widget_rect.height() / data_height
        
        try:
            # Draw UPS data if enabled
            if self.show_ups:
                self._draw_ups_data(painter, widget_rect, scale_x, scale_y)
                
            # Draw mask overlay if enabled
            if self.show_mask and self.mask_data is not None:
                self._draw_mask_overlay(painter, widget_rect, scale_x, scale_y)
                
            # Draw axis lines (no grid) on top of data
            self._draw_axis_lines(painter, widget_rect)
                
        except Exception as e:
            print(f"Error in paintEvent: {str(e)}", file=sys.stderr)
            # Draw error indicator
            painter.fillRect(widget_rect, QColor(255, 200, 200))  # Light red background
            painter.setPen(QColor(255, 0, 0))
            painter.drawText(widget_rect, Qt.AlignCenter, "Error rendering data")
            
        painter.end()
        
    def _draw_ups_data(self, painter, widget_rect, scale_x, scale_y):
        """Draw the UPS basin data with no borders or axis lines"""
        data_height, data_width = self.basin_data.shape
        
        # Set no pen to avoid any border lines
        painter.setPen(Qt.NoPen)
        
        # Normalize data for color mapping
        data_min, data_max = np.nanmin(self.basin_data), np.nanmax(self.basin_data)
        if data_max > data_min:
            # Draw each pixel as a small rectangle with no borders
            for i in range(data_height):
                for j in range(data_width):
                    if not np.isnan(self.basin_data[i, j]):
                        # Calculate pixel position and size
                        pixel_x = int(j * scale_x)
                        pixel_y = int(i * scale_y)
                        pixel_w = max(1, int(scale_x))
                        pixel_h = max(1, int(scale_y))
                        
                        # Normalize value and map to color
                        normalized = (self.basin_data[i, j] - data_min) / (data_max - data_min)
                        color = self._get_viridis_color(normalized)
                        
                        # Set brush and draw pixel with no border
                        painter.setBrush(QBrush(color))
                        painter.drawRect(pixel_x, pixel_y, pixel_w, pixel_h)
                        
    def _draw_mask_overlay(self, painter, widget_rect, scale_x, scale_y):
        """Draw the mask overlay with no borders"""
        data_height, data_width = self.mask_data.shape
        
        # Set up semi-transparent green brush for mask with no pen/borders
        mask_color = QColor(0, 128, 0, 89)  # Green with 35% opacity
        painter.setBrush(QBrush(mask_color))
        painter.setPen(Qt.NoPen)  # Absolutely no borders or lines
        
        # Draw mask pixels with no borders
        for i in range(data_height):
            for j in range(data_width):
                if self.mask_data[i, j] != 0:
                    # Calculate pixel position and size
                    pixel_x = int(j * scale_x)
                    pixel_y = int(i * scale_y)
                    pixel_w = max(1, int(scale_x))
                    pixel_h = max(1, int(scale_y))
                    
                    # Draw mask pixel with no border
                    painter.drawRect(pixel_x, pixel_y, pixel_w, pixel_h)
                    
    def _get_viridis_color(self, normalized_value):
        """Convert normalized value to viridis-like color"""
        # Clamp value between 0 and 1
        val = max(0, min(1, normalized_value))
        
        if val < 0.25:
            # Purple to blue
            t = val / 0.25
            r = int(68 * (1-t) + 30 * t)
            g = int(1 * (1-t) + 100 * t) 
            b = int(84 * (1-t) + 255 * t)
        elif val < 0.5:
            # Blue to cyan
            t = (val - 0.25) / 0.25
            r = int(30 * (1-t) + 0 * t)
            g = int(100 * (1-t) + 180 * t)
            b = int(255 * (1-t) + 255 * t)
        elif val < 0.75:
            # Cyan to green  
            t = (val - 0.5) / 0.25
            r = int(0 * (1-t) + 50 * t)
            g = int(180 * (1-t) + 255 * t)
            b = int(255 * (1-t) + 50 * t)
        else:
            # Green to yellow
            t = (val - 0.75) / 0.25
            r = int(50 * (1-t) + 255 * t)
            g = int(255 * (1-t) + 255 * t)
            b = int(50 * (1-t) + 0 * t)
            
        return QColor(r, g, b)
        
    def _draw_axis_lines(self, painter, widget_rect):
        """Draw clean axis lines without grid"""
        # Set up pen for axis lines - thin, dark gray
        axis_pen = QPen(QColor(64, 64, 64), 1)  # Dark gray, 1px width
        painter.setPen(axis_pen)
        
        # Draw left axis (Y-axis)
        painter.drawLine(0, 0, 0, widget_rect.height())
        
        # Draw bottom axis (X-axis)
        painter.drawLine(0, widget_rect.height() - 1, widget_rect.width(), widget_rect.height() - 1)
        
        # Calculate tick marks - show only major ticks, no grid
        num_x_ticks = min(8, widget_rect.width() // 60)  # Max 8 ticks, spaced at least 60px
        num_y_ticks = min(6, widget_rect.height() // 60)  # Max 6 ticks, spaced at least 60px
        
        if num_x_ticks > 1:
            for i in range(num_x_ticks + 1):
                x = i * widget_rect.width() / num_x_ticks
                # Draw tick mark on bottom axis
                painter.drawLine(int(x), widget_rect.height() - 6, int(x), widget_rect.height() - 1)
        
        if num_y_ticks > 1:
            for i in range(num_y_ticks + 1):
                y = i * widget_rect.height() / num_y_ticks
                # Draw tick mark on left axis
                painter.drawLine(0, int(y), 5, int(y))
    
    def get_coordinates_at_position(self, pos):
        """Get geographic coordinates and data values at widget position"""
        try:
            # Convert widget position to data coordinates
            data_height, data_width = self.basin_data.shape
            widget_rect = self.rect()
            
            # Calculate scales
            scale_x = widget_rect.width() / data_width
            scale_y = widget_rect.height() / data_height
            
            # Convert position to data indices
            data_j = int(pos.x() / scale_x)
            data_i = int(pos.y() / scale_y)
            
            # Clamp to valid ranges
            data_i = max(0, min(data_i, data_height - 1))
            data_j = max(0, min(data_j, data_width - 1))
            
            # Calculate geographic coordinates
            rel_x = data_j / data_width
            rel_y = data_i / data_height
            
            lon = self.lon_min + rel_x * (self.lon_max - self.lon_min)
            lat = self.lat_max - rel_y * (self.lat_max - self.lat_min)  # Flip Y
            
            # Get data values
            basin_val = self.basin_data[data_i, data_j]
            mask_val = self.mask_data[data_i, data_j] if self.mask_data is not None else "N/A"
            
            return lat, lon, basin_val, mask_val
            
        except Exception as e:
            print(f"Error getting coordinates: {str(e)}", file=sys.stderr)
            return None, None, None, None
    
    def mousePressEvent(self, event):
        """Handle mouse press events"""
        if event.button() == Qt.LeftButton:
            self.click_start_pos = event.pos()
            self.last_pan_point = event.pos()
            self.panning = False
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for panning"""
        if event.buttons() & Qt.LeftButton and self.click_start_pos is not None:
            # Check if mouse has moved enough to start panning
            move_distance = (event.pos() - self.click_start_pos).manhattanLength()
            if move_distance > 5:  # 5 pixel threshold to distinguish click from drag
                if not self.panning:
                    self.panning = True
                    self.setCursor(Qt.ClosedHandCursor)
                
                # Calculate the delta for panning
                delta = event.pos() - self.last_pan_point
                self.last_pan_point = event.pos()
                
                # Emit pan delta to parent (scroll area will handle the actual panning)
                self.parent().parent().handle_pan_delta(delta)
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release - emit click signal with coordinate data or end panning"""
        if event.button() == Qt.LeftButton and self.click_start_pos is not None:
            if self.panning:
                # End panning
                self.panning = False
                self.setCursor(Qt.ArrowCursor)
            else:
                # This was a click, not a drag - emit coordinate data
                move_distance = (event.pos() - self.click_start_pos).manhattanLength()
                if move_distance <= 5:  # 5 pixel threshold
                    lat, lon, basin_val, mask_val = self.get_coordinates_at_position(event.pos())
                    if lat is not None and lon is not None:
                        self.clicked.emit(lat, lon, basin_val, mask_val)
            
            self.click_start_pos = None
        
        super().mouseReleaseEvent(event)


class BasinDisplayWindow(QDialog):
    """Qt-native basin display window with interactive features"""
    
    def __init__(self, basin_data, lats, lons, title="Basin Display", mask_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"🗺️ {title}")
        self.setModal(False)  # Allow interaction with main window
        self.resize(910, 585)  # Window made 30% bigger (700x450 * 1.3)
        
        # Set window icon and styling
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
            }
        """)
        
        self.basin_data = basin_data
        self.lats = lats
        self.lons = lons
        self.mask_data = mask_data  # Store mask data
        
        # Display controls
        self.show_ups = True  # Show UPS data overlay
        self.show_mask = True  # Show mask overlay
        
        # Add zoom and pan variables - removed duplicate variables
        
        # Set up the UI first
        self.setup_ui()
        
        # Enable key events
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Ensure initial display update after setup
        self.force_initial_display()
        
    def setup_ui(self):
        """Setup the user interface with PySide6 components"""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)
        
        # Title header
        title_text = self.windowTitle().replace('🗺️ ', '')
        title_label = QLabel(f"Basin Visualization: {title_text}")
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
                margin-bottom: 8px;
            }
        """)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        
        # Image display area with improved styling
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setMinimumSize(520, 390)  # 30% bigger (400x300 * 1.3)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #ffffff;
                border: 2px solid #dee2e6;
                border-radius: 8px;
                margin: 6px;
            }
            QScrollBar:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                width: 14px;
                border: 1px solid #dee2e6;
                border-radius: 7px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #3498db, stop:1 #2980b9);
                border-radius: 6px;
                min-height: 30px;
                margin: 1px;
            }
            QScrollBar::handle:vertical:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #5dade2, stop:1 #3498db);
            }
            QScrollBar:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                height: 14px;
                border: 1px solid #dee2e6;
                border-radius: 7px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #3498db, stop:1 #2980b9);
                border-radius: 6px;
                min-width: 30px;
                margin: 1px;
            }
            QScrollBar::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #5dade2, stop:1 #3498db);
            }
            QScrollBar::add-line, QScrollBar::sub-line {
                border: none;
                background: none;
            }
        """)
        
        # Create the custom basin image widget
        self.basin_widget = BasinImageWidget(self.basin_data, self.lats, self.lons, self.mask_data)
        self.basin_widget.setStyleSheet("""
            BasinImageWidget {
                background-color: white;
                border: 1px solid #e9ecef;
                margin: 2px;
            }
        """)
        
        # Connect basin widget click signal to our handler
        self.basin_widget.clicked.connect(self.on_basin_click)
        
        self.scroll_area.setWidget(self.basin_widget)
        
        main_layout.addWidget(self.scroll_area)
        
        # Status bar for coordinates and values - improved styling
        self.click_info_label = QLabel("Click on the image to see coordinates and values")
        self.click_info_label.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', Consolas, monospace;
                font-size: 12px;
                font-weight: 500;
                color: #2c3e50;
                padding: 12px 16px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border: 2px solid #dee2e6;
                border-radius: 8px;
                margin: 8px 0;
                min-height: 16px;
            }
        """)
        main_layout.addWidget(self.click_info_label)
        
        # Control buttons layout - moved below the screen with improved styling
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.setContentsMargins(8, 8, 8, 8)
        
        # Button style - light blue and smaller
        button_style = """
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
            QPushButton:checked:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #d3d3d3, stop:1 #a9a9a9);
            }
            QPushButton:disabled {
                background: #d3d3d3;
                color: #a9a9a9;
            }
        """
        
        # Show Mask toggle - converted to button with improved styling
        self.mask_button = QPushButton("Hide Mask")
        self.mask_button.setCheckable(True)
        self.mask_button.setChecked(True)
        self.mask_button.clicked.connect(self.toggle_mask)
        self.mask_button.setStyleSheet(button_style)
        
        if self.mask_data is None:
            self.mask_button.setEnabled(False)
            self.mask_button.setText("Mask (N/A)")
        
        button_layout.addWidget(self.mask_button)
        
        # Show UPS toggle - converted to button with improved styling  
        self.ups_button = QPushButton("Hide UPS")
        self.ups_button.setCheckable(True)
        self.ups_button.setChecked(True)
        self.ups_button.clicked.connect(self.toggle_ups)
        self.ups_button.setStyleSheet(button_style)
        button_layout.addWidget(self.ups_button)
        
        button_layout.addStretch()
        main_layout.addLayout(button_layout)
    
    def force_initial_display(self):
        """Force initial display update to ensure immediate visibility"""
        try:
            # Force widget to update immediately
            self.basin_widget.update()
            self.basin_widget.repaint()
            
            # Ensure button states match widget states
            self.mask_button.setChecked(self.basin_widget.show_mask)
            self.ups_button.setChecked(self.basin_widget.show_ups)
            
            # Update button text to match current states
            self.mask_button.setText("Hide Mask" if self.basin_widget.show_mask else "Show Mask")
            self.ups_button.setText("Hide UPS" if self.basin_widget.show_ups else "Show UPS")
            
            # Process any pending events to ensure display
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            
        except Exception as e:
            print(f"Error forcing initial display: {str(e)}", file=sys.stderr)
    
    
    def toggle_mask(self):
        """Toggle mask overlay"""
        self.show_mask = self.mask_button.isChecked()
        self.mask_button.setText("Hide Mask" if self.show_mask else "Show Mask")
        self.basin_widget.toggle_mask(self.show_mask)
        
        # Force immediate visual update
        self.basin_widget.repaint()
    
    def toggle_ups(self):
        """Toggle UPS data overlay"""
        self.show_ups = self.ups_button.isChecked()
        self.ups_button.setText("Hide UPS" if self.show_ups else "Show UPS")
        self.basin_widget.toggle_ups(self.show_ups)
        
        # Force immediate visual update
        self.basin_widget.repaint()
    
    def on_basin_click(self, lat, lon, basin_val, mask_val):
        """Handle click from basin widget - receives already processed coordinate data"""
        try:
            # Format basin value
            if basin_val is not None and np.isnan(basin_val):
                basin_str = "No Data"
            elif basin_val is not None:
                basin_str = f"{basin_val:.3f}"
            else:
                basin_str = "N/A"
            
            # Update info label with coordinates and values
            info_text = f"Lat: {lat:.4f}°, Lon: {lon:.4f}° | Basin: {basin_str} | Mask: {mask_val}"
            self.click_info_label.setText(info_text)
            
        except Exception as e:
            print(f"Error handling click: {str(e)}", file=sys.stderr)
            self.click_info_label.setText("Error getting coordinates")
    
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for toggles"""
        if event.key() == Qt.Key_M and self.mask_data is not None:
            self.mask_button.setChecked(not self.mask_button.isChecked())
            self.toggle_mask()
        elif event.key() == Qt.Key_U:
            self.ups_button.setChecked(not self.ups_button.isChecked())
            self.toggle_ups()
        elif event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
    
    def handle_pan_delta(self, delta):
        """Handle pan delta from basin widget"""
        # Get current scroll bar values
        h_scrollbar = self.scroll_area.horizontalScrollBar()
        v_scrollbar = self.scroll_area.verticalScrollBar()
        
        # Update scroll bar values (negative delta for natural panning)
        h_scrollbar.setValue(h_scrollbar.value() - delta.x())
        v_scrollbar.setValue(v_scrollbar.value() - delta.y())
    
    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel for zooming"""
        # Get the wheel delta
        delta = event.angleDelta().y()
        
        # Zoom the basin widget
        if hasattr(self, 'basin_widget') and self.basin_widget:
            current_size = self.basin_widget.size()
            
            if delta > 0:
                # Zoom in
                scale_factor = 1.25
            else:
                # Zoom out
                scale_factor = 0.8
                
            new_width = int(current_size.width() * scale_factor)
            new_height = int(current_size.height() * scale_factor)
            
            # Apply size limits
            min_width = max(50, self.basin_widget.base_width // 8)
            min_height = max(50, self.basin_widget.base_height // 8)
            max_width = self.basin_widget.base_width * 12
            max_height = self.basin_widget.base_height * 12
            
            new_width = max(min_width, min(new_width, max_width))
            new_height = max(min_height, min(new_height, max_height))
            
            self.basin_widget.resize(new_width, new_height)
            
        event.accept()
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press for panning and coordinate display"""
        if event.button() == Qt.LeftButton:
            self.panning = False  # Start assuming it's a click, not a drag
            self.last_pan_point = event.pos()
            self.click_start_pos = event.pos()  # Store the initial click position
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for panning"""
        if (event.buttons() & Qt.LeftButton) and hasattr(self, 'click_start_pos'):
            # Check if mouse has moved enough to start panning
            move_distance = (event.pos() - self.click_start_pos).manhattanLength()
            if move_distance > 5:  # 5 pixel threshold to distinguish click from drag
                if not self.panning:
                    self.panning = True
                    self.setCursor(Qt.PointingHandCursor)
                
                # Calculate the delta for panning
                delta = event.pos() - self.last_pan_point
                self.last_pan_point = event.pos()
                
                # Get current scroll bar values
                h_scrollbar = self.scroll_area.horizontalScrollBar()
                v_scrollbar = self.scroll_area.verticalScrollBar()
                
                # Update scroll bar values (negative delta for natural panning)
                h_scrollbar.setValue(h_scrollbar.value() - delta.x())
                v_scrollbar.setValue(v_scrollbar.value() - delta.y())
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release to end panning or show coordinates"""
        if event.button() == Qt.LeftButton and hasattr(self, 'click_start_pos'):
            if self.panning:
                # End panning
                self.panning = False
                self.setCursor(Qt.ArrowCursor)
            else:
                # Click handling is now done by the BasinImageWidget directly
                pass
            
            # Clean up
            if hasattr(self, 'click_start_pos'):
                delattr(self, 'click_start_pos')
        super().mouseReleaseEvent(event)
    
    def enterEvent(self, event):
        """Set cursor when entering the widget"""
        if not self.panning:
            self.setCursor(Qt.ArrowCursor)
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """Reset cursor when leaving the widget"""
        self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)
        
            
            
    def resizeEvent(self, event):
        """Handle window resize"""
        super().resizeEvent(event)
        # Could auto-fit on resize if desired


class BasinViewer:
    """Basin viewer class for loading NetCDF files with xarray"""
    
    def __init__(self, config_content=None):
        self.basin_data = None
        self.config_content = config_content
        self.display_window = None
        
    def _resolve_placeholders(self, path):
        """Resolve placeholders in path using configuration file content"""
        if not path or '$' not in path or not self.config_content:
            return path
            
        # Parse configuration content
        config = configparser.ConfigParser()
        config.read_string(self.config_content)

        # Find all placeholders in format $(section_key)
        for ii in range(10):
            placeholders = re.findall(r'\$\(([^)]+)\)', path)
            if not placeholders:
                break

            for placeholder in placeholders:
                # Split by colon to get section and key
                parts = placeholder.split(":")
                if len(parts) >= 2:
                    section_name = parts[0]
                    key_name = parts[1]

                    # Look for section and key in config
                    if config.has_section(section_name) and config.has_option(section_name, key_name):
                        value = config.get(section_name, key_name)
                        path = path.replace(f'$({placeholder})', value)
                    else:
                        print(f"Warning: Placeholder $({placeholder}) not found in config", file=sys.stderr)
                else:
                    # Try FILE_PATHS section if no colon
                    key_name = parts[0]
                    if config.has_section("FILE_PATHS") and config.has_option("FILE_PATHS", key_name):
                        value = config.get("FILE_PATHS", key_name)
                        path = path.replace(f'$({placeholder})', value)

        return path
    
    def _find_ups_path(self):
        """Find the ldd path from [TOPOP] section and replace filename with ups.nc"""
        if not self.config_content:
            return None
            
        try:
            config = configparser.ConfigParser()
            config.read_string(self.config_content)
            
            # Look for ldd in TOPOP section
            if config.has_section("TOPOP") and config.has_option("TOPOP", "ldd"):
                ldd_path = config.get("TOPOP", "ldd")
                
                # Replace the filename with ups.nc
                import os
                directory = os.path.dirname(ldd_path)
                ups_path = os.path.join(directory, "ups.nc")
                
                return ups_path
            else:
                print("Warning: ldd not found in [TOPOP] section", file=sys.stderr)
                return None
                
        except Exception as e:
            print(f"Error parsing configuration for ldd path: {str(e)}", file=sys.stderr)
            return None
    
    def _find_mask_path(self):
        """Find mask path from configuration"""
        if not self.config_content:
            return None
            
        try:
            config = configparser.ConfigParser()
            config.read_string(self.config_content)
            
            # Look for MaskMap in the configuration
            for section_name in config.sections():
                for key, value in config.items(section_name):
                    if key.lower() == 'maskmap':
                        return value
            return None
        except Exception as e:
            print(f"Error finding mask path: {str(e)}", file=sys.stderr)
            return None
    
    def _load_mask_data(self, mask_path, file_path):
        """Load mask data using the same method as mask_viewer.py"""
        try:
            
            coord = mask_path.split()
            if len(coord) < 2:
                # Resolve any placeholders in the path
                resolved_path = self._resolve_placeholders(mask_path)
                
                if not resolved_path or not resolved_path.strip():
                    print("No mask path specified", file=sys.stderr)
                    return None
                
                if not os.path.exists(resolved_path):
                    print(f"Mask file not found: {resolved_path}", file=sys.stderr)
                    return None
                
                # Load raster with rasterio
                with rasterio.open(resolved_path) as src:
                    # Read first band as 2D numpy array
                    mask = src.read(1)
                
                return np.where(mask != 1, 0, 1)
                
            else:
                # coordinate as two numbers - use cwatm method
                mask = run_cwatm.mainwarm(file_path, ["-vgm"], [])
                mask_data = mask[0].data
                mask_data = np.where(mask_data != 1, 0, 1)
                x = mask[1]
                y = mask[2]

                return mask_data,x,y
                
        except Exception as e:
            print(f"Error loading mask: {str(e)}", file=sys.stderr)
            return None
    
    def show_basin(self,settingsfile):
        """Load and display basin data from NetCDF file"""
        try:
            # Get ups path (derived from ldd path with filename replaced)
            ups_path = self._find_ups_path()
            if not ups_path:
                print("No ldd path found in configuration to derive ups path", file=sys.stderr)
                return
                
            
            # Resolve any placeholders in the path
            resolved_path = self._resolve_placeholders(ups_path)
            
            if not resolved_path or not resolved_path.strip():
                print("No ups path specified after resolution", file=sys.stderr)
                return
                
            if not os.path.exists(resolved_path):
                print(f"Basin file not found: {resolved_path}", file=sys.stderr)
                return
            
            # Load NetCDF file with xarray
            ds = xr.open_dataset(resolved_path)
            
            # Print dataset info for debugging
            
            # Try to find the main data variable (excluding coordinates)
            data_vars = [var for var in ds.data_vars.keys()]
            coord_vars = [var for var in ds.coords.keys()]
            
            
            # Get the first data variable as basin data
            if data_vars:
                var_name = data_vars[0]
                basin_data = ds[var_name]
            else:
                # Fallback to first variable that's not a coordinate
                all_vars = list(ds.variables.keys())
                data_var = None
                for var in all_vars:
                    if var not in coord_vars and len(ds[var].dims) >= 2:
                        data_var = var
                        break
                
                if data_var:
                    basin_data = ds[data_var]
                else:
                    print("No suitable data variable found in NetCDF file", file=sys.stderr)
                    return
            
            # Get latitude and longitude coordinates
            lat_var = None
            lon_var = None
            
            # Common names for latitude and longitude
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
            
            if lat_var is None or lon_var is None:
                # Try to use the dimensions directly
                dims = list(basin_data.dims)
                if len(dims) >= 2:
                    # Assume last two dimensions are lat, lon or y, x
                    if len(dims) == 2:
                        lat_var, lon_var = dims[0], dims[1]
                    else:
                        lat_var, lon_var = dims[-2], dims[-1]
                else:
                    print("Cannot determine coordinate system", file=sys.stderr)
                    return
            
            # Extract coordinate arrays
            lats = ds[lat_var].values
            lons = ds[lon_var].values
            
            # Handle squeeze for single time step or level
            if basin_data.ndim > 2:
                # Take first time step or level if data has extra dimensions
                basin_data = basin_data.isel({dim: 0 for dim in basin_data.dims if dim not in [lat_var, lon_var]})
            
            basin_array = basin_data.values
            
            
            # Close the dataset
            ds.close()
            
            # Load mask data
            mask_path = self._find_mask_path()
            mask_data = None

            coord = mask_path.split()
            if len(coord) < 2:

                # Resolve any placeholders in the path
                resolved_path = self._resolve_placeholders(mask_path)
                print(f"Resolved path: {resolved_path}")

                if not resolved_path or not resolved_path.strip():
                    print("No mask path specified", file=sys.stderr)
                    return

                if not os.path.exists(resolved_path):
                    print(f"Mask file not found: {resolved_path}", file=sys.stderr)
                    return

                # Load ras
                with rasterio.open(resolved_path) as src:
                    # Read first band as 2D numpy array
                    mask = src.read(1)

                print(f"Mask loaded successfully: {resolved_path}")
                print(f"Array shape: {mask.shape}")
                mask_data = np.where(mask > 1, 0, 1)

            else:
                mask_result = self._load_mask_data(mask_path, settingsfile)
                if mask_result is not None:
                    if isinstance(mask_result, tuple) and len(mask_result) == 3:
                        # Got mask_data, x, y coordinates
                        mask_data, x, y = mask_result
                        # Check if mask dimensions match basin data
                        if mask_data.shape != basin_array.shape:
                            maskbig = np.zeros(basin_array.shape)
                            maskbig[x:x + mask_data.shape[0], y:y + mask_data.shape[1]] = mask_data
                            mask_data = maskbig
                    else:
                        # Got just mask_data
                        mask_data = mask_result


            
            # Create and show display window
            self.display_window = BasinDisplayWindow(
                basin_array, lats, lons, 
                f"Basin: {os.path.basename(resolved_path)}",
                mask_data=mask_data
            )
            self.display_window.show()
            
        except Exception as e:
            print(f"Error loading basin data: {str(e)}", file=sys.stderr)
            import traceback
            traceback.print_exc()