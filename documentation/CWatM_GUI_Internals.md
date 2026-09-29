# CWatM GUI — Internals (secondary windows & data-visualization deep dives)

> Companion to the root **`CLAUDE.md`** (the concise developer reference). This file
> holds the **per-feature internals** for the secondary windows and the
> **data-visualization** viewers — the deep detail that CLAUDE.md links to but does not
> inline, to keep the always-loaded reference lean. The invariants that must not be
> broken (fast-startup / lazy-import rule, theme-token rule, subprocess run model,
> menu bar, architecture, build) stay in `CLAUDE.md`.

## Secondary-window internals

### Excel workbook editor (Tools ▸ Excel Crops/Reservoirs)
**Tools ▸ Excel Crops/Reservoirs** — in the *Setup & Data* section, directly below
*Change Options* (it used to be a top-level **Excel** menu with this as its only item;
that menu is gone, the action and `_excel_actions`/`_update_excel_menu_enabled` moved
into Tools unchanged) — (`main_window.open_excel_workbook()`) resolves the settings
`Excel_settings_file`
value (placeholders via `_resolve_settings_placeholders`, made absolute against the
settings-file dir) and opens **the whole workbook** in `ExcelSheetWindow`
(`src/gui/widgets/excel_sheet_window.py`). There is no per-sheet menu item any more:
every worksheet the file contains is reachable from the window's own tab bar.
- **Sheet tabs (Excel-like)**: a `QTabBar` with `QTabBar.RoundedSouth` shape sits
  **below the table and above the "N rows × M columns" info line** — the position
  Excel puts its sheet tabs in. `_rebuild_tabs(current)` fills it from
  `wb.sheetnames` (signals blocked while filling) and `_on_tab_changed` →
  `_show_sheet(name)` swaps the table's model. The sheet is looked up **by tab
  position**, never by tab text, because `_refresh_tab_labels` appends a `*` to the
  tabs of sheets with unsaved edits. Tab colours come from theme tokens
  (`surface_bg`/`panel_bg`/`accent`/`border`), like every other secondary window.
- **One model per sheet**: `_show_sheet` builds an `ExcelSheetModel` on a tab's first
  visit and caches it in `self._models`, so **edits on one sheet survive switching to
  another** and Save writes them all. Column widths live on the *view*, so
  `_show_sheet` re-sizes columns on every switch (`resizeColumnsToContents` for
  ≤ 60 columns — cheap thanks to `setResizeContentsPrecision(40)` — else a 90 px
  default) and re-syncs the frozen first row.
- The sheets are read with **openpyxl** (keeping styles) into a **lazy `QTableView` +
  `ExcelSheetModel`** (`QAbstractTableModel`) with Excel A1-style headers (column
  letters / row numbers): only the cells actually on screen are queried, so a
  300k+-cell sheet opens instantly. Each cell reproduces the workbook's **fill** and
  **font** colour (solid `rgb` fills → `QBrush`; `_argb_to_qcolor` converts
  `FF00A87C`-style ARGB; theme/indexed colours are left uncoloured), plus bold/italic.
  `_FrozenRowTableView` keeps row 0 pinned below the column-letter header.
- **Save / Save As** flush **every cached model** (`_write` loops `self._models`), each
  pushing only its **changed** cells back into the loaded workbook
  (`ExcelSheetModel.flush_to_wb`: unchanged cells — including the `\xa0` spacers — are
  left untouched so their type/formatting survives; numbers are re-parsed to
  int/float), then `wb.save()`, so **every unvisited sheet and all styling is
  preserved**; a merged non-anchor cell is skipped, and a file open in Excel reports a
  friendly error. **Reload** re-reads the workbook from disk and **Load** opens a
  different `.xlsx` in the same window (both confirm once if *any* sheet has unsaved
  edits, and both rebuild the tabs — staying on the current sheet when the new
  workbook also has it, else falling back to its first sheet). The window is modal,
  geometry remembered via the QSettings key `excel_workbook`.
- **Never measure or enumerate the whole sheet** — the rule that keeps a wide sheet
  usable, and the one to keep in mind when touching this window. The Morava workbook's
  `Reservoirs_downstream` is **367 × 1021** cells; before these three fixes, opening
  that tab froze the whole GUI for **~165 s** and a Ctrl+A left it unusable
  (~4 s *per repaint*). All three were quadratic, and all three are now O(visible) or
  O(ranges) — verified at 0.05 s per tab switch and 0.00 s per Select All:
  - `resizeRowToContents`/`sizeHintForRow` ask the model for **every column** of the
    row (~8000 `data()` calls on that sheet), and `_sync_frozen` ran **once per column**
    while a sheet was laid out (`setDefaultSectionSize` emits one `sectionResized` per
    section, and `sync_frozen_columns` bounced each width back through the strip's own
    header). Now: syncs are coalesced by `_frozen_timer` (single-shot, 0 ms),
    `sync_frozen_columns` blocks the strip header's signals while copying widths, and
    heights come from `_row_height_hint` over `_visible_columns` only.
  - `_visible_columns` measures a sheet of at most `_MAX_HINT_COLS` (120) columns
    **whole**, so the normal sheet keeps Qt's exact heights; only a wider one is
    narrowed to the columns on screen, and `_on_hscroll` re-measures **only** for such
    a sheet (a whole-measured sheet cannot change when other columns scroll in).
  - `_row_height_hint` reproduces `resizeRowToContents` to the pixel (verified against
    it) by asking the **delegate** with `WrapText` set and a **valid** option rect the
    width of the column. Both details matter: `sizeHintForIndex` never wraps, and a
    zero-height rect is not "valid", so Qt measures the text on one line and a wrapped
    cell comes out too short.
  - Row heights are **remembered** (`_fitted_rows` / `_fitted_span`): a row measured
    against the current columns and widths is not measured again while scrolling back
    and forth. The cache is dropped by `_forget_fitted_rows` on a new model, a column
    resize, an insert/delete and the model's `dataChanged` (edited text can need
    another line). Sideways scrolling re-measures **only the strip** — re-fitting every
    visible row per scroll step cost ~900 delegate measurements and was felt as lag,
    while the header row is the one whose long text has to wrap.
  - `selected_block` reads the selection's **ranges**, not `selectedIndexes()`
    (375 000 index objects on a Select All — and `paintEvent` calls it for the fill
    handle on every repaint), and `_full_lines` answers "which columns/rows are fully
    selected" from the ranges too, replacing
    `QItemSelectionModel.selectedColumns()/selectedRows()` — those walk every line of
    the sheet (>3 s per call there) and are asked on every selection change and by
    every header menu. The range test is equivalent for every selection the GUI can
    make (checked against Qt's answers for header clicks, ctrl-clicked lines, cell
    blocks and Select All); only a full line stitched from several partial ranges
    would differ.
- **The workbook is read off the GUI thread** (`_WorkbookLoader(QThread)` →
  `_load(on_done)` → `_on_loaded`). openpyxl needs ~1.5 s for the ~1 MB Morava workbook
  from a local disk but **tens of seconds when the file sits cold on a network share**,
  and doing that in the constructor greyed the whole application out. While it runs,
  `_set_busy(True)` shows `Loading <file> …` in the info line, puts up a busy cursor and
  disables the table, the tabs and the four **File menu** actions (Load / Reload /
  Save / Save As — the whole button row that used to sit below the table became a
  File menu, `_build_menubar`; only the symbol toolbar below stayed as buttons);
  the window itself stays alive.
  Details that matter:
  - The `done` signal is connected to **`self._on_loaded`, a bound method of the
    window** — never to a bare lambda. A lambda has no receiver QObject, so Qt makes
    the connection **direct** and the slot would run *in the loader thread* and touch
    widgets from there (it deadlocked the first time round). With a QObject receiver
    living in the GUI thread the connection is queued, which is the point of the
    exercise. The per-load callback travels in `self._load_callback` instead of being
    bound into the connection.
  - The loader is **parentless** and holds itself in `_WorkbookLoader._running` until
    it finishes, so closing the window mid-load cannot destroy a running QThread.
    `closeEvent` disconnects it and clears the busy state; the thread finishes into the
    void.
  - `_load_other` passes an `on_done` callback: an unreadable file warns and **loads
    the previous workbook back** (path and title with it), so the window never shows
    one workbook while `self.path` — what Save writes to — points at another.
- **Symbol toolbar** (`_build_toolbar`, the **only** thing in the header row and hard
  **left** — the sheet's name is not repeated there, it is on its tab and in the window
  title; built after `self.table` exists because it wires its own connections):
  `QToolButton`s carrying plain glyphs — ⧉ copy, ✂ cut, 📋 paste, 🗑 delete │ **B** bold
  │ ↶ undo, ↷ redo (a `QLabel` "│" as the separator) — so **no icon files are shipped**;
  the stretch is added *after* the buttons, which is what keeps them left. Styling
  is theme tokens only (`text`/`surface_bg`/`border`/`text_gray`), like the rest of the
  window. Every button is connected straight to the **view's existing** method
  (`copy_selection`, `copy_selection(cut=True)`, `paste_clipboard`, `clear_selection`,
  `undo`, `redo`) — the buttons are a second *face* on the shortcuts, never a second
  implementation. `_update_toolbar` greys out what cannot be done right now: copy/cut/
  delete need `selected_block()`, paste needs `clipboard_block()`, undo/redo follow
  `model.can_undo()`/`can_redo()`. It is re-run on `selectionChanged` (re-connected in
  `_show_sheet`, since a new model brings a new selection model), on the clipboard's
  `dataChanged`, and on the model's `undoStateChanged` signal; a `RuntimeError` from a
  deleted C++ object while the window closes is swallowed.
- **Bold** (toolbar **B** / Ctrl+B → `_SheetTableView.toggle_bold` →
  `ExcelSheetModel.set_bold`): a toggle like Excel's — `all_bold` over the marked block
  decides whether the press bolds or un-bolds. `_apply_bold` copies each cell's font
  (`copy(cell.font)` — `cell.font` is an openpyxl `StyleProxy`, and `copy` is the
  supported way to get a real `Font` to change), sets `bold`, drops those
  `_style_cache` entries and emits `dataChanged` with `FontRole`, so the table repaints
  from the workbook's own font — the same path that shows the workbook's original bold
  cells. The change lives on the worksheet, so `wb.save()` writes it; because no cell
  *text* changed, `_styled` (next to `_structural`) is what puts the `*` on the tab and
  makes the close prompt ask. Undoable as a fourth command kind, `bold`, holding the
  per-cell before/after flags; a block over `_UNDO_CELLS` is refused with a note rather
  than done without an undo.
