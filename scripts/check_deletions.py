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
CC = {"IN": "in", "NG": "ng", "LK": "lk"}
TODAY = datetime.date.today().isoformat()

def check(args):
    jur, app_id = args
    url = f"{B}/api/apps/{urllib.parse.quote(app_id)}?country={CC[jur]}"
    try:
        r = requests.get(url, timeout=25)
        if r.status_code == 200:
            return jur, app_id, "live"
        j = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        msg = str(j.get("message", ""))
        if r.status_code == 404 or "not found" in msg.lower():
            return jur, app_id, "deleted"
        return jur, app_id, f"error:{r.status_code}"
    except Exception as e:
        return jur, app_id, f"error:{type(e).__name__}"

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
            key = ("IN", aid)
            if key not in known:
                con.execute("INSERT INTO deleted_log VALUES ('IN', ?, ?, ?, 'seeded from 2021-22 corpus loanapp_deletedapps')",
                            (aid, str(d)[:10] if d else None, TODAY))
                n_seed += 1
        s.close()
    except Exception as e:
        print("seed:", e)
    q = "SELECT jurisdiction, app_id FROM apps"
    args = []
    if only:
        for jur in only.split(","):
            args += [(r[0], r[1]) for r in con.execute(q + " WHERE jurisdiction=?", [jur]).fetchall()]
    else:
        args = con.execute(q).fetchall()
    if limit:
        args = args[:limit]
    prev = dict(((j, a), st) for j, a, st in con.execute("SELECT jurisdiction, app_id, status FROM availability").fetchall())
    counts = {"live": 0, "deleted": 0, "error": 0}
    done = 0
    with cf.ThreadPoolExecutor(4) as ex:
        for jur, aid, st in ex.map(check, args):
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
    for j in CC:
        n = con.execute("SELECT COUNT(*) FROM deleted_log WHERE jurisdiction=?", [j]).fetchone()[0]
        print(f"deleted_log {j}: {n}")
    con.close()

if __name__ == "__main__":
    main(limit=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         only=sys.argv[2] if len(sys.argv) > 2 else None)
