# CWatM GUI Application

## Overview
This is a graphical user interface for the Community Water Model (CWatM) developed by IIASA. The application allows users to load, parse, edit, and manage CWatM configuration files with an intuitive GUI.

## Features

### File Management
- **Load Configuration Files**: Load INI files with preselected .ini file filter
- **Save Files**: Save changes to the same file or save as a new file - automatically expands all sections and saves without [-] or [+] indicators
- **Auto-save**: Automatic saving when running configuration updates
- **Section Management**: 
  - **Compress All**: Button to collapse all sections in the display for easier navigation
  - **Expand All**: Button to expand all sections for full content view
- **Navigation Controls**:
  - **Top**: Jump to the beginning of the file
  - **Down**: Jump to the bottom of the file

### Configuration Parsing
- **Automatic Parsing**: Parse INI configuration files automatically upon loading with syntax highlighting and interactive expand/collapse functionality
- **Visual Formatting**: 
  - Comments (lines starting with #) displayed in dark gray
  - True values displayed in blue (not bold)
  - False values displayed in red (not bold)
  - Section headers displayed in bold with expand/collapse controls
- **Interactive Sections**:
  - Click [-] next to section headers to collapse content
  - Click [+] next to collapsed sections to expand content
  - All sections expand by default when parsing
- **Whitespace Preservation**: Maintains original file formatting and spacing

### Date Management
- **Three Date Fields**: 
  - Start Date (StepStart)
  - Spin Date (SpinUp) 
  - End Date (StepEnd)
- **Automatic Validation**: Ensures chronological order (start ≤ spin ≤ end)
- **Flexible Date Formats**: Supports multiple date formats including single-digit days/months
- **Auto-population**: Dates automatically extracted from configuration files when parsing

### Smart Run Functionality
- **Change Detection**: Only updates and saves files when dates have actually changed
- **Clean Saving**: Always saves with original content (no [-]/[+] indicators) and expands all sections before saving
- **Manual Change Preservation**: Preserves all user edits even when sections are compressed/expanded
- **Automatic Re-parsing**: Re-parses and reformats file after updates without overwriting status messages
- **Enhanced Status Messages**: "Save" shows "File saved", "Save As" shows "File saved: path"
- **Navigation**: Automatically jumps to StepStart parameter after saving changes
- **Scroll Position Memory**: Maintains scroll position and cursor location across save operations

### Options Management
- **Options Window**: Dedicated window for managing boolean configuration settings
- **Automatic Detection**: Automatically finds and parses all boolean options from the [Options] section
- **Visual Interface**: Clean, modern interface with styled checkboxes and organized layout
- **Real-time Updates**: Changes to checkboxes immediately update the configuration content and color the Actualize button light blue
- **Immediate Configuration Updates**: No Apply/Cancel buttons - changes take effect instantly
- **Professional Styling**: CWatM-branded blue color scheme with hover effects and modern UI elements
- **Smart Parsing**: Recognizes True/False values (case insensitive) and presents them as checkboxes
- **Format Preservation**: Maintains original file formatting and indentation when updating values
- **Empty Section Handling**: Displays informative message when no boolean options are found
- **Auto Section Expansion**: Automatically expands relevant sections ([OPTIONS], [FILE_PATHS], [MASK_OUTLET], [TIME-RELATED_CONSTANTS]) when options window is opened

### CWatM Model Execution
- **Integrated Model Runs**: Execute CWatM model directly from the GUI without external command line calls
- **Real-time Output Display**: All print statements and messages are captured and displayed immediately in the cwatminfo area
- **Instant Updates**: The cwatminfo display updates immediately after each print command for real-time feedback
- **Scrollable Output**: Enhanced cwatminfo area with expanded dimensions (225-450px height, 1080px max width) for comprehensive output display
- **Smart Scrolling**: Auto-scrolls to show latest output only if user was already viewing the bottom
- **Complete Logging**: All GUI output, model messages, errors, and status information are captured and displayed to the user
- **Error Message Highlighting**: Error messages and exceptions displayed in dark red for easy identification
- **Clean Output Filtering**: Internal "Worker:" debug messages are filtered out from display for cleaner user experience
- **Enhanced Font Readability**: cwatminfo display uses 11px monospace font for better readability
- **Threaded Execution**: CWatM runs in separate thread to prevent GUI freezing
- **Stop/Start Control**: Ability to interrupt and stop CWatM execution mid-run
- **Progress Tracking**: Real-time progress clock showing simulation advancement based on actual model dates
- **File Cleanup**: Automatic cleanup of open netCDF files and file handles when execution is stopped

### Data Validation and Checking
- **Check Data Window**: Dedicated window for validating CWatM configuration files
- **Configuration Analysis**: Runs CWatM in check mode (-c flag) to analyze data without full execution
- **NetCDF Comparison**: Optional comparison against existing discharge NetCDF files
- **CSV Output**: Results saved to CSV format for further analysis
- **Real-time Results Display**: Interactive table showing check results with sortable columns
- **Error Detection**: Identifies configuration issues, missing files, and data inconsistencies
- **Streamlined Interface**: Simple workflow without checkbox complications - output file always enabled
- **NetCDF Integration**: Automatically passes NetCDF filename to CWatM when comparison file is selected
- **Settings Restoration**: Extract and restore configuration settings from NetCDF discharge files
  - **Restore Settings Button**: "Restore settings from discharge map" button located below NetCDF file selection
  - **Conditional Activation**: Button only enabled when a discharge NetCDF file is selected
  - **Automatic Extraction**: Reads 'version_settingsfile' global attribute from NetCDF files
  - **Predefined Output**: Saves extracted settings as "settings_restore_dischargenc.ini" in ASCII UTF-8 format
  - **NetCDF4 Integration**: Requires NetCDF4 library for reading global attributes from discharge maps

## Usage

### Basic Workflow
1. **Load a Configuration File**: Click "Load Text" (light blue) to select a .ini configuration file - automatic parsing begins immediately
2. **Navigate and Edit**: Use expand/collapse controls and navigation buttons to browse the parsed file with syntax highlighting
3. **Adjust Dates/Settings**: Modify the Start Date, Spin Date, End Date, PathOut, or MaskMap as needed
4. **Manage Options**: Click "Options" button to configure boolean settings from the [Options] section
5. **Actualize Changes**: Click "Actualize" (becomes light blue when changes are detected) to update and save the file
6. **Run CWatM Model**: Click "RUN CWatM" (becomes blue after successful parsing) to execute the CWatM model
7. **Monitor Progress**: Watch the progress clock and real-time output in the cwatminfo area
8. **Stop if Needed**: Click "STOP CWatM" (button turns light red during execution) to interrupt the model run
9. **Check Data (Optional)**: Use "Check Data" functionality to validate configuration files before running

### Data Validation Workflow
1. **Open Check Data Window**: Access data validation functionality from the main interface
2. **Select Output File**: Choose where to save check results (CSV format)
3. **Optional NetCDF Comparison**: Select discharge NetCDF file for comparison analysis
4. **Restore Settings (Optional)**: Use "Restore settings from discharge map" to extract configuration from NetCDF files
5. **Run Check**: Execute CWatM in check mode to analyze configuration without full run
6. **Review Results**: View detailed results table with file paths, parameters, and validation status

### Advanced Features
- **Section Management**: Use "Compress All" to collapse all sections or "Expand All" to show full content
- **Quick Navigation**: Use "Top" and "Down" buttons to jump to beginning or end of file
- **Interactive Editing**: Click [-] or [+] next to section headers to toggle visibility
- **Save Options**: Use "Save" for current file or "Save As" for new file (both save clean content without visual indicators)

## Architecture

The application is now structured with a modular architecture for better maintainability:

### Core Modules

- **`cwatm_gui.py`**: Main entry point and application launcher with global exception handling
- **`src/gui/components/main_window.py`**: Main window class orchestrating all components
- **`src/gui/components/config_parser.py`**: Configuration file parsing and formatting logic
- **`src/gui/managers/date_manager.py`**: Date input validation and management
- **`src/gui/managers/file_manager.py`**: File I/O operations and management
- **`src/gui/managers/text_display.py`**: Text area operations and cursor management
- **`src/gui/widgets/options_window.py`**: Options management window for boolean configurations
- **`src/gui/widgets/progress_clock.py`**: Circular progress indicator for CWatM execution
- **`src/gui/utils/cwatm_worker.py`**: Threaded CWatM execution worker
- **`src/gui/utils/basin_viewer.py`**: Basin data visualization with NetCDF support
- **`src/gui/widgets/check_data_window.py`**: Data validation window for CWatM configuration checking

### Module Dependencies
```
cwatm_gui.py
    └── src/gui/components/main_window.py
            ├── src/gui/components/config_parser.py
            ├── src/gui/managers/date_manager.py
            ├── src/gui/managers/file_manager.py
            ├── src/gui/managers/text_display.py
            ├── src/gui/widgets/options_window.py
            ├── src/gui/widgets/progress_clock.py
            ├── src/gui/widgets/check_data_window.py
            ├── src/gui/utils/cwatm_worker.py
            └── src/gui/utils/basin_viewer.py
```

### Benefits of New Structure
- **Separation of Concerns**: Each module handles a specific responsibility
- **Maintainability**: Easier to modify and extend individual components
- **Testability**: Components can be tested independently
- **Reusability**: Modules can be reused in other applications
- **Readability**: Clear organization makes code easier to understand

### CWatM Integration
- **Direct CWatM Execution**: GUI can run CWatM model configurations directly using the underlying CWatM model through `run_cwatm.py`
- **Model Status Display**: Shows CWatM execution information including version, IIASA attribution, and platform details
- **Print Redirection System**: Custom `PrintRedirector` class captures all stdout and redirects to cwatminfo display
- **Immediate Output Updates**: All print statements from CWatM and GUI components appear instantly in the cwatminfo area

## Technical Details

### Requirements
- Python 3.8+
- PySide6
- Qt framework components
- CWatM model components (for running configurations)
- NumPy (for data processing)
- xarray (for NetCDF data handling in basin viewer)
- rasterio (for mask data visualization)
- configparser (for INI file processing)
- netCDF4 (for reading NetCDF global attributes in settings restoration)

### Key Components
- **CWatMMainWindow**: Main application window with split-panel layout
- **ConfigParser**: Handles INI file parsing, validation, and formatting
- **DateManager**: Manages date input widgets and validation
- **FileManager**: Handles all file operations (load, save, save as)
- **TextDisplayManager**: Manages text display area and cursor operations
- **PrintRedirector**: Custom stdout redirector for real-time output capture in cwatm_gui.py
- **OptionsWindow**: Dedicated window for managing boolean configuration options
- **ProgressClock**: Circular progress indicator showing CWatM execution progress
- **CWatMWorker**: Threaded worker for non-blocking CWatM model execution
- **BasinViewer**: Advanced NetCDF basin data visualization with coordinate display
- **CheckDataWindow**: Data validation window for checking CWatM configuration files with NetCDF comparison
- **CWatM Integration**: Direct access to CWatM model execution through `cwatm.run_cwatm`

### File Formats Supported
- INI configuration files (.ini)
- Text files (.txt)
- NetCDF files (.nc) for data validation and comparison
- CSV files (.csv) for check results output
- All file types (*)

## Installation
```bash
pip install PySide6
python cwatm_gui.py
```

The application starts in maximized window mode for optimal viewing of configuration files.

## Development Notes
- Built with PySide6 for cross-platform compatibility
- Uses HTML formatting in QTextEdit for syntax highlighting and interactive controls
- Implements real-time date validation with signal connections
- Preserves original file formatting while providing visual enhancements
- Custom event filtering for interactive expand/collapse functionality
- Clean separation between display formatting and file content
- Modular architecture allows for easy extension and maintenance
- Each component is designed to be testable and reusable
- **Dynamic Button Styling**: Intelligent workflow guidance through color-coded buttons
- **Real-time Print Capture**: Custom stdout redirection system for immediate output display
- **Global Exception Handling**: Comprehensive error handling prevents application crashes
- **Thread Safety**: All CWatM operations run in separate threads with proper signal handling
- **Resource Management**: Automatic cleanup of file handles and NetCDF datasets
- **Native Qt Graphics**: Custom drawing routines for high-performance data visualization

## User Interface Layout

### Control Panel (Left Side)
- Interface description
- **Load Text** button (light blue) for file loading with filename display and automatic parsing
- Date input fields with validation (Start Date, Spin Date, End Date)
- PathOut and MaskMap input fields
- **Actualize** button (becomes light blue when changes detected) for saving updates
- **Options** button (150x50px) for managing boolean configuration options
- **RUN CWatM** button (becomes blue after successful parsing) for model execution
- **CWatM Output Area**: Scrollable display (225-450px height, 1080px max width) showing real-time execution output

### Display Panel (Right Side)
Button toolbar (left to right):
- **Save**: Save current file with clean content
- **Save As**: Save to new file with clean content  
- **Compress All**: Collapse all sections
- **Expand All**: Expand all sections
- **Top**: Jump to file beginning
- **Down**: Jump to file end

### Text Display Area
- Syntax-highlighted configuration content
- Interactive section headers with [-]/[+] controls
- Click-to-toggle expand/collapse functionality
- Preserved whitespace and formatting

## Workflow Guidance System

### Dynamic Button Coloring
The GUI provides intelligent visual guidance through the workflow with color-coded buttons:

1. **Load Text**: Always displayed in light blue to indicate the starting point - automatically parses upon successful load
2. **Actualize**: Becomes light blue only when changes are detected in dates, PathOut, or MaskMap fields
3. **Options**: Standard button styling for accessing configuration options window
4. **RUN CWatM**: Becomes blue after successful parsing, indicating the model is ready to execute
5. **STOP CWatM**: Button turns light red during execution, indicating it can be clicked to stop the model

### Change Detection
- **Date Fields**: Monitors Start Date, Spin Date, and End Date for changes
- **Path Fields**: Monitors PathOut and MaskMap text fields for modifications
- **Options Changes**: Monitors boolean option changes in the Options window
- **Smart Reset**: Actualize button color resets after successful use or after automatic parsing (no auto-coloring)
- **Real-time Updates**: Button colors update immediately when changes are detected

### User Experience Benefits
- **Clear Next Steps**: Users always know which action is available next
- **Change Awareness**: Obvious indication when there are unsaved changes
- **Workflow Progression**: Visual confirmation of completed steps
- **Error Prevention**: Reduces confusion about workflow sequence
- **Execution Control**: Easy to start and stop model runs with visual feedback
- **Progress Monitoring**: Real-time progress tracking and output display

## Enhanced Execution Features

### Real-time Progress Tracking
- **Dynamic Progress Clock**: Circular 240x240px progress indicator showing actual simulation progress based on model dates (start, current, end)
- **Percentage Calculation**: `progress = (current_day - start_day + 1) / (total_days) * 100`
- **Live Updates**: Progress clock updates during each model timestep via output.py integration
- **Visual Design**: Clean minimalist circular arc with light gray background circle showing total progress path
- **Brand Consistency**: Uses CWatM blue color (#0066CC) matching the application title
- **Safe Bounds**: Progress values clamped to 0-100% range with error handling

### Advanced Error Handling
- **Color-coded Messages**: 
  - Normal output in black text
  - Error messages and exceptions in dark red
  - Status messages in default color
- **Comprehensive Exception Capture**:
  - Global exception handler catches unhandled errors
  - Local try-catch blocks in critical operations
  - Thread-safe error reporting via Qt signals
- **Rich Text Display**: HTML formatting enables colored text in cwatminfo area

### Execution Control System
- **Threaded Architecture**: 
  - CWatMWorker class runs model in separate QThread
  - GUI remains responsive during long-running simulations
  - Signal-based communication between threads
- **Interrupt Capability**:
  - Cooperative stop mechanism with `should_stop` flag
  - Graceful shutdown with 3-second timeout
  - Force termination fallback if needed
- **Resource Cleanup**:
  - Automatic closure of netCDF4.Dataset objects
  - General file handle cleanup (io.IOBase types)
  - Garbage collection to free unreferenced objects
  - Multi-layer cleanup (immediate, thread-level, error recovery, shutdown)

### File Operation Safety
- **NetCDF File Management**:
  - Detects and closes open netCDF4 datasets
  - Prevents file locks and resource leaks
  - Thread-safe cleanup operations
- **General File Handles**:
  - Closes all io.IOBase file objects
  - Handles TextIOBase, BufferedIOBase, RawIOBase
  - Safe error handling for cleanup operations
- **Integration Points**:
  - Cleanup on execution stop
  - Cleanup on errors and exceptions
  - Cleanup on application shutdown
  - Worker thread cleanup before termination

### Technical Implementation
- **Worker Thread Signals**:
  - `finished(bool, object)`: Completion status and results
  - `error(str)`: Error message reporting
  - `progress(int)`: Progress value 0-100
- **Button State Management**:
  - Ready state: Blue "RUN CWatM" button
  - Running state: Light red "STOP CWatM" button
  - Automatic state transitions and cleanup
- **Progress Integration**: 
  - CWatM output.py modified to calculate and report progress to clock widget
  - Uses `dateVar['intStart']`, `dateVar['intEnd']`, `dateVar['curr']` for accuracy
  - Thread-safe progress updates via Qt signal system

## Data Visualization Features

### Basin Viewer
- **Advanced NetCDF Visualization**: Comprehensive basin data display with native Qt rendering
- **Interactive Features**:
  - Mouse wheel and button zoom controls
  - Click and drag panning with coordinate tracking
  - UPS data visualization with viridis-like colormap
  - Semi-transparent mask overlay in green
- **Coordinate System**: Real-world coordinate display on click with lat/lon values
- **Performance**: Native Qt painting (no matplotlib dependency) for fast rendering
- **Data Integration**: Automatic coordinate calculations and basin value extraction

## User Interface Layout Updates

### Enhanced Control Panel (Left Side)
- **Expanded CWatM Output Area**: 
  - Height: 225-450px (50% increase from original)
  - Width: 1080px (170% increase from original for comprehensive output display)
  - Real-time scrolling with rich text formatting for error highlighting
- **Progress Clock**: 
  - Positioned to the right of cwatminfo area
  - 240x240px circular progress indicator
  - Minimalist design with blue progress arc on light gray background
  - Percentage display in matching blue color
- **Show Basin Button**: Quick access button for launching basin visualization tool

### Progress Clock Features
- **Visual Elements**:
  - Light gray background circle showing 100% progress path
  - Blue progress arc (#0066CC) showing current completion
  - Blue percentage text matching application branding
  - No border, ticks, or center dot for clean appearance
- **Interactive Behavior**:
  - Updates in real-time during CWatM execution
  - Resets to 0% when starting new runs
  - Maintains state during stop/start operations