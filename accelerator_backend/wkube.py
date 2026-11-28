"""Dispatch file for the CWatM points service (an Accelerator interactive routine).

    cd accelerator_backend
    accli login
    accli dispatch cwatm-points-ledger points_service

Build context is the repository (branch below); the image is ``service.Dockerfile``.
The address is ``https://<TUNNEL_NAME>.wkube.iiasa.ac.at`` and must equal
``accelerator_config.points_service_url()`` in the GUI. ``selected_foldernames`` is the one
project folder the service may see; it appears as ``/mnt/wdrv/ledger`` in the container, so
the service (``LEDGER_DIR=/mnt/wdrv``) keeps its events in the project's ``ledger/`` folder,
written back when the app stops. A project admin must have enabled interactive routines.
"""

from accli import WKubeTask

PROJECT = "cwatm-points-ledger"

points_service = WKubeTask(
    name="CWatM points service",
    repo_url="https://github.com/iiasa/CWatM_GUI.git",
    repo_branch="accelerator-account",
    docker_filename="accelerator_backend/service.Dockerfile",
    command="python -u points_service.py",
    required_cores=0.5,
    required_ram=0.5,
    required_storage_local=1,
    required_storage_workflow=1,
    timeout=3600,                                   # ignored for interactive routines
    conf={
        "interactive_socket": "0.0.0.0:8000",
        "TUNNEL_NAME": "cwatm-points",
        "WDRV_ACCESS": "read-write",
        "selected_foldernames": f"{PROJECT}/ledger",
        "IDLE_TIMEOUT_MINUTES": "360",
    },
)
