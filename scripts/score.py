#!/usr/bin/env python3
"""Apply rubric.yaml (DeepStrat indicator framework) to the warehouse -> scores table + scores.json.

v0.2: I5/I7 pending (need APK lane / reviews lane). I3 partial (LK only). NULL families are
excluded and the composite renormalised over scored families, flagged 'partial'.
"""
import json, os, re, datetime, duckdb, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "killerloanapps.duckdb")
RUBRIC = yaml.safe_load(open(os.path.join(ROOT, "rubric.yaml")))

MONEY_KW = ["loan", "cash", "credit", "money", "paisa", "dhan", "quick", "instant", "easy", "fast", "lend", "borrow"]
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "protonmail.com", "icloud.com", "mail.ru"}
RISK_PP_HOSTS = ("docs.google.com", "sites.google.com", "blogspot.", "wordpress.com", "wixsite.com", "apph5", "h5.", "weebly.com", "webnode.")
DANGEROUS = [
    ("read your contacts", "contacts"), ("modify your contacts", "contacts"),
    ("read your own contact card", "contacts"),
    ("send SMS", "sms"), ("read your text messages", "sms"), ("receive text messages", "sms"),
    ("read call log", "calllog"), ("read your call history", "calllog"),
    ("precise location", "location"), ("approximate location", "location"),
    ("record audio", "mic"), ("take pictures", "camera"),
    ("modify or delete the contents of your USB storage", "storage"),
    ("read the contents of your USB storage", "storage"),
    ("retrieve running apps", "procmon"), ("read phone status", "phonestate"),
    ("modify your calendars", "calendarw"),
]
HARVEST = {"IN": "2022-02-27", "NG": "2022-03-04", "LK": "2026-09-20"}
LOCAL_HINT = {"LK": ["sri lanka", "colombo"]}

def ts(v):
    if v is None: return None
    if isinstance(v, str):
        try: return int(datetime.datetime.fromisoformat(v.replace("Z","+00:00")).timestamp()*1000)
        except Exception: return None
    return int(v)

def i1(app):
    aid = (app["app_id"] or "").lower()
    kws = sum(1 for k in MONEY_KW if k in aid)
    depth = aid.count(".") + 1
    s = 0
    if kws >= 3: s += 35
    if kws >= 5: s += 25
    if depth >= 6: s += 25
    if depth >= 8: s += 15
    flags = []
    if kws >= 3: flags.append("aso_keyword_stuffing")
    if depth >= 6: flags.append("aso_deep_package")
    return s, flags

def i2(app):
    s = 0; flags = []
    pp = app["privacy_policy"]
    host = (pp or "").lower()
    if not pp or not pp.strip():
        s += 40; flags.append("no_privacy_policy")
    elif any(h in host for h in RISK_PP_HOSTS):
        s += 30; flags.append("pp_on_free_host")
    if not (app["developer_website"] or "").strip():
        s += 20; flags.append("no_website")
    mail = (app["developer_email"] or "").strip().lower()
    if not mail:
        s += 15; flags.append("no_dev_email")
    else:
        dom = mail.split("@")[-1]
        if dom in FREE_MAIL:
            s += 10; flags.append("free_mail_contact")
    rel = ts(app["released"]); upd = app["updated"]
    if rel and upd and upd - rel < 30*86400*1000:
        s += 10; flags.append("released_then_frozen")
    return min(100, s), flags

def i3(app):
    jur = app["jurisdiction"]
    if jur != "LK":
        return None, ["era_no_legal_fields"]
    s = 0; flags = []
    if not (app["legal_name"] or "").strip():
        s += 45; flags.append("no_legal_entity")
    addr = (app["legal_address"] or "").strip()
    if not addr:
        s += 25; flags.append("no_legal_address")
    elif not any(h in addr.lower() for h in LOCAL_HINT.get(jur, [])):
        s += 15; flags.append("addr_jurisdiction_mismatch")
    if not (app["legal_phone"] or "").strip():
        s += 15; flags.append("no_legal_phone")
    if not (app["legal_email"] or "").strip():
        s += 15; flags.append("no_legal_email")
    return min(100, s), flags

def i4(app):
    s = 0; flags = []
    upd = app["updated"]; hv = ts(HARVEST[app["jurisdiction"]])
    if upd and hv:
        days = (hv - upd) / 86400000
        if days >= 90:
            s += 30; flags.append("stale_90d")
        if days >= 365:
            s += 30; flags.append("stale_1y")
    if not (app["version"] or "").strip():
        s += 10; flags.append("no_version")
    return min(100, s), flags

def i5(app):
    ds = app["datasafety"]
    if not ds: return None, ["no_datasafety"]
    try: d = json.loads(ds)
    except Exception: return None, ["unparsed_datasafety"]
    blob = json.dumps(d).lower()
    s = 0; flags = []
    if "shared" in blob and ("device or other ids" in blob or "device id" in blob):
        s += 50; flags.append("device_id_shared_3p")
    if "financial info" in blob and "shared" in blob:
        s += 30; flags.append("financial_data_shared")
    return (s if s else None), flags

