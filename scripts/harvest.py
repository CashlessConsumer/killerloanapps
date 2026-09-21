#!/usr/bin/env python3
"""Multi-jurisdiction loan-app harvest — killerloanapps playbook.

Usage:
  python3 scripts/harvest.py --country in --label 2026-09-21 [--terms extra1,extra2]
Writes data/harvests/<CC>_<label>.db with the killerloanapps schema
(loanapp_playdata + loanapp_permissions, incl. legal-entity + datasafety columns).
"""
import argparse, json, os, sqlite3, time, urllib.parse, requests

B = "https://gplayapiv2.fly.dev"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TERMS = {
    "in": ["loan", "personal loan", "instant loan", "cash loan", "online loan", "fast loan",
           "salary loan", "borrow money", "paisa loan", "udhaar", "rupee loan", "lending app",
           "पैसा लोन", "तत्काल लोन"],
    "lk": ["loan", "personal loan", "instant loan", "cash loan", "online loan", "fast loan",
           "salary loan", "borrow money", "lending app", "urgent cash",
           "ණය", "මුදල් ණය", "கடன்",
           "கடன் அப்ளிகேஷன்"],
    "ng": ["loan", "personal loan", "instant loan", "cash loan", "online loan", "fast loan",
           "salary loan", "borrow money", "naira loan", "urgent cash", "lending app"],
}
KW = {
    "in": ("loan", "lend", "borrow", "cash", "paisa", "rupee", "udhaar", "kredit", "credit"),
    "lk": ("loan", "lend", "borrow", "cash", "ණය", "கடன்"),
    "ng": ("loan", "lend", "borrow", "cash", "credit", "naira"),
}

