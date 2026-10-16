"""CWatM Academy follows the GUI language (Preferences ▸ Display ▸ Language).

Its texts are rows of ``translations/ui_strings_languages.csv`` like every other
GUI string, so a changed or added Academy text without a row would silently stay
English. These tests hold that for the curriculum (``academy_content``, pure data)
and for the templates the Academy builds at run time. No Qt needed.
"""

import pytest

from src.gui.utils import academy_content as content
from src.gui.utils import i18n

LANGUAGES = sorted(i18n._COLUMNS)          # every language except English


def _content_texts():
    """Every user-visible text of the curriculum: what the level list, the lesson
    page, the mission briefing and the celebration show."""
    texts = []
    for lvl in content.LEVELS:
        texts += [lvl["title"], lvl["badge"], lvl["summary"], lvl["menu_hint"]]
        texts += list(lvl["teaches"])
    for table in (content.CELEBRATIONS, content.FIELD_TESTS):
        for entry in table.values():
            texts += [entry["title"], entry["body"]]
    texts += list(content.field_test_for(10**6)[1:])        # the generic fallback
    return sorted(set(texts))


@pytest.fixture(scope="module")
def catalogs():
    return {lang: i18n.load_catalog(lang) for lang in LANGUAGES}


def _has_row(catalog, text):
    if text in catalog._exact:
        return True
    return any(regex.fullmatch(text) for _l, regex, _g, _t in catalog._patterns)


@pytest.mark.parametrize("text", _content_texts())
def test_every_curriculum_text_has_a_row(catalogs, text):
    missing = [lang for lang, cat in catalogs.items() if not _has_row(cat, text)]
    assert not missing, f"no translation row for {text!r} ({', '.join(missing)})"


def test_lesson_templates_translate_their_parts(catalogs):
    # what academy_window._show_level builds: the title and badge labels go through
    # the i18n filter, the lesson page through i18n.tr - both via the same catalog
    lvl = content.level_by_id(2)
    for lang, cat in catalogs.items():
        title = cat.translate(f"Level {lvl['id']}: {lvl['title']}")
        assert cat.translate(lvl["title"]) in title, lang
        badge = cat.translate(f"Badge: {lvl['badge']}")
        assert cat.translate(lvl["badge"]) in badge, lang
        hint = cat.translate(f"Try it: {lvl['menu_hint']}")
        assert cat.translate(lvl["menu_hint"]) in hint, lang
        assert cat.translate("You'll use:") != "You'll use:", lang


def test_generic_celebration_and_outlet_texts(catalogs):
    de = catalogs["de"]
    assert de.translate("Level 7 complete.") == "Level 7 abgeschlossen."
    assert de.translate("Picked: lat 45.123, lon 13.456 — upstream area: no data") == \
        "Gewählt: Breite 45.123, Länge 13.456 — Einzugsfläche: keine Daten"
    # the longer template wins over the shorter one it contains
    assert de.translate("Picked: lat 45.123, lon 13.456") == "Gewählt: Breite 45.123, Länge 13.456"


@pytest.mark.parametrize("text", ["Back", "Next", "Got it!", "Continue", "Accept Mission",
                                  "Waiting for this …", "✓ Ready"])
def test_guide_bubble_chrome(catalogs, text):
    # the buttons and status line of every Torus guide bubble (academy_guide)
    for lang, cat in catalogs.items():
        assert _has_row(cat, text), (lang, text)
