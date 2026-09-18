"""GUI language (src/gui/utils/i18n.py): the catalog rules, the shipped table, and the
live translation of real widgets."""

import csv
import re

import pytest

from src.gui.utils import i18n
from src.gui.utils.i18n import Catalog

_PH = re.compile(r"\{[^{}]*\}")


def _cat():
    return Catalog([
        ("Save", "Speichern"),
        ("Find & Replace", "Suchen & Ersetzen"),
        ("Language", "Sprache"),
        ("Run '{name}'", "'{name}' starten"),
        ("Copy {what}", "{what} kopieren"),
        ("Paste into this {kind}", "In diese {kind} einfügen"),
        ("Paste {span} {where}", "{span} {where} einfügen"),
        ("{tip}\nNo {type} here - use {type}.", "{tip}\nKein {type} - {type} verwenden."),
        ("{a} {b}", "only placeholders - never compiled"),
        ("cell", "Zelle"), ("columns", "Spalten"), ("column", "Spalte"), ("left", "links"),
    ])


def test_exact_and_unknown():
    cat = _cat()
    assert cat.translate("Save") == "Speichern"
    assert cat.translate("Unknown text") == "Unknown text"
    assert cat.translate("") == ""


def test_colon_suffix_uses_the_bare_entry():
    assert _cat().translate("Language:") == "Sprache:"


def test_template_translates_catalog_values_only():
    cat = _cat()
    assert cat.translate("Run 'scenario 1'") == "'scenario 1' starten"
    assert cat.translate("Copy cell") == "Zelle kopieren"
    assert cat.translate("Copy 4 cells") == "4 cells kopieren"   # 'cells' not in this catalog


def test_count_prefix_value():
    assert _cat().translate("Copy 3 columns") == "3 Spalten kopieren"


def test_most_specific_template_wins_and_split_is_greedy():
    cat = _cat()
    assert cat.translate("Paste into this column") == "In diese Spalte einfügen"
    assert cat.translate("Paste 3 columns left") == "3 Spalten links einfügen"


def test_repeated_placeholder_must_match_the_same_value():
    cat = _cat()
    assert cat.translate("tip\nNo X here - use X.") == "tip\nKein X - X verwenden."
    assert cat.translate("tip\nNo X here - use Y.") == "tip\nNo X here - use Y."


def test_placeholder_only_template_is_ignored():
    assert _cat().translate("hello world") == "hello world"


def test_english_of_reverses_translations_but_never_english_keys():
    cat = _cat()
    assert cat.english_of("Speichern") == "Save"
    assert cat.english_of("Save") is None


def test_shipped_table_is_consistent():
    path = i18n.csv_path()
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    columns = list(i18n._COLUMNS.values())
    assert rows and {"No", "English", *columns} <= set(rows[0])
    # every selectable language except English has a column, and vice versa
    assert {c for _n, c in i18n.LANGUAGES} - {"en"} == set(i18n._COLUMNS)
    english = [r["English"] for r in rows]
    assert len(english) == len(set(english)), "duplicate English entries"
    for r in rows:
        for col in columns:
            text = r[col]
            assert text.strip(), f"row {r['No']} has no {col} text"
            assert sorted(_PH.findall(r["English"])) == sorted(_PH.findall(text)), \
                f"row {r['No']} {col}: placeholders differ"
            assert r["English"].count("\n") == text.count("\n"), \
                f"row {r['No']} {col}: line breaks differ"
    assert [int(r["No"]) for r in rows] == list(range(1, len(rows) + 1))
    assert i18n.load_catalog("de").translate("Language") == "Sprache"
    assert i18n.load_catalog("uk").translate("Language:") == "Мова:"
    assert "Run Ledger" not in " ".join(english)


@pytest.mark.qt
def test_live_switch_round_trip(qapp, isolated_qsettings):
    from PySide6.QtWidgets import QMenu, QPushButton
    menu = QMenu("File")
    save = menu.addAction("Save")
    section = menu.addAction("Find && Replace")
    button = QPushButton("Save")
    try:
        i18n.set_language("de")
        assert i18n.current_language() == "de"
        assert save.text() == "Speichern"
        assert section.text() == "Suchen && Ersetzen"
        assert button.text() == "Speichern"

        # A relabel after display is caught (ActionChanged) and becomes the new source.
        save.setText("Load")
        assert save.text() == "Laden"
        # A new action added while German is active is translated on arrival.
        assert menu.addAction("Exit").text() == "Beenden"

        i18n.set_language("en")
        assert save.text() == "Load"
        assert section.text() == "Find && Replace"
        assert button.text() == "Save"
        assert i18n.saved_language() == "en"
    finally:
        i18n.set_language("en")
