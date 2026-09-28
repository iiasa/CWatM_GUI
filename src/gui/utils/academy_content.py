"""CWatM Academy - the ten-level lesson curriculum.

Pure data, no Qt: a list of dicts, one per level, consumed by
``src/gui/widgets/academy_window.py``. Each level teaches a real, existing GUI
feature - the curriculum climbs the same Beginner -> Advanced -> Expert feature
ladder the "Skill of user" setting already gates (see CLAUDE.md), so a learner
finishing all ten levels has genuinely toured every part of the settings file
and every menu, not a fictional subset.

This is a first-pass syllabus written from the GUI's own documented behaviour,
not a transcript of the "Learn with Silvia" videos (this tool has no way to
fetch external video content) - replace ``summary``/``teaches`` with the real
lesson text/links whenever that material is available.
"""

LEVELS = [
    {
        "id": 1,
        "title": "Welcome to CWatM",
        "badge": "First Steps",
        "summary": (
            "Every CWatM run starts from a settings file and a catchment. "
            "Drag one in when your companion the Torus asks for it, then "
            "click your catchment's outlet on the upstream-area map - that "
            "one click writes both MaskMap and Gauges into the settings "
            "file for you."
        ),
        "teaches": [
            "Loading a settings file (drag & drop, or File ▸ Load .ini)",
            "MaskMap - the coordinate CWatM delineates a catchment from",
            "Gauges - where discharge is measured and reported",
        ],
        "menu_hint": "File ▸ Load .ini",
    },
    {
        "id": 2,
        "title": "Running CWatM and visualising the Water cycle",
        "badge": "First Run",
        "summary": (
            "The settings file is already set up from Level 1 - all that's "
            "left is pointing PathOut at a real output folder and, if you "
            "like, changing the run period. Then RUN CWATM does the rest; "
            "once it finishes, Analyse ▸ Watercycle shows the whole water "
            "balance as a sunburst. This level is a walkthrough, not a "
            "reading exercise - your companion the Torus will point at "
            "PathOut, the three run-period dates, and RUN CWATM itself, in "
            "order, right where they live in the real GUI."
        ),
        "teaches": [
            "PathOut - where CWatM writes its results",
            "StepStart / SpinUp / StepEnd - the run period",
            "RUN CWATM (Ctrl+R)",
            "Analyse ▸ Watercycle - the water balance sunburst",
        ],
        "menu_hint": "RUN CWATM ▸ Run CWATM",
    },
    {
        "id": 3,
        "title": "Running CWatM",
        "badge": "First Run",
        "summary": (
            "RUN CWATM (Ctrl+R) starts the model in its own process, so a stuck "
            "or crashed run never takes the GUI down with it. Progress shows on "
            "the clock and the live discharge sparkline; the output box streams "
            "CWatM's own log underneath."
        ),
        "teaches": [
            "RUN CWATM / Stop (Ctrl+R)",
            "The progress clock and elapsed/remaining time",
            "The output box and the live discharge sparkline",
        ],
        "menu_hint": "RUN CWATM ▸ Run CWATM",
    },
    {
        "id": 4,
        "title": "Checking Before You Run",
        "badge": "Detective",
        "summary": (
            "Check settingsfile (F4) scans every path in the file, flags the "
            "ones that don't exist, and checks the run dates make sense - "
            "catching the most common \"crashes an hour in\" mistakes before "
            "you spend the time running them."
        ),
        "teaches": [
            "Settings ▸ Check settingsfile / Clear checking (F4)",
            "Reading a red line vs. an orange (inactive) line",
            "The gauge-in-mask and PathOut warnings above RUN CWATM",
        ],
        "menu_hint": "Settings ▸ Check settingsfile (F4)",
    },
    {
        "id": 5,
        "title": "Choosing What CWatM Writes",
        "badge": "Output Artist",
        "summary": (
            "The [OUTPUT] section controls which variables CWatM writes and "
            "how (daily map, monthly total time series, ...). Tools ▸ Add "
            "output variables is a searchable picker so you never have to "
            "remember the exact OUT_TSS_/OUT_MAP_ syntax by hand."
        ),
        "teaches": [
            "The [OUTPUT] section of the settings file",
            "Tools ▸ Add output variables",
            "Tools ▸ Add output Watercycle",
        ],
        "menu_hint": "Tools ▸ Add output variables",
    },
    {
        "id": 6,
        "title": "Looking at Results",
        "badge": "Analyst",
        "summary": (
            "Once a run finishes, Analyse ▸ Output Explorer lists everything "
            "in PathOut - double-click a result and the GUI picks the right "
            "viewer for it: a line chart for a .csv, a map for a .nc."
        ),
        "teaches": [
            "Analyse ▸ Output Explorer",
            "Analyse ▸ Timeseries (a result .csv as a line chart)",
            "Analyse ▸ NetCDF (a result .nc as a map)",
        ],
        "menu_hint": "Analyse ▸ Output Explorer",
    },
    {
        "id": 7,
        "title": "Turning Physics On and Off",
        "badge": "Options Explorer",
        "summary": (
            "The [OPTIONS] section is CWatM's big switchboard - glaciers, "
            "water demand, lakes and reservoirs, groundwater. Tools ▸ Change "
            "Options shows every switch as a tick box with a short explanation, "
            "instead of a wall of True/False lines. This is the first stop "
            "beyond the Beginner view - Advanced and Expert show it in the "
            "editor too."
        ),
        "teaches": [
            "The [OPTIONS] section",
            "Tools ▸ Change Options",
            "The colour-coded Beginner / Advanced / Expert button by the editor",
        ],
        "menu_hint": "Tools ▸ Change Options",
    },
    {
        "id": 8,
        "title": "Forcing and Initial Conditions",
        "badge": "Meteorologist",
        "summary": (
            "[METEO] points CWatM at its climate forcing NetCDFs; "
            "[EVAPORATION] controls how evaporation is computed; "
            "[INITITIAL CONDITIONS] lets a run pick up state saved by an "
            "earlier one instead of always starting cold. All three live in "
            "the Advanced view."
        ),
        "teaches": [
            "The [METEO] and [EVAPORATION] sections",
            "The [INITITIAL CONDITIONS] section (initLoad / initSave)",
            "Why Check settingsfile also verifies the run dates against the "
            "forcing's own time coverage",
        ],
        "menu_hint": "Advanced view → [METEO] / [EVAPORATION] / [INITITIAL CONDITIONS]",
    },
    {
        "id": 9,
        "title": "Many Runs at Once",
        "badge": "Batch Runner",
        "summary": (
            "RUN CWATM ▸ Batch Run runs several scenarios from one settings "
            "file - each row overrides a few keys and gets its own PathOut, up "
            "to several running in parallel. Every run, batch or single, is "
            "logged in the Journal of Runs so you can reopen its results or "
            "reload its settings later."
        ),
        "teaches": [
            "RUN CWATM ▸ Batch Run…",
            "RUN CWATM ▸ Journal of Runs",
            "RUN CWATM ▸ Windowed Run CWatM (a second run in its own window)",
        ],
        "menu_hint": "RUN CWATM ▸ Batch Run…",
    },
    {
        "id": 10,
        "title": "Going Expert",
        "badge": "CWatM Graduate",
        "summary": (
            "Expert view unlocks the rest: several settings files open in tabs "
            "at once, Compare Tab (F8) to diff two of them in place, and Create "
            "batch to hand a colleague a settings file as a standalone .bat "
            "that runs without the GUI at all. You've now toured every level of "
            "the settings file this GUI edits."
        ),
        "teaches": [
            "Settings-file tabs and Settings ▸ Compare Tab (F8)",
            "RUN CWATM ▸ Create batch",
            "Tools ▸ Excel Crops/Reservoirs",
        ],
        "menu_hint": "Preferences ▸ Editor & Dates ▸ Skill of user → Expert",
    },
]

