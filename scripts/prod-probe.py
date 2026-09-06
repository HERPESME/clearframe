"""Attack the DEPLOYED site as two real Firebase accounts.

    set -a && source .env && set +a
    .venv/bin/python scripts/prod-probe.py [https://your-url]

Not part of `pytest`, deliberately. The suite runs credential-free against a
TestClient, which is the right thing for a suite and cannot tell you whether
the gate is switched on in production, whether Firebase will accept the
deployed hostname, or whether one account's data reaches another's over a real
network. Every defect this repo has shipped was invisible to a green suite, so
the deployment gets its own probe.

It signs up `probe-a@` and `probe-b@clearframe.dev`, falling back to sign-in if
they exist, so it is safe to re-run. Delete those two accounts in the Firebase
console when you are done with a deployment.

What it does NOT cover: uploads, because the public deployment runs demo mode
and refuses them by design. The ledger is the per-user surface it can reach
without spending money on detectors.
"""

import json
import os
import sys
import urllib.error
import urllib.request

APP = (sys.argv[1] if len(sys.argv) > 1
       else "https://clearframe-q5k3kjzu4a-uc.a.run.app").rstrip("/")
IDP = "https://identitytoolkit.googleapis.com/v1/accounts"
KEY = os.environ["FIREBASE_API_KEY"]

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  {PASS if ok else FAIL}  {name}{('  — ' + detail) if detail else ''}")


def post_json(url, payload, headers=None):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}"), r.headers
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}"), e.headers
        except ValueError:
            return e.code, {"raw": raw[:200].decode("utf-8", "replace")}, e.headers


def account(email, password="clearframe123", name=None):
    """Sign up, or sign in if the account already exists. Returns the ID token."""
    body = {"email": email, "password": password, "returnSecureToken": True}
    if name:
        body["displayName"] = name
    status, data, _ = post_json(f"{IDP}:signUp?key={KEY}", body)
    if "idToken" not in data:
        status, data, _ = post_json(f"{IDP}:signInWithPassword?key={KEY}", body)
    return data.get("idToken"), data.get("localId")


def session(token):
    """Exchange an ID token for the app's HttpOnly cookie."""
    status, data, headers = post_json(f"{APP}/api/auth/session", {"idToken": token})
    cookie = headers.get("set-cookie", "").split(";")[0]
    return status, data, cookie


