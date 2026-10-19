"""Re-consent after the privacy notice changed, and the minimum age (no Qt needed).

After every login the GUI compares the notice version a user agreed to with the one
it ships (account_config.privacy_consent_needed) and shows the new notice when they
differ; the server records the new agreement (accept_privacy). The Register form's
consent tick box states the minimum age. These tests pin the decision, the texts the
dialog and the tick box show (in every GUI language) and the server's rule that only
the caller's own consent is read or written.
"""

import ast
import csv
import os
import re

import pytest

from src.gui.utils import account_config, i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIALOGS = os.path.join(ROOT, "src", "gui", "widgets", "account_dialogs.py")
NOTICE = os.path.join(ROOT, "documentation", account_config.PRIVACY_DOC)


# ---- the decision ---------------------------------------------------------------------

@pytest.mark.parametrize("consent, needed", [
    ({"privacy_version": account_config.PRIVACY_VERSION}, False),   # agreed to this one
    ({"privacy_version": "2026-09-28-draft5"}, True),              # an older notice
    ({"privacy_version": None, "privacy_accepted_at": None}, True),  # never recorded
    ({"privacy_version": ""}, True),
    ({}, True),                                                    # no profile row
    (None, False),                                                 # no answer: never lock out
    ("garbage", False),
])
def test_privacy_consent_needed(consent, needed):
    assert account_config.privacy_consent_needed(consent) is needed


# ---- the texts, in every language -------------------------------------------------------

def _dialog_constants():
    """CONSENT_INTRO and the tick-box text, read from the source (the module needs Qt)."""
    tree = ast.parse(open(DIALOGS, encoding="utf-8").read())
    intro = tick = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "CONSENT_INTRO":
            intro = ast.literal_eval(node.value)
        if isinstance(node, ast.FunctionDef) and node.name == "consent_checkbox_text":
            src = ast.unparse(node)
            assert "account_config.MIN_AGE" in src
            tick = ("I am at least {} years old and agree that these data are stored "
                    "(privacy notice)").format(account_config.MIN_AGE)
    assert intro and tick
    return intro, tick


@pytest.fixture(scope="module")
def table():
    with open(i18n.csv_path(), encoding="utf-8-sig", newline="") as fh:
        return {r["English"]: r for r in csv.DictReader(fh)}


@pytest.mark.parametrize("which", ["intro", "tick", "Agree", "Log out",
                                   "CWatM account privacy",
                                   "Your agreement to the privacy notice is recorded.",
                                   "Please confirm your age and agree to the storage of "
                                   "your data (tick the box above)."])
def test_dialog_texts_have_rows_in_every_language(table, which):
    intro, tick = _dialog_constants()
    text = {"intro": intro, "tick": tick}.get(which, which)
    assert text in table, f"no translation row for {text[:60]!r}"
    row = table[text]
    for column in i18n._COLUMNS.values():
        assert row[column].strip(), (column, text[:40])
    if which == "tick":
        for column in i18n._COLUMNS.values():
            assert str(account_config.MIN_AGE) in row[column], column


def test_notice_states_the_age_and_the_tick_box():
    notice = " ".join(open(NOTICE, encoding="utf-8").read().split())
    _intro, tick = _dialog_constants()
    assert f"at least **{account_config.MIN_AGE} years old**" in notice
    assert tick.replace(" (privacy notice)", "") in notice      # the Legal basis section
    # the promise the re-consent keeps
    assert "shown to you in CWatM GUI at your next login" in notice


# ---- the server: only the caller's own consent --------------------------------------------

def _latest(fn):
    migrations = sorted(os.listdir(os.path.join(ROOT, "supabase", "migrations")))
    body = None
    for name in migrations:
        text = open(os.path.join(ROOT, "supabase", "migrations", name), encoding="utf-8").read()
        text = re.sub(r"--[^\n]*", "", text)
        m = re.search(rf"function\s+public\.{fn}\s*\(.*?\$\$(.*?)\$\$", text,
                      re.IGNORECASE | re.DOTALL)
        if m:
            body = re.sub(r"\s+", " ", m.group(1)).lower()
    assert body, fn
    return body


def test_accept_privacy_writes_only_the_callers_row():
    b = _latest("accept_privacy")
    assert "v_user uuid := auth.uid()" in b
    assert "where id = v_user" in b
    assert "char_length(v_version) > 40" in b          # the column's own limit


def test_get_privacy_consent_reads_only_the_callers_row():
    b = _latest("get_privacy_consent")
    assert "auth.uid()" in b and "where p.id = v_user" in b
