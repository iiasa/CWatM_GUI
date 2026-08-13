"""Array variables and their output indices (`src/gui/utils/var_dims.py`).

This table is **mirrored by hand** from the allocation lists in
`cwatm/hydrological_modules/` (which the hard rule forbids editing), so it can silently
drift from the model. These tests pin the contract its two callers rely on:

* Check settingsfile calls `dim_problem(base, idx)` to flag a bad index;
* Add output variables calls `index_options(base)` to offer the good ones by name.

The two must agree - every suffix the picker offers has to be one `dim_problem` accepts.
That cross-check is the test that would actually catch drift.
"""

import pytest

from src.gui.utils import var_dims


class TestKindOf:
    @pytest.mark.parametrize("base,kind", [
        ("actualET", "landcover6"),
        ("fracVegCover", "landcover6"),
        ("w1", "landcover4"),
        ("rootZoneWaterStorageCap", "landcover4"),
        ("soildepth", "soil3"),
        ("rootDepth", "soil3x4"),
        ("adjRoot", "soil3x4"),
        ("irr_crop", "crop"),
    ])
    def test_known(self, base, kind):
        assert var_dims.kind_of(base) == kind
        assert var_dims.needs_index(base)

    @pytest.mark.parametrize("base", ["discharge", "runoff", "sum_gwRecharge", ""])
    def test_scalar_variables_need_no_index(self, base):
        assert var_dims.kind_of(base) is None
        assert not var_dims.needs_index(base)
        assert var_dims.index_options(base) == []
        assert var_dims.hint_of(base) == ""


class TestDimProblem:
    def test_missing_index_on_a_land_cover_array(self):
        msg = var_dims.dim_problem("actualET", [])
        assert msg and "needs one index" in msg
        assert "actualET[1]" in msg          # the message shows a usable example

    def test_valid_index_is_accepted(self):
        for i in range(6):
            assert var_dims.dim_problem("actualET", [str(i)]) is None

    def test_out_of_range_index(self):
        assert var_dims.dim_problem("actualET", ["6"]) is not None
        assert var_dims.dim_problem("actualET", ["-1"]) is not None

    def test_non_numeric_index(self):
        assert var_dims.dim_problem("actualET", ["grassland"]) is not None

    def test_too_many_indices(self):
        assert var_dims.dim_problem("actualET", ["1", "2"]) is not None

    def test_land_cover_4_stops_at_three(self):
        assert var_dims.dim_problem("w1", ["3"]) is None
        assert var_dims.dim_problem("w1", ["4"]) is not None

    def test_soil_three_layers(self):
        assert var_dims.dim_problem("soildepth", ["2"]) is None
        assert var_dims.dim_problem("soildepth", ["3"]) is not None

    class TestTwoDimensional:
        def test_needs_exactly_two(self):
            assert var_dims.dim_problem("rootDepth", ["0"]) is not None
            assert var_dims.dim_problem("rootDepth", ["0", "1", "2"]) is not None
            assert var_dims.dim_problem("rootDepth", ["0", "1"]) is None

        def test_first_index_is_the_soil_layer(self):
            assert var_dims.dim_problem("rootDepth", ["3", "0"]) is not None
            msg = var_dims.dim_problem("rootDepth", ["9", "0"])
            assert "first index" in msg

        def test_second_index_is_the_land_cover(self):
            msg = var_dims.dim_problem("rootDepth", ["0", "4"])
            assert msg and "second index" in msg

    def test_crop_index_has_no_upper_bound(self):
        # The crop list is user-defined in the settings Excel sheet.
        assert var_dims.dim_problem("irr_crop", ["0"]) is None
        assert var_dims.dim_problem("irr_crop", ["99"]) is None

    def test_crop_index_must_be_a_non_negative_number(self):
        assert var_dims.dim_problem("irr_crop", []) is not None
        assert var_dims.dim_problem("irr_crop", ["-1"]) is not None
        assert var_dims.dim_problem("irr_crop", ["x"]) is not None

    def test_unknown_variable_with_an_index_is_never_flagged(self):
        # Other modules allocate 2-D variables this table does not track; flagging
        # them would produce false errors in Check settingsfile.
        assert var_dims.dim_problem("somethingElse", ["3"]) is None
        assert var_dims.dim_problem("somethingElse", []) is None