ap = argparse.ArgumentParser()
ap.add_argument("--country", required=True)
ap.add_argument("--label", required=True)
ap.add_argument("--terms", default="")
a = ap.parse_args()
CC = a.country.lower()
SEARCH_TERMS = TERMS[CC] + ([t.strip() for t in a.terms.split(",") if t.strip()] if a.terms else [])
KW = KW[CC]
os.makedirs(os.path.join(ROOT, "data", "harvests"), exist_ok=True)
DB_PATH = os.path.join(ROOT, "data", "harvests", f"{CC.upper()}_{a.label}.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
schema = open(os.path.join(ROOT, "scripts", "schema_playdata.sql")).read() + \
         open(os.path.join(ROOT, "scripts", "schema_perms.sql")).read()
for stmt in schema.split(";"):
    if "CREATE TABLE" in stmt:
        conn.execute(stmt)
extra = [
    "ALTER TABLE loanapp_playdata ADD COLUMN developerLegalEmail TEXT",
    "ALTER TABLE loanapp_playdata ADD COLUMN developerLegalName TEXT",
    "ALTER TABLE loanapp_playdata ADD COLUMN developerLegalAddress TEXT",
    "ALTER TABLE loanapp_playdata ADD COLUMN developerLegalPhoneNumber TEXT",
    "ALTER TABLE loanapp_playdata ADD COLUMN privacyPolicy TEXT",
    "ALTER TABLE loanapp_playdata ADD COLUMN contentRating TEXT",
    "ALTER TABLE loanapp_playdata ADD COLUMN released TEXT",
    "ALTER TABLE loanapp_playdata ADD COLUMN genre TEXT",
    "ALTER TABLE loanapp_playdata ADD COLUMN datasafety TEXT",
]
for s in extra:
    try:
        conn.execute(s)
    except sqlite3.OperationalError:
        pass
conn.commit()

def api(path, params, tries=3):
    for i in range(tries):
        try:
            r = requests.get(f"{B}{path}", params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print("  err", path, params, e)
        time.sleep(1.5 * (i + 1))
    return None

candidates = {}
for term in SEARCH_TERMS:
    d = api("/api/apps/", {"country": CC, "lang": "en", "q": term, "num": 100})
    ids = [r["appId"] for r in (d or {}).get("results", []) if r.get("appId")]
    print(f"search '{term}': {len(ids)}")
    for a in ids:
        candidates.setdefault(a, set()).add(term)
    time.sleep(0.8)

print("unique candidates:", len(candidates))

def qualifies(r):
    text = " ".join(str(r.get(f, "")) for f in ("title", "summary", "description")).lower()
    return any(k in text for k in KW)

rows, perm_rows, skipped = 0, 0, 0
PLAY_COLS = None
for n, (app_id, terms) in enumerate(candidates.items()):
    d = api(f"/api/apps/{urllib.parse.quote(app_id)}", {"country": CC, "lang": "en"})
    r = (d or {}).get("results", d or {})
    if not isinstance(r, dict) or "error" in r or not r.get("title"):
        skipped += 1
        continue
    if not qualifies(r):
        skipped += 1
        continue
    if PLAY_COLS is None:
        PLAY_COLS = [x[1] for x in conn.execute("PRAGMA table_info(loanapp_playdata)")]
    _h = r.get("histogram")
    if isinstance(_h, dict):
        hist = [_h.get(str(k)) for k in (5, 4, 3, 2, 1)]
    elif isinstance(_h, (list, tuple)) and len(_h) == 5:
        hist = list(_h)
    else:
        hist = [None] * 5
    shots = r.get("screenshots") or []
    cats = r.get("categories") or []
    dev = r.get("developer") or {}
    vals = {
        "id": app_id, "title": r.get("title"), "description": r.get("description"),
        "descriptionHTML": r.get("descriptionHTML"), "summary": r.get("summary"),
        "installs": r.get("installs"), "minInstalls": r.get("minInstalls"),
        "maxInstalls": r.get("maxInstalls"), "score": r.get("score"),
        "scoreText": r.get("scoreText"), "ratings": r.get("ratings"),
        "reviews": r.get("reviews"),
        "histogram|0": hist[0], "histogram|1": hist[1], "histogram|2": hist[2],
        "histogram|3": hist[3], "histogram|4": hist[4],
        "price": r.get("price"), "free": 1 if r.get("free") else 0,
        "currency": r.get("currency"),
        "appId": app_id, "url": r.get("url"), "icon": r.get("icon"),
        "developerId": dev.get("devId") or r.get("developerId"),
        "developerEmail": r.get("developerEmail"),
        "developerWebsite": r.get("developerWebsite"),
        "developerLegalPhoneNumber": r.get("developerLegalPhoneNumber"),
        "privacyPolicy": r.get("privacyPolicy"),
        "contentRating": r.get("contentRating"),
        "released": r.get("released"),
        "genre": r.get("genre"),
        "datasafety": json.dumps(r.get("datasafety")) if r.get("datasafety") else None,
        "screenshots|0": shots[0] if len(shots) > 0 else None,
        "screenshots|1": shots[1] if len(shots) > 1 else None,
        "screenshots|2": shots[2] if len(shots) > 2 else None,
        "screenshots|3": shots[3] if len(shots) > 3 else None,
        "screenshots|4": shots[4] if len(shots) > 4 else None,
        "video": r.get("video"), "androidVersionText": r.get("androidVersionText"),
        "androidVersion": r.get("androidVersion"), "updated": r.get("updated"),
        "version": r.get("version"), "developerInternalID": r.get("developerInternalID"),
        "adSupported": 1 if r.get("adSupported") else 0,
        "genres": ", ".join(cats) if cats else r.get("genre"),
        "developerLegalEmail": r.get("developerLegalEmail"),
        "developerLegalName": r.get("developerLegalName"),
        "developerLegalAddress": r.get("developerLegalAddress"),
        "developerLegalPhoneNumber": r.get("developerLegalPhoneNumber"),
        "privacyPolicy": r.get("privacyPolicy"), "contentRating": r.get("contentRating"),
        "released": r.get("released"), "genre": r.get("genre"),
        "datasafety": json.dumps(r.get("datasafety")) if r.get("datasafety") else None,
    }
    cols = [c for c in PLAY_COLS if c in vals]
    conn.execute(
        f"INSERT OR REPLACE INTO loanapp_playdata ({','.join(chr(34)+c+chr(34) for c in cols)}) VALUES ({','.join('?'*len(cols))})",
        [vals[c] for c in cols])
    rows += 1
    pd = api(f"/api/apps/{urllib.parse.quote(app_id)}/permissions", {})
    perms = (pd or {}).get("results", [])
    for p in perms:
        conn.execute("INSERT INTO loanapp_permissions (appId, permission) VALUES (?,?)",
                     (app_id, f"{p.get('type','')}: {p.get('permission','')}"))
    perm_rows += len(perms)
    if n % 10 == 0:
        print(f"{n+1}/{len(candidates)} kept={rows} skipped={skipped}")
    conn.commit()
    time.sleep(0.5)

conn.commit()
print(f"DONE kept={rows} skipped={skipped} perms={perm_rows} -> {DB_PATH}")
