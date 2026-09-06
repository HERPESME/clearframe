"""One person's footage is not another person's footage.

Authentication landed a phase ago and stopped at the door: the middleware
checked that you were signed in and nothing after it asked *who*. So with the
gate on, every signed-in user could read and mutate every production on the
deployment — the findings, the dossier, and the uploaded film itself.

It was worse than a listing leak. `production_id` was the literal string
`"upload"` — a `Form` default meeting a hardcoded client value — so two people
uploading did not merely see each other's work, they *overwrote* it: same state
file, same media directory, and the upload handler actively deletes the previous
occupant's cached boxes and thumbnails.

Two rules make the fix safe to ship:

  **404, never 403.** A 403 confirms the id exists, which turns a guessable id
  into an existence oracle. An unknown production is already a 404 everywhere in
  this file, so somebody else's is indistinguishable from one that never was.

  **Ownership is opt-in, exactly as authentication is.** With `CLEARFRAME_AUTH`
  unset there is no user to scope to and nothing changes — which is what keeps
  demo mode, the credential-free suite and the smoke script green. A production
  with no owner (the demo, anything the CLI or MCP wrote) belongs to everybody.
"""

import json

import pytest
from fastapi.testclient import TestClient

from clearframe.storage import IndexRow, build_backends
from clearframe.config import ClearFrameConfig
from clearframe.webapp import auth
from clearframe.webapp.server import create_app

# Every route that takes a production id. Four of them are reached by browser
# primitives that cannot send a header — <video src>, <img src>, EventSource and
# <a href> — which is exactly why the session rides a cookie.
PID_ROUTES = [
    ("GET", "/api/productions/{pid}"),
    ("GET", "/api/productions/{pid}/media"),
    ("GET", "/api/productions/{pid}/thumbnail"),
    ("GET", "/api/productions/{pid}/ground?at_s=1"),
    ("GET", "/api/productions/{pid}/preground"),
    ("POST", "/api/productions/{pid}/preground"),
    ("GET", "/api/productions/{pid}/events"),
    ("POST", "/api/productions/{pid}/freshness"),
    ("POST", "/api/productions/{pid}/dossier"),
    ("GET", "/api/productions/{pid}/artifacts/dossier.html"),
]


def _state(tmp_path, pid="p1"):
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / f"{pid}.json").write_text(json.dumps({
        "production": {"id": pid, "title": "Alice's Film", "footage_uri": "c.mp4",
                       "duration_s": 10.0, "fps": 24.0},
        "elements": [{
            "id": "e1", "label": "Nike", "element_type": "LOGO",
            "description": "", "category": "TRADEMARK",
            "time_ranges": [{"start_s": 1.0, "end_s": 4.0}],
            "prominence": {"screen_time_s": 3.0, "frame_coverage": 0.1,
                           "centrality": 0.5, "plot_integral": False},
        }],
    }))
    media = tmp_path / "media" / pid
    media.mkdir(parents=True, exist_ok=True)
    (media / "footage.mp4").write_bytes(b"\x00" * 1024)


def _owned_by(tmp_path, uid, pid="p1", title="Alice's Film"):
    """Give the production an owner, the way an upload would."""
    backends = build_backends(ClearFrameConfig.from_env({}), tmp_path)
    backends.index.put(IndexRow(id=pid, owner_uid=uid, title=title))


def _as(monkeypatch, uid, email):
    monkeypatch.setattr(
        auth, "verify_token",
        lambda _raw: {"uid": uid, "email": email, "name": email},
    )


@pytest.fixture
def gated(monkeypatch):
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")


def _client(tmp_path):
    c = TestClient(create_app(out_root=tmp_path))
    c.cookies.set(auth.SESSION_COOKIE, "any-token")
    return c


# --- the leak ------------------------------------------------------------------


