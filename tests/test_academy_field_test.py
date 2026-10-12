"""CWatM Academy Level 1 Field Test: a random basin of all 100, graded
against its 4 biggest upstream cells on the bundled 30' grid."""

import random

import numpy as np
import pytest

pytestmark = pytest.mark.qt

from src.gui.widgets import academy_field_test as ft  # noqa: E402


class _Initials:
    """Answers the new-highscore question (ask_initials is modal) and records it."""

    def __init__(self):
        self.answer = "PB"
        self.asked = []          # the suggestion of every question

    def __call__(self, parent, suggestion=""):
        self.asked.append(suggestion)
        return self.answer


@pytest.fixture
def initials(monkeypatch):
    rec = _Initials()
    monkeypatch.setattr(ft, "ask_initials", rec)
    # the Level 2 message is modal too - answered (and counted) here
    rec.level2 = []
    monkeypatch.setattr(ft, "show_level2_message",
                        lambda parent, image=None: rec.level2.append(image))
    return rec


@pytest.fixture
def field_settings(tmp_path, monkeypatch, initials):
    """The logged-out highscore in a temp ini, never the real (native) store; the
    initials question answered by `initials`."""
    from PySide6.QtCore import QSettings
    path = str(tmp_path / "field_test.ini")
    monkeypatch.setattr(ft, "_settings", lambda: QSettings(path, QSettings.IniFormat))
    return QSettings(path, QSettings.IniFormat)


@pytest.fixture(scope="module")
def grid(qapp):
    data, lats, lons = ft.load_ups_grid()
    assert data is not None
    return np.asarray(data, dtype=float), np.asarray(lats), np.asarray(lons)


def test_pool_is_all_100_basins():
    basins = ft.load_basins()
    assert len(basins) == 100
    assert all(b["rank"] <= 100 for b in basins)
    assert "Danube" in {b["name"] for b in basins}
    assert basins[0]["name"] == "Amazon"


def test_four_biggest_cells_for_every_basin(grid):
    data, lats, lons = grid
    for b in ft.load_basins():
        cells = ft.target_cells(data, lats, lons, b["lat"], b["lon"])
        assert len(cells) == 4, b["name"]
        assert cells[0] == (b["lat"], b["lon"]), b["name"]        # listed outlet
        vals = [data[ft._nearest_index(lats, lons, la, lo)] for la, lo in cells]
        assert vals[0] == pytest.approx(b["size_km2"], rel=1e-4), b["name"]
        assert all(vals[0] > v for v in vals[1:]), b["name"]
        # (a *neighbour* may still be larger - the Uruguay's outlet borders the
        # Parana / Rio de la Plata cells of a bigger basin - so the targets only
        # ever step to smaller neighbours, which drain into the outlet)


def test_grading_snaps_to_cells(grid):
    data, lats, lons = grid
    nile = next(b for b in ft.load_basins() if b["name"] == "Nile")
    targets = ft.target_cells(data, lats, lons, nile["lat"], nile["lon"])
    lat, lon = targets[1]
    assert ft.is_target(lats, lons, lat + 0.1, lon - 0.1, targets)   # same cell
    assert not ft.is_target(lats, lons, 0.0, 0.0, targets)


def test_distance_shrinks_longitude_with_latitude():
    assert ft.distance_km(0, 0, 0, 1) == pytest.approx(111.19, rel=1e-3)
    assert ft.distance_km(60, 0, 60, 1) == pytest.approx(111.19 / 2, rel=1e-2)
    assert ft.distance_km(0, 0, 1, 0) == pytest.approx(111.19, rel=1e-3)
    assert ft.distance_km(0, 179.5, 0, -179.5) == pytest.approx(111.19, rel=1e-3)


def test_a_miss_reports_the_distance(qapp, field_settings):
    from PySide6.QtCore import QCoreApplication, QEvent
    win = ft.BasinFieldTestWindow()
    try:
        b = win._basin
        lat = b["lat"] + 10 if b["lat"] < 70 else b["lat"] - 10
        win._on_web_title(f"NILETEST {b['lon']}|{lat}|1")
        assert not win._basin_found
        assert "Not the outlet - you are 1,112 kilometers away." in \
            win.status_label.text()
    finally:
        win.close()
        if win.web_view is not None:
            win.web_view.setPage(None)
        win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qapp.processEvents()