class TestIndexOptions:
    def test_land_cover_names_are_offered(self):
        opts = var_dims.index_options("actualET")
        assert len(opts) == 6
        assert opts[0][0] == "[0]"
        assert "forest" in opts[0][1]
        assert "grassland" in opts[1][1]

    def test_land_cover_4_offers_four(self):
        assert len(var_dims.index_options("w1")) == 4

    def test_soil_layers(self):
        opts = var_dims.index_options("soildepth")
        assert len(opts) == 3
        assert "top soil layer" in opts[0][1]

    def test_two_dimensional_offers_the_full_grid(self):
        opts = var_dims.index_options("rootDepth")
        assert len(opts) == 3 * 4
        assert opts[0][0] == "[0][0]"
        assert "[2][3]" in [o[0] for o in opts]

    def test_crop_offers_a_free_entry(self):
        opts = var_dims.index_options("irr_crop")
        # a suffix of None means "ask the user for a number"
        assert opts[-1][0] is None
        assert all(o[0] is not None for o in opts[:-1])

    def test_every_entry_is_suffix_label_tooltip(self):
        for base in ("actualET", "w1", "soildepth", "rootDepth", "irr_crop"):
            for opt in var_dims.index_options(base):
                assert len(opt) == 3
                assert all(isinstance(x, str) for x in opt[1:])


class TestPickerAndCheckerAgree:
    """The regression that matters: every index the picker offers must be one the
    checker accepts. If the mirrored table drifts from cwatm, this is what catches it."""

    @pytest.mark.parametrize("base", [
        "actualET", "fracVegCover", "w1", "rootZoneWaterStorageCap",
        "soildepth", "rootDepth", "adjRoot", "irr_crop",
    ])
    def test_offered_indices_are_accepted(self, base):
        for suffix, label, _tip in var_dims.index_options(base):
            if suffix is None:
                continue                      # "other crop number…" - user types it
            idx = suffix.replace("[", "").rstrip("]").split("]")
            assert var_dims.dim_problem(base, idx) is None, (
                f"{base}{suffix} is offered by the picker but rejected by the checker")

    @pytest.mark.parametrize("base", ["actualET", "w1", "soildepth", "rootDepth"])
    def test_one_past_the_end_is_rejected(self, base):
        """The picker's list is complete: the next index up must be invalid."""
        opts = [o for o in var_dims.index_options(base) if o[0] is not None]
        last = opts[-1][0].replace("[", "").rstrip("]").split("]")
        beyond = [str(int(last[0]) + 1)] + last[1:]
        assert var_dims.dim_problem(base, beyond) is not None

    def test_hints_exist_for_every_indexed_kind(self):
        for base in ("actualET", "w1", "soildepth", "rootDepth", "irr_crop"):
            assert var_dims.hint_of(base)


class TestTableIntegrity:
    def test_the_dimension_sets_do_not_overlap(self):
        sets = {
            "DIM6": var_dims.DIM6, "DIM4": var_dims.DIM4,
            "DIM3X4": var_dims.DIM3X4, "DIM3": var_dims.DIM3,
            "DIMCROP": var_dims.DIMCROP,
        }
        names = list(sets)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                overlap = sets[a] & sets[b]
                assert not overlap, f"{a} and {b} both claim {sorted(overlap)}"

    def test_land_cover_and_soil_layer_names_are_the_expected_length(self):
        assert len(var_dims.LANDCOVER) == 6
        assert len(var_dims.SOIL_LAYERS) == 3
