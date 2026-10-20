# MODFLOW coupling: why the groundwater tests stopped, and the fix

Status 2026-10-02: **fixed** - the 3 MODFLOW pytest cases (3rd and 4th Bhima, 3rd Burgenland) pass again
(4 passed together with 1st Burgenland, 3 min).

## 1. Symptom

A pytest run stopped at the first MODFLOW case ("3rd Bhima - with Groundwater and with crop specific data").
The whole Python process ended with exit code 2:

- only a single `2` is printed, no Python traceback, no CWatM error
- `sys.exit` / `os._exit` are not called and `atexit` is not reached -> the process is ended from native (Fortran) code
- the same with a direct run: `python run_cwatm.py settings_Bhima_03.ini` -> prints `2`, exit code 2

Because the process ends, the rest of the pytest list is not run at all.

## 2. Finding 1: MODFLOW runs in the wrong folder (xmipy 1.5)

The last Python call before the exit is `xmipy.XmiWrapper.initialize()` in
`cwatm/hydrological_modules/groundwater_modflow/modflow6.py`, `load_bmi()`.
MODFLOW writes `mfsim.lst` into the folder where CWatM was started (here `pytest/`), not into the MODFLOW `wd` folder:

    ERROR REPORT:
      1.       SPECIFIED FILE STATUS: OLD
      ...
      5.         IOSTAT ERROR NUMBER: 29
      6.  -- STOP EXECUTION (openfile)

IOSTAT 29 (Intel Fortran) = file not found. MODFLOW cannot open the files listed in `mfsim.nam`, because they are
given relative to the `wd` folder. The Fortran `STOP` ends the whole process with code 2, so the `try/except`
around `initialize` cannot catch it.

Reason: newer xmipy versions (installed: **xmipy 1.5.0**) store the current folder when the wrapper is created
(`working_directory = Path.cwd()` if not given) and change into it in **every** call (`initialize`, `update`,
`get_value_ptr`, ...). CWatM creates the wrapper before its own `with cd(self.working_directory)`, so xmipy
changes back to the start folder inside `initialize()`. Older xmipy versions did not change the folder, so the
old code worked with them.

### Change (modflow6.py, `load_bmi`)

Before:

```python
            self.mf6 = xmipy.XmiWrapper(library_path)
```

After:

```python
            # xmipy >= 1.1 changes to working_directory for every call (default: folder at creation time)
            self.mf6 = xmipy.XmiWrapper(library_path, working_directory=self.working_directory)
```

After this change MODFLOW initializes, and the process does not exit any more.

## 3. Finding 2: libmf6.dll too old for xmipy 1.5

Next error (now a normal Python error, the test fails instead of the process ending):

    File "modflow6.py", line 242, in load_bmi
        self.recharge = self.mf6.get_value_ptr(recharge_tag)[:, 0]
    File "xmipy/xmiwrapper.py", line 455, in get_value_ptr
        self.lib.get_value_ptr,
    AttributeError: function 'get_value_ptr' not found

The dll in `P:/watmodel/Modflow/mf6/libmf6.dll` is **MODFLOW 6.2.2 (July 2021)**. It only exports the old
`get_value_ptr_double` / `get_value_ptr_int`; xmipy 1.5 calls the newer `get_value_ptr`.

| Function | libmf6 6.2.2 (mf6) | libmf6 6.8.1 (mf6_681) |
|---|---|---|
| `get_value_ptr` | no | yes |
| `get_value_ptr_double` | yes | yes |
| `get_value_ptr_int` | yes | yes |
| `get_version` | no | yes |

### Change (new MODFLOW version, test settings)

- MODFLOW **6.8.1** (USGS release 2026-09-23, `mf6.8.1_win64.zip` from
  https://github.com/MODFLOW-ORG/modflow6/releases) - the `bin` folder (`libmf6.dll`, `mf6.exe`, `mf5to6.exe`,
  `zbud6.exe`) is copied to the new folder `P:/watmodel/Modflow/mf6_681`. The old folder `P:/watmodel/Modflow/mf6`
  is not changed.
