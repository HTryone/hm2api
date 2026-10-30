"""Process-wide runtime handles; the only place that bridges sync helpers to the ASGI loop."""
from __future__ import annotations

import asyncio
import os
import sys

_STATE = {"upstream": None, "loop": None}


def bind_upstream(client, loop):
    _STATE["upstream"] = client
    _STATE["loop"] = loop


def current_upstream_client(url):
    """Return the running loop's upstream client, or None when called off-loop."""
    client = _STATE["upstream"]
    loop = _STATE["loop"]
    if client is None or loop is None:
        return None
    try:
        if asyncio.get_running_loop() is not loop:
            return None
    except RuntimeError:
        return None
    return client.get(url)


def stderr(message):
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")