def test_view_contains_the_outlet_off_centre():
    b = dict(size_km2=2_904_390, lat=31.25, lon=31.25)
    rng = random.Random(3)
    for _ in range(20):
        (s, w), (n, e) = ft.view_bounds(b, rng)
        assert s < b["lat"] < n and w < b["lon"] < e


def test_window_picks_a_basin_and_grades(qapp, field_settings):
    from PySide6.QtCore import QCoreApplication, QEvent
    win = ft.BasinFieldTestWindow()
    try:
        name = win._basin["name"]
        assert name in win.title_label.text()
        lat, lon = win._targets[0]
        win._on_web_title(f"NILETEST {lon}|{lat}|1")
        assert win._basin_found and win.end_button.isEnabled()
        win._next_basin()
        assert win._basin["name"] != name and not win._basin_found
    finally:
        win.close()
        if win.web_view is not None:
            win.web_view.setPage(None)
        win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qapp.processEvents()




# ------------------------------------------------------------ score / highscore

def _close(qapp, win):
    from PySide6.QtCore import QCoreApplication, QEvent
    win.close()
    if win.web_view is not None:
        win.web_view.setPage(None)
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def _miss(win, degrees=10):
    """A click `degrees` of latitude from the outlet; returns the penalty (capped
    by how many misses the basin already had)."""
    b = win._basin
    lat = b["lat"] + degrees if b["lat"] < 70 else b["lat"] - degrees
    misses = win._misses
    win._on_web_title(f"NILETEST {b['lon']}|{lat}|1")
    return ft.capped_penalty(ft.distance_km(lat, b["lon"], b["lat"], b["lon"]), misses)


def _hit(win):
    lat, lon = win._targets[0]
    win._on_web_title(f"NILETEST {lon}|{lat}|2")


def test_miss_penalty_is_whole_km():
    assert ft.miss_penalty(1111.6) == 1112
    assert ft.miss_penalty(0.4) == 0


def test_clean_initials():
    assert ft.clean_initials(" pb ") == "PB"
    assert ft.clean_initials("abc") == "ABC"
    for bad in ("", "P", "ABCD", "P1", "P B", None):
        assert ft.clean_initials(bad) == "", bad


def test_score_found_basins_minus_km_of_misses(qapp, field_settings, initials):
    win = ft.BasinFieldTestWindow()
    try:
        assert win.points_label.text() == "Points: 0"
        assert win.best_label.text() == "Your best: 0"
        assert win.highscore_label.text() == "Highscore: –"     # no account here
        _miss(win)
        assert win.points_label.text() == "Points: 0"            # never below 0
        assert win.best_label.text() == "Your best: 0"
        _hit(win)
        assert win.points_label.text() == f"Points: {ft.FOUND_POINTS}"
        # a found basin is scored once: another hit or a miss changes nothing
        _hit(win)
        _miss(win)
        assert win._score == ft.FOUND_POINTS
        # the score runs on over the next basin; a miss costs its km
        win._next_basin()
        p1 = _miss(win, degrees=3)
        assert win._score == ft.FOUND_POINTS - p1
        _hit(win)
        assert win._score == 2 * ft.FOUND_POINTS - p1
        assert win.best_label.text() == f"Your best: {win._score}"
        assert initials.asked == []          # no record to beat without the server
    finally:
        _close(qapp, win)


def test_logged_out_own_best_is_kept_on_this_computer(qapp, field_settings):
    win = ft.BasinFieldTestWindow()
    try:
        _hit(win)
    finally:
        _close(qapp, win)
    assert int(field_settings.value(ft.HIGHSCORE_KEY)) == ft.FOUND_POINTS
    win = ft.BasinFieldTestWindow()
    try:
        assert win.best_label.text() == f"Your best: {ft.FOUND_POINTS}"
        assert win.points_label.text() == "Points: 0"
        _miss(win)
        assert win.best_label.text() == f"Your best: {ft.FOUND_POINTS}"
    finally:
        _close(qapp, win)


