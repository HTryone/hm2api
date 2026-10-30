"""Neutral session-provider contract shared by every upstream platform.

A platform session is anything that can answer ``token()`` with a bearer
string on demand (raising :class:`SessionError` when unavailable), describe
itself without leaking the secret, and re-read its source on demand.
Implementations: ``loomy_session.LoomySession`` (desktop session file) and
``qwenwork_session.QwenworkSession`` (千问办公 desktop credentials).
"""
from __future__ import annotations


class SessionError(RuntimeError):
    """The platform session source is missing, unreadable or does not yield a usable token."""