@pytest.mark.parametrize("method,path", PID_ROUTES)
def test_another_users_production_is_not_reachable(tmp_path, monkeypatch, gated,
                                                   method, path):
    _state(tmp_path)
    _owned_by(tmp_path, "alice-uid")
    _as(monkeypatch, "bob-uid", "bob@studio.com")
    client = _client(tmp_path)

    resp = client.request(method, path.format(pid="p1"))

    assert resp.status_code == 404, (
        f"{method} {path} let Bob reach Alice's production ({resp.status_code})"
    )


def _refused_as_unknown(resp) -> bool:
    """Was this the OWNERSHIP 404, or an ordinary missing-resource one?

    Three of these routes answer 404 for reasons that have nothing to do with
    who is asking — no extractable poster frame, no event log for a run that
    never started, no dossier generated yet. Asserting on the status alone would
    conflate "hidden from you" with "not there for anybody", and the first is
    the only one this file is about.
    """
    if resp.status_code != 404:
        return False
    try:
        return str(resp.json().get("detail", "")).startswith("Unknown production")
    except ValueError:
        return False


@pytest.mark.parametrize("method,path", PID_ROUTES)
def test_the_owner_is_not_locked_out_of_their_own(tmp_path, monkeypatch, gated,
                                                  method, path):
    """The opposite failure, and the easier one to ship by accident."""
    _state(tmp_path)
    _owned_by(tmp_path, "alice-uid")
    _as(monkeypatch, "alice-uid", "alice@studio.com")
    client = _client(tmp_path)

    resp = client.request(method, path.format(pid="p1"))

    assert not _refused_as_unknown(resp), f"{method} {path} hid Alice's own production"


def test_someone_elses_production_is_404_not_403(tmp_path, monkeypatch, gated):
    """403 would confirm the id exists. With ids in URLs that is an oracle."""
    _state(tmp_path)
    _owned_by(tmp_path, "alice-uid")
    _as(monkeypatch, "bob-uid", "bob@studio.com")
    client = _client(tmp_path)

    seen = client.get("/api/productions/p1").status_code
    unseen = client.get("/api/productions/never-existed").status_code

    assert seen == unseen == 404


def test_the_listing_shows_only_your_own(tmp_path, monkeypatch, gated):
    _state(tmp_path, "p1")
    _state(tmp_path, "p2")
    _owned_by(tmp_path, "alice-uid", "p1")
    _owned_by(tmp_path, "bob-uid", "p2", title="Bob's Film")
    _as(monkeypatch, "alice-uid", "alice@studio.com")
    client = _client(tmp_path)

    rows = client.get("/api/productions").json()

    assert [r["id"] for r in rows] == ["p1"]


# --- what must NOT change ------------------------------------------------------


@pytest.mark.parametrize("method,path", PID_ROUTES)
def test_with_auth_off_nothing_is_scoped(tmp_path, method, path):
    """Ownership is opt-in for the same reason authentication is. This property
    is what keeps demo mode and the credential-free smoke script green."""
    _state(tmp_path)
    _owned_by(tmp_path, "alice-uid")
    client = TestClient(create_app(out_root=tmp_path))

    resp = client.request(method, path.format(pid="p1"))

    assert not _refused_as_unknown(resp)


def test_an_unowned_production_stays_readable_by_anyone(tmp_path, monkeypatch, gated):
    """The demo, and anything the CLI or MCP wrote, has no owner. Hiding those
    would make a signed-in judge's dashboard look empty."""
    _state(tmp_path, "demo")
    _as(monkeypatch, "bob-uid", "bob@studio.com")
    client = _client(tmp_path)

    assert client.get("/api/productions/demo").status_code == 200


def test_a_production_written_before_ownership_existed_is_still_visible(
    tmp_path, monkeypatch, gated
):
    """There is no migration. A production on disk with no index row must not
    vanish from its owner's dashboard the day this ships."""
    _state(tmp_path, "legacy")
    _as(monkeypatch, "alice-uid", "alice@studio.com")
    client = _client(tmp_path)

    rows = client.get("/api/productions").json()

    assert [r["id"] for r in rows] == ["legacy"]