def test_global_map_from_2000_points(qapp, field_settings):
    win = ft.BasinFieldTestWindow()
    try:
        assert win._view != ft.GLOBAL_VIEW
        win._score, win._basin_found = ft.GLOBAL_VIEW_POINTS - 1, True
        win._next_basin()
        assert win._view != ft.GLOBAL_VIEW            # still framed on the basin
        win._score, win._basin_found = ft.GLOBAL_VIEW_POINTS, True
        win._next_basin()
        assert win._view == ft.GLOBAL_VIEW
        assert "whole world map" in win.instructions_label.text()
    finally:
        _close(qapp, win)


class _FakeMainWindow:
    """account_status() -> logged in (or not); account_worker() records submits."""

    def __init__(self, logged_in=True):
        from PySide6.QtCore import QObject, Signal

        class Worker(QObject):
            succeeded = Signal(str, object)
            failed = Signal(str, str, str)

            def __init__(self):
                super().__init__()
                self.submitted = []

            def submit(self, op, *args):
                self.submitted.append((op,) + args)

        self.worker = Worker()
        self.logged_in = logged_in

    def account_status(self):
        return {"profile": {"username": "tester"}} if self.logged_in else None

    def account_worker(self):
        return self.worker


def test_logged_in_record_and_own_best_from_the_account(qapp, field_settings, initials):
    mw = _FakeMainWindow()
    win = ft.BasinFieldTestWindow(main_window=mw)
    try:
        assert mw.worker.submitted == [("get_field_test_highscore",)]
        assert win.highscore_label.text() == "Highscore: …"
        assert win.best_label.text() == "Your best: …"
        mw.worker.succeeded.emit("get_field_test_highscore", {
            "highscore": 500, "initials": None,
            "record_score": 1500, "record_initials": "ABC"})
        assert win.highscore_label.text() == "Highscore: 1500 ABC"
        assert win.best_label.text() == "Your best: 500"
        _hit(win)                     # 1000: own best beaten, the record not
        assert initials.asked == []
        assert mw.worker.submitted[-1] == ("field_test_submit_score", 1000, None)
        assert win.best_label.text() == "Your best: 1000"
        win._next_basin()
        _hit(win)                     # 2000: the record - initials asked, sent
        assert len(initials.asked) == 1
        assert mw.worker.submitted[-1] == ("field_test_submit_score", 2000, "PB")
        assert win.highscore_label.text() == "Highscore: 2000 PB"
        mw.worker.succeeded.emit("field_test_submit_score", {
            "status": "new_highscore", "highscore": 2000, "initials": "PB",
            "record_status": "new_record", "record_score": 2000,
            "record_initials": "PB"})
        assert win.highscore_label.text() == "Highscore: 2000 PB"
        win._next_basin()
        _hit(win)                     # 3000: own record again - not asked again
        assert len(initials.asked) == 1
        assert mw.worker.submitted[-1] == ("field_test_submit_score", 3000, "PB")
        # the own best is never written to this computer while logged in
        assert field_settings.value(ft.HIGHSCORE_KEY) is None
    finally:
        _close(qapp, win)
    # closed: no longer listening
    mw.worker.succeeded.emit("get_field_test_highscore", {"record_score": 9})


def test_someone_else_beat_the_record_meanwhile(qapp, field_settings, initials):
    mw = _FakeMainWindow()
    win = ft.BasinFieldTestWindow(main_window=mw)
    try:
        mw.worker.succeeded.emit("get_field_test_highscore", {
            "highscore": 0, "record_score": 500, "record_initials": "ABC"})
        _hit(win)                     # 1000 > 500: claimed
        assert win.highscore_label.text() == "Highscore: 1000 PB"
        # ...but another user got 5000 in the meantime: the server says so
        mw.worker.succeeded.emit("field_test_submit_score", {
            "status": "new_highscore", "highscore": 1000, "initials": "PB",
            "record_status": "kept", "record_score": 5000, "record_initials": "XYZ"})
        assert win.highscore_label.text() == "Highscore: 5000 XYZ"
        assert win.best_label.text() == "Your best: 1000"
    finally:
        _close(qapp, win)


