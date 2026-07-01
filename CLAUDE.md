# CWatM GUI Application

## Overview
This is a graphical user interface for the Community Water Model (CWatM) developed by IIASA. The application allows users to load, parse, edit, and manage CWatM configuration files with an intuitive GUI.

## Menu Bar & Keyboard Shortcuts (current UI)

The GUI is now **menu-driven**. A banner (CWatM icon, title, the centered text
"The Community Water Model User Interface", and the IIASA logo) sits at the very
top, with the menu bar directly **below the banner**. Most former side buttons were
removed from view and their actions live in menus.

Menu bar (left → right): **File · Settings · Tools · RUN CWATM · Configure · Info**

| Menu | Item | Shortcut | Action |
|------|------|----------|--------|
| File | Load .ini | Ctrl+O | Load a settings file (was the "Load Text" button) |
| File | Reload | Ctrl+L | Reload the current file from disk (prompts if there are unsaved changes) |
| File | Save .ini | Ctrl+S | Save to current file |
| File | Save As | Ctrl+Alt+S | Save to a new file |
| File | Exit | — | Quit (prompts Save/Discard/Cancel if there are unsaved changes) |
| Settings | Fold All | Alt+0 | Collapse all sections (was "Compress All") |
| Settings | Unfold All | Alt+Shift+0 | Expand all sections (was "Expand All") |
| Settings | Top | Alt+T | Jump to start of file |
| Settings | Down | Alt+D | Jump to end of file |
| Settings | Find | F5 | Prompt for text and find it in the editor |
| Settings | Find next | Ctrl+F | Repeat the last Find (wraps around) |
| Settings | Undo | Ctrl+Z | Undo editor change |
| Settings | Redo | Ctrl+Y | Redo editor change |
| Tools | Change Options | — | Open the Options window (tooltip: "Display a popup with the settingsfile [Options]") |
| Tools | Show Basin | — | Open the basin viewer |
| Tools | Set Gauge | — | Set Gauges to the largest-upstream point inside the mask (tooltip: "Find the point with the largest upstream area in Mask Map") |
| Tools | Add output Watercycle | — | Insert `OUT_TSS_AreaSum_Daily = WaterCycle` under `[OUTPUT]` if absent (tooltip: "Adds an additional output for creating watercycles") |
| Tools | Check Data | — | Open the Check Data window |
| Tools | Create PathOut Folder | — | Create the resolved PathOut directory if missing |
| RUN CWATM | Run CWATM | Ctrl+R | Run / stop the CWatM model |
| Configure | Set output box file | — | Choose a custom output-box log file (kept in memory) |
| Configure | Write output box | — | Checkable; writes the run log (tooltip shows the current output path) |
| Info | About CWatM | — | About dialog |

### Behavioral notes
- **Auto-apply of field changes**: changing Start/Spin/End Date, PathOut, or MaskMap
  updates the in-memory settings content (and the editor view) automatically after a
  ~500 ms debounce — **without saving to disk**. Save / Run flush any pending change
  first. The old **Actualize** action was removed (it had also saved to disk).
- **Unsaved-changes indicator**: the **Save** and **Save As** buttons turn light blue
  when there are unsaved edits (editor text or field changes) and return to normal
  after a save or load. The same dirty state drives the Exit prompt.
- **Output box**: the CWatM output area is left-aligned with the progress clock
  centred/left **below** it (no longer beside it). Its text is selectable and
  copyable (Ctrl+C, or right-click → "Copy all output").
- **Live progress line**: per-timestep "date + discharge" output (printed by CWatM
  with a leading `\r`) overwrites a single line in place instead of accumulating,
  mirroring the console.
- **Taskbar icon**: the app sets a Windows AppUserModelID and `assets/cwatm.ico` so
  the taskbar shows the CWatM icon (see `cwatm_gui.py`).
- The former side buttons (Load Text, Actualize, Options, Show Basin, Check Data) and
  the "Write output" checkbox are hidden/removed; their objects may remain in code
  for state styling, but the actions are reached through the menus above.

### Gauges, mask and PathOut checks
- **Gauges field**: under MaskMap (see `create_gauges_controls`), linked to the
  settings `Gauges` entry; auto-applies like the other fields.
