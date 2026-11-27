"""Who is calling? - checks a user's Accelerator access token with ``/user/me``.

The service never trusts an identity sent in a request body: the ``uid`` always comes
from here. Read-only towards Accelerator. Standard library only, so the service's
Docker image needs no packages. Only ``uid`` and the display name are kept (in memory,
for a few minutes); the email address is never stored.
"""

import hashlib
import json
import time
import urllib.error
import urllib.request

import config

CACHE_SECONDS = 300
_CACHE_MAX = 2000
_TIMEOUT_SECONDS = 10

_cache = {}          # sha256(token) -> (expires_at, identity)


class IdentityError(Exception):
    """``code``: ``unauthorized`` (token refused) or ``unavailable`` (Accelerator unreachable)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def verify(token, now=time.monotonic):
    """``{"uid": int, "name": str}`` for a valid access token, else ``IdentityError``."""
    if not token or not isinstance(token, str):
        raise IdentityError("unauthorized")
    key = hashlib.sha256(token.encode()).hexdigest()
    hit = _cache.get(key)
    if hit and hit[0] > now():
        return hit[1]

    req = urllib.request.Request(f"{config.ATERM_BASE}/user/me/",
                                 headers={"x-authorization": token})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise IdentityError("unauthorized" if exc.code in (401, 403) else "unavailable") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise IdentityError("unavailable") from exc

    uid = data.get("uid") if isinstance(data, dict) else None
    if isinstance(uid, bool) or not isinstance(uid, int) or uid <= 0:
        raise IdentityError("unauthorized")
    identity = {"uid": uid, "name": str(data.get("full_name") or "")}

    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[key] = (now() + CACHE_SECONDS, identity)
    return identity
