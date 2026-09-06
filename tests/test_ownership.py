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
    # The one that was missing from this list, and therefore the one route with
    # no ownership check at all — while being the route that writes a signature
    # into somebody's E&O audit trail. A list is only a safety net for what is
    # on it.
    ("POST", "/api/productions/{pid}/decisions"),
]

# Bodies for the routes that need one, so the parametrized cases above get past
# request validation and actually reach the ownership check rather than 422ing
# and looking like a pass.
BODIES = {
    "/api/productions/{pid}/decisions": {
        "element_id": "e1", "action": "approve_risk", "note": "",
    },
}


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


@pytest.fixture
def open_roles(monkeypatch, gated):
    """The configuration the public deployment actually runs.

    Anyone signed in may call themselves `legal`, which is the point — a judge
    has nobody to ask for a grant. It is also the configuration in which a shared
    resource is most dangerous, because the role gate in front of it is one the
    caller sets for themselves. So the ledger tests below run HERE rather than in
    the stricter default, on the principle that a guard should be tested under
    the conditions that stress it.
    """
    monkeypatch.setenv("CLEARFRAME_OPEN_ROLES", "1")


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

    resp = client.request(method, path.format(pid="p1"), json=BODIES.get(path))

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

    resp = client.request(method, path.format(pid="p1"), json=BODIES.get(path))

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

    resp = client.request(method, path.format(pid="p1"), json=BODIES.get(path))

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


# --- the rights ledger ---------------------------------------------------------
#
# The most consequential shared thing in the deployment. One global
# `licences.json` meant Alice's grant for Nike marked Bob's Nike finding COVERED,
# and that conclusion went into Bob's E&O dossier. And because the upload
# defaults to `replace=True` and is gated on a role that an open-roles deployment
# lets the client assert for itself, any visitor could wipe the lot.

_CSV = (
    "rights_holder,work,scope,territories,media,starts,expires,reference,notes\n"
    "Nike Inc,Swoosh,ALL,US,THEATRICAL,2020-01-01,2030-01-01,REF-1,\n"
)


def _upload_ledger(client, csv=_CSV):
    return client.post(
        "/api/licences",
        files={"file": ("ledger.csv", csv.encode(), "text/csv")},
        data={"replace": "true"},
        headers={"X-ClearFrame-Role": "legal"},
    )


def test_one_users_licences_are_not_another_users(tmp_path, monkeypatch, open_roles):
    """Being wrong in the COVERED direction is the one failure the ledger must
    not have: it tells a producer they are cleared when they are not."""
    _as(monkeypatch, "alice-uid", "alice@studio.com")
    alice = _client(tmp_path)
    assert _upload_ledger(alice).status_code == 200

    _as(monkeypatch, "bob-uid", "bob@studio.com")
    bob = _client(tmp_path)

    assert bob.get("/api/licences").json()["licences"] == []


def test_a_visitor_cannot_wipe_someone_elses_ledger(tmp_path, monkeypatch, open_roles):
    """`replace=True` is the default, and with open roles anyone may call
    themselves legal — so this has to be prevented by SCOPE, not by the role."""
    _as(monkeypatch, "alice-uid", "alice@studio.com")
    alice = _client(tmp_path)
    _upload_ledger(alice)

    _as(monkeypatch, "bob-uid", "bob@studio.com")
    _upload_ledger(_client(tmp_path), csv=_CSV.replace("Nike Inc", "Adidas AG"))

    _as(monkeypatch, "alice-uid", "alice@studio.com")
    still = _client(tmp_path).get("/api/licences").json()["licences"]

    assert len(still) == 1
    assert still[0]["rights_holder"] == "Nike Inc"


def test_with_auth_off_the_ledger_stays_global(tmp_path):
    """The demo, the CLI and the smoke script all share one ledger and should:
    there is no user to attribute one to."""
    client = TestClient(create_app(out_root=tmp_path))
    _upload_ledger(client)

    assert len(client.get("/api/licences").json()["licences"]) == 1


# --- taking a production by naming it ------------------------------------------


def test_an_upload_cannot_claim_someone_elses_production(tmp_path, monkeypatch, gated):
    """The id comes back to the client, so it is guessable by its owner and
    quotable by anyone who saw it. Naming it on an upload used to overwrite the
    footage and state, wipe the event log and thumbnails, and reassign the owner
    — because the index row is replaced wholesale."""
    _state(tmp_path)
    _owned_by(tmp_path, "alice-uid")
    _as(monkeypatch, "bob-uid", "bob@studio.com")
    monkeypatch.setenv("CLEARFRAME_MODE", "live")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "a-project")
    monkeypatch.setenv("PARALLEL_API_KEY", "a-key")
    bob = _client(tmp_path)

    resp = bob.post(
        "/api/productions",
        files={"file": ("clip.mp4", b"\x00" * 2048, "video/mp4")},
        data={"title": "Mine now", "production_id": "p1"},
    )

    assert resp.status_code == 404
    from clearframe.storage import build_backends as _bb
    from clearframe.config import ClearFrameConfig as _cfg
    row = _bb(_cfg.from_env({}), tmp_path).index.get("p1")
    assert row.owner_uid == "alice-uid", "ownership was reassigned by an upload"


# --- the dossier that belonged to everybody ------------------------------------


async def test_one_productions_dossier_is_not_anothers(tmp_path):
    """`DossierStage` wrote five fixed filenames flat at `out_root` with no pid,
    so every production overwrote the same report — and the artifact route,
    which checks ownership on the pid and then ignored the pid when resolving
    the file, handed you whichever had been generated last, by anyone.

    A collision and a cross-account leak from one missing path segment.
    """
    from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
    from clearframe.review import generate_dossier_async
    from clearframe.store import LocalJsonStore

    store = LocalJsonStore(tmp_path / "state")
    for pid in ("alpha", "beta"):
        ctx = demo_context(tmp_path)
        ctx.store = store
        ctx.state.production = ctx.state.production.model_copy(
            update={"id": pid, "title": f"Film {pid}"}
        )
        await Pipeline(build_demo_pipeline()).run(ctx)
        from clearframe.dossier import auto_decisions
        state = store.load(pid)
        state.decisions = auto_decisions(state)
        store.save(state)
        await generate_dossier_async(store, tmp_path, pid, at="2026-09-06T00:00:00Z")

    alpha = (tmp_path / "artifacts" / "alpha" / "dossier.html").read_text()
    beta = (tmp_path / "artifacts" / "beta" / "dossier.html").read_text()

    assert "Film alpha" in alpha and "Film beta" not in alpha
    assert "Film beta" in beta and "Film alpha" not in beta
