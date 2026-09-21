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

# Corpus registry: id -> (country, status, harvested_on, label, sqlite source)
# Live corpora are re-harvested by scripts/harvest.py into data/harvests/<CC>_<date>.db
# Historical corpora are frozen era snapshots kept for the deletion/attrition record.
CORPORA = [
    ("IN", "in", "live", "2026-09-21",
     "India harvest 2026-09-21 via GPlayAPI v2 (killerloanapps playbook run)",
     "data/harvests/IN_*.db"),
    ("LK", "lk", "live", "2026-09-20",
     "Sri Lanka harvest 2026-09-20 via GPlayAPI v2",
     "data/harvests/LK_*.db"),
    ("IN_2020_2022", "in", "historical", "2022-02-27",
     "India corpus Dec 2020 - Feb 2022 (dbhub copy, byte-exact)",
     "/home/workspace/Datasets/loanapps-in/loanapps_dbhub_20220227.db"),
    ("NG_2022", "ng", "historical", "2022-03-04",
     "Nigeria corpus Mar 2022 (DStudio x CC shared drive)",
     "/home/workspace/Datasets/loanappsdata_NG.db"),
]


COUNTRY_LABEL = {"in": "India", "lk": "Sri Lanka", "ng": "Nigeria"}


def resolve(pathspec):
    """Newest file matching a glob pathspec (relative to ROOT or absolute)."""
    hits = resolve_all(pathspec)
    return hits[-1] if hits else None


def resolve_all(pathspec):
    """Every file matching a glob pathspec, oldest first. Single paths return [path].

    Live corpora accumulate one snapshot per refresh. The warehouse unions ALL of them
    (newest row wins) so an app that disappears from the store is retained in the corpus
    with a last_seen date instead of silently dropping out of the record."""
    if not any(ch in pathspec for ch in "*?["):
        return [pathspec] if os.path.exists(pathspec) else []
    import glob
    pat = pathspec if os.path.isabs(pathspec) else os.path.join(ROOT, pathspec)
    return sorted(glob.glob(pat))


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

