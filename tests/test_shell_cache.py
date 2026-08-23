"""The browser kept an old app shell, so two fixes never reached the screen.

Twice in one session a defect was found, fixed, rebuilt and committed — and
the reviewer still saw the old behaviour, because the SPA was mounted as plain
`StaticFiles` with no cache policy on index.html. The browser served the shell
from its heuristic cache, which pointed at a bundle filename from two commits
earlier, and every subsequent diagnosis was of code that was no longer
running. The log settles it: three requests for `index-DZDz24te.js` and none
for the bundle that was actually on disk.

This is the same class of bug as `media_version` — a URL whose content changed
while the browser held the old bytes — and it deserves the same treatment. The
shell must revalidate; the hashed assets it points at never need to, because
their names change when their contents do.
"""

import pytest
from fastapi.testclient import TestClient

from clearframe.webapp.server import DIST_DIR, create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(out_root=tmp_path)) as c:
        yield c


def test_the_app_shell_must_revalidate(client):
    if DIST_DIR is None:
        pytest.skip("no built SPA; run `cd webapp && npm run build`")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "no-cache" in resp.headers.get("cache-control", "")


def test_a_hashed_asset_may_be_cached_forever(client):
    """Its name changes when its bytes do, so revalidating it is pure latency."""
    if DIST_DIR is None:
        pytest.skip("no built SPA")
    asset = next(iter(sorted((DIST_DIR / "assets").glob("*.js"))), None)
    if asset is None:
        pytest.skip("no hashed assets in dist")
    resp = client.get(f"/assets/{asset.name}")
    assert resp.status_code == 200
    assert "immutable" in resp.headers.get("cache-control", "")
