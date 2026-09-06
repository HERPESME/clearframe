"""Who has used this deployment, recorded by the deployment.

Firebase Authentication owns the credentials — the email, the provider, the
scrypt hash — and a second copy of any of that would be the one duplication
nobody should keep. What Firebase cannot tell you is what an account did HERE:
which role they have been working as, when they first appeared, how often they
have come back. A deployment that records a clearance decision against
`someone@x.com` should be able to say who that is without opening another
console.

One document per user, keyed by uid. Emphatically not a reason to add a
relational database: a handful of fields read by primary key.
"""

import json

import pytest
from fastapi.testclient import TestClient

from clearframe.storage.users import LocalUserDirectory
from clearframe.webapp import auth
from clearframe.webapp.server import create_app


@pytest.fixture
def users(tmp_path):
    return LocalUserDirectory(tmp_path / "users")


def test_a_first_sighting_creates_the_person(users):
    rec = users.seen("uid-1", email="a@b.com", name="A Reviewer")

    assert rec.email == "a@b.com"
    assert rec.sign_ins == 1
    assert rec.first_seen > 0 and rec.last_seen == rec.first_seen


def test_a_later_sighting_updates_without_losing_the_beginning(users):
    first = users.seen("uid-1", email="a@b.com")

    again = users.seen("uid-1", email="a@b.com")

    assert again.first_seen == first.first_seen
    assert again.last_seen >= first.last_seen
    assert again.sign_ins == 2


def test_the_role_they_last_worked_as_is_kept(users):
    """Worth recording precisely BECAUSE on an open-roles deployment it was
    their choice rather than a grant."""
    users.seen("uid-1", role="editor")

    assert users.seen("uid-1", role="legal").role == "legal"


def test_verification_status_travels_with_the_record(users):
    rec = users.seen("uid-1", email="a@b.com", email_verified=False)

    assert rec.email_verified is False


def test_an_unknown_user_is_none(users):
    assert users.get("nobody") is None


def test_the_directory_lists_most_recently_seen_first(users):
    users.seen("uid-old")
    users.seen("uid-new")

    assert [r.uid for r in users.list()][0] == "uid-new"


def test_no_password_or_token_is_ever_stored(users):
    """The point of the module. If this ever fails, something has started
    keeping a second copy of the thing Firebase exists to hold."""
    rec = users.seen("uid-1", email="a@b.com", name="A")

    stored = json.loads(rec.model_dump_json()).keys()
    assert not {"password", "password_hash", "token", "id_token"} & set(stored)


# --- wired to the sign-in ------------------------------------------------------


def _signed_in(monkeypatch, uid="uid-1", email="a@b.com", verified=True):
    monkeypatch.setattr(
        auth, "verify_token",
        lambda _raw: {"uid": uid, "email": email, "name": "A Reviewer",
                      "email_verified": verified},
    )


def test_signing_in_records_the_person(tmp_path, monkeypatch):
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    _signed_in(monkeypatch)
    client = TestClient(create_app(out_root=tmp_path))

    client.post("/api/auth/session", json={"idToken": "x"})

    rec = LocalUserDirectory(tmp_path / "users").get("uid-1")
    assert rec is not None and rec.email == "a@b.com"


def test_signing_in_twice_counts_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    _signed_in(monkeypatch)
    client = TestClient(create_app(out_root=tmp_path))

    client.post("/api/auth/session", json={"idToken": "x"})
    client.post("/api/auth/session", json={"idToken": "x"})

    assert LocalUserDirectory(tmp_path / "users").get("uid-1").sign_ins == 2


def test_a_directory_failure_does_not_cost_a_sign_in(tmp_path, monkeypatch):
    """Being unable to write a convenience record must never lock somebody out
    of the product."""
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    _signed_in(monkeypatch)
    client = TestClient(create_app(out_root=tmp_path))
    monkeypatch.setattr(
        "clearframe.storage.users.LocalUserDirectory.seen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )

    assert client.post("/api/auth/session", json={"idToken": "x"}).status_code == 200