LEVEL_COUNT = len(LEVELS)


# Per-level "you did it" congratulations, shown as a floating, centred
# TorusPrompt the moment a level completes (see
# academy_guide.show_level_celebration, used by academy_outlet_map for
# Level 1 and academy_window for Level 2) - a bold one-line "title" (e.g.
# "Level 1 complete.") over a plain-weight "body" of a sentence or two of
# detail, not one wall of bold text. ``image`` is broken out per level - not
# just one constant - so a distinct celebration mascot for a given level can
# be dropped in later (a new asset under assets/, referenced here) without
# touching any calling code, just this table; every level uses the plain
# academy_torus.png today since no per-level celebration art exists yet.
# Deliberately no emoji in the text - see celebration_for.
CELEBRATIONS = {
    1: {
        "image": "academy_torus.png",
        "title": "Level 1 complete.",
        "body": (
            "You loaded a settings file, picked a catchment outlet, and "
            "CWatM Academy wrote both MaskMap and Gauges into it for you."
        ),
    },
    2: {
        "image": "academy_torus.png",
        "title": "Level 2 complete.",
        "body": (
            "You pointed PathOut at a real folder, set the run period, "
            "and ran CWatM for real."
        ),
    },
}


def celebration_for(level_id):
    """The ``(image_asset, title_html, body_html)`` celebration for
    finishing ``level_id`` - falls back to a generic title (no body) and
    the default mascot for a level that hasn't been given its own entry in
    CELEBRATIONS yet, so every level can celebrate even before all ten have
    bespoke text/art."""
    entry = CELEBRATIONS.get(level_id)
    if entry is not None:
        return entry["image"], entry["title"], entry["body"]
    lvl = level_by_id(level_id)
    title = lvl["title"] if lvl else f"Level {level_id}"
    return "academy_torus.png", f"Level {level_id} complete.", title


# The "will you accept this mission" briefing shown before each level's
# Field Test (see academy_guide.show_mission_briefing) - same shape as
# CELEBRATIONS (image/title/body), shown right before the graded check
# instead of right after it. Levels without a Field Test yet fall back to a
# generic briefing in field_test_for, same pattern as celebration_for.
FIELD_TESTS = {
    1: {
        "image": "academy_torus.png",
        "title": "Field Test Available",
        "body": (
            "Before you graduate this level, prove it without help: "
            "locate the outlet of the Nile on the map. Land within the "
            "last few cells of the river and you pass - nothing on this "
            "map points at the answer for you."
        ),
    },
    2: {
        "image": "academy_torus.png",
        "title": "Field Test Available",
        "body": (
            "Configure and run a real simulation: February 2015, with a "
            "one-month spin-up. Set StepStart to 01/01/2015, SpinUp to "
            "01/02/2015 and StepEnd to 28/02/2015, then run it - land on "
            "exactly those dates and finish the run to pass."
        ),
    },
}


def field_test_for(level_id):
    """The ``(image_asset, title_html, body_html)`` mission briefing for
    ``level_id``'s Field Test - falls back to a generic briefing (and the
    default mascot) for a level without one yet in FIELD_TESTS."""
    entry = FIELD_TESTS.get(level_id)
    if entry is not None:
        return entry["image"], entry["title"], entry["body"]
    return ("academy_torus.png", "Field Test Available",
            "Complete the mission to graduate this level.")


def level_by_id(level_id):
    """The level dict for ``level_id`` (1-based), or None if out of range."""
    for lvl in LEVELS:
        if lvl["id"] == level_id:
            return lvl
    return None
