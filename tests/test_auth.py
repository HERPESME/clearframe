"""Who is allowed to do this, and who actually did it.

Until now the answer to both was a string the browser chose for itself.
`X-ClearFrame-Role: legal` was checked on two of seventeen endpoints, and the
smoke script's happy path is literally to change that header from `editor` to
`legal` to get past a 403. Meanwhile every endpoint that SPENDS MONEY — the
upload that runs three Gemini video passes and up to 25 Parallel Task runs, the
grounding calls, the freshness search, the dossier's monitor creation — had no
check at all. The cheap mutations were guarded and the expensive ones were not.

The second half matters more for the product than the first. `Decision.reviewer`
was set to the role word, so an E&O dossier's audit trail recorded that *"legal"*
signed off a clearance decision. A job title cannot sign anything. With a
verified user it records the person.

Two properties hold this design together:

  Auth is OPT-IN. `CLEARFRAME_AUTH` unset means the app behaves exactly as it
  always has — which is what keeps 683 tests and a credential-free smoke script
  green, and keeps the public demo reachable by a judge with no account.

  Verification is one seam. `verify_token` is the only thing that talks to
  Google, so every test below runs with no network and no credentials.
"""

import json

import pytest
from fastapi.testclient import TestClient

from clearframe.webapp import auth
from clearframe.webapp.server import create_app


def _state(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "p1.json").write_text(json.dumps({
        "production": {"id": "p1", "title": "t", "footage_uri": "c.mp4",
                       "duration_s": 10.0, "fps": 24.0},
        "elements": [{
            "id": "e1", "label": "Nike", "element_type": "LOGO",
            "description": "", "category": "TRADEMARK",
            "time_ranges": [{"start_s": 1.0, "end_s": 4.0}],
            "prominence": {"screen_time_s": 3.0, "frame_coverage": 0.1,
                           "centrality": 0.5, "plot_integral": False},
        }],
    }))


def _signed_in(monkeypatch, email="reviewer@studio.com", claims=None):
    """Stand in for Google. The only place the real SDK would be called."""
    token = {"uid": "uid-1", "email": email, "name": "A Reviewer"}
    token.update(claims or {})
    monkeypatch.setattr(auth, "verify_token", lambda _raw: token)


# --- off by default -----------------------------------------------------------


def test_with_auth_off_everything_answers_exactly_as_before(tmp_path, monkeypatch):
    """The property that keeps the suite, the smoke script and the demo alive."""
    monkeypatch.delenv("CLEARFRAME_AUTH", raising=False)
    _state(tmp_path)
    c = TestClient(create_app(out_root=tmp_path))

    assert c.get("/api/productions").status_code == 200
    assert c.get("/api/productions/p1").status_code == 200
    assert c.get("/api/meta").status_code == 200


def test_with_auth_off_the_role_header_still_decides(tmp_path, monkeypatch):
    """Unchanged on purpose: demo mode has no user to ask."""
    monkeypatch.delenv("CLEARFRAME_AUTH", raising=False)
    _state(tmp_path)
    c = TestClient(create_app(out_root=tmp_path))

    refused = c.post("/api/productions/p1/decisions",
                     headers={"X-ClearFrame-Role": "editor"},
                     json={"element_id": "e1", "action": "approve_risk"})
    assert refused.status_code == 403


# --- on: nothing gets through unauthenticated ---------------------------------


@pytest.mark.parametrize("method,path", [
    ("get", "/api/productions"),
    ("get", "/api/productions/p1"),
    ("get", "/api/productions/p1/ground?at_s=2"),
    ("post", "/api/productions/p1/preground"),
    ("post", "/api/productions/p1/dossier"),
    ("get", "/api/licences"),
])
def test_every_api_route_is_closed_without_a_session(tmp_path, monkeypatch, method, path):
    """Including the ones that spend money, which had no check of any kind."""
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    _state(tmp_path)
    c = TestClient(create_app(out_root=tmp_path))

    assert getattr(c, method)(path).status_code == 401


def test_the_sign_in_surface_stays_reachable(tmp_path, monkeypatch):
    """A login page that needs a login cannot be used."""
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    _state(tmp_path)
    c = TestClient(create_app(out_root=tmp_path))

    assert c.get("/api/meta").status_code == 200
    assert c.get("/api/auth/config").status_code == 200
    assert c.get("/api/auth/me").status_code == 401  # answers, does not 500


def test_a_verified_token_opens_a_session(tmp_path, monkeypatch):
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    _state(tmp_path)
    _signed_in(monkeypatch)
    c = TestClient(create_app(out_root=tmp_path))

    opened = c.post("/api/auth/session", json={"idToken": "anything"})
    assert opened.status_code == 200
    assert opened.json()["email"] == "reviewer@studio.com"
    # The cookie is what carries it, because EventSource, <video src> and a
    # download link cannot send an Authorization header.
    assert c.get("/api/productions").status_code == 200


def test_a_rejected_token_opens_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    _state(tmp_path)

    def _refuse(_raw):
        raise ValueError("token expired")

    monkeypatch.setattr(auth, "verify_token", _refuse)
    c = TestClient(create_app(out_root=tmp_path))

    assert c.post("/api/auth/session", json={"idToken": "stale"}).status_code == 401
    assert c.get("/api/productions").status_code == 401


