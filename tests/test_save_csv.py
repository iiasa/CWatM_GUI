"""Save CSV of Analyse ▸ Watercycle / Flow Diagram: the pure writer, and the table
the Flow Diagram window builds alongside its figure (driven on a bare window with
a synthetic monthly frame - no csv file, no web page)."""

import csv

import pytest

pytestmark = pytest.mark.qt

from src.gui.widgets.analysis_plot_base import write_table_csv  # noqa: E402


def test_writer_puts_meta_then_table(tmp_path):
    path = tmp_path / "out.csv"
    write_table_csv(str(path), [("Basin", "Morava"), ("lon", 17.1)],
                    ["Flow", "mm_per_year"], [["Rain", 512.3], ["Snow", 40.0]])
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows == [["Basin", "Morava"], ["lon", "17.1"], [],
                    ["Flow", "mm_per_year"], ["Rain", "512.3"], ["Snow", "40.0"]]


def test_default_names():
    from src.gui.widgets.analysis_flowdiagram import FlowDiagramWindow
    from src.gui.widgets.analysis_watercycle import WatercycleWindow
    assert WatercycleWindow._csv_name == "watercycle.csv"
    assert FlowDiagramWindow._csv_name == "flowdiagram.csv"


def test_flowdiagram_table_follows_the_figure(qapp):
    import pandas as pd
    from src.gui.widgets.analysis_flowdiagram import FlowDiagramWindow
    w = FlowDiagramWindow.__new__(FlowDiagramWindow)     # skip __init__
    months = pd.date_range("2000-01-31", periods=24, freq="ME")
    w._df = pd.DataFrame({"Date": months, "Precipitation": [100.0] * 24})
    w._month_dates = list(months)
    w._cellAreaSum = 1_000_000.0
    w._start_idx, w._end_idx = 0, 23
    w.settings_title, w.csv_path = "Test basin", "wc.csv"
    w.lon, w.lat = 17.1, 48.2
    w._build_figure()
    meta, header, rows = w._csv_data
    assert dict(meta)["Basin"] == "Test basin"
    assert dict(meta)["Period"] == "from 1/2000 to 12/2001"
    assert header == ["Flow", "From", "To", "mm_per_year"]
    assert rows and all(len(r) == 4 for r in rows)


def test_watercycle_table_follows_the_figure(qapp):
    import pandas as pd
    from src.gui.widgets.analysis_watercycle import WatercycleWindow
    w = WatercycleWindow.__new__(WatercycleWindow)       # skip __init__
    months = pd.date_range("2000-01-31", periods=24, freq="ME")
    w._df = pd.DataFrame({"Date": months,
                          "Rain_areasum_m3": [1.0e6] * 24,
                          "totalET_areasum_m3": [0.6e6] * 24,
                          "avgdischarge_m3s-1": [0.15] * 24})
    w._month_dates = list(months)
    w._cellAreaSum = 1_000_000.0
    w._start_idx, w._end_idx = 0, 23
    w.settings_title, w.csv_path = "Test basin", "wc.csv"
    w.lon, w.lat = 17.1, 48.2
    w._build_figure()
    meta, header, rows = w._csv_data
    assert dict(meta)["Basin"] == "Test basin"
    assert header[:2] == ["Group", "Component"]
    assert rows[0][:2] == ["", "Water balance"]            # the root, named plainly
    comps = {r[1]: r for r in rows}
    assert comps["Rain"][0] == "Inputs"
    assert comps["River discharge at outlet"][5] == 0.15   # discharge in m3/s
