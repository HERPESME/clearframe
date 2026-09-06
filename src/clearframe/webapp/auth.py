"""Who is signed in, and what they are allowed to do.

Before this, the role was a string the browser chose for itself. `X-ClearFrame-
Role: legal` was checked on two of seventeen endpoints, and `scripts/smoke.sh`
demonstrates the bypass as its happy path — it gets a 403 as `editor`, changes
one header value, and records every decision. Meanwhile the endpoints that
actually SPEND MONEY had no check at all: the upload that runs three Gemini
video passes and up to twenty-five Parallel Task runs, the grounding calls, the
freshness search, the monitors the dossier creates.

Two design rules, both load-bearing:

**Opt-in.** With `CLEARFRAME_AUTH` unset nothing here engages and the app
behaves exactly as it always has. That is not timidity — it is what keeps a
credential-free test suite and smoke script green, and keeps the public demo
reachable by a judge who has no account and should not need one.

**One seam.** `verify_token` is the only function that talks to Google, so
every test runs with no network and no credentials by replacing it.

The ID token rides in an HttpOnly cookie rather than an Authorization header,
because three things the player depends on cannot send headers at all:
`EventSource` for the pipeline stream, `<video src>` for the footage, and the
`<a href>` that downloads the dossier. A scheme that only worked for `fetch`
would lock the reviewer out of the video.

Deliberately NOT a Firebase session cookie. `create_session_cookie` needs
Identity Toolkit signing rights that may not be present under a user-account
ADC, and discovering that days before a deadline is a bad trade. The ID token
is verified in full on every request — signature, issuer, audience, expiry —
and the client refreshes it. Session cookies are the hardening upgrade.
"""

import json
import os

from pydantic import BaseModel

# The cookie the browser sends back on every request, including the ones that
# cannot set headers.
SESSION_COOKIE = "clearframe_session"

# What an authenticated stranger gets. `editor` is the role that can look at
# everything and decide nothing, which is the only safe default: being signed
# in is not the same as being counsel.
DEFAULT_ROLE = "editor"


class AuthUser(BaseModel):
    uid: str
    email: str | None = None
    name: str | None = None
    role: str = DEFAULT_ROLE

    @property
    def actor(self) -> str:
        """What the audit trail records.

        `Decision.reviewer` used to be the role word, so an E&O dossier said
        that "legal" signed off a clearance decision. A job title cannot sign
        anything. Email first because it is the identity a studio recognises.
        """
        return self.email or self.uid


def auth_enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return (env.get("CLEARFRAME_AUTH") or "").strip().lower() == "firebase"


def firebase_web_config(env=None) -> dict:
    """The public client config, served from env rather than committed.

    These values are public by design — they identify the project, they do not
    authorise anything. Kept out of the repo anyway because the GCP project id
    is one of the things to redact before this goes public.
    """
    env = os.environ if env is None else env
    return {
        "apiKey": env.get("FIREBASE_API_KEY", ""),
        "authDomain": env.get("FIREBASE_AUTH_DOMAIN", ""),
        "projectId": env.get("FIREBASE_PROJECT_ID") or env.get("GOOGLE_CLOUD_PROJECT", ""),
        "appId": env.get("FIREBASE_APP_ID", ""),
    }


def _role_map(env=None) -> dict[str, str]:
    """email -> role, from `CLEARFRAME_ROLE_MAP` as JSON.

    Custom claims are the better home for this, but setting one needs an admin
    script and a deploy. An allowlist lets a production name its counsel in an
    environment variable, which is enough to run a real review today.
    """
    env = os.environ if env is None else env
    raw = env.get("CLEARFRAME_ROLE_MAP")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k).strip().lower(): str(v).strip().lower() for k, v in parsed.items()}


def verify_token(raw: str) -> dict:
    """Verify a Firebase ID token and return its claims. The only seam.

    Imported lazily so `firebase-admin` stays an optional extra: the deployed
    demo container installs base dependencies only and has no Google packages
    in it at all.
    """
    import firebase_admin
    from firebase_admin import auth as fb_auth

    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return fb_auth.verify_id_token(raw)


def user_from_token(raw: str, env=None) -> AuthUser:
    """Claims -> user. Raises whatever `verify_token` raises on a bad token."""
    claims = verify_token(raw)
    email = claims.get("email")
    # Custom claim first (it travels with the account), then the allowlist,
    # then the least-privileged default. Never the caller's own assertion.
    role = (claims.get("role") or "").strip().lower()
    if not role and email:
        role = _role_map(env).get(email.strip().lower(), "")
    return AuthUser(
        uid=claims.get("uid") or claims.get("sub") or "",
        email=email,
        name=claims.get("name"),
        role=role or DEFAULT_ROLE,
    )


def user_from_request(request, env=None) -> AuthUser | None:
    """The signed-in user for this request, or None."""
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        return user_from_token(raw, env)
    except Exception:
        # An expired or malformed token is not an error to report, it is simply
        # not a session. The client refreshes and tries again.
        return None


# Paths that must answer before anyone can sign in. A login page that requires
# a login cannot be used, and `/api/meta` is how the client learns whether it
# needs one at all. Webhooks are machine callers with their own secret.
OPEN_PREFIXES = ("/api/meta", "/api/auth/", "/api/webhooks/")


def is_open(path: str) -> bool:
    return any(path.startswith(p) for p in OPEN_PREFIXES)


def webhook_secret(env=None) -> str:
    env = os.environ if env is None else env
    return (env.get("CLEARFRAME_WEBHOOK_SECRET") or "").strip()
