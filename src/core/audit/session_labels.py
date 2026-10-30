"""Record the Loomy session identity as the audit "credential"/"profile" dimension.

The audit store aggregates by ``credential`` and ``profile``; the generic
middleware leaves them empty because it knows nothing about this gateway's
identity model.  Filling them here makes the logs page and the dashboard
distribution meaningful without touching the shared audit implementation.
"""
from __future__ import annotations

import hashlib

from core.audit.observability import observe_route


def session_labels(session):
    """Return (profile, credential) labels for the session that served this request."""
    if session is None:
        return None, None
    try:
        token = session.token()
    except Exception:
        return None, None
    credential = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    return getattr(session, "platform", None) or "loomy", credential


def label_request(session):
    """Attach the session identity to the in-flight audit observation, if any."""
    profile, credential = session_labels(session)
    if profile and credential:
        observe_route(None, None, profile, credential)
