"""`src/gui/managers/date_manager.py` - the parts of DateManager that don't need a
real QDateEdit widget.

`_resolve_date_value` is pure logic that doesn't touch `self` at all: CWatM allows
SpinUp/StepEnd to be given as either a date or an integer number of timesteps counted
from StepStart (StepStart = timestep 1), and this is the one place that turns that
into a QDate for the field widgets. The forcing-range cache
(`set_forcing_provider`/`invalidate_forcing_range`/`refresh_forcing_range`/
`forcing_range`) is plain state management that only touches `self.timeline` (None
until `create_date_widgets` runs), so it is also exercisable on a bare `DateManager()`
with no widgets created.

`set_dates_from_config`/`validate_dates`/`dates_changed_from_config` all guard on
`self.start_date_edit` etc. being real `QDateEdit` widgets and are left untested here -
covering them needs the widgets `create_date_widgets` builds, which is a bigger,
lower-value lift than the pure logic above.
"""

import pytest

from PySide6.QtCore import QDate

from src.gui.components.config_parser import ConfigParser
from src.gui.managers.date_manager import DateManager

pytestmark = pytest.mark.qt


@pytest.fixture
def dm():
    return DateManager()


@pytest.fixture
def cfgp():
    return ConfigParser()


class TestResolveDateValue:
    def test_a_real_date_string_is_used_directly(self, dm, cfgp):
        result = dm._resolve_date_value("1/1/2000", cfgp, QDate(1999, 1, 1))
        assert result == QDate(2000, 1, 1)

    def test_an_integer_is_days_from_start_date_step_1(self, dm, cfgp):
        # SpinUp/StepEnd = 45 means timestep 45; StepStart itself is timestep 1,
        # so the offset is (45 - 1) days.
        start = QDate(2000, 1, 1)
        result = dm._resolve_date_value("45", cfgp, start)
        assert result == start.addDays(44)

    def test_a_float_looking_integer_string_also_works(self, dm, cfgp):
        start = QDate(2000, 1, 1)
        assert dm._resolve_date_value("45.0", cfgp, start) == start.addDays(44)

    def test_whitespace_around_the_integer_is_trimmed(self, dm, cfgp):
        start = QDate(2000, 1, 1)
        assert dm._resolve_date_value("  10  ", cfgp, start) == start.addDays(9)

    def test_an_integer_with_no_start_date_returns_none(self, dm, cfgp):
        assert dm._resolve_date_value("10", cfgp, None) is None

    def test_neither_a_date_nor_an_integer_returns_none(self, dm, cfgp):
        assert dm._resolve_date_value("not-a-date", cfgp, QDate(2000, 1, 1)) is None

    def test_empty_value_returns_none(self, dm, cfgp):
        assert dm._resolve_date_value("", cfgp, QDate(2000, 1, 1)) is None

    def test_none_value_returns_none(self, dm, cfgp):
        assert dm._resolve_date_value(None, cfgp, QDate(2000, 1, 1)) is None


class TestForcingRangeCache:
    def test_initially_unknown(self, dm):
        assert dm.forcing_range() is None

    def test_setting_a_provider_marks_the_cache_dirty(self, dm):
        dm.set_forcing_provider(lambda: None)
        assert dm._forcing_dirty is True

    def test_refresh_reads_the_provider_once_while_clean(self, dm):
        calls = []

        def provider():
            calls.append(1)
            return (QDate(2000, 1, 1), QDate(2010, 12, 31))

        dm.set_forcing_provider(provider)
        dm.refresh_forcing_range()
        assert dm.forcing_range() == (QDate(2000, 1, 1), QDate(2010, 12, 31))
        assert len(calls) == 1

        dm.refresh_forcing_range()                # not dirty any more - no re-read
        assert len(calls) == 1

    def test_refresh_without_a_provider_is_a_no_op(self, dm):
        dm.refresh_forcing_range()
        assert dm.forcing_range() is None

    def test_a_provider_error_yields_none_and_stops_retrying(self, dm):
        calls = []

        def provider():
            calls.append(1)
            raise RuntimeError("boom")

        dm.set_forcing_provider(provider)
        dm.refresh_forcing_range()
        assert dm.forcing_range() is None
        assert dm._forcing_dirty is False          # a failed read isn't retried every open

        dm.refresh_forcing_range()
        assert len(calls) == 1

    def test_invalidate_schedules_a_re_read_on_the_next_refresh(self, dm, qapp):
        calls = []

        def provider():
            calls.append(1)
            return (QDate(2000, 1, 1), QDate(2001, 1, 1))

        dm.set_forcing_provider(provider)
        dm.refresh_forcing_range()
        assert len(calls) == 1

        dm.invalidate_forcing_range()              # a new settings file was loaded
        assert dm._forcing_dirty is True
        dm.refresh_forcing_range()
        assert len(calls) == 2
