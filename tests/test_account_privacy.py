"""The privacy notice must describe what the code does - checked where it can be.

A notice that drifts from the code is worse than none: these tests tie the facts the
notice states (its version, the offline-queue file and how long it is kept, what a
counted run sends) to the constants the code uses, and check that the notice is
bundled into the exe and that registering without consent is impossible.
"""

import os
import re

import pytest

# needs Qt (imports a module that imports PySide6) - skipped by the CI job without Qt
pytestmark = pytest.mark.qt

from src.gui.utils import account_config, account_runs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "documentation", account_config.PRIVACY_DOC)


@pytest.fixture(scope="module")
def notice():
    with open(DOC, encoding="utf-8") as f:
        # whitespace normalised: the markdown wraps phrases across lines
        return " ".join(f.read().split())


def test_version_line_matches_the_version_sent_at_sign_up(notice):
    m = re.search(r"\*\*Version (\d{4}-\d{2}-\d{2})", notice)
    assert m, "the notice has no 'Version YYYY-MM-DD' line"
    assert account_config.PRIVACY_VERSION.startswith(m.group(1))


def test_draft_marker_matches(notice):
    # a draft version string must go with a notice that says it is a draft
    is_draft = "draft" in account_config.PRIVACY_VERSION
    assert ("DRAFT" in notice) == is_draft


def test_offline_queue_facts(notice):
    assert account_runs._PENDING_NAME in notice
    assert f"after {account_runs._MAX_AGE_DAYS} days" in notice


def test_every_field_a_run_sends_is_named(notice):
    meta = account_runs.run_meta({"kind": "run", "timesteps": 1, "duration_s": 1.0,
                                  "settings_hash": "0" * 64}, "1.07")
    words = {"timesteps": "number of timesteps", "settings_hash": "fingerprint"}
    assert set(meta) == set(words), "run_meta changed - update the notice"
    for phrase in words.values():
        assert phrase in notice
    # what is no longer collected must not be claimed either
    for gone in ("GUI version", "run time", "run kind"):
        assert gone not in notice, gone
    assert "**not stored**: the number of timesteps" in notice
    assert "which level it was - no date" in notice
    assert "masked" in notice


def test_bundled_into_the_exe():
    with open(os.path.join(ROOT, "cwatm_gui_dir.spec"), encoding="utf-8") as f:
        assert account_config.PRIVACY_DOC in f.read()


supabase_auth = pytest.importorskip("supabase_auth")
from src.gui.utils import account_client as AC  # noqa: E402


class _Auth:
    def __init__(self):
        self.signed_up = None

    def sign_up(self, credentials):
        from types import SimpleNamespace
        self.signed_up = credentials
        return SimpleNamespace(user=SimpleNamespace(identities=[object()]),
                               session=None)


def _client(monkeypatch):
    from types import SimpleNamespace
    c = AC.AccountClient.__new__(AC.AccountClient)
    c._remember = False
    c._stored_refresh = None
    auth = _Auth()
    c._client = SimpleNamespace(auth=auth)
    monkeypatch.setattr(c, "username_available", lambda name: True)
    return c, auth


def test_register_without_consent_is_refused(monkeypatch):
    c, auth = _client(monkeypatch)
    with pytest.raises(AC.AccountError) as info:
        c.register("a@example.org", "secret123", "Blabla")
    assert info.value.code == "invalid_input"
    assert auth.signed_up is None                      # nothing sent


def test_register_sends_the_consent_version(monkeypatch):
    c, auth = _client(monkeypatch)
    result = c.register("a@example.org", "secret123", "Blabla",
                        privacy_version=account_config.PRIVACY_VERSION)
    assert result["status"] == "confirm_email"
    assert auth.signed_up["options"]["data"]["privacy_version"] == \
        account_config.PRIVACY_VERSION


def test_notice_describes_the_shop(notice):
    # the purchases table and the local copy of what is owned (account_ui caches it
    # under account/owned/<user>), and that deleting the account removes purchases
    from src.gui.components import account_ui
    assert "account/owned/" in account_ui.AccountMixin._owned_cache_key(None, "x")
    for phrase in ("Shop purchases", "the points paid", "marked as given",
                   "list of Shop items you own", "actual points",
                   "badges, Shop purchases, point decays and run records are deleted"):
        assert phrase in notice, phrase


def test_notice_describes_the_point_decay(notice):
    # the rule the notice states = the rule the GUI explains (account_ui.DECAY_RULE)
    from src.gui.components.account_ui import DECAY_RULE
    for number in ("-3 %", "-5 %", "5 points"):
        assert number in DECAY_RULE and number in notice, number
    assert "time of your last login" in notice


def test_notice_describes_the_run_locations(notice):
    for phrase in ("first gauge", "0.001°", "anonymous", "cannot be shown, exported or "
                   "deleted per person", "Record the location of my runs",
                   "Info ▸ World Map", "Only runs that earn a point",
                   "Your location - latitude/longitude",
                   "Show my location on the world map", "without your name"):
        assert phrase in notice, phrase