def test_signing_out_closes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    _state(tmp_path)
    _signed_in(monkeypatch)
    c = TestClient(create_app(out_root=tmp_path))

    c.post("/api/auth/session", json={"idToken": "x"})
    c.post("/api/auth/signout")
    assert c.get("/api/productions").status_code == 401


# --- role comes from the verified user, never from the caller -----------------


def test_a_stranger_gets_the_role_that_cannot_decide(tmp_path, monkeypatch):
    """Least privilege. Being signed in is not the same as being counsel."""
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    _state(tmp_path)
    _signed_in(monkeypatch, email="someone@example.com")
    c = TestClient(create_app(out_root=tmp_path))

    assert c.post("/api/auth/session", json={"idToken": "x"}).json()["role"] == "editor"
    refused = c.post("/api/productions/p1/decisions",
                     json={"element_id": "e1", "action": "approve_risk"})
    assert refused.status_code == 403


def test_the_role_header_cannot_promote_an_authenticated_user(tmp_path, monkeypatch):
    """The whole bypass, closed: the header stops being evidence."""
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    _state(tmp_path)
    _signed_in(monkeypatch, email="someone@example.com")
    c = TestClient(create_app(out_root=tmp_path))
    c.post("/api/auth/session", json={"idToken": "x"})

    refused = c.post("/api/productions/p1/decisions",
                     headers={"X-ClearFrame-Role": "legal"},
                     json={"element_id": "e1", "action": "approve_risk"})
    assert refused.status_code == 403


def test_a_custom_claim_carries_the_role(tmp_path, monkeypatch):
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    _state(tmp_path)
    _signed_in(monkeypatch, claims={"role": "legal"})
    c = TestClient(create_app(out_root=tmp_path))

    assert c.post("/api/auth/session", json={"idToken": "x"}).json()["role"] == "legal"


def test_an_allowlist_can_grant_the_role_without_touching_firebase(tmp_path, monkeypatch):
    """Setting custom claims needs an admin script; a hackathon needs a file."""
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    monkeypatch.setenv("CLEARFRAME_ROLE_MAP",
                       '{"counsel@studio.com": "legal"}')
    _state(tmp_path)
    _signed_in(monkeypatch, email="counsel@studio.com")
    c = TestClient(create_app(out_root=tmp_path))

    assert c.post("/api/auth/session", json={"idToken": "x"}).json()["role"] == "legal"


# --- the audit trail names a person -------------------------------------------


def test_the_decision_is_attributed_to_the_person_not_the_job_title(tmp_path, monkeypatch):
    """`reviewer` used to be the word "legal". Nobody can sign as a job title."""
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    monkeypatch.setenv("CLEARFRAME_ROLE_MAP", '{"counsel@studio.com": "legal"}')
    _state(tmp_path)
    _signed_in(monkeypatch, email="counsel@studio.com")
    c = TestClient(create_app(out_root=tmp_path))
    c.post("/api/auth/session", json={"idToken": "x"})

    ok = c.post("/api/productions/p1/decisions",
                json={"element_id": "e1", "action": "approve_risk"})
    assert ok.status_code == 200

    state = json.loads((tmp_path / "state" / "p1.json").read_text())
    assert state["decisions"]["e1"]["reviewer"] == "counsel@studio.com"
    assert any(e["actor"] == "counsel@studio.com" for e in state["audit_log"])


# --- the webhook is not a user, and needs its own secret ----------------------


def test_the_webhook_is_open_when_no_secret_is_configured(tmp_path, monkeypatch):
    """Unchanged default, so the smoke script keeps working."""
    monkeypatch.delenv("CLEARFRAME_WEBHOOK_SECRET", raising=False)
    _state(tmp_path)
    c = TestClient(create_app(out_root=tmp_path))

    r = c.post("/api/webhooks/parallel-monitor",
               json={"monitor_id": "nope", "summary": "s"})
    assert r.status_code == 404  # reached the handler; no watch matched


def test_a_configured_secret_refuses_an_unsigned_webhook(tmp_path, monkeypatch):
    """It writes to the audit trail and can reopen a signed-off dossier.

    Monitor ids are readable from an open endpoint, so without this anyone can
    forge an alert against a real finding.
    """
    monkeypatch.setenv("CLEARFRAME_WEBHOOK_SECRET", "s3cret")
    _state(tmp_path)
    c = TestClient(create_app(out_root=tmp_path))

    unsigned = c.post("/api/webhooks/parallel-monitor",
                      json={"monitor_id": "m1", "summary": "forged"})
    assert unsigned.status_code == 401

    wrong = c.post("/api/webhooks/parallel-monitor",
                   headers={"X-ClearFrame-Signature": "guess"},
                   json={"monitor_id": "m1", "summary": "forged"})
    assert wrong.status_code == 401

    signed = c.post("/api/webhooks/parallel-monitor",
                    headers={"X-ClearFrame-Signature": "s3cret"},
                    json={"monitor_id": "m1", "summary": "real"})
    assert signed.status_code == 404  # authorised, just no matching watch