- **Undo / redo** (`ExcelSheetModel`, per sheet — the stacks live on the model, so each
  tab undoes its own history). Ctrl+Z / Ctrl+Y (and Ctrl+Shift+Z) are handled in
  `_SheetTableView.keyPressEvent`; both the shortcut and the toolbar button call
  `model.undo()`/`redo()`. A command is one of **three shapes**: `cells` (a
  `{(r, c): restore-text}` *before*/*after* pair — one edit, a paste, a fill, a Delete),
  `insert` (undone by deleting the band again) and `delete` (undone by re-inserting the
  band **and** writing its captured contents back). The captured text is what would
  **re-create** the cell (`_restore_text`: a formula's source, else the edit/stored
  text, a stored value that looks like a formula escaped with `'`), so undo works the
  same before and after a Save. `_suspend` is on while a command replays, so the replay
  does not record commands of its own; `_push` keeps `_UNDO_DEPTH` (200) commands and
  clears the redo stack; a deleted band above `_UNDO_CELLS` (100 000 cells) is **not**
  captured and `_clear_undo()` runs instead — better no undo than one that silently
  drops what it cannot put back. `undoStateChanged` drives the toolbar's enabled state.
- **Closing with unsaved edits** (`closeEvent`): `_has_edits()` (any cached model with
  `has_edits()` — cell edits **or** the `_structural` flag from an insert/delete) opens a
  Save / Discard / Cancel question naming the affected **sheets**; Cancel and a *failed*
  Save `event.ignore()` so the window stays open with the edits intact. Reload and Load
  ask their own discard question first (see above), so no path loses edits silently.
- Needs `openpyxl` (already a dependency - cwatm reads xlsx settings sheets via
  `pd.read_excel`; do not exclude it from the build, §4.4). Reusable elsewhere:
  `ExcelSheetWindow(path, sheet_name=None, parent=None)` — `sheet_name` only picks the
  tab shown first.
- **Why openpyxl and not XlsxWriter / xlwings** (asked more than once): this editor
  must **read an existing workbook, keep every sheet and style it does not touch, and
  write it back**. *XlsxWriter* is **write-only** — it cannot open a file, so saving
  would mean re-emitting the whole workbook from scratch and losing everything the GUI
  never modelled (charts, formats, other sheets). *xlwings* drives a **real Excel** over
  COM: it needs Excel installed and licensed on the user's machine and cannot be frozen
  into the distributed exe. openpyxl reads values **and** the fills/fonts the table
  paints, and is already in the build for cwatm's own `pd.read_excel`. Its known limits
  are accepted and documented here: `insert_rows`/`insert_cols` move cells and styles
  but do **not** rewrite formulas or merged ranges, and a file it writes carries no
  cached formula results (which is why formula cells are saved as values).

#### Spreadsheet behaviour (`_SheetTableView` + `ExcelSheetModel`)
- **Formulas** (`src/gui/utils/cell_formula.py`). `_set_text` routes a cell's new text
  through `is_formula`: a leading `=` always, plus **bare** expressions whose every
  token is a number, a cell reference (`I3`), a known function or an operator **and**
  that contain at least one operation — so `2+3.5` and `2 + I3` compute while
  `Winter wheat`, `A-B` and a plain `0.35` stay text. A leading `'` forces text
  (Excel's escape). `evaluate` walks an **`ast` whitelist** (BinOp/UnaryOp/Constant/
  Name/Call only — never `eval` of arbitrary code): a `Name` is resolved as a cell ref
  or a constant (`PI`, `E`), ranges are pre-rewritten (`SUM(A1:B3)` →
  `SUM(_RNG_("A1:B3"))`, since `A1:B3` is not valid Python), `^` becomes `**`;
  functions are SUM/AVERAGE(AVG)/MIN/MAX/COUNT/ABS/ROUND/INT/SQRT/EXP/LN/LOG10/LOG/
  MOD/POWER. Failures raise `FormulaError` whose text is the Excel-ish marker shown in
  the cell (`#NAME?`, `#SYNTAX`, `#DIV/0!`, `#VALUE!`, `#REF!`, `#CYCLE`).
  - The model keeps `_formulas[(r, c)]` **live for the session**: `DisplayRole` shows
    the computed value, `EditRole` gives the formula back (so re-editing shows it, as
    in Excel), the tooltip shows `formula = value`, and `_calc` caches results until
    **any** cell changes (`_invalidate` clears it and emits one whole-model
    `dataChanged`, which is what makes dependants recalculate). `_compute` guards
    cycles with `_calc_stack` → `#CYCLE`.
  - **Saving writes the computed value, not the formula** — CWatM reads these sheets
    with pandas/openpyxl, which would hand it the formula *string* (a file openpyxl
    writes carries no cached result). Formula cells therefore stay in `_formulas`
    after a save and are re-written on every later save, while `has_edits()` (the tab
    `*`, the Reload/Load prompt) only tracks `_edits`.
- **Clipboard blocks**: `keyPressEvent` handles `QKeySequence.Copy/Cut/Paste` and
  Delete/Backspace (only outside `EditingState`) over the selection's bounding
  rectangle (`selected_block`); the **right-click menu on the cells**
  (`_on_cell_menu`) offers the same four, labelled with what they will act on
  ("Copy 12 cells"), and right-clicking outside the selection moves it to that cell
  first. Copy/Cut put `model.block_text` — the **displayed** values, tab-separated,
  newline per row — on the clipboard, which is exactly what Excel reads, so blocks
  travel both ways. `paste_block` (fed by `clipboard_block`, the shared parser)
  writes at the current cell and calls `ensure_size` first, so a paste running past
  the last row/column **grows the sheet** (openpyxl extends the worksheet on write);
  each pasted cell goes through `_set_text`, so pasted formulas compute too.
- **Header right-click — copy / insert / paste / delete whole columns and rows**
  (`_header_menu`, shared by both headers via `columns=True/False`). The clicked
  section is selected if it was not already, so the menu always acts on a real
  selection, and the number of **fully** selected columns/rows
  (`selected_columns`/`selected_rows`) decides how many lines the actions touch — as
  in Excel, marking three columns and choosing insert makes three. Items: *Copy
  column(s)*, *Insert empty column(s) left / right* (rows: *above / below*), *Paste N
  column(s) left / right* (only while the clipboard holds a block), *Delete
  column(s)*. `_insert`/`_paste_lines`/`_delete_lines` then call `_after_structure`
  (re-sync the frozen strip, re-wrap).
  - **Paste inserts, never overwrites**: `_paste_lines` first inserts as many empty
    lines as the block is wide/tall, then pastes into them.
  - **`_LineClip` — a copied line knows what and where it is.** Only the header's
    *Copy column(s)/row(s)* (`copy_lines`) records one: its **kind** (`column`/`row`)
    and its **source** `(workbook path, sheet name)`, alongside the clipboard text.
    An ordinary Ctrl+C over cells never records one, so **a full line can only be
    copied from a header** — a cell selection that happens to cover a whole column is
    just a block. `_LineClip.current()` compares the stored text with the clipboard's
    current content, so a copy made anywhere else (this app or another program)
    silently retires the record.
  - `_paste_line_block(kind)` turns that into the reason a paste is refused, and the
    menu keeps the item **visible but disabled with the reason as its tooltip**
    (`menu.setToolTipsVisible(True)`) rather than doing the wrong thing: a **row** on
    the clipboard is never pasted as a column (and vice versa), and a line is only
    pasted back into **the sheet it came from** (`self._source`, stamped by
    `set_source` on every `_show_sheet`). A plain block of cells carries no such
    claim and stays pasteable either way.
  - `copy_lines` refuses a copy above `_MAX_COPY` (200k cells) with a note, so a
    header click on a huge sheet cannot hang on building one giant string.
  - `_delete_lines` asks for confirmation when `model.has_content` finds anything in
    the lines (that scan stops at the first hit and never looks at more than 5000
    rows) — the message says whether **Ctrl+Z** can bring the data back
    (`ExcelSheetModel.delete_is_undoable`); only a band above `_UNDO_CELLS` clears the
    undo history, and then Reload is the way back.
  - The model side is `insert_rows`/`insert_columns` and `delete_rows`/
    `delete_columns`: `beginInsert…`/`beginRemove…`, openpyxl's
    `ws.insert_rows`/`insert_cols`/`delete_rows`/`delete_cols` on the **live
    worksheet** (so Save just writes it), then `_shift_keys` re-keys
    `_edits`/`_formulas` around the change (`remove=True` drops the keys inside the
    deleted band and shifts the rest back) and the style/calc caches are dropped.
    Because the worksheet changed without any cell being "edited", `_structural`
    joins `has_edits()` — otherwise an insert-only change would show no `*` on the
    tab and Reload would not warn. It is deliberately **not** cleared by undoing the
    insert/delete again: the worksheet was mutated and rebuilt, and openpyxl cannot
    promise the styles/merges came back byte-identical, so the sheet stays marked
    dirty until it is saved or reloaded. **Not** rewritten: formulas that point at moved
    cells (neither openpyxl's nor this editor's) and merged ranges.
- **The strip stays the header row** (`_FrozenStrip`): it shows the same model as the
  body, so left alone it scrolls like any table — a click, a drag or the mouse wheel
  over it moved it to row 5 and the sheet then carried a "header" that was really a data
  row. The subclass refuses all of that: `scrollTo` is a no-op (a click cannot scroll
  row 1 away — it forwards the *sideways* part to the body instead, so stepping to a
  column off screen still works), `wheelEvent` is handed to the **body** (spinning the
  wheel over the header scrolls the table, as expected), and `keep_at_top` on its
  `verticalScrollBar().valueChanged` snaps any remaining vertical scroll back to 0.
- **Row 1 is edited on the strip** — it is the only place that row is shown (the body
  hides it), so the strip takes focus, a selection and the usual edit triggers
  (double-click / F2 / just type), and `ExcelSheetModel.flags` marks **every** row
  editable. The edit runs through the same `setData`, so it joins the undo stack, marks
  the tab `*` and is written by Save like any other cell. Because there are now two
  selections, `_selection_source()` decides whose the clipboard, Delete and **B** act
  on — and `_show_sheet` connects **both** selection models to `_update_toolbar`.
  - It returns `_active_view`, recorded by `set_active_view` from each view's
    `focusInEvent`, **not** `hasFocus()` read when the action runs. Reading the focus
    live was wrong in exactly the way it sounds: pressing a toolbar button moves the
    focus first, so **B** pressed straight after marking header cells found the strip
    unfocused and bolded the *table's* old selection — or did nothing when the table
    had none ("sometimes it does not work, or it bolds another cell"). Toolbar buttons
    are `Qt.NoFocus` as well, so they cannot take the focus off the cells they act on,
    and `activeViewChanged` re-runs `_update_toolbar` when the user moves between the
    two views.
  - `_on_letter_clicked` hands the active view **back to the body**: the click lands on
    the strip, but the column it selects is the body's.
  - `_FrozenStrip.keyPressEvent` forwards Ctrl+C/X/V, Delete, Ctrl+Z/Y and Ctrl+B to
    the body's handler (which then acts on the strip's selection through
    `_selection_source`), so the header row has the same shortcuts as any other row.
    Everything else falls through to `QTableView`, so typing a character or F2 still
    opens the cell editor — and while an editor is open the keys stay with it.
- **Column widths belong to the view, not the sheet**: `_show_sheet` therefore sets
  **every** column's width for a wide sheet (`_WIDE_COL` = 90 px, signals blocked, one
  `sync_frozen_columns` afterwards) instead of relying on `setDefaultSectionSize` —
  a default does not touch sections that were already sized, so a wide sheet opened
  after a narrow one inherited the narrow one's widths and showed some columns at one
  width and the rest at another. **B and C get 70 % more** (`_WIDE_COL * 1.7`): on a
  wide sheet those name the rows (in `Reservoirs_downstream` the station and its river)
  while the rest is the data matrix.
- **Strip scrolled exactly with the body** (`_sync_hscroll`): the strip has no vertical
  scrollbar (the body has), so its viewport is ~16 px wider and Qt gives its horizontal
  scrollbar a **smaller maximum** — at the right-hand end of a wide sheet the column
  letters stopped short of the data they belong to. The strip's scrollbar is hidden, so
  `_sync_hscroll` simply widens its maximum when the body scrolls past it; a relayout
  that recomputes (and shortens) the range again is caught by the strip's
  `rangeChanged` → `_on_strip_range_changed`, which re-applies the body's position.
  (`setViewportMargins` on the strip does *not* work — it changes the margin without
  moving the scroll range.)
- **Selection colours**: `_update_selection_tint` (on every `selectionChanged`) sets the
  view's `QPalette.Highlight` from theme tokens instead of leaving the platform's accent
  blue — **`selection_cell`** (dark gray) for marked cells and the stronger
  **`selection_line`** for a whole marked column/row (`selected_columns()`/
  `selected_rows()`), with white highlighted text; the frozen strip gets the same
  palette. Both tokens exist in all three themes (on the dark ones the *line* shade is
  the lighter of the two, since that is what reads as stronger there).
- **Fill handle**: `_handle_rect` puts a 7 px accent square on the selection's
  bottom-right corner (painted in `paintEvent` after the base class; the cursor turns
  into a cross over it). A press inside it starts `_filling` **without** clearing the
  selection; the drag picks the **dominant** axis (`_fill_target` — a drag is either
  vertical or horizontal, as in Excel), auto-scrolls past the viewport edges
  (`_fill_autoscroll`) and paints a dashed preview of the target block. On release
  `_apply_fill` reduces it to the *new* strip and calls `model.fill_range`, which
  extends **each line along the fill axis on its own** through
  `cell_fill.extend_series` (number series, `Crop1`→`Crop2`, weekday/month lists, else
  repeat) — dragging up/left passes the reversed values and writes them outward.
  A **single source cell fills its own value** into the rest: `extend_series` returns
  early for a one-value source, so no series is ever guessed from one cell (this is
  deliberate, and differs from Excel, which would count `Crop1` up). Filling copies
  the *displayed* values, so a formula fills as its value: there is no
  relative-reference translation (`A1` does not become `A2`).
- **Nothing spills into the next column**: both views use `Qt.ElideRight`, so a value
  word wrap cannot break (an ID, a path, one long word) is **cut off with an ellipsis**
  at the column edge instead of being painted across the neighbouring cell and over its
  content. Widening the column shows the rest.
- **Column sizing** (`_show_sheet`, sheets of ≤ 60 columns), in order:
  `resizeColumnsToContents()` → **`fit_header_widths()`** → `cap_column_widths()` →
  `wrap_columns()` → `_apply_sheet_minimums()`.
  - `fit_header_widths` (`header_width_hints` = `frozen.sizeHintForColumn`) is what
    stops a **header** from running into the next column: the body's auto-size measures
    the *data* only, because row 1 is hidden there — it lives on the strip. That was the
    Reservoirs "column E overlaps column F" case, where the header is the longest text
    in the column.
  - `wrap_columns` therefore also floors its halving at the header's width: halving a
    text column must not undo what the line above just fixed.
  - `_SHEET_MIN_CHARS` / `_apply_sheet_minimums` give named sheets a **minimum width in
    characters** for named columns, because what a column *contains* is not always what
    makes it readable: `reservoirtransfer` → **F and G ≥ 12 characters** so a reservoir
    ID (`400001`) is never cut, `reservoir` → **E ≥ 30**. The key comes from
    `_sheet_key` (letters/digits only, lowercase, plural *s* dropped per word), so
    `Reservoir_transfers`, `Reservoir transfer` and `ReservoirTransfers` all match while
    `Reservoirs` stays distinct from `Reservoirs_downstream`. Adding a sheet is one line
    in that table; the minimum only ever widens a column.
- **Word-wrapped text columns**: `ExcelSheetModel.is_text_column` samples the first 60
  **data** rows (row 0 is the sheets' header row and would make everything look
  textual) and calls a column text when non-numeric values are at least as common as
  numeric ones. `_show_sheet` auto-sizes the columns, caps every one of them at
  **~120 characters** (`cap_column_widths`, `_MAX_CHARS` × `averageCharWidth` — one
  long cell would otherwise stretch a column across several screens; the text wraps
  into more lines instead), then `wrap_columns` **halves**
  each text column wider than 140 px (floor 70) — the view has `setWordWrap(True)` +
  `ElideNone`, so the text wraps instead of being cut off. Row heights are computed
  for the **visible rows only** (`_resize_visible_rows`, capped at 300 rows), debounced
  by a 60 ms timer and re-run on scroll, on resize and on `sectionResized` — so
  **widening or narrowing a column re-wraps it** without ever walking the whole sheet.
  Row 0's height is mirrored onto the frozen strip in `_update_frozen_geometry`.

### Compare settings (Settings menu)
**Settings ▸ Compare settings** (last item, separator above)
(`main_window.open_compare_settings` →
`src/gui/widgets/compare_settings_window.py`, `CompareSettingsWindow`) opens a
non-modal side-by-side diff of two settings files. Two `_ComparePane`s, each a
`SettingsEditor` + `LineNumberGutter` with the main window's top button row
(**Save / Save As / Fold All / Unfold All / Top / Down**). The **left** pane is
preloaded with the main window's **current** editor text (live, incl. unsaved edits)
and file path — i.e. the **active settings tab**. The **right** pane adds a **Load**
button (left of Save) for a `*.ini`, and with **more than one tab open it is
preloaded too** (`_preload_right` → `main_window.compare_partner_source`, the
`SettingsTabsMixin`): the tab immediately **left** of the active one, or — when the
active tab is already the first — the one immediately **right** of it, taken live
from that tab's own editor. A single tab, or a neighbour with no content yet, leaves
the right pane empty exactly as before. The Journal-of-Runs and Batch entry points
(`load_files` / `load_contents`) overwrite both panes afterwards, so they are
unaffected.
- **Alignment**: `align_and_diff` (difflib opcodes) inserts light-gray **filler**
  lines on the shorter side of each change so equal lines share a row on both sides;
  both editors end up the same length. Differing lines are marked **orange**
  (`SettingsEditor.set_diff_rows` + `diff_line` token), filler lines **gray**
  (`set_filler_rows` + `filler_line` token), and the difference you **jumped to**
  (Next/Previous Diff) a **darker orange** (`set_current_diff_rows` +
  `current_diff_line`). File-name headers are **bold dark green**. Each pane's
  `real_text()` strips the (empty) filler rows,
  so **Save never writes the padding** and edits to real lines survive; `real_text` is
  also what feeds the next re-compare (Load / Save re-run `_recompare`).
- **Editing keeps the alignment** (`_install_line_sync` → `_on_pane_edit`, on the
  documents' `contentsChange`). Without it the first inserted or deleted line slides one
  pane against the other for the whole rest of the file. An edit that changes the **line
  count** is answered with **virtual lines** — empty, `filler_line` light gray, tracked in
  `filler_rows`, stripped again by `real_text()`, so they exist **only on screen** and
  reach neither a Save nor the next diff:
  - **lines added** on one side (`_lines_added`) → the same number of gray lines at the
    same rows on the other side;
  - **a line deleted** (`_lines_removed`) → a gray line stays behind in its place —
    **unless** the rows opposite it are gray themselves (deleting a line that exists only
    on this side, or undoing an insert), in which case the pair is dropped on both sides.
  - Typing into a gray line makes it real again (`_unmark_typed_filler`).

  Both documents always change length at the same row, so one row transform
  (`_shift_rows` → `_shift_marks`) moves `filler_rows`/`diff_rows` on both panes plus
  `_changed_rows`/`_diff_blocks` together, and the orange marks and Next/Previous Diff
  stay attached to their lines. Three guards keep it from eating itself: `_sync_busy`
  (the mirrored insert/delete is not a user edit), `_ComparePane._suspend_sync` (set by
  `_replace_text`, so a wholesale `load_text` is not read as typing) and `_aligned`
  (off until both sides have content — an unaligned window is left alone). Because a
  Qt document cannot tell an undo from a delete, undoing an insert leaves a gray pair
  rather than nothing; the files are unaffected. A Save/Load re-runs `_recompare`,
  which rebuilds the real alignment.
- **Synced scrolling**: the two editors' vertical + horizontal scrollbars mirror each
  other (`_link_scrollbars`, reentrancy-guarded). Only the **right** pane shows a
  vertical scrollbar (wide 16px, same as the main window's right part) — a single
  scrollbar on the very right that drives both; the left pane hides its own.
- **Next Diff F6 / Prev Diff Sh+F6** (bigger **blue** buttons flush-right on the
  **left** pane = the **centre of the window**, between the left pane's Down and the
  right pane's Load; hotkeys **F6 / Shift+F6**; also in the Settings menu): jump both
  editors to the next/previous difference block (`_diff_blocks`, `_goto_diff` →
  `centerCursor`) and mark that block a **darker orange** (`_highlight_current_block`).
  The right pane's Load/Save/Save As are shifted right of the divider (`lead_spacing=60`).
  Only the **left** pane has Top/Down (scrollbars synced).
- **Fold sync**: only the **left** pane has **Fold All / Unfold All**, and they fold/
  unfold **both** sides (`_fold_all_both`/`_unfold_all_both`); folding/unfolding a
  single **section** on either side mirrors to the other (`foldingChanged` →
  `_sync_folds` via `apply_folds(folded_sections())`, reentrancy-guarded).
- **File / History / Settings menu bar** operating on the **active** side (whichever
  editor last had focus, tracked via a FocusIn event filter): File = Load/Reload/Save/
  Save As/Close (Ctrl+O/L/S, Ctrl+Alt+S); History = the main window's `_recent_files`
  opened into the active pane; Settings = Fold All/Unfold All (fold both, Alt+0/
  Alt+Shift+0), Top/Down (Alt+T/Alt+D), Find (**F5** — free now that diff-nav is F6),
  Find next (Ctrl+F), **Bookmarks** (Toggle/Next/Previous/Clear — Ctrl+F2/F2/Shift+F2/
  Ctrl+Shift+F2, same as the main window), Next/Previous Diff.
Themed like the other secondary windows; geometry key `compare_settings`.
- **Save propagates to the main window**: each pane's Save / Save As reports the
  written path up via an `on_saved(path)` callback → `_on_pane_saved`. If that path is
  the file currently open in the **main** settings window, the main window is refreshed
  from disk (`main_window.reload_after_external_save`) so it shows the saved version
  instead of the pre-save content — reloaded silently when the main editor is clean,
  and behind a discard-changes prompt when it has unsaved edits. A Save As to a
  different path does not touch the main window.
- **Open two specific files** (used by Journal of Runs ▸ Compare settings):
  `open_compare_files(parent, a, b)` → `CompareSettingsWindow.load_files(left, right)`
  reads both paths into the two panes and re-diffs (a missing file loads as empty).

### Output Explorer (Analyse menu)
**Analyse ▸ Output Explorer** (`main_window.open_output_explorer` →
`src/gui/widgets/output_explorer.py`, `OutputExplorerWindow`) opens a **non-modal**
`QTreeView`/`QFileSystemModel` rooted at the resolved **PathOut** (falls back to the
settings-file directory; a friendly note if neither exists). Name-filtered to
`*.nc/*.csv/*.html/*.txt/*.tif/*.map` (`setNameFilterDisables(False)` hides other
files, keeps folders). **Double-clicking** a file (or Open) **dispatches** it to the
existing viewer by name: `*.nc`→`NetcdfWindow` (incl. `dis*.nc`),
`*watercycle*.csv`→`WatercycleWindow`, other `*.csv`→`TimeseriesWindow`, else
`os.startfile`. Each viewer is imported lazily at dispatch (fast-startup rule) and
opened modally over the still-open explorer. **Refresh** re-roots (picks up new run
output), **Change folder…** browses elsewhere. Themed at construction; kept alive on
`parent._output_explorer_windows`; geometry key `output_explorer`.

### Windowed Run CWatM (RUN CWATM menu)
**RUN CWATM ▸ Windowed Run CWatM** (`run_controller.open_hidden_run` →
`src/gui/widgets/hidden_run_window.py`, `HiddenRunWindow`) opens a small **non-modal**
window that runs CWatM on one settings file in its **own OS process**, independent of
the main run and of every other Windowed Run window — so **several can run in parallel**
while the main GUI stays fully interactive. The feature was called **Hidden Run CWatM**
before, and the code still carries that name — the module `hidden_run_window.py`, the
`open_hidden_run` / `_hidden_run_windows` members, the geometry key `hidden_run` and the
journal's `kind="hidden"` (renaming the stored kind would orphan the existing
`run_ledger.json` rows). Each window:
- opens **pre-loaded** with `open_hidden_run(settings_path)` — by default the settings
  file currently loaded in the main window (an `.ini` in that file's directory), and the
  settings tab bar's right-click ▸ **Run CWatM** passes *that tab's* path instead; a **Load** button picks a different `.ini` (dialog
  starts in that directory), **Use current** takes whatever the main window has loaded
  *now* (this window otherwise keeps the file it was opened with), and an `.ini`/`.txt`
  can simply be **dropped onto the window** (`setAcceptDrops` + `dragEnterEvent` /
  `dropEvent`, refused while a run is going);
- shows the settings-file path in **bold green** — the `ok_color` **theme token**, not a
  hardcoded hex, so it follows the Mode like the rest of the chrome;
- shows the run's **Title and resolved PathOut** under it (`_read_settings_facts`, a
  cheap best-effort read refreshed whenever the file changes; `_preflight` re-reads
  authoritatively before the run) with an **Open PathOut** button — with several windows
  open the Title is what tells them apart, and the window title uses it too;
- **output box extras** (`_on_output_menu`): the standard read-only menu plus *Copy all
  output*, *Save output as…*, *Find…* and *Clear output*; **Ctrl+F / F3** search the box
  (wrapping, and saying so once when the text is not there);
- has a **Run CWatM** button that toggles to **Stop CWatM** (blue→red) while running;
- streams the run into its **own** read-only output box (per-timestep `\r` discharge
  line overwrites in place, errors in dark red — same rendering as the main box).
- The run reuses **`CWatMProcessWorker`** with a new **`output_sink`** parameter, so the
  model output is delivered to *this* window's box instead of the global
  `sys.stdout`/`sys.stderr` (default `None` = unchanged main-window behaviour). Each
  window owns its own worker + `QProcess`; `WA_DeleteOnClose` + `closeEvent` kill an
  in-flight run when the window is closed (no orphan model process). The main window
  keeps the windows in `self._hidden_run_windows` so they are not GC'd; the list entry
  is dropped on `destroyed`.
- **Progress bar + times**: the worker's `progress` signal (which this window simply did
  not connect) drives a themed `QProgressBar`, and a 1 s `QTimer` writes
  `elapsed m:ss · remaining ~m:ss` beside it — the same linear estimate the main
  window's clock uses, shown only from 3 % so it is not nonsense at the start. It
  freezes as `run time` / `failed after` / `stopped after` when the run ends, and
  `QApplication.alert` flashes the taskbar: a Windowed Run is the one nobody watches.
- **Pre-flight** (`_preflight`, before the worker is created): the settings file must be
  readable, and its **PathOut** is resolved (`basin_viewer.pathout_exists`) and
  **created** — CWatM does not create it, so the run would otherwise die minutes in.
  It also caches the content, the resolved PathOut and the settings `Title` for the
  ledger entry. Failure writes the reason into the output box and does not start.
- **Journal of Runs**: every Windowed Run is recorded (`kind="hidden"`, with the content
  snapshot for Compare settings) on success, error **and** stop — Windowed Runs used to
  leave no trace in the history at all.
- **Geometry + cascade**: `GeometryMemoryMixin` with the key `hidden_run`; since all
  these windows share one key, each new one is offset by 28 px per window already open
  (`main_window._hidden_run_windows`), so several do not land exactly on top of each
  other.
- **Closing asks** when a run is in progress (window title, file name and elapsed time
  in the question) instead of killing it silently; the same guard is in
  `main_window.closeEvent`, which lists how many Windowed Run windows are still running
  before the GUI (their parent) takes them down with it.

### Batch Run (RUN CWATM menu)
**RUN CWATM ▸ Batch Run…** (`main_window.open_batch_runner` →
`src/gui/widgets/batch_runner_window.py`, `BatchRunnerWindow`) runs many scenarios
derived from **one base settings file** (the file loaded in the main window). A
**table** where each row is a scenario: **Scenario** name, its own **PathOut**, plus
per-scenario **key = value overrides** (columns added with **Add key column**, which
takes the key from the **settings-editor cursor line** via `_key_at_main_cursor`, no
dialog — with a tooltip; a non-`key = value` line is ignored with a hint). For each
row the GUI builds the scenario content (`set_settings_key` replaces each override key's
value + PathOut in the base content — first uncommented `key =` line, appended if absent)
and writes a temporary `<base>.batch_<name>.ini` **next to the base file** (so
placeholders / relative paths resolve identically), then runs it in its **own OS
process** via `CWatMProcessWorker` (the same subprocess worker as the main run).
- **Menu-driven** (`_build_menubar`): most of the former button row became **File**
  (Import CSV / Export CSV), **Action** (Add scenario / Duplicate / Remove / Clear /
  Compare results / Sweep… / Add key column) and **Run** (Run all / Stop all). **Run
  all** / **Stop all** are also kept as a blue/red button pair below the table
  (`_run_stop_button_style`, the same look as Windowed Run CWatM's Run/Stop toggle) —
  the batch's core, most-clicked action, mirroring the Run menu items exactly (both
  paths call `_run_all`/`_stop_all` and are kept in sync at every enable/disable site).
  A top-level **Preferences** action (same click-to-open pattern as the main window's
  CWatM AI/Display, not a dropdown) holds **Parallel runs** / **Stop on first
  failure** / **Skip finished** in a small buffered dialog (OK/Cancel/Apply, like
  the main window's Configure ▸ Preferences). Those three settings still live on
  the original `self.parallel_spin`/`self.stop_on_fail`/`self.skip_finished`
  widgets - just never shown inline any more - so every other read of them
  (`_eta_seconds`, `_preflight`, `_pump`, `_on_finished`/`_on_error`, `_run_rows`,
  `_save_config`/`_restore_config`) is unchanged; the dialog is a second face on
  that state, not a second implementation. There is no Close button - the window
  closes via its title-bar X or Alt+F4.
- **Up to N in parallel** (Preferences ▸ Parallel runs, default 1): `_pump` keeps up to N workers running
  and starts queued rows as slots free; each row shows a live **Progress** (`worker.progress`)
  and **Status** (queued/running/done/failed/stopped) cell. **Run all** / **Stop all**
  (Stop kills every running process). New rows default PathOut to
  `<base PathOut>_<scenario>` so runs don't collide; **Duplicate** copies a row,
  **Remove** deletes one, **Clear** wipes the whole table (all rows + override columns)
  back to one fresh row. Each scenario's resolved PathOut (placeholders expanded via
  `basin_viewer.pathout_exists`) is **created with `os.makedirs` before its run** if
  missing (CWatM does not create it), and a row that cannot create its folder is marked
  `error` and skipped.
- **Parameter sweep** (Action ▸ **Sweep…**, `_open_sweep`/`_apply_sweep`): auto-generates
  scenario rows from `<key>: <values>` lines — `values` a **list** (`3.5, 4.0, 4.5`) or a
  **range** `min:max:step` (`3.5:4.5:0.5`; step optional → 5 steps), parsed by
  `_parse_values`. **Several keys → the full grid** (`itertools.product`); each row is
  named `<key><val>[_<key2><val2>…]` with its own PathOut, the swept keys get override
  columns, and >200 scenarios prompts a confirm. **Replace** (default) gives a clean
  table (rows + old override columns dropped).
- **The scenario table persists across sessions, per base settings file**: on close
  (`_save_config`) the rows (name/PathOut/overrides), the override-key columns, the
  parallel count and the stop-on-failure flag are stored as JSON in `QSettings` under
  **`batch_runner/config_<md5(base path)>`** (`_cfg_key`) — one global key used to greet
  another project with the *previous* project's scenarios and PathOuts. A table saved
  under the old global key is adopted once for the file being opened, then re-saved
  under the new one. **Clear** starts fresh (the empty state is persisted on the next
  close).
- **Duration + ETA** (`_TRAILING` = Progress · **Duration** · Status): a 1 s `QTimer`
  (`_tick` → `_update_times`) ticks the elapsed time of every running scenario and the
  batch line under the title — `3/20 finished · 2 running · 15 queued · ~1:12:30 left`.
  The estimate (`_eta_seconds`) is the **mean of the scenarios that have already
  finished** times what is left (queued rows plus the unfinished fraction of the running
  ones, from their `progress` %), divided by the parallel count; it stays hidden until
  the first scenario finishes, because a guess before that is worse than silence.
  `_freeze_duration` stops a row's clock and feeds `_durations`; when the batch ends the
  line becomes `Batch finished: 18 done, 2 failed in 3:41:12` and `QApplication.alert`
  flashes the taskbar entry — batches are long enough to walk away from.
- **Progress as a bar** (`_ProgressDelegate` on the Progress column): the cell **text**
  stays `NN%` — that is what the CSV export and every read of the table use — the
  delegate only paints a themed bar behind it (`surface_bg` groove, `accent` fill), so
  twenty rows can be taken in at a glance. `_refresh_headers` moves the delegate when an
  override column shifts the Progress column, clearing it from the old index.
- **Compare results** (`_compare_results` → `analysis_timeseries.open_comparison`):
  scans every scenario's PathOut for result `.csv` files, keeps the names that appear in
  **more than one** scenario, and overlays that file from all of them in a single
  Timeseries plot, each series labelled with its scenario name. One candidate is used
  straight away; several ask which (`QInputDialog`, most-covered first). `open_comparison`
  is the programmatic form of the Timeseries window's Action ▸ *Compare*: it builds the
  window on the first file and appends the rest to `win.compare` before the first render.
- **Resume an interrupted batch** (Preferences ▸ *Skip finished*): `_run_rows(rows,
  force=False)` drops rows whose PathOut already holds output (`_has_results`: any
  `.nc`/`.tss`/`.csv` — the scenario's own `cwatm_out.txt` is a `.txt`, so the log alone
  never counts) and marks them `skipped (has results)`. **`force=True` for the row
  menu's *Run this scenario***: asking for one scenario explicitly must run it whatever
  is in its folder. Skipped and `cancelled` rows are counted separately by `_counts`, so
  the batch line and the summary say `… · 3 skipped` instead of silently never reaching
  the total.
- **CSV import/export** (`_import_csv` / `_export_csv`): the columns are
  `Scenario, PathOut, <override keys…>, Duration, Status, LastDischarge`. Export writes the results
  alongside the definition, so the same file **is** the batch's result summary; import
  takes every column that is not Scenario/PathOut and not one of `_INFO_COLS`
  (progress/duration/status) as an **override key**, so a table built in Excel drops
  straight in. Written as `utf-8-sig` for Excel; a file without a Scenario/PathOut
  header is refused with the header it did find.
- **Parallelism**: Preferences ▸ Parallel runs starts at `_default_parallel()` =
  `min(4, cores//2)` rather than 1, and `_preflight` **warns** when it is raised past
  `cores//2` (CWatM is CPU- and IO-hungry; beyond that a batch gets slower, not
  faster). **Stop on first failure** (Preferences) clears the queue on the first
  failed/errored scenario
  (`_cancel_queued`, remaining rows read `cancelled`) but deliberately **lets running
  ones finish** — killing them would throw away hours of work.
- **Pre-flight check** (`_preflight` → `_confirm_problems`), run by *Run all*, *Run this
  scenario* and *Re-run failed* before a single process starts. A batch is expensive and
  its worst failures are **silent**, so these are checked up front:
  - *(blocking)* a row with **no PathOut** — it would write into the base PathOut
    together with every other scenario; two rows with the **same resolved PathOut** —
    they would overwrite each other's results; a PathOut that **cannot be created**
    (`_writable_dir` walks up to the nearest existing ancestor and tests `W_OK`).
  - *(warning, "Run anyway?")* an override key that is **not in the base file** — the
    key is otherwise appended silently by `set_settings_key`, so a typo runs the base
    value to completion; two rows with the same sanitised **name** (they look alike in
    the Journal of Runs); a PathOut that already **holds files**.
- **Per-scenario log** (`_ScenarioLog`): each worker gets its own `output_sink`, so the
  batch never writes into the **main window's** output box — with several scenarios in
  parallel their lines used to interleave there into one unreadable stream. The log
  keeps a 3000-line tail in memory (*Show log*) and appends the full stream to
  `<PathOut>/cwatm_out.txt` (lazy open, flushed every 50 lines, `====`/date header per
  run, `\r` progress lines overwriting in place like the main box). stderr lines are
  kept separately and become the **tooltip** of a failed row — the status cell can only
  show `error: …` cut to 60 characters.
- **Row context menu** (`_on_row_menu`): *Run '<name>'* (`_run_single` — pre-flights just
  that row and queues it, so it also works while a batch is running), *Re-run failed (N)*
  (`_failed_rows` = status starting with failed/error/stopped), *Show log*, *Open output
  folder* (through `utils/open_path.py`, so it works on Linux too) and *Show settings
  (diff vs base)*, which opens the **Compare settings** window on the generated scenario
  against the base file via its `load_contents(left, left_name, right, right_name)`
  entry point. `_run_all` is now `_preflight` + `_run_rows(all rows)`; `_run_rows` is the
  shared queue-and-pump path.
- **Temp `.ini` per row**: the name carries the **row number**
  (`<base>.batch001_<name>.ini`) — two scenarios whose names sanitise alike (`run 1` /
  `run_1`) used to write, and delete, the *same* file while both were running. Writing a
  row's file first removes that row's older ones (`_temp_glob`), so a rename leaves no
  orphan. Deleted on success **and on stop**; kept on failure for inspection (and
  overwritten by that row's next attempt).
- On finish each scenario is logged to the **Journal of Runs** (`kind="batch"`, title
  `<base Title> [<scenario>]`, PathOut resolved via `basin_viewer.pathout_exists`) —
  **stopped** scenarios are recorded too, instead of vanishing. Non-modal; the main
  GUI stays usable. `closeEvent` stops in-flight processes and closes the logs; geometry
  key `batch_runner`.

### Journal of Runs (RUN CWATM menu)
**RUN CWATM ▸ Journal of Runs** — the **2nd item**, right under *Run CWATM* (it was
Tools ▸ *Run Ledger*; only the visible name and place changed — the window class is still
`RunLedgerWindow`, the storage module `utils/run_ledger.py`, the file `run_ledger.json`)
— (`main_window.open_run_ledger` →
`src/gui/widgets/run_ledger_window.py`, `RunLedgerWindow`) shows a table of **past runs**
recorded by `src/gui/utils/run_ledger.py` — one JSON row per run (`run_ledger.json`):
time, `kind` (run/hidden/batch/stopped), settings path, settings **Title**, resolved
**PathOut**, duration, success, last discharge. The former button row is a menu bar —
**File** (Open results, Load settings, Refresh, Export CSV), **Action** (Show log,
Re-run, Compare settings, Compare results), **Clean** (Delete entry, Clear Journal);
tooltips moved from the buttons to the `QAction`s, and only **Close** stayed a button
(`_build_menubar`). Rows are actionable: **Open results**
(the run's PathOut in the **Output Explorer**), **Show log**, **Load settings** (reload
the run's settings file into the main window), **Re-run**, **Compare settings**,
**Compare results**, **Refresh**, **Delete**, **Clear journal**. Newest first;
non-modal; geometry key `run_ledger`.
- **Finding a run**: a **filter box** hides every row that does not contain the typed
  text (any column — Title, PathOut, settings file, kind, date), and the table is
  **sortable** by any column (`setSortingEnabled`). Sorting means a table row is no
  longer its entry's index, so each row stashes that index in column 0's `Qt.UserRole`
  and `_entry_at`/`_selected_entries` read it back; `_SortItem` sorts by a **key**
  (timestamp, seconds, discharge) rather than the displayed text, so `2m 05s` sorts
  after `45s`.
- **Show log** (`_log_path`): the `log` path recorded with the entry, else
  `<PathOut>/cwatm_out.txt` when one is there; shown read-only with only the **last
  2 MB** read, since a long run's log is big. Main runs record theirs when
  **Preferences ▸ Output ▸ Write output box** is on; batch scenarios always write one.
  The journal otherwise records *that* a run failed and never *why*.
- **Re-run**: opens a **Windowed Run** window on that settings file and starts it,
  falling back to the run-time **snapshot** when the original file is gone (with a note
  saying so). The journal knows exactly what ran, so repeating it should not be a
  manual load-then-run.
- **Compare results**: for two or more marked runs, collects the result `.csv` names
  present in several of their PathOuts, asks which one when there is a choice, and
  overlays them in a single Timeseries plot through
  `analysis_timeseries.open_comparison`, each series labelled with the run's Title.
  *Compare settings* answers "what differed in the set-up"; this answers "what differed
  in the results".
- **Delete** removes the marked runs and their snapshots (`run_ledger.remove_entries`,
  matched on ts + settings + pathout because the window works on copies). Until now it
  was all-or-nothing via *Clear journal*. Deleting a **grouped batch row** deletes all
  its scenarios.
- **Grouping** (*Group batches*, on by default): entries sharing a `batch_id` — written
  by the Batch runner, one id per batch — collapse into a single row
  (`<Title> — batch of N`, summed duration, `12/14` in the OK column). Entries without
  a batch id (everything before this, and every main/Windowed Run) are untouched. Untick
  to see every scenario.
- **Dead rows are visible**: a PathOut or settings file that no longer exists is drawn
  in `text_gray` with a "does not exist any more" tooltip, instead of being discovered
  by clicking. One `os.path` check per **distinct path** per reload (`exists` dict), not
  per row, so a few hundred rows on a share stay cheap.
- **Note column** (last, editable): free text stored in the journal
  (`run_ledger.set_note`, matched on the same ts+settings+pathout key as the delete).
  Titles come from the settings file and repeat, so a note — *"calibration attempt 3"* —
  is what makes a months-old journal navigable. `_filling` guards `itemChanged` while
  the table is rebuilt, live rows and **grouped batch rows** are read-only (their
  tooltip says to untick *Group batches* to note a single scenario).
- **Export CSV** writes the rows **currently shown** — so the filter narrows the export
  — with the visible columns plus `Kind` and `Log`.
- **Right-click a row** (`_on_row_menu`) for everything that applies to it, including
  the two things with no menu-bar equivalent: **Open output folder** (the file manager,
  through `utils/open_path.py`) and **Copy PathOut / Copy settings path** (retyping a
  path out of the table was the only way before). The rest mirrors the File/Action menu
  items — open results, show log, load settings, re-run, delete — each greyed out when
  it does not apply.
- **What is running now**: `_live_entries` builds pseudo-rows for the **main run**
  (`_run_ledger_ctx`), every **Windowed Run** window and every in-flight **Batch**
  scenario, shown at the top with `running…`, a live elapsed time and a tinted
  background, refreshed by a 2 s timer (which also picks up runs that finish while the
  window is open). They cannot be deleted or re-run, and the timer is stopped in
  `closeEvent`.
- **Compare settings**: the table is **ExtendedSelection**, so two runs can be marked
  (Ctrl/Shift+click). The **Compare settings** action (and *Compare results*, *Re-run*,
  *Show log*, *Delete*) is **disabled** until the marked rows make it valid — Compare
  settings needs **exactly two** rows (`itemSelectionChanged` →
  `_update_compare_enabled`, `QAction.setEnabled`); triggering it diffs the two runs' settings in the **Compare
  settings** window via `compare_settings_window.open_compare_files(parent, a, b)` (a new
  `CompareSettingsWindow.load_files` reads both paths into the two panes and re-diffs).
  It prefers each run's **run-time snapshot** (`entry["snapshot"]`, what actually ran)
  over the live `settings` path, so the diff is accurate even if the file was edited
  afterwards; a missing file loads as empty.
- **Logging**: `run_controller` captures the run facts at start (`_run_ledger_ctx`:
  settings path, Title via `_current_settings_title`, resolved PathOut, start time) and
  `_log_run_to_ledger(success, last_dis, kind)` appends an entry on **finish** (`run`),
  **error** (`run`, success False), and **stop** (`stopped`) — logged **once** per run
  (best-effort; a logging failure never breaks a run). The **Batch runner** logs its
  scenarios too (`kind="batch"`).
- **Settings snapshot**: at run start `run_controller` reads the on-disk settings file
  (what CWatM actually runs) into `_run_ledger_ctx["content"]`; on log, `make_entry`
  writes it via `_write_snapshot` to `<history>/snapshots/<YYYYMMDD_HHMMSS>_<base>.ini`
  (name **uniquified** so parallel runs finishing in the same second don't collide) and
  stores its path as `entry["snapshot"]`. This is what **Compare settings** diffs. The
  **Batch runner** snapshots each scenario's generated content too.
- **Storage / retention** (`run_ledger.py`, `QSettings`): folder `history/folder`
  (default `%LOCALAPPDATA%/CWatM_GUI`, set via **Preferences ▸ Run History ▸ Run history folder**),
  retention `history/retention_days` (default 60; 0 = keep forever, set via **Preferences ▸ Run History ▸
  Run history retention**) — entries older than the window are pruned on write **and
  their snapshot files deleted**, plus a hard `_MAX_ENTRIES` cap. **Clear ledger** also
  removes the `snapshots/` folder. Writes are atomic (`.tmp` + `os.replace`).

### Restore settingsfile (Tools menu)
**Tools ▸ Restore settingsfile** (`main_window.restore_settingsfile`) opens a `dis*.nc`
output file and shows its global attributes in a table (`RestoreSettingsWindow`,
`src/gui/widgets/restore_settings_window.py`), **excluding** the three bulky ones
(`version_settingsfile`, `version_inputfiles`, `version_modules`) — each of which has
its own viewer instead. **One `Dataset` open for the whole window**: the call site reads
*every* global attribute (`read_netcdf_attrs`) and hands the list to the window, which
filters its table and serves all buttons from that dict (these files usually sit on a
network share, where each open is the slow part; `read_netcdf_metadata` /
`read_netcdf_attr` stay as thin wrappers). Above the table sits a **summary card**
(`_summary_rows`): Title · Created (`history`, minus the leading "Created") · CWatM
(`Source_Software`, else `Version`) · Settings file · Output folder — the facts everyone
hunted for in the alphabetical list; rows the file does not carry are simply absent, and
each value is selectable.

**Menu-driven** (`_build_menubar`): **File** (Export as CSV), **Action** (Preview
settingsfile, Compare with current, Show Inputfiles) and **Restore** (Restore
settingsfile) — tooltips moved from the buttons to the `QAction`s. There is no Close
button — the window closes via its title-bar X or Alt+F4. **Show in Journal** (button
and its backing `_on_show_in_journal`/`_journal_entry`) was **removed outright**, not
moved into a menu.

Every action is **enabled by what the file actually contains** (`_update_actions`) —
a NetCDF without `version_settingsfile` greys the three settings actions with the reason
in the tooltip, instead of explaining it after the click.

- **Preview settingsfile** (`_on_preview` → `SettingsPreviewWindow`): the stored
  settings in a **read-only `SettingsEditor`** (highlighting + folding for free, styled
  with `_ComparePane._editor_style()`). *Look before you restore* — until it existed the
  only way to see the stored file was to write it somewhere and load it, i.e. replace the
  file you were working on. Its own buttons: **Save as…** (write, don't load),
  **Load into editor (unsaved)** and **Compare with current**.
- **Load into editor (unsaved)** (`RestoreSettingsWindow.load_into_editor`): pushes the
  stored content into the main editor through `set_content_preserving`, so it is **one
  undo step** (Ctrl+Z restores the current file) and **nothing is written to disk** — the
  Save buttons just turn blue. Asks first, naming the file whose content is replaced;
  refuses when no settings file is loaded (there would be no editor to put it in).
- **Compare with current** (`_on_compare`): diffs the stored settings against
  `main_window._live_content()` in a `CompareSettingsWindow` (`load_contents`, panes
  labelled *current file* vs *stored in \<nc\>*). This window is **modal**, which would
  block the diff window, so it `accept()`s itself (and the preview) first.
- **Restore settingsfile** (`_on_restore`): writes `version_settingsfile` (the full
  settings file CWatM stamped into the output) to a **new file** (Save-As dialog,
  suggested in PathOut / next to the nc), then **loads** it in the main window
  (`load_recent_file`). If the currently loaded settings file has **unsaved changes**
  (`main_window._is_dirty`) it first warns *"Current settingsfile is not saved. Save it
  or loose content."* with **Save current first / Continue (lose changes) / Cancel**
  (`_confirm_unsaved`). The suggested name is `<title>_<run date>.ini`
  (`_suggested_name`, from the `title` and `history` attributes, falling back to
  `restored_settings.ini`) — restoring three runs into one folder used to collide three
  times on the same name.
- **Show Inputfiles** (`_on_show_inputfiles` → `InputFilesWindow`): parses
  `version_inputfiles` (entries separated by `;`, each `<filename> <DD/MM/YYYY HH:MM>`,
  via `parse_input_files`, exact duplicates dropped) into a **File / Date at run time /
  Status / Found at** table, and **checks** each entry (`check_input_files`): is the file
  still there, and is it still the version the run used? CWatM records only the
  **base name** (`data_handling.py: os.path.basename(filename)`), so there is nothing to
  `os.path.exists` — the check instead resolves the *stored* settings file
  (`candidate_dirs`: every `Path*` value and the folder of every file value, placeholders
  resolved by the module's **own** `_resolve_placeholders` — a deliberate copy of
  `basin_viewer._resolve_settings_placeholders`, because importing that module for one
  regex helper drags numpy/xarray/rasterio into a worker thread; relative paths against
  the run's settings folder from the `settingsfile` attribute) and builds one
  basename → path index over those folders (`_dir_index`, one `os.scandir` each). The
  recorded date is compared against **both** the file's mtime and ctime in CWatM's own
  `%d/%m/%Y %H:%M` format (it writes `getctime`, so comparing only mtime would cry wolf)
  → `ok` / `changed (now …)` / `missing` / `found` (no date recorded) / `?` (nowhere to
  look — no stored settings, or none of its folders readable), the status cell tinted
  `error_line` / `wrongext_line`, with a count line *"188 files · 3 missing · 5 changed
  since the run"*; the `?` count is reported too, because otherwise a check that checked
  **nothing** summarised as "all still there and unchanged". The listing runs in a
  **`QThread`** (`_InputCheckWorker`, `done` connected to a **bound method** so it stays
  queued) — folder listings take seconds on a share — and **Re-check files** repeats it.
  **Double-clicking a row opens that input file** (`_on_double_clicked`): a `.nc`/`.nc4`
  in the **NetCDF viewer** (`analysis_netcdf.NetcdfWindow`, `WA_DeleteOnClose` like the
  Output Explorer's viewers), anything else through `open_path`; the resolved path is
  kept on the name cell (`Qt.UserRole`), so a row that is missing or not yet checked
  says so instead of doing nothing.
- **Getting values out** (`install_table_tools`, both tables): **Ctrl+C** copies the
  marked rows tab-separated, a right-click offers *Copy value / Copy row(s) / Export as
  CSV…*, and an **Export as CSV** — the main window's **File** menu, the Input Files
  window's own button (untouched by the menu conversion above) — writes the visible
  rows (`;`-separated, utf-8-sig, suggested next to the nc as `<name>_metadata.csv` /
  `<name>_inputfiles.csv`). Before this, a read-only table with no menu meant a value
  could not leave the window at all.

### CWatM AI (Gemini NotebookLM)
**CWatM AI** button (left of Help) opens a chat window where questions about CWatM are
answered by Google **NotebookLM** (Gemini) over a predefined CWatM notebook (source
PDF, e.g. `CWATM_shorter.pdf`). Uses the **`notebooklm-py`** library (fully async;
httpx RPC — **not** Playwright at runtime). **Source-run feature**: not in the
PyInstaller spec; a frozen build degrades gracefully (friendly message, never a crash).
See `ai.md` for the full plan/history.
- **Threading**: all `notebooklm` work runs off the GUI thread. `NotebookLMWorker`
  (`src/gui/utils/notebooklm_worker.py`, a `QThread`) owns a question `queue.Queue`,
  connects lazily on the first question, and emits `status/reply/error/busy` signals.
  The **only** importer of `notebooklm` is `src/gui/utils/notebooklm_client.py`
  (`NotebookLMClientWrapper` — one persistent asyncio loop drives `connect/ask/close`;
  `is_authenticated`, notebook auto-resolve by title containing "cwat"). Lazy-imported
  in `main_window.open_cwatm_ai()` (fast-startup rule — never import notebooklm/httpx
  at module level).
- **Query-latency shaves** (the answer time is dominated by NotebookLM's server-side
  generation, which the GUI cannot shorten, but two avoidable round-trips were removed):
  - **Background pre-warm** — once the session is *confirmed* valid (`_on_auth_result`
    "ok" on open, or `_auto_on_verify` "ok" after login) the window calls
    `_warm_worker()` → `NotebookLMWorker.warm()`, which queues a `_WARM` sentinel the
    run loop turns into a **connect-only** step (no `busy()`, quiet on failure). So the
    connect + `notebooks.list` + `chat.configure` cost is paid in the background, not on
    the first question.
  - **Cached source ids** — `chat.ask(source_ids=None)` re-fetches the whole notebook
    (`get_source_ids` → `get_raw`, *not* cached in notebooklm 0.7.3) on **every**
    question. `NotebookLMClientWrapper._prefetch_source_ids()` fetches them once at
    connect and `ask()` passes `source_ids=self._source_ids`, removing that per-question
    round-trip (best-effort: an empty/failed fetch falls back to `None` so correctness
    wins). A shorter **answer length** (the Short/Medium/Long selector) also cuts
    generation time.
- **Window** (`src/gui/widgets/notebooklm_window.py`, `NotebookLMWindow` =
  `GeometryMemoryMixin` + non-modal `QDialog`, geometry key `cwatm_ai`, themed like the
  NetCDF window — every colour a `theme.c(token)`): header + a centred login-state line,
  a `QTextBrowser` transcript (You / Gemini / status / error colours), a multi-line
  input (Enter sends, Shift+Enter = newline) + **Send** (blue), and **Login… /
  Choose browser… / Notebook… / Clear / Exit** (all but Login grey). **Gemini answers are
  rendered as markdown** (`markdown-it-py` "gfm-like": bold/lists/tables/code —
  `_render_markdown`), each answer followed by an `<hr>` **separator** before the next
  question; the *Explaining settings line: …* notice (Explain button / phrase) is shown
  **bold blue** (`_append_action`).
- **Answer-length selector** (compact Short / Medium / Long exclusive toggle buttons
  in the bottom row, right of **Notebook…**; selected = blue, persisted
  `notebooklm/response_length`, default Medium):
  sets NotebookLM verbosity via `chat.configure(notebook_id, response_length=…)`
  (`ChatResponseLength` SHORTER/DEFAULT/LONGER). The wrapper applies it on its asyncio
  loop from `connect`/`ask`; the worker pushes the current choice on the worker thread
  before each ask. (It is a NotebookLM **server-side** per-notebook setting.)
- **Transcript + question history persist** across close/open (QSettings
  `notebooklm/transcript_html`, `notebooklm/history`; saved in `closeEvent`/`done`,
  restored in `__init__` — a restored transcript shows a "— New session —" separator).
  **Up/Down** in the input recall older/newer questions (only at the first/last line, so
  multi-line editing still works; a live draft is kept when paging past the newest).
- **Login state is verified, not assumed**: a stored session **file** existing does
  not mean it still works, so on open (and after a login) a background `_AuthCheckWorker`
  (QThread) calls `notebooklm_client.check_connection()` — a real `notebooks.list()`
  probe — off the GUI thread. `_refresh_login_state()` then colours the Login button
  **blue "✓ Logged in"** only when *confirmed* (`_auth_verified is True`), **"Checking…"
  (blue)** while the probe runs, and **red "Login required"** when the session is
  **expired/invalid** (`check_connection` → `"auth"`, detected via `is_auth_error`:
  "Authentication expired or invalid", a Google-accounts redirect, "Run 'notebooklm
  login'"…). On an expired session (also if a **question** fails with an auth error —
  `_on_worker_error`) it drops the dead worker and **prompts to re-authenticate**
  (`_prompt_reauth` → the Google login window). A transient network/proxy error leaves
  the state unchanged (just a note). `playwright` (pinned) drives that Google-login
  re-auth path. **Login…** is now **one click, auto-detect**
  (`_start_auto_login`): it walks a browser list **Firefox → Chrome → Edge → Opera**
  (`_auto_try_next`), for each runs `notebooklm login --browser-cookies <browser>`
  (`QProcess`) and — because a written cookie file does not prove a working session —
  **verifies each** with a background `_AuthCheckWorker` (`_auto_verify` →
  `_auto_on_verify`), **stopping at the first browser whose `check_connection()`
  returns `"ok"`** (transcript shows "Trying Firefox… / Chrome: no valid session… /
  Logged in via Chrome"). A `"error"` (network/proxy) stops the run and reports it
  (other browsers can't help); `"auth"`/`"no_session"` moves to the next. If none work
  (`_auto_login_failed`) it explains why — noting the **Windows app-bound cookie
  encryption** admin caveat when a Chrome/Edge/Opera decrypt error was seen
  (`_auto_saw_decrypt`) — and offers the manual picker. **Choose browser…**
  (`_on_choose_browser`, the former per-browser dialog) is the fallback: pick a
  specific browser or the interactive **Google login window** (Playwright, source-run;
  system Chrome via `--browser chrome`, no download; bundled-Chromium fallback offered
  on failure). Cookies are read via **`rookiepy`** (`notebooklm-py[cookies]`); Firefox
  is tried first as its store is readable without elevation.
- **Notebook selection**: `notebooklm/notebook_id` (a bare id or a NotebookLM URL;
  `Notebook…` sets/persists it); if unset the wrapper auto-picks a notebook whose title
  contains "cwat", else the only one, else raises listing the choices.
- **Settings bridge** (settings editor → answer): one grey **Explain current line**
  button above the input, also triggerable by typing a set phrase (e.g. "explain this
  line" — matched in `_maybe_handle_command`, so genuine questions are not intercepted).
  It reads `main_window.ai_current_settings_line()` (the editor's cursor line, or the
  selection) and asks NotebookLM to explain it; the *Explaining settings line: …* notice
  uses `_append_label_line` (**bold-blue label + normal-weight body**). (The former
  **→ Settings** button and its answer→settings insertion machinery —
  `_cmd_put_in_settings`/`_do_put_in_settings`, the `_pending_ctx` section lookup, the
  "put this in the settings" phrases, and `main_window.ai_put_text_in_settings` +
  `_parse_settings_block`/`_apply_settings_entries` — were **removed**.)

### Settings-file tabs (Expert level)
`src/gui/components/tab_manager.py` — `SettingsTabsMixin` + `SettingsTab`. The
always-true rules (the bar's visibility condition, "the active tab is the application
state", "one file, one tab", and what is fanned out to every tab) are in `CLAUDE.md`;
this is the rest.

**The bar.** Directly below the button row, above the editor. A **new tab** comes from
the small **`+` tab** right of the last one (`add_tab_plus`, a `QToolButton` sharing the
`_tabs_row` layout with the bar, because a `QTabBar` has no corner widget; styled from
theme tokens like a tab and sized to the real tabs' height in `_style_tab_chrome`, which
`_retheme` also calls). That is the **only** way to add one — the right-click menu has no
*Add empty Tab* item, and there is deliberately no Add Tab button in the button row. The
**✕** appears **on the hovered tab only** (`HoverCloseTabBar`: `setTabsClosable(True)`
with every button hidden except the hovered one, so tab widths never jump) and runs the
same `close_settings_tab` as *Delete Tab*. A tab is captioned with the file's base name
(`untitled` when empty) and a leading **`*`** while it has unsaved edits.

**Per-tab state.** Each tab owns its own `SettingsEditor` + `LineNumberGutter` page in a
`QStackedWidget`, so undo stack, bookmarks, folds, changed-line highlights and check
marks are per tab by construction.

**What a switch re-points.** `text_area` / `line_number_gutter` / `text_display` /
`file_manager.current_file_path` / `original_content` / `_clean_content` / `_is_dirty` /
`_filename_state` / `_working_dir_override` / the mask cache, and then it refreshes the
left panel the way a load does (labels, dates, PathOut, MaskMap, Gauges, warnings,
`os.chdir`).

**Three rules that keep that honest:**
1. The outgoing tab's debounced field changes are **flushed** before the switch — its
   content is then authoritative, and the boxes are re-derived from it on the way back
   in. Stale boxes would poison `_live_content()` and the next save.
2. `_on_doc_modified` / `_on_editor_text_changed` ignore signals from a **background**
   editor (`_is_active_editor_signal`).
3. Closing a tab **stores the active tab first**, because the close ends in
   `_activate_tab`, which restores the window from the tab object.

**Where a load goes.** Into the active tab (the first one at startup), and so does a
dropped file — dropping a `.ini`/`.txt` onto **either side**, the left panel or the
editor itself, loads it the same way (`SettingsEditor.fileDropped`, its own
`dragEnterEvent`/`dropEvent` override, wired to `load_recent_file`); a drop on the editor
used to just insert the path as text. The **`+`** tab opens an empty one first. The
one-file-one-tab guard
(`guard_duplicate_file` / `same_file`, paths compared absolute + `normcase`) makes a load
of an already-open file switch to the tab that has it — History, drag & drop, the Load
dialog and the startup restore all funnel through `load_recent_file`, while
`File ▸ Load .ini` only picks the path (`file_manager.choose_load_path`). **Save As**
onto another tab's file is refused **without** switching away. Re-loading a tab's own
file (Reload) is unaffected — the guard excludes the active tab.

**Right-click a tab:**
- *Delete Tab* — unsaved prompt; deleting the **last** tab empties it instead of leaving
  none. Closing (✕ or *Delete Tab* alike, both funnel through `close_settings_tab`) first
  calls `_interrupt_tab_run(tab)`: if a run (main, a Windowed Run, or a Batch scenario) is
  using that tab's file (`same_file`), it **asks Yes/No** before stopping it — answering
  No aborts the close entirely, so the tab and its run are left alone. Then
  `_release_tab_folder_lock(closed_folder)` `os.chdir`s the process away from the closed
  tab's folder if it was still cwd and no remaining tab needs it, so the folder is no
  longer held open (Windows won't let Explorer delete a folder the process has as its
  working directory).
- *Copy Tab* — writes the tab's **current** content, unsaved edits included, to
  `next_copy_path()` (`settings.ini` → `settings_2.ini` → `settings_3.ini`, skipping
  names that exist) and opens the copy in a new tab right of the source.
- *Compare* (`compare_tab_to_next`) — opens the **Compare settings** window
  (`open_compare_sources`) side by side on this tab and its **neighbour**: left pane =
  the right-clicked tab, right pane = `compare_next_partner_index` (the tab **right** of
  it, or the one **left** when it is the last tab — the **mirror** of F8's
  `compare_partner_index`, which prefers the left neighbour of the *active* tab). Both
  sides are handed their tab's **live editor text** (`tab_source`, the same reader
  `compare_partner_source` uses), so unsaved edits are what gets compared, not the files
  on disk. **Greyed out with only one tab open.**
- *Run CWatM* — opens a **Windowed Run CWatM** window on *this tab's* file
  (`open_hidden_run(tab.file_path)`), independent of the main run and the other tabs.
  Disabled while the tab has no file, and it runs the file **as saved on disk**.
- *Link scrolling* (checkable, `set_tab_link_scroll`) — **greyed out on the first tab**,
  which has no predecessor.

**Link scrolling.** Ticking it scrolls this tab and the **previous** one together **and
mirrors the folded sections** (`_on_editor_folding` → `apply_folds(folded_sections())`) —
without the fold mirror the two would stop being at the same place the moment a section
collapsed. The flag lives on the *later* tab of each pair, so a run of ticked tabs forms
one chain (`_linked_group`). The mirrored value is the vertical scrollbar's position
clamped to each partner's own maximum; `_scroll_sync` / `_fold_sync` guard the
reentrancy, and the fold mirror also skips a **load** and a **tab switch** — both emit
`foldingChanged` without the user folding anything, and a load would otherwise unfold the
partner. `_normalize_links` clears the flag off whatever becomes tab 0 after a close or a
drag. Only one tab is visible at a time, so what this buys is that **switching** between
two linked tabs lands you on the same lines. In-memory per session, not persisted.

### Change Options (Tools menu)
`src/gui/widgets/options_window.py` — `OptionsWindow`: the `[OPTIONS]` boolean switches
as tick boxes. **Non-modal** (each tick is applied at once, so there is nothing to
accept), geometry key `options`.

- Rows are **grouped by topic** (`option_help.GROUPS`, unknown ones under *Other*),
  carry an **ⓘ badge** with the switch's explanation and a **changed dot** vs the file as
  opened, and are narrowed by a **filter box** + *Changed only*.
- **Revert all** puts them back; **Add option…** offers a known switch the file does not
  define yet and appends `name = False` at the end of `[OPTIONS]`.
- **Two invariants.** The parse **strips an inline comment before the boolean test** —
  `includeGlaciers = False  # …` used to make the switch disappear from the window
  entirely; and `_rewrite_value` **keeps whatever followed the value** when writing (the
  comment used to be dropped). The edit goes to the editor through
  `set_content_preserving`, so a tick is **one undo step**.

The badge text lives in `src/gui/utils/option_help.py`: `text(option)` (wrapped, and it
does not repeat the name — the tooltip already hangs off that option), `has()`, plus
`GROUPS`/`KNOWN`/`group_of()` for the grouping and the *Add option…* list. Adding a
switch is one entry.

### Check Data (Tools menu)
`src/gui/widgets/check_data_window.py` — `CheckDataWindow`, CWatM's `-c` data analysis
over the loaded settings. **Three invariants:**

1. The check runs in a **`QThread`** (`_CheckWorker`) — it opens every input file, and in
   the GUI thread it froze the app.
2. The window is therefore **not modal** (a modal dialog would block the GUI just the
   same; `main_window.open_check_data_window` uses `show()`).
3. Its output is mirrored into the window's **own log pane** — `_LogTee` wraps
   `sys.stdout`/`sys.stderr` **filtered to the worker thread**, so unrelated GUI prints
   stay out. Everything used to go to the main output box *behind* a modal dialog.

Also: a **double-click on a result row jumps to that settings key** (column "Name" of
CWatM's check table is the key — `cwatm/management_modules/checks.py`); an
unsaved-changes prompt, because CWatM reads the file from **disk**;
`_check_maskmap_supported` (coordinate MaskMap → Run Check disabled, with the reason in
the tooltip); one renderer for the full and the trouble view (`_render_results_table`,
whole-row tint + `_CheckItem` numeric sorting); a filter box + `_summarize` count line;
`Export CSV` of the visible rows; `<PathOut>/check_cwatm1.csv` as the default; and
*Restore settings from discharge map* delegating to `RestoreSettingsWindow` — its own
copy iterated the `version_settingsfile` **string character by character**, writing one
character per line.

### Add output variables (Tools menu)
`src/gui/widgets/output_variables_window.py` — `OutputVariablesWindow`, a filterable,
**topic-grouped** picker of the metaNetcdf output variables.

- **Grouping** (`_GROUPS`/`group_of`): substring patterns, `=name` for exact, first match
  wins, unmatched → *Other*; a header hides itself when a filter empties it.
- **What is offered**: `meta_netcdf.output_varnames()` (data variables; no-type,
  `_`-prefixed, list-table and scalar-type vars excluded), narrowed to those that fit the
  loaded `[OPTIONS]` (`_FEATURE_VAR_PATTERNS` hides glacier/modflow/small-lake/waterbody/
  water-demand/runoff-conc/environ vars when their switch is off). By default only
  `priority="high"` vars (116 of 580 in the shipped xml); the **Load all Variable**
  toggle shows every fitting one, and **whatever the settings file already writes is
  listed in either view** — a used-but-low-priority variable could otherwise be neither
  seen nor clicked off.
- **The filter searches the metadata too** (`_haystack`: name + unit + long_name +
  description, so "evapo" finds `actualET`).
- **Marks**: `_file_vars()` → `_make_item`/`_refresh_marks` mark a used variable **✓ bold
  green** with its keys/lines in the tooltip; the **Only variables already in the
  settings file** tick filters on that mark. Each tooltip also carries `unit:` +
  `Dimension:` (`meta_netcdf.dim_of`).
- **Array variables** are suffixed `[index]`, and both click styles resolve the index
  through `var_dims.index_options` — `_pick_index` (a named menu at the mouse) for a
  left-click, an index submenu under each time step for a right-click, `QInputDialog` for
  per-crop. A left-click toggle matches on the **base** name, so one click removes
  `actualET[1]`.
- **Left-click toggles** the varname on the editor's current line — inserted at the
  cursor with auto comma separators if absent, removed if already present — but only on
  an `OUT_TSS_…`/`OUT_MAP_…` line (else it warns + beeps). **Removal deletes the whole
  output line** when the varname was the last one on it (`_remove_output`, shared by both
  click styles, so a line the right-click menu just created disappears again on a second
  pick).
- **Right-click needs no cursor position**: `_on_context_menu` builds a two-level `QMenu`
  (`setToolTipsVisible`) — **Timeseries (TSS)** with the ten `_TIME_TYPES` plus an
  **upstream calculation** submenu branching into `AreaSum`/`AreaAvg` (`_AREA_AGGS`),
  each listing the seven `_AREA_TIME_TYPES` (TSS-only), and **Map (MAP)** with the same
  ten types. Every entry's tooltip explains the time step (`_TYPE_TOOLTIPS`) and shows
  the resulting line. `_add_output` appends to the existing `OUT_<TSS|MAP>_<sel>` line
  (preferring a hit inside `[OUTPUT]`; a `None`/empty value is replaced rather than
  appended to) or creates the key at the end of `[OUTPUT]` (`_insert_output_line`, same
  placement as `add_output_watercycle`), written through `set_content_preserving` so it
  is **one undo step** that keeps folding, then jumps the cursor there (`_goto_row` +
  `reveal_cursor`).
- **No Refresh button**: `changeEvent` re-reads on activation, calling `_refresh_marks`
  (cheap, keeps scroll + filter) and rebuilding only when `_current_signature()` shows a
  gating option changed.
- `OUT_TSS_TotalEnd` is shown **disabled** — `outputTypTss` (cwatm `globals.py`) has no
  `totalend`, it is map-only.
- Safety net: if a future `cwatm/metaNetcdf.xml` shipped **without** `priority` flags the
  default view would be empty, so `_available_varnames` falls back to the full list and
  says so in the status line (`_priority_missing`). It does not fire with the current xml.

## Data Visualization internals

### Basin viewer infrastructure (`src/gui/widgets/basin_viewer.py`)
This module no longer holds a viewer window — the classic native-canvas / Mercator
`BasinWindow` + `BasinCanvas` were **removed** (there is only one basin viewer now:
the folium EPSG:4326 one in `basin_viewer2.py`, below). What remains here:
- **`BasinViewer`**: the data loader (ups.nc/mask NetCDF loading, `Title`/`MaskMap`
  lookup, placeholder resolution) used by `show_basin2`.
- **`BasinDataHelpers`**: a mixin of the display-agnostic helpers (`_build_ups_rgba`/
  `_build_mask_rgba` overlay images, `_field_gauges`/`_mask_start_point`/
  `_largest_ups_point`/`_ups_text` field readers, `_mask_bbox`, `_run_gauge_check`) —
  `BasinWindow2` inherits it. They only read `self.basin_data/lats/lons/mask_data`.
  The ups.nc overlay's valid cells are drawn at **full per-pixel alpha (255)** so the
  transparency slider's opaque extreme fully hides the OSM basemap.
- **Networking / WebGL**: the app-lifetime `osmtile://` scheme handler
  (`_get_tile_handler`) serves the map pages **and** basemap tiles/WMS with Python
  `requests` (bypasses a proxy that blocks Chromium, caches results); reused across
  every basin/NetCDF window. `cwatm_gui.py` sets `QTWEBENGINE_CHROMIUM_FLAGS=
  "--disable-gpu --no-sandbox --use-gl=angle --use-angle=swiftshader"` (swiftshader =
  **software WebGL**, needed by the Leaflet maps) and `AA_ShareOpenGLContexts`.
- **Gauge-in-mask / PathOut checks**: module-level `build_mask_context`,
  `gauges_inside`, `pathout_exists`, `find_largest_ups_gauge` (used by the main window).

### Basin Viewer (`src/gui/widgets/basin_viewer2.py`) — folium / EPSG:4326
**Tools ▸ Show Basin**: the basin viewer in a **single**
view, built on **folium** (`folium.Map(crs='EPSG4326')` → Leaflet) in
QtWebEngine. Rewritten from the earlier Plotly/MapLibre experiment (which warped
the raster onto a Mercator basemap and did not render well).
- **Projection = EPSG:4326** (`crs='EPSG4326'`), matching the CWatM results
  (ups.nc, mask, and the NetCDF Analyse maps are all plain lon/lat). So the
  overlays need **no rasterio reprojection**: `_build_ups_rgba`/`_build_mask_rgba`
  (inherited from the `BasinDataHelpers` mixin, with the marker/field/check helpers)
  are added as `folium.raster_layers.ImageOverlay`
  with their lon/lat corner **bounds** and `mercator_project=False` — drawn 1:1,
  so the raster stays **crisp** (no Mercator warp blur). `pixelated=True` +
  nearest-neighbour `_upscale_rgba` keep the cell edges sharp.
- **Basemap = WMS (not XYZ tiles)**: OSM XYZ tiles are Web-Mercator and **cannot**
  align on an EPSG:4326 map — using them left the basemap blank and fired a storm
  of failing tile requests (extremely slow). The basemap is instead a **WMS**
  layer (`L.tileLayer.wms`), which returns imagery in the map's own CRS so it
  aligns exactly with the lon/lat overlays. The `_B2_PROVIDERS` selector holds
  **EPSG:4326 WMS layer names** (OSM-WMS / TOPO-OSM-WMS / SRTM30-Colored-Hillshade
  / Dark) served by the terrestris OSM WMS through the `osmtile://wms/…` handler
  branch (query forwarded verbatim, Python-fetched, cached, proxy-proof). The
  Preferences default (a Mercator XYZ key) falls back to `OSM-WMS`.
- **Markers are CSS teardrop pins** (`L.divIcon`, `.cwatm-pin`, ~22 px, the
  `folium.Icon` look but self-contained — no font-awesome, which is stripped):
  red gauges labelled **1..N** (the station number, from `setRedAll`'s forEach
  index), blue **M** = mask-start, black (blank) = last clicked.
  Created/moved by JS helpers (`setRedAll`/`setBlue`/`setBlack`/`clearBlack`) so
  Create gauge / Create mask / Copy actions update them live. The map cursor is a
  plain **arrow** (Leaflet's grab/hand cursor is overridden via CSS).
- **Gauge editing (working list `self._gauges`)**: the red pins are a **working list**
  of `(lon, lat)`, **seeded** from the live Gauges box on open
  (`BasinWindow2._field_gauges` overrides the mixin to read `gauges_field` only, no
  settings-file fallback). **Create gauge** *appends* the clicked point as a new
  numbered pin (it no longer replaces the set); **clicking a pin** removes it
  (`B2DEL <idx> <nonce>` → `_on_web_title` → `_remove_gauge`, popping it from the list),
  and the remaining pins **renumber** automatically (index-based labels). **Copy Gauge**
  commits the *whole* list to the Gauges box (`lon lat …`, which auto-applies to the
  settings) and re-runs the gauge-in-mask check. `_refresh_markers` always draws
  `self._gauges`. (Since the window is modal, the box can't change underneath it, so
  seeding once is safe.)
- **Page assembly**: folium's map is rendered, then the sizing CSS and the helper
  `<script>` are **string-inserted** into the HTML (before `</head>` / `</html>`)
  — *not* via `folium.Element`, which re-renders the string as a Jinja template
  and mangles JS/CSS braces. The sizing CSS (`html,body{height:100%}` +
  `.folium-map` absolute-fill) is essential: a standalone folium page gives
  `<body>` no height, so the map would otherwise collapse to 0 px (blank). The
  helper script is inserted last so folium's global map/overlay vars already
  exist when it runs.
- **Menu-driven** (`_build_menubar`): **File** (Load JSON, Load shape), **Mask** (Hide
  Mask, Create new Mask, Copy Mask, Zoom to Mask), **Gauge** (Create gauge, Copy
  gauge) — tooltips moved from the buttons to the `QAction`s. Mask/Gauge are **also**
  kept as buttons below the menu bar (this window's core, most-clicked actions — same
  reasoning as Batch Run's Run all/Stop all); the menu items call the exact same slots
  and are kept in sync with the buttons' text/enabled state at every mutation site
  (`_toggle_mask_from_menu`, `_use_coordinates`, `_create_gauge`, `_remove_gauge`,
  `_create_new_mask`). Behaviour: Hide/Show Mask, Create new Mask (same
  `mainwarm -vgm` temp-ini call; `updateMask` swaps the mask ImageOverlay in
  place — creating it if the basin had none), Copy Mask, Create gauge / Copy Gauge
  (see gauge editing above), Zoom to Mask (`fitBounds`), **OSM transparency slider**,
  basemap selector (`setBasemap` swaps the `L.tileLayer.wms` in place). There is no
  Exit button any more — the window closes via its title-bar X or Alt+F4. Clicks
  route via `document.title` (`B2 <lon>|<lat>`) → `_on_web_title`.
- **OSM transparency slider** (`_on_opacity_changed`) — same coupled model as NetCDF:
  as it goes 0 → 100% the **OSM basemap opacity** rises 0.0 → 1.0 (`setBaseOpacity` →
  `_tile.setOpacity`) and the **ups.nc/mask overlay opacity** falls 1.0 → 0.5
  (`setOverlayOpacity`). So **0% = OSM hidden + data fully opaque** (only ups.nc/mask,
  over white) and **100% = OSM fully visible + data 50% opaque on top**. The **initial**
  value comes from **Preferences ▸ Display ▸ Initial map transparency** (`display_format.get_transparency()`,
  default 100). `setBasemap` re-applies `_baseOp` on a basemap switch.
- **File ▸ Load JSON** (`_load_json`): opens a `*.geojson`/`*.json` file (starting in
  the settings file's folder), parses it with `json.load`, and draws it via the
  `addGeoJson` JS helper (`L.geoJSON` — orange lines/polygons, circle markers for
  points, feature `properties` shown in a popup, `fitBounds` to the layer). Kept in
  its own `geoGroup` layer under the pin markers; parse errors are reported, never
  crash.
- **File ▸ Load shape** (`_load_shape`): opens a `*.shp` file (its companion
  `.shx`/`.dbf` must sit alongside it) and draws it exactly like Load JSON — read
  with **pyshp** (`shapefile.Reader`, pure Python, no GDAL/fiona dependency), each
  `ShapeRecord` converted to a GeoJSON `Feature` (`shape.__geo_interface__` for the
  geometry, `record.as_dict()` for the properties) into one `FeatureCollection`, then
  handed to the **same** `addGeoJson` JS helper — so it lands in the same `geoGroup`
  layer, styled and popped-up identically. Coordinates are assumed already lon/lat
  (WGS84), like Load JSON — no reprojection. Read/parse errors are reported, never
  crash.
- **JS readiness**: helpers exist once Leaflet has loaded, so `_js()` **queues**
  calls until `loadFinished`, then flushes and re-applies markers from the live
  boxes (`_refresh_markers`).
- **Networking / offline**: the page is served **same-origin** from the shared
  `osmtile://` handler (`osmtile://map2`, `set_html2`); WMS basemap requests go
  through the handler's `wms` branch — Python-fetched, cached, proxy-proof. Only
  the assets the map needs are kept: folium's Leaflet + awesome-markers CSS/JS are
  **inlined** by `_inline_remote_assets` (each `<script src>` / `<link>` fetched
  with Python `requests`; CSS `url()` marker PNGs/fonts become `data:` URIs), and
  the unused CDN libs (jquery, bootstrap, font-awesome) are **stripped** by
  `_strip_unused_assets` — so the page is self-contained, ~0.3 MB (was ~4.6 MB),
  and renders behind the proxy that blocks Chromium. Any inlining failure leaves
  the original markup (never worse than plain folium).

### Timeseries Analysis (`src/gui/widgets/analysis_timeseries.py`)
**Analyse ▸ Timeseries** opens a **`.csv`-only** file dialog (starting in the resolved
**PathOut** directory when a settings file is loaded) and shows the result as a
**Plotly** line chart (`plotly.graph_objects`, `mode="lines"`) rendered in a
QtWebEngine window (plotly.js inlined — no CDN).
- **Menu bar** (`_build_menubar`): **File** (Save as csv, Save HTML), **Action**
  (Compare, Load observed, Flow duration, Flow regime) — tooltips moved from the former
  buttons to the `QAction`s. **Backward / Forward** stayed as buttons (the frequently
  clicked pair, right below the plot); `observed_action` replaces the old
  `observed_button` and still toggles its text between "Load observed" / "Clear
  observed".
- **Flow duration / Flow regime** (Action menu; `_show_flow_duration` /
  `_show_flow_regime`): open `analysis_flow_duration.FlowDurationWindow` /
  `analysis_flow_regime.FlowRegimeWindow` on the **currently displayed column**
  (`self.series[self.index]`, dates converted from the day-first csv format to ISO via
  `_flow_duration_regime_dates`), **cut to the displayed period** (the range slider,
  `_flow_input` via `_window_bounds`). An open window **follows the slider**: the
  debounced `_range_timer` also fires `_refresh_flow_windows`, which recomputes it for
  the series it was opened on (`_flowdur_index` / `_flowregime_index`) through
  `FlowDurationWindow.set_series` / `FlowRegimeWindow.set_data` (a period too short for
  a regime keeps the last diagram and says so in the header). See their shared description under **Analyse ▸
  NetCDF** below — both windows are the same code whether opened from here (a csv
  column) or from the NetCDF map (a clicked cell).
- CWatM result CSV layout: series names in **row 4 from column 2**; **column 1 = date**
  (daily/monthly/yearly) and columns 2+ = values from row 5 on.
- Multiple result columns are shown **one at a time** with **Forward / Backward**
  buttons (hidden for a single column).
- A blue **Compare** button (bottom-left) opens another result `.csv` and overlays its
  series on the current plot; both axes are rescaled to the combined min/max of all
  series and a **legend** is shown. Overlays follow Forward/Backward (matching column
  index, else the compare file's first column). Multiple Compare files can be stacked.
- A **Load observed** button (right of Compare) overlays an **observed** series (a CWatM
  result `.csv` — first result column — or a simple `date,value` two-column `.csv`;
  `_parse_observed`) as a **dashed high-contrast** line and shows goodness-of-fit
  metrics — **KGE / NSE / PBIAS / RMSE** (+ n) — in a label under the description
  (`src/gui/utils/metrics.py`). Metrics are computed on the **date overlap** of the
  observed series and the **currently shown** simulated column (`_aligned_obs_sim`
  aligns via a pandas day-normalised key, so a `dd/mm/yyyy` sim and an ISO observed
  match), and recompute on Forward/Backward. The button toggles to **Clear observed**.
- A **two-handle range slider** below the plot (`RangeSlider`, reused from
  `analysis_watercycle.py`; shown only with >2 time steps) **shrinks the displayed
  period** from either end — the plot's x-axis (and y-axis) rescale to the selected
  `[lo, hi]` index window (`_window_bounds`; the "Displayed period: … – …" label above
  it updates live). The **same window defines the period** over which the observed
  goodness-of-fit metrics are computed (`_aligned_obs_sim` iterates only `lo..hi`), so
  KGE/NSE/PBIAS/RMSE follow the slider. Metrics/label update immediately on drag; the
  heavier figure rebuild is debounced 200 ms (`_range_timer`). The window is display/
  metrics only — **Save as csv still writes every day** (full series), unchanged.
- The variable name is the part of the file name **before the first `_`** (e.g.
  `discharge_daily.csv` → `discharge`); its **unit**, **long_name** and **description**
  are looked up in `cwatm/metaNetcdf.xml` (regex, as the file has non-XML `#` lines):
  long_name = figure title, unit = y-axis label, description (trailing `[Array]`/`[Flag]`
  stripped) = caption below the figure.
- Can also be built **in-memory** (not from a CSV) via `TimeseriesWindow.from_point(...)`
  — used by **Analyse ▸ NetCDF ▸ Display timeserie** to plot a grid cell's series,
  rendered identically but with a **legend** labelled by the point location.
- **Save as csv** button (left of Save HTML, `_save_csv`): writes the current series +
  any overlaid point series to a CWatM result `.csv` **byte-format-compatible with
  `discharge_daily.csv`** — `Timeseries,settingsfile: …` header, `xloc`/`yloc` rows
  (`%#.4f`), `Date,G1..Gn` header, `DD/MM/YYYY` dates, values as `,%13.10g`, CRLF line
  endings. Station coords come from `xlocs/ylocs` (main) or are parsed from a point's
  `lon …, lat …` label (overlays); re-opening the file reproduces the data.

### NetCDF Analysis (`src/gui/widgets/analysis_netcdf.py`)
**Analyse ▸ NetCDF** draws the variable **on a map**: a **folium** (Leaflet,
**EPSG:4326**) page with the grid as a `folium.raster_layers.ImageOverlay` over an
**OSM WMS** basemap (same WMS providers as **Show Basin**), served same-origin
through the shared `osmtile://` handler so it renders behind the proxy that blocks
Chromium. `NetcdfWindow` **subclasses `NetcdfDataBase`** (`analysis_netcdf_base.py`)
and reuses its data loading (`_load`), meta lookup (`_lookup_meta`) and point-series
extraction (`_point_series`); the rendering/interaction is implemented here. (This is
the former "NetCDF2"; the plain Plotly heatmap that used to be "NetCDF" was removed,
so this folium viewer is now simply **NetCDF**.)
- **Menu bar** (`_build_menubar`): **File** (Save HTML, Load JSON, Load shape),
  **Action** (Fast Display Timeserie, Total Timeseries, Compare A−B, Flow duration,
  Flow regime), and a top-level clickable **Display** action (not a dropdown — the
  same pattern as the main window's "CWatM AI") opening a small non-modal window
  (`_build_display_dialog`/`_open_display_dialog`) holding **Colour scale** / **OSM
  transparency** / **Basemap**, moved out of the inline row below. Play, the timestep
  timeline/slider, **Speed** and **Log scale** stayed inline (frequently used while
  animating). The map itself also has a **right-click menu** — see below.
- **File ▸ Load JSON / Load shape**: identical to **Show Basin**'s File menu items of
  the same name — same file dialogs, same shared reader functions
  (`basin_viewer2._read_geojson_file` / `_read_shapefile`, imported here rather than
  duplicated) and the same `window.addGeoJson` JS drawn into this window's own
  `_helper_js` (its own `geoGroup` layer group; the JS is byte-identical to Show
  Basin's, just under the `NC2ERR` error-title prefix instead of `B2ERR`). `pyshp` is
  imported lazily inside `_read_shapefile`, so it costs nothing at GUI startup — see
  the Requirements/`pyshp` note in `CLAUDE.md`.
- **Projection = EPSG:4326** (`crs='EPSG4326'`), matching the CWatM `.nc` output, so
  the raster needs **no rasterio reprojection** — each timestep is colourised in
  numpy to an RGBA image (`_colorize`: fixed `zmin/zmax`, NaN → transparent alpha,
  flipped north-up + west→east to match the lon/lat corner **bounds**) and handed to
  Leaflet as a **base64 PNG `data:` URI** (`_rgba_to_datauri`, via `QImage`), drawn
  1:1 with `pixelated=True` so cells stay crisp. LUTs (`_lut`, from
  `plotly.colors.sample_colorscale`) and per-`(scale, timestep)` URIs are cached.
- **Basemap = WMS**, not XYZ tiles (XYZ are Web-Mercator and cannot align on an
  EPSG:4326 map — same reason as Show Basin). The `L.tileLayer.wms` is kept **below**
  the overlay (`bringToBack`) so the overlay-transparency slider fades the data to
  reveal the basemap.
- **Controls (no description caption** — the NetCDF description label is intentionally
  omitted here): row 1 = timestep slider + **▶ Play** (driven by a Qt `QTimer`, since a
  folium overlay has no built-in animation) + date + **Speed** + **Log scale**, plus
  `ts_progress` / `ts_elapsed_label` / `ts_cancel_button` (shown only while a background
  point-series read is in flight — shared by Total Timeseries, Flow duration and Flow
  regime, see below). **Colour scale**, **OSM transparency** and **Basemap** moved into
  the **Display** window (`setBasemap` still swaps the WMS in place; colour-scale changes
  still rebuild the overlay URI + HTML colour-bar). Play/slider/colourscale changes
  rebuild the overlay's `data:` URI in Python and push it with `_ov.setUrl(...)`.
- **OSM transparency slider** (`_on_opacity_changed`): one slider fades **both** layers
  as it goes 0 → 100% — the **OSM basemap opacity** 0.0 → 1.0 (`setBaseOpacity` →
  `_tile.setOpacity`) **and** the **NetCDF overlay opacity** 1.0 → 0.5 (`setNcOpacity`
  → `_ov.setOpacity`). So **0% = OSM hidden + NetCDF fully opaque** (only the data, over
  white) and **100% = OSM fully visible + NetCDF 50% opaque on top**. The **initial**
  value comes from **Preferences ▸ Display ▸ Initial map transparency** (`display_format.get_transparency()`,
  default 100). `setBasemap` re-applies `_baseOp` when the layer is swapped. (There is no separate
  Hide OSM button — sliding to 0% hides the basemap.)
- **Log scale** button (checkable, `_toggle_log`): maps the values to colour on a
  **logarithmic** scale (`_colorize`: `log1p(clip(z)-zmin) / log1p(zmax-zmin)`, which
  tolerates a zero/negative minimum) instead of linear; the `_uri_cache` key includes
  the log flag so linear/log frames don't collide, and toggling re-pushes the current
  frame. The info-label value read-out stays the raw cell value.
- **Coordinate/value read-out**: an `info_label` under the map shows "Click on the map
  to see coordinates and values"; on each click it becomes
  `Lon: … | Lat: … | Value: … <unit> | <timestep>` (the clicked cell's value at the
  current timestep), like Show Basin's info label.
- **Click-to-mark**: clicking routes the lon/lat via `document.title` (`NC2 <lon>|<lat>`,
  read through `titleChanged` like the basin viewers) → `_on_web_title`, which snaps to
  the nearest cell, stores `_clicked`, drops a red **pending** pin, and updates the
  read-out. Pressing
  Either **Fast Display Timeserie** or **Total Timeseries** adds that cell to the
  persisted point set and (re)builds the Timeseries window from **all** points
  (`_open_or_refresh_timeseries` — recreated from scratch each time since
  `TimeseriesWindow` has no remove-series API: first point → `from_point`, rest →
  `add_point_series`; the mode is remembered in `self._ts_full`). **Two modes**
  (`_point_series(..., full=)`), because reading one cell across time is one chunk read
  **per timestep** (CWatM `.nc` is chunked `[1, lat, lon]`), so the cost scales with the
  number of timesteps:
  - **Total Timeseries** (`full=True`) — **every timestep** (dates from
    `_point_source["full_time_labels"]`), so the plotted / **Save as csv**'d series has
    every day. This can be **slow** (tens of seconds on a long / networked file), so it
    is read **off the GUI thread** by `_PointSeriesWorker` (a `QThread` calling
    `_series_for(p, full=True)` per point) with **progress + elapsed time + Cancel**
    (`_start_point_series_read_ui`/`_stop_point_series_read_ui`/
    `_update_ts_elapsed_label`/`_cancel_point_series_read` — shared UI plumbing also used
    by Flow duration/regime below; `ts_progress`: busy/indeterminate for a single point,
    per-point `n/m` for several). Cancel calls the worker's cooperative
    `request_stop()` (checked between points — **never `QThread.terminate()`**, since the
    worker holds the shared dataset handle below) and emits `cancelled`. Both Timeseries
    buttons/actions are disabled while loading, the newest request wins (`_ts_next`
    chain), and `closeEvent` `request_stop()`s and waits on every in-flight worker
    (`_ts_worker`, `_fdc_worker`, `_regime_worker`).
  - **Speed** (`analysis_netcdf_base.py`, `NetcdfDataBase`): `_open_dataset_safe` opens
    with `xr.open_dataset(path, chunks={})`, wrapping variables as **dask** arrays that
    respect the file's own on-disk chunking (CWatM `.nc` is chunked `[1, lat, lon]`) so
    chunk decompression parallelises over dask's threaded scheduler instead of one
    Python-level read per timestep. `_shared_point_dataset` opens the file **once** per
    window (lock-guarded against the open race) and every point-series read reuses that
    handle instead of reopening; `_point_series` additionally caches by
    `(lati, loni, full)` so re-reading an already-clicked point (e.g. re-running Flow
    duration on the same cell) is free. `_load()` resets the shared handle/cache whenever
    it (re)runs, so **Compare A−B**'s second file never mixes cached values with the
    first.
  - **Fast Display Timeserie** (`full=False`) — only the **strided map-animation frames**
    (`time_indices` / `time_labels`, `_MAX_FRAMES`), so it is quick (far fewer chunk
    reads) but the series has **gaps**. Read **synchronously** (no progress bar), like the
    original behaviour.

  Both build from the precomputed series in `_build_ts_window(..., full=)` (dates chosen
  to match the mode) on the main thread. Confirmed points are drawn by
  **`_update_map_markers`** as **numbered pin icons** (`L.divIcon`, `.nc-pin` CSS
  teardrop) whose fill is the point's **Timeseries line colour** (index-derived:
  `TimeseriesWindow._MAIN_COLOR` / `_COMPARE_COLORS`), so map marker N == legend line N.
- **A left click toggles a point** (`_toggle_point`): the map click (and a click on a
  gauge reference pin) fires `NC2 <lon>|<lat>|<nonce>`; the cell is snapped
  (`_cell_of`) and **added** to `_displayed_points` as a new numbered pin, or **removed**
  when it is already selected - so points are collected directly on the map, no
  Timeseries run needed in between. An open Timeseries window follows every change
  (`_open_or_refresh_timeseries(open_if_closed=False)`); the newest selection is
  `self._clicked` (Flow duration/regime), falling back to the newest remaining point
  when it is removed. There is no separate "pending" marker any more.
- **Points persist & are removable**: `_displayed_points` holds the confirmed cell
  centres as `(lon, lat)`; closing the Timeseries window (`_on_ts_closed`) **keeps**
  the pins (reopening re-plots the same points). **Clicking a numbered pin removes it**
  everywhere — the pin's click fires `document.title='NC2DEL <n> <nonce>'` (nonce so a
  repeat refires `titleChanged`; `L.DomEvent.stopPropagation` keeps the map click from
  re-selecting the cell) → `_on_web_title` → `_remove_point`, which drops it from the list, renumbers/
  recolours the remaining pins, and refreshes the Timeseries **only if it is open**
  (`open_if_closed=False`, so removing a pin never pops the plot open).
- **Gauge reference pins**: the main-window **Gauges** stations (read from the parent's
  `gauges_field` via `_parse_coord_pairs`, `_gauge_stations`) are drawn as **smaller
  red numbered pins** (`.nc-gauge` / `gpin`, in their own `gaugeGroup`, `setGauges`) —
  clicking one selects its cell like a map click (its own click handler posts the
  gauge's lon/lat); applied on
  load (`_refresh_gauges` in `_on_loaded`).
- **Right-click menu on the map** (`_on_web_context_menu`/`_open_map_action_menu`):
  `self.web_view.setContextMenuPolicy(Qt.CustomContextMenu)` + `customContextMenuRequested`
  opens a plain Qt menu mirroring every **Action**-menu item (`_mirror(source_action,
  slot)`), working off the selection — the Timeseries items plot every selected point, Flow
  duration/regime `self._clicked` (the newest selection). It is a pure Qt signal with **no JS
  hit-testing dependency**: earlier attempts gated the menu on right-clicking a gauge pin
  specifically (JS `hitTestGauge`) and used `Qt.PreventContextMenu`, which suppressed
  Qt's native menu without reliably delivering the JS click; both the gauge dependency
  and the hit-testing JS were removed, so right-click now works **anywhere on the map**,
  gauges configured or not.
- **Flow duration / Flow regime** (Action menu; `_show_flow_duration`/
  `_show_flow_regime`, no arguments): operate purely on `self._clicked` — the most recently
  selected cell, never accumulated (unlike the numbered Timeseries points). With nothing clicked yet they
  show "Click a point on the map first, then press Flow duration/regime." A background
  `_PointSeriesWorker` (`_fdc_worker`/`_regime_worker`) reads the point's full series
  through the same shared-dataset/cache/progress/cancel plumbing as Total Timeseries;
  `_on_fdc_ready`/`_on_regime_ready` then build a `FlowDurationWindow`/
  `FlowRegimeWindow` (`src/gui/widgets/analysis_flow_duration.py` /
  `analysis_flow_regime.py`) from the single point. Reached identically from **Analyse ▸
  Timeseries ▸ Action ▸ Flow duration/regime** on a loaded csv column — same two window
  classes, same button layout, only the data source (a clicked NetCDF cell vs. a csv
  column) differs.
  - **`FlowDurationWindow`**: `compute_flow_duration(dates, values)` ranks each
    calendar year's values into an exceedance-probability curve (Weibull plotting
    position, `probs = 100·m/(n+1)`), plus **cross-year percentile bands** — each year's
    curve interpolated onto a common 0–100 %/1 % grid (`np.interp`), then
    `np.nanpercentile` across years. Plot: one line per year (width 1.5, opacity 0.6),
    the **cross-year average** in black at width **1.5** (not double — an earlier pass
    doubled it, reverted per feedback), and two `fill="toself"` bands — 0–100 % very
    light gray, 40–60 % light gray. Buttons (left→right): **Remove single years**
    (toggles to *Show single years*, hides/shows the per-year lines), **Show Percentile
    bands** (toggles to *Hide Percentile bands*), a stretch, **Save as csv**
    (`_duration_table`/`_save_csv`: rows = the probability grid, columns = one per year,
    or `"{label} {year}"` with more than one input series), **Save HTML**.
  - **`FlowRegimeWindow`**: single-gauge only by construction (one clicked point/one csv
    column). `compute_regime(dates, values)` detects **daily vs. monthly** resolution
    from the median timestep gap (≤3 days = daily, 25–35 = monthly, else raises) and
    groups by `(month, day)` or `month` across years — **29 Feb is dropped** so every
    year contributes the same 365 daily rows; x-values are placed in a fixed non-leap
    reference year purely so Plotly's date axis formats the month labels. Same button
    layout as Flow duration (years/bands/save-csv/save-HTML); `_regime_table`/
    `_save_csv` write rows = `"MM-DD"` (daily) or `"MM"` (monthly) in calendar order,
    columns = year.
- **JS readiness**: helper calls are **queued** until `loadFinished` then flushed
  (`_js` / `_on_loaded`), like Show Basin. **Save HTML** writes the self-contained
  page (its basemap WMS only resolves inside the app's `osmtile://` scheme, so an
  external browser shows the data overlay only). Window geometry remembered via
  QSettings key `netcdf2`.
- **Compare A−B** (`_toggle_compare` → `_enter_compare`/`_exit_compare`): loads a second
  `.nc` and shows **this − other** per timestep on a **diverging** scale. It calls
  `_load(B)` (restoring A's `_point_source` afterwards), checks the grids match
  (`frames[0].shape`), builds `diff[i] = A[i] − B[i]` over the `min(len)` overlapping
  frames, sets a **symmetric** `zmin/zmax = ±max|diff|`, the `RdBu (diff)` colour scale
  (blue = negative, red = positive) and **linear** scale. `_apply_data_swap` re-syncs the
  slider/colour-scale/log controls, clears `_uri_cache`, pushes the frame + colour-bar,
  and disables the point-timeserie buttons (a difference has no single source series). The
  button toggles to **Clear compare**, which restores A from the saved `_orig` state.
  (Frames are aligned by index — the strided animation frames — so compare same-period
  runs.)

### Watercycle Analysis (`src/gui/widgets/analysis_watercycle.py`)
**Analyse ▸ Watercycle** opens a **`.csv`-only** file dialog (starting in the resolved
**PathOut** directory) for a CWatM **`WaterCycle_areasum_monthtot.csv`** result and shows
the overall water balance as a Plotly **`go.Sunburst`** rendered in a QtWebEngine window
(plotly.js inlined — no CDN). The balance computation is **ported from the stand-alone
`Watercycles1.py`** template (see *Watercycle template scripts* in CLAUDE.md).
- **Window/plot title** = the settings-file **`Title`** (from the settings file named in
  the csv header row 1 `settingsfile:`, else the title loaded in the main window —
  `_read_settings_title`).
- **Subtitle** "Station: lon: x, lat: y" — **x** from csv **row 2, col 2** (`xloc`), **y**
  from **row 3, col 2** (`yloc`), each to 3 decimals (`_read_station` / `_fmt3`). With
  **multiple stations** it reads "Station k/N: lon: x, lat: y" (`_station_label`).
- **Multiple stations** (`_load_data`): a WaterCycle csv can hold several stations laid
  out side by side — after the Date column each station occupies a **fixed-width block**
  of variable columns (the ~79 `<var>_<unit>` names are **repeated** per station and its
  lon/lat is repeated across its block in rows 2/3, matching CWatM's
  `writeFileHeaderWaterCycle`). The block width is auto-detected from the **first repeat**
  of the leading column name (single-station csvs have no repeat → whole width, N=1), the
  numeric data is read **headerless** (`skiprows=4, header=None`, so pandas doesn't
  de-duplicate the repeated names) into `self._full`, and `_select_station(idx)` slices
  that station's block into `self._df` with the canonical column names and refreshes
  `self.lon/lat` + `self._cellAreaSum`. A name can legitimately repeat **within** one
  block (CWatM's watercycle list holds `act_livConsumption` twice), so `_select_station`
  mangles repeats to `name.1` pandas-style — `df[name]` stays a Series (first
  occurrence), exactly like the old header-based read. Blue **◀ Backward / Forward ▶** buttons (same
  styling as the Timeseries window, centred in the bottom row left of Save HTML) switch
  stations and rebuild the figure (`_prev_station`/`_next_station`/`_goto_station` →
  `_refresh_figure`); they are **hidden when N=1** and enable/disable at the ends
  (`_update_station_nav`).
- **Month range slider** (`RangeSlider`, two draggable handles over the csv's months):
  the sunburst is recomputed for the selected **[start, end]** window (defaults to the
  full span); dragging shows the range live and **debounces** the heavy rebuild (200 ms
  `_rebuild_timer`). The 3rd subtitle line is the covered range (`_date_range_text`).
  The minimum gap between the handles is normally **1 month**, but **2 months** when
  the low handle sits at the very start of the range (`low == minimum`) — the storage
  *change* the sunburst measures needs one month *before* the window as its baseline
  (`baseline_idx = start_idx − 1` in `_build_figure`); at `start_idx == 0` there is no
  month before, so month 0 is sacrificed as the baseline and the flux data actually
  starts one month later. A 1-month gap there would describe a **zero**-month flux
  window instead of one, unlike everywhere else on the slider — the 2-month floor at
  the start keeps "N months selected" meaning the same thing regardless of where the
  window starts. Flow Diagram shares the same `RangeSlider` and gets the identical
  slider behaviour for consistency, even though its own balance sum has no baseline
  month to protect.
- **Sunburst computation** (`_build_figure`, ported from `Watercycles1.py`):
  - Data read once in `_load_data` (headerless per-station slice, see above); `cellAreaSum` =
    `cellArea_sum_m3[0] / days_in_month[0]` (monthly cell-area is summed over the
    month's days). Dates parsed from column 0 (`%d/%m/%Y`).
  - A `Vars` table classifies each variable as **flux** or **store** and assigns it to
    an **Inputs / Outputs / Storage / Evapotranspiration / Transpiration** wedge. Fluxes
    are **summed** over the window (`flux_start:end_idx`); stores use the **change**
    `store[end_idx] − store[baseline_idx]` (baseline = the month before the window start,
    so the full-span default reproduces the template). Unit suffix per variable:
    `M`→`_areasum_m3`, `M3`→`_sum_m3`, `M3/S`→`_m3s-1` (discharge × 86400 s/day). Columns
    whose variable is **absent are skipped** (e.g. the optional `Glacier` pair,
    added only when both `GlacierMelt`/`GlacierRain` columns exist).
  - The wedge assembly computes `total_input/output/store`; **negative** total storage is
    folded into discharge as "Storage (out)", otherwise the residual is a **"Balance"**
    wedge ("Storage (into)"). The root wedge shows the station **lon/lat** (monospace);
    hover shows per-wedge **% of parent**, **volume (km³)**, and **mm/year** (`Σm³ /
    cellAreaSum × 1000 / noyears`; the discharge wedge shows **m³/s** instead), plus the
    basin name / area / date-range on the root.
- **Save HTML** button (same as Timeseries): saves the self-contained Plotly plot to a
  user-chosen `.html`, suggesting the resolved PathOut directory.
- Themed like the other Analyse windows (Plotly template + layout overrides from
  `theme`); the plot **fills the page** (`themed_plot_page` + a `100vh` style so there is
  no internal scrollbar); window geometry remembered via QSettings key `watercycle4`.

### Flow Diagram Analysis (`src/gui/widgets/analysis_flowdiagram.py`)
**Analyse ▸ Flow Diagram** opens the **same** `WaterCycle_areasum_monthtot.csv`
result file as Watercycle and shows the overall water balance as a Plotly
**`go.Sankey`** flow diagram (precipitation → rain/snow → soil/groundwater/runoff
→ discharge, plus withdrawal/consumption), rendered in a QtWebEngine window
(plotly.js inlined — no CDN). The Sankey nodes/links/colour helpers and the
`build_sankey` builder are **ported from the stand-alone
`sankey_waterbalance_month.py`** template.
- **Header + subtitle + month range slider + multi-station support are identical to
  the Watercycle window** — `RangeSlider` and `WatercycleWindow`'s csv-parsing/station
  helpers (`_read_station`, `_read_settings_title`, `_load_data`, `_fmt_month`,
  `_date_range_text`, `_select_station`, `_station_label`, `_goto_station`,
  `_prev_station`, `_next_station`, `_update_station_nav`) are imported/reused from
  `analysis_watercycle.py`; only `_refresh_figure` is overridden to rebuild the **Sankey**.
  Window title = settings-file **`Title`**, subtitle = station **lon/lat** (csv row 2/3
  col 2, "Station k/N:" when several) + the selected month range. Multi-station csvs get
  the same blue **◀ Backward / Forward ▶** buttons.
- Link values are **long-term averages in mm/yr** over the basin area, computed
  over the **slider-selected month window** (a shorter window rescales `nyears`);
  missing csv columns read as 0 so an incomplete watercycle csv still renders.
  Per-link **source→target SVG gradients** (`_GRADIENT_JS`) are injected into the
  exported HTML.
- **Save CSV** button (bottom-left, both Watercycle and Flow Diagram): writes the
  numbers behind the current plot (station + month window) - a few meta lines (Basin,
  lon, lat, Period) then the table (Watercycle: Group, Component, Volume_km3,
  mm_per_year, Percent, Discharge_m3s; Flow Diagram: Flow, From, To, mm_per_year).
  Suggested name `watercycle.csv` / `flowdiagram.csv` in PathOut, changeable.
- **Save HTML** button (same as Watercycle): saves the self-contained Plotly plot,
  suggesting the resolved PathOut directory. Window geometry remembered via
  QSettings key `flowdiagram`.


