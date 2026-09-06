"""Proving the caller is the queue, not the internet.

Defence in depth, and deliberately the *second* line rather than the first. The
worker is deployed `--no-allow-unauthenticated`, so Cloud Run's own IAM already
refuses anything without a token minted for a service account holding
`run.invoker`. This is what catches the day somebody makes the service public to
debug something and forgets.

One seam, for the same reason `auth.verify_token` is one seam: it is the only
function here that talks to Google, so every test runs offline.

Opt-in, like the auth gate: `CLEARFRAME_WORKER_AUDIENCE` unset means no check,
which is what lets the two-container topology run on a laptop and under a test
client with no credentials at all.
"""

from __future__ import annotations

import logging

log = logging.getLogger("clearframe.worker.oidc")


def verify_token(raw: str, audience: str) -> dict:
    """The only call to Google. Raises on anything it will not vouch for."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(raw, google_requests.Request(), audience)


def verify(raw: str, audience: str, expected_sa: str | None = None) -> bool:
    """True only for a token this worker should act on.

    Checks the signature and audience through the seam above, and then — if one
    is configured — that the caller is the service account the queue was told to
    sign as. Without that last check any Google-issued token for this audience
    would do, which is a much larger set of callers than intended.
    """
    if not raw:
        return False
    try:
        claims = verify_token(raw, audience)
    except Exception as exc:
        log.warning("rejected a worker call: %s", exc)
        return False
    if expected_sa and claims.get("email") != expected_sa:
        log.warning("worker call from unexpected account %s", claims.get("email"))
        return False
    return True