def test_a_record_played_before_the_answer_arrived(qapp, field_settings, initials):
    mw = _FakeMainWindow()
    win = ft.BasinFieldTestWindow(main_window=mw)
    try:
        _hit(win)                     # nothing known yet: no question, nothing sent
        assert initials.asked == [] and len(mw.worker.submitted) == 1
        mw.worker.succeeded.emit("get_field_test_highscore", {
            "highscore": 0, "record_score": 400, "record_initials": "ZZ"})
        assert len(initials.asked) == 1
        assert mw.worker.submitted[-1] == ("field_test_submit_score", 1000, "PB")
        assert win.highscore_label.text() == "Highscore: 1000 PB"
    finally:
        _close(qapp, win)


def test_logged_out_sees_the_record_but_cannot_claim_it(
        qapp, field_settings, initials, monkeypatch):
    from src.gui.utils import account_config
    monkeypatch.setattr(account_config, "is_configured", lambda: True)
    mw = _FakeMainWindow(logged_in=False)
    win = ft.BasinFieldTestWindow(main_window=mw)
    try:
        assert mw.worker.submitted == [("get_field_test_record",)]
        mw.worker.succeeded.emit("get_field_test_record",
                                 {"record_score": 700, "record_initials": "ABC"})
        assert win.highscore_label.text() == "Highscore: 700 ABC"
        _hit(win)
        assert initials.asked == [] and len(mw.worker.submitted) == 1
        assert "Log in to put your initials on it" in win.status_label.text()
        assert win.highscore_label.text() == "Highscore: 700 ABC"
        assert int(field_settings.value(ft.HIGHSCORE_KEY)) == ft.FOUND_POINTS
    finally:
        _close(qapp, win)


def test_cancelled_initials_still_take_the_record(qapp, field_settings, initials):
    initials.answer = ""
    mw = _FakeMainWindow()
    win = ft.BasinFieldTestWindow(main_window=mw)
    try:
        mw.worker.succeeded.emit("get_field_test_highscore",
                                 {"highscore": 0, "record_score": 0})
        _hit(win)
        assert mw.worker.submitted[-1] == ("field_test_submit_score", 1000, None)
        assert win.highscore_label.text() == f"Highscore: {ft.FOUND_POINTS}"
    finally:
        _close(qapp, win)


def test_the_initials_box_takes_2_to_3_letters_in_capitals(qapp):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit
    seen = {}

    def answer():
        dlg = next(w for w in QApplication.topLevelWidgets()
                   if isinstance(w, QDialog) and w.isVisible()
                   and w.windowTitle() == "New highscore")
        edit = dlg.findChild(QLineEdit)
        ok = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
        seen["suggested"] = edit.text()
        edit.setText("p")
        seen["ok_one_letter"] = ok.isEnabled()
        edit.setText("pbx")
        seen["ok_three"] = ok.isEnabled()
        seen["shown"] = edit.text()
        ok.click()

    QTimer.singleShot(0, answer)
    assert ft.ask_initials(None, "ab") == "PBX"
    assert seen == {"suggested": "AB", "ok_one_letter": False, "ok_three": True,
                    "shown": "PBX"}


def test_level1_again_goes_straight_to_the_field_test(monkeypatch):
    """Level 1 done before: "do it again" skips the load prompt, the outlet map,
    the guide and the briefing - only the Field Test window opens."""
    from types import SimpleNamespace
    from src.gui.widgets import academy_window as aw
    opened = []

    class Stub:
        def __init__(self, main_window=None):
            opened.append(main_window)

        def show(self):
            opened.append("shown")

        def raise_(self):
            pass

        def activateWindow(self):
            pass

    monkeypatch.setattr(ft, "BasinFieldTestWindow", Stub)
    host = SimpleNamespace(
        mw="main window",
        outlet_map=SimpleNamespace(reset=lambda: opened.append("outlet map")),
        stack=SimpleNamespace(setCurrentIndex=lambda i: opened.append(("page", i))),
        _show_load_settings_prompt=lambda: opened.append("load prompt"))
    aw.AcademyWindow._replay_level1(host)
    assert opened == ["main window", "shown"]

