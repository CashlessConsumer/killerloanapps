#!/usr/bin/env python3
"""Merge IN/NG/LK loan-app corpora into one DuckDB warehouse.

Sources (provenance in CHECKSUMS + README):
  IN: Datasets/loanapps-in/loanapps_dbhub_20220227.db  (725 apps, corpus Dec 2020-Feb 2022, published on dbhub)
  NG: Datasets/loanappsdata_NG.db                      (126 apps, Mar 2022)
  LK: Datasets/loanapps-lk/loanappsdata_LK.db          (155 apps, harvested 2026-09-20)
Output: data/killerloanapps.duckdb (apps, permissions, deleted) + data/apps.json (light API dump)
"""
import json, os, sqlite3, duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
os.makedirs(DATA, exist_ok=True)
OUT = os.path.join(DATA, "killerloanapps.duckdb")

SOURCES = [
    ("IN", "/home/workspace/Datasets/loanapps-in/loanapps_dbhub_20220227.db", "2022-02-27",
     "India corpus Dec 2020 - Feb 2022 (published dbhub copy, byte-exact)"),
    ("NG", "/home/workspace/Datasets/loanappsdata_NG.db", "2022-03-04",
     "Nigeria corpus Mar 2022 (DStudio x CC shared drive)"),
    ("LK", "/home/workspace/Datasets/loanapps-lk/loanappsdata_LK.db", "2026-09-20",
     "Sri Lanka harvest 2026-09-20 via GPlayAPI v2 (killerloanapps playbook run)"),
]

COLS = ["app_id","title","summary","installs","min_installs","max_installs","score","ratings",
        "free","currency","developer_id","developer_email","developer_website","developer_address",
        "legal_name","legal_email","legal_address","legal_phone","privacy_policy","released",
        "updated","version","content_rating","genre","url","datasafety"]

MAP = {  # normalized -> per-corpus sqlite column
    "app_id":"appId","title":"title","summary":"summary","installs":"installs",
    "min_installs":"minInstalls","max_installs":"maxInstalls","score":"score","ratings":"ratings",
    "free":"free","currency":"currency","developer_id":"developerId",
    "developer_email":"developerEmail","developer_website":"developerWebsite",
    "developer_address":"developerAddress","legal_name":"developerLegalName",
    "legal_email":"developerLegalEmail","legal_address":"developerLegalAddress",
    "legal_phone":"developerLegalPhoneNumber","privacy_policy":"privacyPolicy",
    "released":"released","updated":"updated","version":"version",
    "content_rating":"contentRating","genre":"genre","url":"playstoreUrl",
    "datasafety":"datasafety",
}

def rows_from(sqlite_path, table, cols, extra_where=""):
    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    use = [c for c in cols if c in have]
    sel = ",".join(use)
    out = []
    for row in con.execute(f"SELECT {sel} FROM {table} {extra_where}"):
        out.append(dict(zip(use, row)))
    con.close()
    return out

if os.path.exists(OUT):
    os.remove(OUT)
con = duckdb.connect(OUT)
con.execute("""CREATE TABLE apps (
    jurisdiction VARCHAR, app_id VARCHAR, title VARCHAR, summary VARCHAR,
    installs VARCHAR, min_installs BIGINT, max_installs BIGINT, score DOUBLE, ratings BIGINT,
    free BOOLEAN, currency VARCHAR, developer_id VARCHAR, developer_email VARCHAR,
    developer_website VARCHAR, developer_address VARCHAR, legal_name VARCHAR,
    legal_email VARCHAR, legal_address VARCHAR, legal_phone VARCHAR,
    privacy_policy VARCHAR, released VARCHAR, updated BIGINT, version VARCHAR,
    content_rating VARCHAR, genre VARCHAR, url VARCHAR, datasafety VARCHAR,
    harvested_on DATE, corpus VARCHAR)""")
con.execute("CREATE TABLE permissions (jurisdiction VARCHAR, app_id VARCHAR, permission VARCHAR)")
con.execute("CREATE TABLE deleted (jurisdiction VARCHAR, app_id VARCHAR, deleted_on VARCHAR)")

stats = {}
for jur, path, harvest, corpus in SOURCES:
    apps = rows_from(path, "loanapp_playdata", [MAP[c] for c in COLS])
    n = 0
    for a in apps:
        ds = a.pop("datasafety", None)
        dsj = json.dumps(ds) if isinstance(ds, (dict, list)) else (ds if isinstance(ds, str) else None)
        vals = []
        for c in COLS:
            v = a.get(MAP[c])
            if c == "updated" and isinstance(v, str):
                v = None
            if c == "updated" and isinstance(v, (int, float)) and v and v < 10**12:
                v = int(v * 1000)  # seconds -> ms
            vals.append(v)
        ins_cols = ["jurisdiction"] + COLS + ["harvested_on", "corpus"]
        con.execute(f"INSERT INTO apps ({','.join(ins_cols)}) VALUES ({','.join('?'*len(ins_cols))})",
                    [jur] + vals + [harvest, corpus])
        n += 1
    perms = rows_from(path, "loanapp_permissions", ["appId", "permission", "type"])
    np = 0
    for p in perms:
        perm = (p.get("permission") or "").strip()
        if p.get("type") and p.get("type") not in perm:
            perm = f"{p['type']}: {perm}" if perm else p["type"]
        if not perm:
            continue
        con.execute("INSERT INTO permissions VALUES (?,?,?)", (jur, p.get("appId"), perm))
        np += 1
    nd = 0
    try:
        dels = rows_from(path, "loanapp_deletedapps", ["appId", "date"])
        for d in dels:
            con.execute("INSERT INTO deleted VALUES (?,?,?)", (jur, d.get("appId"), str(d.get("date"))))
            nd += 1
    except Exception:
        pass
    stats[jur] = {"apps": n, "permissions": np, "deleted": nd, "corpus": corpus}
    print(jur, stats[jur])

# light API dump (no descriptions)
apps_json = con.execute("""SELECT jurisdiction, app_id, title, summary, installs, max_installs,
    score, ratings, currency, developer_email, developer_website, legal_name, privacy_policy,
    released, updated, harvested_on FROM apps ORDER BY jurisdiction, app_id""").fetchall()
cols = ["jurisdiction","app_id","title","summary","installs","max_installs","score","ratings",
        "currency","developer_email","developer_website","legal_name","privacy_policy",
        "released","updated","harvested_on"]
dump = [dict(zip(cols, r)) for r in apps_json]
for d in dump:
    d["harvested_on"] = str(d["harvested_on"])
    d["updated"] = int(d["updated"]) if d["updated"] else None
json.dump({"generated": harvest and "2026-09-21", "count": len(dump), "apps": dump},
          open(os.path.join(DATA, "apps.json"), "w"), ensure_ascii=False)
json.dump(stats, open(os.path.join(DATA, "warehouse_stats.json"), "w"), indent=1)
con.close()
print("warehouse:", OUT, "| apps.json:", len(dump))