- `pytest/settings/1km/Bhima/settings_Bhima.ini` and `pytest/settings/1km/Burgenland/settings_burgenland.ini`:

```ini
#path_mf6dll = P:/watmodel/Modflow/mf6
# MODFLOW 6.8.1 (2026): xmipy >= 1.3 needs get_value_ptr, not in libmf6 6.2.2 (2021) in mf6
path_mf6dll = P:/watmodel/Modflow/mf6_681
```

(`settings_Bhima_01..04.ini` / `settings_burgenland_01..03.ini` are written by pytest from these base files.)

## 4. Test

    cd pytest
    python -m pytest test_cwatm3.py --settingsfile=cwatm_pytests_settings.ini --cwatm=../run_cwatm.py
           -k "(Bhima and Groundwater and not without) or (Burgenland and groundwater) or (1st and Burgenland)"

Result: 4 passed (3rd Bhima, 4th Bhima, 3rd Burgenland, 1st Burgenland).

Note: the results now come from MODFLOW 6.8.1 instead of 6.2.2. A comparison with 6.2.2 is not possible with
xmipy 1.5 (6.2.2 does not run with it). "Passed" means the checks in `test_cwatm3.py`.

## 5. Open points

- Other pytest settings still point to the old dll (`path_mf6dll = P:\watmodel\Modflow\mf6`): Morava (also
  calibration), Tisa, UpperDanube, Rhine 5min, Niger, Ebro. This only matters if `modflow_coupling = True` there.
- Version limits are not checked: only xmipy 1.5.0 + libmf6 6.2.2 (fails) and xmipy 1.5.0 + libmf6 6.8.1 (works)
  were tested. The numbers "xmipy >= 1.1" (working_directory) and "xmipy >= 1.3" (get_value_ptr) in the comments
  are estimates. An old xmipy without the `working_directory` argument would give a `TypeError`.
  Requirements could say: a current xmipy together with a current libmf6.
- CLAUDE.md lists flopy 3.3.2; installed here are flopy 3.10.0 and xmipy 1.5.0 (Python 3.12).
- ~~`load_bmi`: the bare `except:` around `initialize` cannot catch a Fortran `STOP`~~ - done 2026-10-04, see 6.

## 6. MODFLOW errors without ending Python (2026-10-04)

A Fortran `STOP` in libmf6 ends the whole process; it cannot be caught in Python. Two changes:

1. Checks before `initialize` in `modflow6.py` (`load_bmi`), each gives a CWatM error:
   - Error 310: `libmf6.dll` / `libmf6.so` not found or cannot be loaded
   - Error 311: libmf6 too old for xmipy (missing functions, e.g. `get_value_ptr` in 6.2.2)
   - Error 226: `mfsim.nam` not found (`load_modflow_from_disk = True` without a created model)
   - Error 227: files listed in `mfsim.nam` or the model name file are missing in `wd`
   - Error 312: `initialize` raised a Python error (+ ERROR REPORT of `mfsim.lst`)
2. `modflow6_process.py`: `ModFlowProcess` runs `ModFlowSimulation` (and libmf6) in a child process
   (multiprocessing, spawn). The arrays go through a Pipe with their dtype - results are bit-identical.
   - Error 313: the child process ended (e.g. Fortran STOP, exit code 2) - with the ERROR REPORT of `mfsim.lst`
   - Error 314: Python error in the child process during a time step (e.g. XMIError, no convergence)
   - Python keeps running, the next run (pytest, calibration) starts a new child process with a fresh libmf6
   - `mfsim.lst` in `wd` is deleted before the start (no old error report)
   - `modflow_subprocess = False` in the settings file: libmf6 in the CWatM process as before

