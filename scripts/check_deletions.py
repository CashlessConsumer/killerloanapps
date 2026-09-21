#!/usr/bin/env python3
"""Play-availability checker: multi-jurisdiction deleted-app tracking.

For every app in the warehouse, ask GPlayAPI v2 whether it is still listed
in its jurisdiction's storefront. Writes:
  availability(jurisdiction, app_id, last_checked, status)   -- latest state
  deleted_log(jurisdiction, app_id, first_missing, last_live, note) -- transitions
Seeds deleted_log from the IN corpus's historical loanapp_deletedapps table.
"""
import datetime, os, sqlite3, sys, time, urllib.parse
import concurrent.futures as cf
import requests, duckdb

B = "https://gplayapiv2.fly.dev"
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "killerloanapps.duckdb")
TODAY = datetime.date.today().isoformat()

def check(args):
    jur, country, app_id = args
    url = f"{B}/api/apps/{urllib.parse.quote(app_id)}?country={country}"
    try:
        r = requests.get(url, timeout=25)
        if r.status_code == 200:
            return jur, country, app_id, "live"
        j = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        msg = str(j.get("message", ""))
        if r.status_code == 404 or "not found" in msg.lower():
            return jur, country, app_id, "deleted"
        return jur, country, app_id, f"error:{r.status_code}"
    except Exception as e:
        return jur, country, app_id, f"error:{type(e).__name__}"

def main(limit=None, only=None):
    con = duckdb.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS availability (
        jurisdiction VARCHAR, app_id VARCHAR, last_checked DATE, status VARCHAR,
        PRIMARY KEY (jurisdiction, app_id))""")
    con.execute("""CREATE TABLE IF NOT EXISTS deleted_log (
        jurisdiction VARCHAR, app_id VARCHAR, first_missing DATE, last_live DATE, note VARCHAR)""")
    # seed historical IN deletions (idempotent)
    n_seed = 0
    try:
        s = sqlite3.connect("file:/home/workspace/Datasets/loanapps-in/loanapps_dbhub_20220227.db?mode=ro", uri=True)
        known = {(j, a) for j, a in con.execute("SELECT jurisdiction, app_id FROM deleted_log")}
        for aid, d in s.execute("SELECT appId, date FROM loanapp_deletedapps"):
            key = ("IN_2020_2022", aid)
            if key not in known:
                con.execute("INSERT INTO deleted_log VALUES ('IN_2020_2022', ?, ?, ?, 'seeded from 2021-22 corpus loanapp_deletedapps')",
                            (aid, str(d)[:10] if d else None, TODAY))
                n_seed += 1
        s.close()
    except Exception as e:
        print("seed:", e)
    # country + kind per corpus
    corpora = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT corpus_id, country, kind FROM corpora").fetchall()}
    if only and only != "live":
        ids = [c.strip() for c in only.split(",") if c.strip()]
    elif only == "live":
        ids = [c for c, (_, kind) in corpora.items() if kind == "live"]
    else:  # default: every corpus, so historical attrition keeps updating
        ids = list(corpora)
    q = "SELECT jurisdiction, app_id FROM apps WHERE jurisdiction = ?"
    args = []
    for cid in ids:
        if cid not in corpora:
            print("skip unknown corpus:", cid)
            continue
        country = corpora[cid][0]
        args += [(cid, country, r[1]) for r in con.execute(q, [cid]).fetchall()]
    if limit:
        args = args[:limit]
    prev = dict(((j, a), st) for j, a, st in con.execute("SELECT jurisdiction, app_id, status FROM availability").fetchall())
    counts = {"live": 0, "deleted": 0, "error": 0}
    done = 0
    with cf.ThreadPoolExecutor(4) as ex:
        for jur, _cc, aid, st in ex.map(check, args):
            done += 1
            if st.startswith("error"):
                counts["error"] += 1
                if (jur, aid) not in prev:      # keep last known good state on transient errors
                    continue
                st = prev[(jur, aid)]
            counts["live" if st == "live" else "deleted"] += 1
            con.execute("INSERT OR REPLACE INTO availability VALUES (?, ?, ?, ?)", (jur, aid, TODAY, st))
            was = prev.get((jur, aid))
            if st == "deleted" and was != "deleted":
                row = con.execute("SELECT last_live FROM deleted_log WHERE jurisdiction=? AND app_id=?", (jur, aid)).fetchone()
                if not row:
                    con.execute("INSERT INTO deleted_log VALUES (?, ?, ?, ?, ?)", (jur, aid, TODAY, None if was is None else TODAY, "play availability check"))
            if st == "live" and was == "deleted":
                con.execute("DELETE FROM deleted_log WHERE jurisdiction=? AND app_id=?", (jur, aid))
            if done % 100 == 0:
                con.commit()
                print(f"{done}/{len(args)} {counts}", flush=True)
    con.commit()
    print(f"DONE checked={len(args)} seeded={n_seed} {counts}")
    for j in corpora:
        n = con.execute("SELECT COUNT(*) FROM deleted_log WHERE jurisdiction=?", [j]).fetchone()[0]
        av = con.execute("SELECT status, COUNT(*) FROM availability WHERE jurisdiction=? GROUP BY 1", [j]).fetchall()
        print(f"deleted_log {j}: {n} | availability {dict(av)}")
    con.close()

if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    only = argv[1] if len(argv) > 1 else None
    if only is None and "--all" in sys.argv:
        only = ",".join(["IN", "LK", "IN_2020_2022", "NG_2022"])
    main(limit=int(argv[0]) if argv else None, only=only)