def i6(app, perms):
    s = 0; flags = []
    kinds = set()
    for p in perms:
        low = (p or "").lower()
        for pat, kind in DANGEROUS:
            if pat in low:
                kinds.add(kind)
    reach = {"contacts","sms","calllog","location","mic","camera","storage","phonestate","calendarw"}
    hits = kinds & reach
    s = min(100, len(hits) * 18)
    if {"contacts","sms"} <= kinds:
        s = min(100, s + 20); flags.append("contacts_plus_sms")
    if hits:
        flags.append("dangerous_perms:" + ",".join(sorted(hits)))
    return s, flags

def i7(app):
    return None, ["reviews_lane_pending"]

def score_all(con):
    fams = {k: v for k, v in RUBRIC["families"].items()}
    fn = {"I1_brand_aso": i1, "I2_metadata_opacity": i2, "I3_physical_presence": i3,
          "I4_cyber_hygiene": i4, "I5_supply_chain": i5, "I6_permissions": None,
          "I7_responsiveness": i7}
    con.execute("""CREATE TABLE IF NOT EXISTS scores (
        jurisdiction VARCHAR, app_id VARCHAR,
        i1 SMALLINT, i2 SMALLINT, i3 SMALLINT, i4 SMALLINT, i5 SMALLINT, i6 SMALLINT, i7 SMALLINT,
        composite SMALLINT, band VARCHAR, partial BOOLEAN, flags VARCHAR[],
        rubric_version VARCHAR, scored_on DATE)""")
    rows = con.execute("SELECT * FROM apps").fetchdf().to_dict("records")
    pmap = {}
    for jur, aid, p in con.execute("SELECT jurisdiction, app_id, permission FROM permissions").fetchall():
        pmap.setdefault((jur, aid), []).append(p)
    av = dict(((j, a), st) for j, a, st in con.execute("SELECT jurisdiction, app_id, status FROM availability").fetchall()) if con.execute("SELECT 1 FROM information_schema.tables WHERE table_name='availability'").fetchone() else {}
    n = 0
    for app in rows:
        key = (app["jurisdiction"], app["app_id"])
        perms = pmap.get(key, [])
        sub, allflags = {}, []
        sub["I1"] = fn["I1_brand_aso"](app)
        sub["I2"] = fn["I2_metadata_opacity"](app)
        sub["I3"] = i3(app)
        sub["I4"] = fn["I4_cyber_hygiene"](app)
        sub["I5"] = i5(app)
        sub["I6"] = i6(app, perms)
        sub["I7"] = i7(app)
        scored, weights = {}, 0.0
        for fam_id, fam in fams.items():
            s, fl = sub[fam_id[:2]]
            if s is not None:
                scored[fam_id] = s
                weights += fam["weight"]
            allflags += fl
        if weights:
            comp = sum(scored[f] * fams[f]["weight"] for f in scored) / weights
            comp = round(comp)
            partial = len(scored) < len(fams)
            adj = RUBRIC.get("adjustments", {})
            for adj_id, cfg in adj.items():
                if cfg.get("status") != "active":
                    continue
                if adj_id == "platform_removed" and av.get(key) == "deleted":
                    comp += cfg["points"]
                    allflags.append("platform_removed")
        else:
            comp = None
            partial = True
        if comp is not None:
            comp = max(0, min(100, comp))
        band = "unscored"
        if comp is not None:
            for b, (lo, hi) in RUBRIC["bands"].items():
                if lo <= comp < hi or (b == "severe" and comp >= 75):
                    band = b; break
        con.execute(
            "INSERT INTO scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (app["jurisdiction"], app["app_id"],
             sub["I1"][0], sub["I2"][0], sub["I3"][0], sub["I4"][0], sub["I5"][0], sub["I6"][0], sub["I7"][0],
             comp, band, partial, sorted(set(allflags)), RUBRIC["version"],
             datetime.date.today().isoformat()))
        n += 1
    return n

if __name__ == "__main__":
    con = duckdb.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS scores (
        jurisdiction VARCHAR, app_id VARCHAR,
        i1_brand_aso INT, i2_metadata INT, i3_presence INT, i4_hygiene INT,
        i5_supplychain INT, i6_permissions INT, i7_responsive INT,
        composite INT, band VARCHAR, partial BOOLEAN, flags VARCHAR[],
        rubric_version VARCHAR, scored_on DATE)""")
    con.execute("DELETE FROM scores")
    n = score_all(con)
    bands = con.execute("SELECT band, COUNT(*) FROM scores GROUP BY band ORDER BY 2 DESC").fetchall()
    print("scored", n, "rows |", bands)
    out = con.execute("""SELECT s.*, a.title, a.installs, a.max_installs, a.score AS rating,
        a.legal_name, a.privacy_policy, a.developer_website, a.currency, a.harvested_on
        FROM scores s JOIN apps a USING (jurisdiction, app_id)
        ORDER BY composite DESC NULLS LAST""").fetchdf().to_dict("records")
    for r in out:
        r["scored_on"] = str(r["scored_on"]); r["harvested_on"] = str(r["harvested_on"])
    json.dump({"rubric_version": RUBRIC["version"], "scores": out},
              open(os.path.join(ROOT, "data", "scores.json"), "w"), ensure_ascii=False, default=str)
    print("wrote data/scores.json")
