"""Analyse > Mean Weekly Fluxes: the panels chosen in the gear window."""
import types

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import QSettings

from src.gui.widgets import analysis_mean_fluxes as mf

pytestmark = pytest.mark.skipif(not mf._FD_AVAILABLE, reason="plotly stack not available")

ALL_COLUMNS = sorted({c for p in mf.PANELS for c in p[2]})


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(mf, "_settings", lambda: QSettings(path, QSettings.IniFormat))


def _figure(columns=ALL_COLUMNS):
    dates = pd.date_range("2001-01-01", "2002-12-31", freq="D")
    host = types.SimpleNamespace(
        _df=pd.DataFrame({c: np.full(len(dates), 1e9) for c in columns}),
        _start_idx=0, _end_idx=len(dates) - 1, _cellAreaSum=1e11, _rows_per_year=365.25,
        _month_dates=list(dates), settings_title="t", csv_path="x.csv", lon=1, lat=2,
        _fmt_month=str)
    host._daily_mm = types.MethodType(mf.MeanFluxesWindow._daily_mm, host)
    return mf.MeanFluxesWindow._build_figure(host), host


def _names(fig):
    return [t.name for t in fig.data]


def test_panel_table():
    assert len(mf.PANELS) == 47
    assert len({p[0] for p in mf.PANELS}) == 47
    assert "," not in "".join(p[0] for p in mf.PANELS)     # the stored list is comma-joined


def test_defaults_are_shown_until_changed():
    defaults = ["Precipitation", "Rain", "Snow", "Snowmelt", "Glacier melt", "Runoff",
                "Actual ET", "Discharge"]
    assert mf.shown_panels() == set(defaults)
    assert _names(_figure()[0]) == defaults


def test_preference_round_trip():
    mf.set_panel_shown("Rain", False)
    mf.set_panel_shown("Return flow", True)
    assert "Rain" not in mf.shown_panels()
    assert "Return flow" in mf.shown_panels()
    assert "Snow" in mf.shown_panels()


def test_removed_panel_is_not_drawn_and_not_in_the_csv():
    mf.set_panel_shown("Snow", False)
    fig, host = _figure()
    assert "Snow" not in _names(fig)
    assert "Snow" not in host._csv_data[1]
    # the letters follow what is shown, the remark stands in brackets after the name
    assert [a.text for a in fig.layout.annotations][:3] == [
        "a) Precipitation (Rain + Snow)", "b) Rain", "c) Snowmelt (Snow + icemelt)"]


def test_every_panel_at_once_can_be_drawn():
    for p in mf.PANELS:
        mf.set_panel_shown(p[0], True)
    fig, _host = _figure()
    assert len(fig.data) == 47
    assert fig.layout.annotations[46].text == "au) Return flow"


def test_panel_needs_all_its_columns():
    host = _figure()[1]
    host._df = host._df[["act_irrWithdrawal_areasum_m3"]]
    assert host._daily_mm(["act_irrWithdrawal_areasum_m3"]) is not None
    assert host._daily_mm(["act_irrWithdrawal_areasum_m3",
                           "act_nonIrrWithdrawal_areasum_m3"]) is None


def test_flux_is_per_week_and_storage_is_the_mean_state():
    mf.set_panel_shown("Rain", True)
    mf.set_panel_shown("Soil Storage", True)
    fig, host = _figure()
    y = {t.name: t.y for t in fig.data}
    # 1e9 m3 per day over 1e11 m2 = 10 mm/day
    assert y["Rain"][10] == pytest.approx(70.0)
    assert y["Soil Storage"][10] == pytest.approx(10.0)
    assert host._csv_data[0][-1] == ("Unit", "mm/week (storage: mm)")


def test_csv_without_the_chosen_panels_shows_its_defaults():
    for name in ("Actual ET", "Rain"):
        mf.set_panel_shown(name, False)
    columns = ("totalET_areasum_m3", "Rain_areasum_m3")
    assert _names(_figure(columns)[0]) == ["Rain", "Actual ET"]
    columns = ("sum_soil_areasum_m3",)                     # no default panel at all
    assert _names(_figure(columns)[0]) == ["Soil Storage"]