- **Gauge-in-mask check** (`basin_viewer.py`: `build_mask_context`, `gauges_inside`):
  works for a **file-based** MaskMap (raster) *and* a **coordinate-based** MaskMap (a
  basin is generated via CWatM's mask routine / `mainwarm -vgm`). The built mask is
  cached in memory (`self._mask_context`) and only rebuilt on **load** or when the
  **MaskMap changes and is saved** (`_rebuild_mask_cache`). The Gauges field text is
  coloured **blue** if all gauges are inside the basin, **red** if any is outside.
- **Warning label** to the right of RUN CWATM shows problems in red:
  - "Gauge is not inside the basin! Change manually or use Tools/Set Gauge."
  - "PathOut does not exists! You can use Tools/Create PathOut Folder."
  The gauge check runs on load/save and after gauge edits; the **PathOut** check
  (`basin_viewer.pathout_exists`, placeholders resolved) runs only on load/save.
- **Set Gauge** (`find_largest_ups_gauge`): sets Gauges to the cell centre with the
  largest upstream area (from ups.nc) that is inside the mask, formatted to 4 decimals.
- **Create PathOut Folder**: `os.makedirs` of the resolved PathOut, then clears the
  warning.

### Output-box log file (Configure menu)
- Default location is `<PathOut>/cwatm_out.txt` (placeholders resolved); **Set output
  box file** overrides it with a custom path kept in memory. The **Write output box**
  tooltip shows the current effective path.
- The file is **appended**, not overwritten. Each run is delimited by a header written
  straight to the file (not shown in the box): a `====` line, the date/time, a `----`
  line; and a blank line is written after the run's content
  (`_finalize_output_file`).

## Features

### File Management
- **Load Configuration Files**: Load INI files with preselected .ini file filter
- **Save Files**: Save changes to the same file or save as a new file - automatically expands all sections and saves without [-] or [+] indicators
- **Auto-apply (no save)**: changing Start/Spin/End Date, PathOut, or MaskMap updates the settings content in memory automatically (debounced ~500 ms); writing to disk only happens on Save / Save As
- **Section Management** (Settings menu):
  - **Fold All** (Alt+0): collapse all sections in the display for easier navigation
  - **Unfold All** (Alt+Shift+0): expand all sections for full content view
- **Navigation Controls** (Settings menu):
  - **Top** (Alt+T): Jump to the beginning of the file
  - **Down** (Alt+D): Jump to the bottom of the file
  - **Find** (F5) / **Find next** (Ctrl+F): search text in the editor
  - **Undo** (Ctrl+Z) / **Redo** (Ctrl+Y)

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
- **Integer SpinUp/StepEnd**: if SpinUp or StepEnd is given as an integer N (a timestep
  count) instead of a date, the field is computed as StepStart + (N-1) days, matching
  CWatM's `datetoInt` convention (StepStart = timestep 1). See `date_manager.py`.
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
- **Real-time Updates**: Changes to checkboxes immediately update the configuration content and mark the document as having unsaved changes (Save / Save As turn light blue)
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
- **Modal Dialog Behavior**: 
  - Opens as modal dialog using `exec()` method
  - Does not show separate taskbar icon
  - Includes minimize/maximize/close buttons
  - Properly tied to parent window
- **Settings Restoration**: Extract and restore configuration settings from NetCDF discharge files
  - **Restore Settings Button**: "Restore settings from discharge map" button located below NetCDF file selection
  - **Conditional Activation**: Button only enabled when a discharge NetCDF file is selected
  - **Automatic Extraction**: Reads 'version_settingsfile' global attribute from NetCDF files
  - **Predefined Output**: Saves extracted settings as "settings_restore_dischargenc.ini" in ASCII UTF-8 format
  - **NetCDF4 Integration**: Requires NetCDF4 library for reading global attributes from discharge maps

## Usage

### Basic Workflow
1. **Load a Configuration File**: **File ▸ Load .ini** (Ctrl+O) - automatic parsing begins immediately
2. **Navigate and Edit**: Use Settings ▸ Fold/Unfold/Top/Down/Find and the [-]/[+] controls to browse the parsed file
3. **Adjust Dates/Settings**: Modify Start Date, Spin Date, End Date, PathOut, or MaskMap - changes auto-apply to the content (in memory, not saved); Save / Save As turn blue
4. **Manage Options**: **Tools ▸ Change Options** to configure boolean settings from the [Options] section
5. **Save**: **File ▸ Save .ini** (Ctrl+S) or **Save As** (Ctrl+Alt+S) to write changes to disk
6. **Run CWatM Model**: **RUN CWATM ▸ Run CWATM** (Ctrl+R) to execute the model (note: it runs the file on disk, so Save first)
7. **Monitor Progress**: Watch the progress clock (below the output box) and real-time output in the cwatminfo area
8. **Stop if Needed**: Run CWATM (Ctrl+R) again to interrupt the model run
9. **Check Data (Optional)**: **Tools ▸ Check Data** to validate configuration files before running
10. **Exit**: **File ▸ Exit** prompts to save if there are unsaved changes

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
- **`src/gui/widgets/check_data_window.py`**: Data validation window for CWatM configuration checking
- **`src/gui/widgets/basin_viewer.py`**: Basin data visualization with NetCDF support
- **`src/gui/utils/progress_clock.py`**: Circular progress indicator for CWatM execution
- **`src/gui/utils/cwatm_worker.py`**: Threaded CWatM execution worker

### Module Dependencies
```
cwatm_gui.py
    └── src/gui/components/main_window.py
            ├── src/gui/components/config_parser.py
            ├── src/gui/managers/date_manager.py
            ├── src/gui/managers/file_manager.py
            ├── src/gui/managers/text_display.py
            ├── src/gui/widgets/options_window.py
            ├── src/gui/widgets/check_data_window.py
            ├── src/gui/widgets/basin_viewer.py
            ├── src/gui/utils/progress_clock.py
            └── src/gui/utils/cwatm_worker.py
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

### Virtual environment & building the executable
- The project venv is **`venv/`** (run with `venv\Scripts\python.exe`; activate via `venv\Scripts\Activate.ps1`). An older `build_env/` was a copied venv and is deprecated.
- PyInstaller specs: **`cwatm_gui_dir.spec`** (one-folder, recommended) and **`cwatm_gui.spec`**. They collect rasterio + xarray submodules/data and `copy_metadata('xarray')`, bundle `cwatm`/`src`/`assets`, and set `console=False`.
- Build: `python -m PyInstaller cwatm_gui_dir.spec --noconfirm` (UPX disabled for faster builds).
- Reference docs in this folder: **`cwtmexe.md`** (rasterio/xarray/GDAL packaging fixes), **`makeitfaster.md`** (PyInstaller speed), **`nuitka_plan.md`** (optional Nuitka build for faster runtime).

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

### Top
- **Banner**: CWatM icon + "CWatM GUI" title, centered "The Community Water Model User Interface", IIASA logo
- **Menu bar** (below the banner): File · Settings · Tools · RUN CWATM · Configure · Info (see the Menu Bar section above)

### Control Panel (Left Side)
- "Loaded: …" filename label (left-aligned, slightly larger font)
- Date input fields with validation (Start Date, Spin Date, End Date)
- PathOut and MaskMap input fields (changes auto-apply to content in memory)
- **CWatM Output Area**: left-aligned scrollable display (taller box; max width capped at the End Date field), text selectable/copyable
- **Progress Clock**: centred/left **below** the output box

### Display Panel (Right Side)
Button toolbar (left to right):
- **Save** / **Save As**: save clean content (turn light blue when there are unsaved changes)
- **Fold All** / **Unfold All**: collapse / expand all sections
- **Top** / **Down**: jump to file beginning / end

(Removed from view: Load Text, Actualize, Options, Show Basin, Check Data buttons and the
"Write output" checkbox — their actions are in the menus.)

### Text Display Area
- Syntax-highlighted configuration content
- Interactive section headers with [-]/[+] controls
- Click-to-toggle expand/collapse functionality
- Preserved whitespace and formatting
- **Optimized Width**: Right panel reduced by 20% to provide more space for control panel

## Workflow Guidance System

### Dynamic Button Coloring
The GUI provides visual guidance through color-coded buttons:

1. **Save / Save As**: turn light blue whenever there are unsaved changes (editor edits or field changes); return to normal after a save or load
2. **RUN CWATM ▸ Run CWATM**: runs the model; selecting it again while running stops it

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
- **Modal Dialog Behavior**: 
  - Opens as modal dialog using `exec()` method
  - Does not show separate taskbar icon
  - Includes minimize/maximize/close buttons
  - Properly tied to parent window

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