Tested: Bhima 3 / Burgenland 3 bit-identical with and without child process (Bhima 107 s both, Burgenland 47 s
vs 43 s); wrong `TRANSIENT.ims` (before: exit code 2 without message, now Error 313 with "Error occurred while
reading file 'TRANSIENT.ims'"), missing file (227), old dll (311), killed child (313), wrong array (314);
pytest MODFLOW subset 4 passed.

Setting: `modflow_subprocess = True` (default, also if the key is missing) or `False`, in section
`[GROUNDWATER_MODFLOW]` next to `load_modflow_from_disk` (added to the pytest base settings of Bhima and Burgenland).

pytest: `test_modflow_error` (tiny MODFLOW model written to tmp_path, no input data): Error 313 (wrong
`TRANSIENT.tdis`, child process), 227 and 226 with True and False; `4th Burgenland` runs with
`modflow_subprocess = False`, `3rd Burgenland` with True.

Note: on Windows the child process imports the `__main__` file again - a script that runs CWatM with MODFLOW
needs `if __name__ == "__main__":` (run_cwatm.py and pytest have it).

## 7. Several layers and steady state (merged from Dor's version, 2026-10-09)

Details: `cwatm/hydrological_modules/groundwater_modflow/claude_dor_modflow.md` (steps 1-9 with tests),
`wmodflow.md` section 21, `todiscuss_ms_df.md` (open questions), `bug_report.md` (bugs in Dor's version).
New keys in [GROUNDWATER_MODFLOW] (a key without number is layer 1; all optional except as noted):

| key | meaning | default |
|---|---|---|
| `nlay` | number of ModFlow layers (same active cells) | 1 |
| `thickness<n>`, `poro<n>`, `permeability<n>` | per layer: value, CWatM map or raster at ModFlow resolution (required for each layer) | - |
| `permeability_vertical<n>` | vertical permeability (k33, m/s) | horizontal |
| `specific_storage<n>` | specific storage (1/m) | 0 |
| `confined<n>` | 0 confined, 1 convertible | 1 |
| `specific_yield_coeff<n>` | specific yield = poro * coefficient | 1 |
| `initial_water_table_depth<n>` | depth below the top of the aquifer | layer 1 |
| `pump_location<n>` | > 0: wells in this layer | all active cells |
| `water_table_limit_for_pumping` | minimum saturated fraction kept in each layer (new meaning) | 0.7 |
| `modflow_solver` | simple, complex, super_complex, cooley | simple |
| `topo_percentile_modflow`, `topo_percentile_prm` | drains at a sub-grid elevation percentile (netCDF) | -, z_p10 |
| `adjust_drainage_by_river`, `chanWidthThreshold` | drains of main rivers at bankfull bottom + water depth | False, 25 m |
| `channel_ratio_lakes` | channel ratio 1 under lakes / reservoirs | False |
| `wetland_fraction`, `wetland_bf_coeff` | wetland fraction as minimum channel ratio | -, 1 |
| `collect_recharge` | share of the recharge exported to other basins | - |
| `lowPermabilityCover` | recharge limit (m/day) in soil.py, with permeability_vertical | - |
| `run_only_steady_state` | steady state only, head -> steady_state_heads.nc, no time step | False |
| `longterm_recharge`, `Ndays_steady`, `modflow_solver_steady` | steady state recharge (m/day), period, solver | 0.0001, 1, dbd |
| `include_constant_head_steady_state`, `chd_boundary_map`, `chd_absolute` | constant head (steady state) | False |
| `cal_prm<n>`, `cal_prm_v<n>` | permeability multipliers (steady state) | 1 |

New outputs: `head<n>`, `gwdepth<n>`, `groundwater_storage_total`, `depth_to_water`, `sum_gwRecharge_actualM`,
`rejected_recharge_previous_day`, `sum_gwRechargeExported`, `balance_gw`, `permeability_vertical`, `recharge_limit`.
New errors: 146 (nlay < 1), 149 (layers of a head file), 150-153 (see 61_errors.rst).