def test_another_basin_before_finding_this_one_costs_500(qapp, field_settings):
    win = ft.BasinFieldTestWindow()
    try:
        assert ft.SKIP_PENALTY == 500
        win._next_basin()                       # not found: skipped (floored at 0)
        assert win._score == 0
        assert f"-{ft.SKIP_PENALTY} points" in win.status_label.text()
        win._score = 800
        win._next_basin()                       # skipped again: 800 -> 300
        assert win._score == 800 - ft.SKIP_PENALTY
        assert win.points_label.text() == f"Points: {800 - ft.SKIP_PENALTY}"
        _hit(win)
        win._next_basin()                       # found first: free
        assert win._score == 800 - ft.SKIP_PENALTY + ft.FOUND_POINTS
        assert "skipped" not in win.status_label.text()
        # the penalty counts before the next basin is framed: 2000 -> 1500, framed
        win._score, win._basin_found = ft.GLOBAL_VIEW_POINTS, False
        win._next_basin()
        assert win._view != ft.GLOBAL_VIEW
    finally:
        _close(qapp, win)


def test_penalty_is_capped_1000_then_500_then_250():
    assert ft.capped_penalty(10000, 0) == 1000
    assert ft.capped_penalty(10000, 1) == 500
    assert ft.capped_penalty(10000, 2) == 250
    assert ft.capped_penalty(10000, 7) == 250
    assert ft.capped_penalty(120.4, 0) == 120          # below the cap: the km


def test_basin_cells_match_the_listed_sizes(grid):
    """The basin rebuilt from the ups grid alone: the outlet's own upstream area is
    the basin size, so the cells must add up to it (98 of 100 within 5 %)."""
    data, lats, lons = grid
    areas = ft.cell_areas(lats, lons)
    close = 0
    for b in ft.load_basins()[:50]:
        cells = ft.basin_cells(data, lats, lons, b["lat"], b["lon"])
        total = sum(areas[r] for r, _ in cells)
        close += abs(total - b["size_km2"]) / b["size_km2"] < 0.05
    assert close >= 48


def test_level_2_at_2500_points(qapp, field_settings, initials):
    from PySide6.QtCore import QCoreApplication
    win = ft.BasinFieldTestWindow()
    try:
        win._score, win._basin_found = ft.SHAPE_MODE_POINTS - ft.FOUND_POINTS, False
        _hit(win)                                   # reaches 2500
        QCoreApplication.processEvents()            # the queued level-up
        assert len(initials.level2) == 1
        # isHidden, not isVisible: the window itself is never shown in the test
        assert win._shape_mode and not win.shape_label.isHidden()
        assert win._basin["rank"] <= ft.LEVEL2_POOL
        assert win._basin["name"] not in win.title_label.text()
        # a click inside the basin wins, anywhere
        r, c = win._basin_cells[-1]
        before = win._score
        win._on_web_title(f"NILETEST {win._lons[c]}|{win._lats[r]}|3")
        assert win._score == before + ft.FOUND_POINTS
        # falling below 2500 again does not go back
        win._score, win._basin_found = 0, True
        win._next_basin()
        assert win._shape_mode and len(initials.level2) == 1
    finally:
        _close(qapp, win)


def test_field_test_badge_tiers():
    from src.gui.utils import account_shop as s
    assert s.field_test_tier(0, 5000) is None              # not played
    assert s.field_test_tier(3000, 9000) == "bronze"
    assert s.field_test_tier(10001, 20000) == "silver"     # more than 10000
    assert s.field_test_tier(10000, 20000) == "bronze"
    assert s.field_test_tier(9000, 9000) == "gold"         # holds the record
    assert s.field_test_tier(20000, 25000) == "silver"     # record lost again


def test_end_test_shows_the_statistics_and_passes(qapp, field_settings, monkeypatch):
    shown, passed = [], []
    monkeypatch.setattr(ft, "show_end_statistics", lambda parent, stats: shown.append(stats))
    win = ft.BasinFieldTestWindow()
    win.passed.connect(lambda: passed.append(1))
    try:
        km = _miss(win, degrees=3)              # a wrong click ...
        _hit(win)                               # ... then found
        win._next_basin()
        _miss(win, degrees=10)                  # tried, missed and left open
        win._on_end_clicked()
        stats = shown[0]
        assert stats["level"] == 1 and stats["found"] == 1 and stats["failed"] == 1
        assert stats["wrong_clicks"] == 2
        assert stats["max_miss_km"] > km
        assert stats["badge"] is None and not stats["logged_in"]
        assert passed == [1]                    # one basin found passes Level 1
    finally:
        _close(qapp, win)
