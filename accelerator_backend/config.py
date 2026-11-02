"""Accelerator server URLs - duplicated from
``src/gui/utils/accelerator_config.py`` on purpose: ``accelerator_backend/``
is a separate component (its own test runner, eventually its own GitHub
Actions deployment), not meant to import from ``src/gui/`` at all. Keep
both in sync if these ever change.
"""

SERVER_URL = "https://accelerator.iiasa.ac.at"
API_BASE = f"{SERVER_URL}/api/v1"
OAUTH_BASE = f"{API_BASE}/oauth/device"
ATERM_BASE = f"{API_BASE}/aterm-cli"