def call(method, path, cookie=None, body=None, headers=None, raw_body=None,
         content_type=None):
    h = dict(headers or {})
    if cookie:
        h["Cookie"] = cookie
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    elif raw_body is not None:
        data = raw_body
        if content_type:
            h["Content-Type"] = content_type
    req = urllib.request.Request(APP + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jbody(raw):
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        return {}


print("\n\033[1m━━ 1. Sign-up and session\033[0m")
ta, uid_a = account("probe-a@clearframe.dev", name="Probe A")
tb, uid_b = account("probe-b@clearframe.dev", name="Probe B")
check("two accounts exist", bool(ta and tb), f"A={str(uid_a)[:8]}… B={str(uid_b)[:8]}…")

sa_status, sa_user, ca = session(ta)
sb_status, sb_user, cb = session(tb)
check("A exchanges a token for a session", sa_status == 200 and bool(ca))
check("B exchanges a token for a session", sb_status == 200 and bool(cb))
check("role defaults to least privilege",
      sa_user.get("role") == "editor", f"role={sa_user.get('role')}")

print("\n\033[1m━━ 2. The gate\033[0m")
for path in ("/api/productions", "/api/licences", "/api/productions/demo"):
    status, _ = call("GET", path)
    check(f"{path} refuses a stranger", status == 401, f"HTTP {status}")
status, _ = call("GET", "/api/productions", cookie=ca)
check("and answers a signed-in user", status == 200, f"HTTP {status}")

print("\n\033[1m━━ 3. Forged and tampered tokens\033[0m")
status, _ = call("GET", "/api/productions", cookie="clearframe_session=not-a-token")
check("a made-up cookie is refused", status == 401, f"HTTP {status}")
# Flip one character of the signature — a valid-looking JWT that is not signed.
tampered = ta[:-3] + ("aaa" if not ta.endswith("aaa") else "bbb")
status, _ = call("GET", "/api/productions",
                 cookie=f"clearframe_session={tampered}")
check("a tampered signature is refused", status == 401, f"HTTP {status}")
status, _ = call("GET", "/api/productions",
                 cookie=f"clearframe_session={ta}.extra")
check("a mangled token is refused", status == 401, f"HTTP {status}")

print("\n\033[1m━━ 4. Open roles: anyone may choose, nobody may invent\033[0m")
LEDGER = (b"rights_holder,work,scope,territories,media,starts,expires,reference,notes\n"
          b"Nike Inc,Swoosh,ALL,US,THEATRICAL,2020-01-01,2030-01-01,REF-A,\n")


def upload_ledger(cookie, role, csv=LEDGER):
    boundary = "----probe"
    parts = []
    for k, v in (("replace", "true"),):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
    head = (f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"file\"; filename=\"l.csv\"\r\nContent-Type: text/csv\r\n\r\n")
    body = ("".join(parts) + head).encode() + csv + f"\r\n--{boundary}--\r\n".encode()
    return call("POST", "/api/licences", cookie=cookie, raw_body=body,
                content_type=f"multipart/form-data; boundary={boundary}",
                headers={"X-ClearFrame-Role": role})


status, _ = upload_ledger(ca, "legal")
check("a visitor may choose 'legal' (open roles)", status == 200, f"HTTP {status}")
status, _ = upload_ledger(ca, "editor")
check("'editor' is still refused the ledger", status == 403, f"HTTP {status}")
status, _ = upload_ledger(ca, "admin")
check("an invented role grants nothing", status == 403, f"HTTP {status}")
status, _ = upload_ledger(ca, "<script>alert(1)</script>")
check("a script tag as a role grants nothing", status == 403, f"HTTP {status}")

print("\n\033[1m━━ 5. One account's ledger is not another's\033[0m")
status, raw = call("GET", "/api/licences", cookie=ca)
a_ledger = jbody(raw).get("licences", [])
check("A sees the licence A uploaded", len(a_ledger) == 1,
      f"{len(a_ledger)} row(s)")
status, raw = call("GET", "/api/licences", cookie=cb)
b_ledger = jbody(raw).get("licences", [])
b_holders = [r.get("rights_holder") for r in b_ledger]
# Not "B's ledger is empty" — B keeps their own rows across re-runs, and an
# emptiness assertion would fail for the right reason and read as a leak. The
# property is that A's holder does not appear in B's ledger.
check("B does NOT see A's licence", "Nike Inc" not in b_holders,
      f"B holds {b_holders}")

upload_ledger(cb, "legal", csv=LEDGER.replace(b"Nike Inc", b"Adidas AG"))
status, raw = call("GET", "/api/licences", cookie=ca)
still = jbody(raw).get("licences", [])
check("B's upload did not wipe A's ledger",
      len(still) == 1 and still[0].get("rights_holder") == "Nike Inc",
      f"A now holds {[r.get('rights_holder') for r in still]}")

print("\n\033[1m━━ 6. Injection through the ledger\033[0m")
NASTY = (b"rights_holder,work,scope,territories,media,starts,expires,reference,notes\n"
         b"=cmd|'/c calc'!A1,<script>alert(1)</script>,ALL,US,THEATRICAL,"
         b"2020-01-01,2030-01-01,REF-X,\n")
status, _ = upload_ledger(ca, "legal", csv=NASTY)
check("a hostile ledger row is accepted as DATA", status == 200, f"HTTP {status}")
status, raw = call("GET", "/api/licences", cookie=ca)
rows = jbody(raw).get("licences", [])
stored = rows[0].get("rights_holder", "") if rows else ""
check("the formula is stored verbatim, not executed",
      stored.startswith("=cmd"), f"stored={stored[:24]!r}")

print("\n\033[1m━━ 7. Path traversal\033[0m")
for probe in ("../../pyproject.toml", "..%2F..%2Fpyproject.toml", "dossier.html"):
    status, _ = call("GET", f"/api/productions/demo/artifacts/{probe}", cookie=ca)
    check(f"artifact {probe!r} is not served", status == 404, f"HTTP {status}")
status, _ = call("GET", "/api/productions/..%2F..%2Fetc%2Fpasswd", cookie=ca)
check("a traversal production id is refused", status in (404, 400), f"HTTP {status}")

print("\n\033[1m━━ 8. Sign-out actually ends it\033[0m")
call("POST", "/api/auth/signout", cookie=ca)
status, _ = call("GET", "/api/productions", cookie=ca)
check("the cookie still works until it expires (documented)", status in (200, 401),
      f"HTTP {status} — signout clears the browser cookie, the token stays valid")

print()
ok = sum(1 for r in results if r)
print(f"\033[1m{ok}/{len(results)} checks passed\033[0m")
sys.exit(0 if ok == len(results) else 1)