# The availability / deleted_log tables are accumulated history, not derived data: carry them
# across a rebuild so step order can never silently erase the deletion record.
carry = {}
if os.path.exists(OUT):
    try:
        prev = duckdb.connect(OUT, read_only=True)
        for t, cols in (("availability", "jurisdiction, app_id, last_checked, status"),
                        ("deleted_log", "jurisdiction, app_id, first_missing, last_live, note")):
            if prev.execute("SELECT 1 FROM information_schema.tables WHERE table_name=?",
                            [t]).fetchone():
                carry[t] = (cols, prev.execute(f"SELECT {cols} FROM {t}").fetchall())
        prev.close()
    except Exception as e:
        print("carry-over skipped:", e)
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
    harvested_on DATE, corpus VARCHAR,
    first_seen DATE, last_seen DATE, snapshots INTEGER, gone_from_store BOOLEAN)""")
con.execute("CREATE TABLE permissions (jurisdiction VARCHAR, app_id VARCHAR, permission VARCHAR)")
con.execute("""CREATE TABLE availability (jurisdiction VARCHAR, app_id VARCHAR, last_checked DATE,
    status VARCHAR, PRIMARY KEY (jurisdiction, app_id))""")
con.execute("""CREATE TABLE deleted_log (jurisdiction VARCHAR, app_id VARCHAR, first_missing DATE,
    last_live DATE, note VARCHAR)""")
for t, (cols, rows) in carry.items():
    if rows:
        con.executemany(f"INSERT INTO {t} ({cols}) VALUES ({','.join('?' * len(cols.split(',')))})", rows)
        print(f"carried {len(rows)} rows -> {t}")
con.execute("CREATE TABLE deleted (jurisdiction VARCHAR, app_id VARCHAR, deleted_on VARCHAR)")
con.execute("""CREATE TABLE corpora (corpus_id VARCHAR, label VARCHAR, short VARCHAR, kind VARCHAR,
    country VARCHAR, harvested_on DATE, seed_date DATE, description VARCHAR, source VARCHAR)""")

stats = {}

# Carried-forward record: apps.json is the accumulated corpus state from the previous run.
# A live app that is present there but absent from every current snapshot has left the store;
# it is re-inserted with gone_from_store so the record survives snapshot rotation.
PRIOR = {}
PRIOR_PATH = os.path.join(DATA, "apps.json")
if os.path.exists(PRIOR_PATH):
    try:
        for row in json.load(open(PRIOR_PATH))["apps"]:
            PRIOR[(row["jurisdiction"], row["app_id"])] = row
        print("prior apps.json:", len(PRIOR), "rows")
    except Exception as e:
        print("prior apps.json skipped:", e)


def date_of(path, fallback):
    """Harvest date for a snapshot file: the YYYY-MM-DD in its name, else the configured date."""
    stem = os.path.basename(path).rsplit(".", 1)[0]
    if "_" in stem:
        cand = stem.rsplit("_", 1)[1]
        if len(cand) == 10 and cand[4] == "-":
            return cand
    return fallback


for jur, country, status, harvest, corpus, pathspec in CORPORA:
    files = resolve_all(pathspec)
    if not files:
        print(jur, "SKIP (no source:", pathspec + ")")
        continue
    snapshots = [(f, date_of(f, harvest)) for f in files]
    newest_path, hv = snapshots[-1]

    # union across every snapshot, oldest -> newest so the newest row wins
    order, seen_first, seen_last, counts, perm_set, del_set = {}, {}, {}, {}, set(), set()
    for path, hdate in snapshots:
        for a in rows_from(path, "loanapp_playdata", [MAP[c] for c in COLS]):
            aid = a.get("appId")
            if not aid:
                continue
            if aid not in order:
                seen_first[aid] = hdate
            order[aid] = (a, hdate)
            seen_last[aid] = hdate
            counts[aid] = counts.get(aid, 0) + 1
        for pm in rows_from(path, "loanapp_permissions", ["appId", "permission", "type"]):
            perm = (pm.get("permission") or "").strip()
            if pm.get("type") and pm.get("type") not in perm:
                perm = f"{pm['type']}: {perm}" if perm else pm["type"]
            if perm and pm.get("appId"):
                perm_set.add((pm["appId"], perm))
        try:
            for d in rows_from(path, "loanapp_deletedapps", ["appId", "date"]):
                if d.get("appId"):
                    del_set.add((d["appId"], str(d.get("date"))))
        except Exception:
            pass

    carried = []
    if status == "live":
        for (pjur, paid), row in PRIOR.items():
            if pjur == jur and paid not in order:
                carried.append(row)

    label = COUNTRY_LABEL.get(country, country.upper())
    con.execute("INSERT INTO corpora VALUES (?,?,?,?,?,?,?,?,?)",
                (jur, label, jur, status, country, hv, hv, corpus, newest_path))

    ins_cols = ["jurisdiction"] + COLS + ["harvested_on", "corpus",
                                          "first_seen", "last_seen", "snapshots", "gone_from_store"]
    n = 0
    for aid, (a, hdate) in order.items():
        a = dict(a)
        ds = a.pop("datasafety", None)
        dsj = json.dumps(ds) if isinstance(ds, (dict, list)) else (ds if isinstance(ds, str) else None)
        vals = []
        for c in COLS:
            v = a.get(MAP[c])
            if c == "updated" and isinstance(v, str):
                v = None
            if c == "updated" and isinstance(v, (int, float)) and v and v < 10**12:
                v = int(v * 1000)  # seconds -> ms
            if c == "datasafety":
                v = dsj
            vals.append(v)
        # an app last seen before the newest snapshot has left the store
        gone = hdate != hv
        con.execute(f"INSERT INTO apps ({','.join(ins_cols)}) VALUES ({','.join('?'*len(ins_cols))})",
                    [jur] + vals + [hdate, corpus, seen_first[aid], seen_last[aid], counts[aid], gone])
        n += 1

    for row in carried:
        vals = []
        for c in COLS:
            v = row.get(c)
            if c == "free" and v is not None:
                v = bool(v)
            vals.append(v)
        con.execute(f"INSERT INTO apps ({','.join(ins_cols)}) VALUES ({','.join('?'*len(ins_cols))})",
                    [jur] + vals + [row.get("last_seen") or row.get("harvested_on"), corpus,
                                    row.get("first_seen") or row.get("harvested_on"),
                                    row.get("last_seen") or row.get("harvested_on"),
                                    int(row.get("snapshots") or 1), True])
        n += 1

    np = 0
    for aid, perm in sorted(perm_set):
        con.execute("INSERT INTO permissions VALUES (?,?,?)", (jur, aid, perm))
        np += 1
    nd = 0
    for aid, d in sorted(del_set):
        con.execute("INSERT INTO deleted VALUES (?,?,?)", (jur, aid, d))
        nd += 1
    n_gone = con.execute("SELECT COUNT(*) FROM apps WHERE jurisdiction=? AND gone_from_store",
                         [jur]).fetchone()[0]
    stats[jur] = {"apps": n, "permissions": np, "deleted": nd, "snapshots": len(snapshots),
                  "gone_from_store": n_gone, "corpus": corpus, "country": country,
                  "status": status, "harvested_on": hv, "source": newest_path}
    print(jur, stats[jur])

# light API dump (no descriptions)
cols = ["jurisdiction","app_id","title","summary","installs","min_installs","max_installs",
        "score","ratings","free","currency","developer_id","developer_email","developer_website",
        "developer_address","legal_name","legal_email","legal_address","legal_phone",
        "privacy_policy","released","updated","version","content_rating","genre","url","datasafety",
        "harvested_on","corpus","first_seen","last_seen","snapshots","gone_from_store"]
apps_json = con.execute("SELECT " + ",".join(cols) + " FROM apps ORDER BY jurisdiction, app_id").fetchall()
dump = [dict(zip(cols, r)) for r in apps_json]
for d in dump:
    for k in ("harvested_on", "first_seen", "last_seen"):
        d[k] = str(d[k]) if d[k] else None
    d["updated"] = int(d["updated"]) if d["updated"] else None
json.dump({"generated": harvest and "2026-09-21", "count": len(dump), "apps": dump},
          open(os.path.join(DATA, "apps.json"), "w"), ensure_ascii=False)
json.dump(stats, open(os.path.join(DATA, "warehouse_stats.json"), "w"), indent=1)
con.close()
print("warehouse:", OUT, "| apps.json:", len(dump))
