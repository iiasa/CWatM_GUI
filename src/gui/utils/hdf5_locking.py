"""HDF5 file locking over network-mounted filesystems.

netCDF4 (built on HDF5) defaults to using HDF5's own file-locking, which
many network-backed filesystems - NFS, SMB/CIFS, FUSE mounts, Docker
volumes, WSL2 drives - don't support correctly. The symptom is a cryptic
"NetCDF: HDF error" with no hint that locking is the cause. Confirmed live:
CWatM failed exactly this way reading ups.nc over an accli-mounted
Accelerator project drive (a drive letter backed by an NFS-over-loopback
bridge, e.g. "\\\\127.0.0.1 (W:)") - a legitimate, expected way to run the
existing desktop GUI directly against Accelerator-hosted data, with no
remote job dispatch involved.

HDF5_USE_FILE_LOCKING=FALSE is the standard, widely documented mitigation
for this across the netCDF4/HDF5/xarray ecosystem. It's safe for CWatM's
own I/O pattern: many input files read sequentially and never written to,
each output file written by exactly one process at a time, never shared
across concurrent writers within a single run.

Applied unconditionally - same reasoning as the rasterio warning filter
next to this module: it's one environment value that costs nothing for an
ordinary local-disk run, and reliably detecting "is this path on a network
filesystem" across drive letters, UNC paths and mapped drives alike isn't
worth doing when the blanket fix is free.
"""

import os

#: The environment variable HDF5 itself reads at its own first
#: initialization (inside the first netCDF4/h5py import) - must be set
#: before that happens, same timing requirement as PYTHONWARNINGS.
HDF5_LOCKING_VAR = "HDF5_USE_FILE_LOCKING"
HDF5_LOCKING_VALUE = "FALSE"


def apply(export_env=True):
    """Set the variable in this process and (by default) export it for any
    child process. Call as early as possible - before numpy/rasterio/cwatm
    are imported, same as warning_filters.apply()."""
    os.environ.setdefault(HDF5_LOCKING_VAR, HDF5_LOCKING_VALUE)
    if export_env:
        export_to_environment(os.environ)


def export_to_environment(env):
    """Set our value in `env` (os.environ or any dict-like) unless the user
    already set their own there. Returns the value in effect."""
    env.setdefault(HDF5_LOCKING_VAR, HDF5_LOCKING_VALUE)
    return env[HDF5_LOCKING_VAR]
