#!/usr/bin/env python3
"""Build static site from warehouse + scores. Output: site/ (GH Pages)."""
import json, html, os, shutil, duckdb, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
DATA = os.path.join(ROOT, "data")
if os.path.exists(SITE):
    shutil.rmtree(SITE)
os.makedirs(os.path.join(SITE, "apps"))

RUBRIC = yaml.safe_load(open(os.path.join(ROOT, "rubric.yaml")))
FAMS = RUBRIC["families"]
con = duckdb.connect(os.path.join(DATA, "killerloanapps.duckdb"), read_only=True)

apps = con.execute("""
    SELECT a.*, s.i1_brand_aso, s.i2_metadata, s.i3_presence, s.i4_hygiene,
           s.i5_supplychain, s.i6_permissions, s.i7_responsive,
           s.composite, s.band, s.partial, s.flags, s.rubric_version, s.scored_on
    FROM apps a JOIN scores s USING (jurisdiction, app_id)
    QUALIFY row_number() OVER (PARTITION BY a.jurisdiction, a.app_id ORDER BY a.title) = 1""").fetchdf()
perms = {}
for jur, aid, p in con.execute("SELECT jurisdiction, app_id, permission FROM permissions").fetchall():
    perms.setdefault((jur, aid), []).append(p)
deleted = {}
DELSRC = {}
for jur, aid, d in con.execute("SELECT jurisdiction, app_id, deleted_on FROM deleted").fetchall():
    deleted.setdefault(jur, []).append((aid, d))
    DELSRC[(jur, aid)] = "2021 corpus record"
try:
    for jur, aid, fm, note in con.execute(
            "SELECT jurisdiction, app_id, first_missing, note FROM deleted_log").fetchall():
        if aid in {a for a, _ in deleted.get(jur, [])}:
            DELSRC[(jur, aid)] = "2021 corpus record + absent at recheck"
        else:
            deleted.setdefault(jur, []).append((aid, str(fm) if fm else None))
            DELSRC[(jur, aid)] = "availability recheck"
except Exception as e:
    print("deleted_log read failed:", e)

GONE = {}
LIVE = {}
for jur, st, n in con.execute(
        "SELECT jurisdiction, status, COUNT(*) FROM availability GROUP BY 1,2").fetchall():
    (GONE if st == "deleted" else LIVE)[jur] = n
TRACKED = int(apps.shape[0])
HIST_EXTRA = con.execute(
    "SELECT COUNT(*) FROM deleted d LEFT JOIN apps a USING (jurisdiction, app_id) "
    "WHERE a.app_id IS NULL").fetchone()[0]

DANGEROUS = ("contacts", "sms", "call log", "location", "microphone", "camera", "phone", "storage", "calendar")
JURS = {"LK": ("Sri Lanka", "Live harvest 2026-09-20 via GPlayAPI v2 (country=lk). 176 candidates → 155 lending apps."),
        "IN": ("India", "Historical corpus Dec 2020 – Feb 2022, the published killerloanapps dataset (725 apps; 339 apps were deleted from Play by Feb 2022)."),
        "NG": ("Nigeria", "Mar 2022 corpus from the same playbook run (126 apps).")}

def esc(x):
    return html.escape(str(x)) if x is not None else "—"

def slug(jur, aid):
    return f"{jur}_{aid.replace('/', '_')}"

def score_badge(comp, band, partial):
    if comp is None:
        return '<span class="badge b-none">unscored</span>'
    p = " (partial)" if partial else ""
    return f'<span class="badge b-{band}">{comp} {band}{p}</span>'

def sub_table(a):
    rows = []
    labels = {"i1_brand_aso": "I1", "i2_metadata": "I2", "i3_presence": "I3", "i4_hygiene": "I4",
              "i5_supplychain": "I5", "i6_permissions": "I6", "i7_responsive": "I7"}
    for col, fid in labels.items():
        v = getattr(a, col)
        f = FAMS[fid + "_" + col.split("_", 1)[1]] if fid + "_" + col.split("_", 1)[1] in FAMS else None
        name = f["name"] if f else fid
        w = f["weight"] if f else "?"
        shown = "—" if v is None else f"{v}/100"
        rows.append(f"<tr><td>{fid} {esc(name)}</td><td>w={w}</td><td>{shown}</td></tr>")
    return "<table><tr><th>Indicator family</th><th>Weight</th><th>Score</th></tr>" + "".join(rows) + "</table>"

# ---------- CSS ----------
open(os.path.join(SITE, "style.css"), "w").write("""
:root{--bg:#0e1116;--fg:#e6e6e6;--mut:#9aa4b2;--card:#161b22;--line:#2a313c;--acc:#e05252;--ok:#3fb26f;--warn:#e0a52f}
*{box-sizing:border-box}body{margin:0;font:16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg)}
a{color:#7ab8ff}main{max-width:1080px;margin:0 auto;padding:24px}
h1,h2,h3{line-height:1.2}small,.mut{color:var(--mut)}
table{border-collapse:collapse;width:100%;font-size:14px;margin:12px 0}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:var(--card);color:var(--mut);font-weight:600}
.badge{display:inline-block;padding:2px 8px;border-radius:99px;font-size:12px;font-weight:700;white-space:nowrap}
.b-low{background:#12331f;color:var(--ok)}.b-elevated{background:#3a2c10;color:var(--warn)}
.b-high{background:#3a1414;color:#ff8484}.b-severe{background:#5c0f0f;color:#ffb3b3}
.b-none{background:#222;color:var(--mut)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.disclaimer{border:1px solid var(--warn);border-radius:8px;padding:10px 14px;background:#241c0c;margin:16px 0}
.kv td:first-child{color:var(--mut);width:220px}
footer{border-top:1px solid var(--line);margin-top:32px;padding:16px;color:var(--mut);font-size:13px}
""")

# ---------- shared chrome ----------
def page(title, body, rel=""):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<link rel="stylesheet" href="{rel}style.css"></head><body><main>
<p class="mut"><a href="{rel}index.html">killerloanapps</a> · jurisdictions: <a href="{rel}jurisdiction/lk.html">LK</a> · <a href="{rel}jurisdiction/in.html">IN</a> · <a href="{rel}jurisdiction/ng.html">NG</a> · <a href="{rel}deletions.html">deleted</a> · <a href="{rel}methodology.html">methodology</a></p>
{body}
<footer>CashlessConsumer · data: Play Store metadata + permissions, own harvests · scoring: rubric {esc(RUBRIC['version'])} (experimental) · <a href="{rel}methodology.html">what this score is not</a></footer>
</main></body></html>"""

DISC = ('<div class="disclaimer"><b>Risk signals, not verdicts.</b> Scores flag <i>indicators</i> of abusive-lending '
        'behaviour from public app-store data. A high score is not proof of illegality; a low score is not a safety '
        'certificate. See <a href="methodology.html">methodology</a>.</div>')

# ---------- index ----------
tot = len(apps)
by_band = apps["band"].value_counts().to_dict()
stats = "".join(f"<div class='card'><div class='mut'>{k}</div><div style='font-size:28px;font-weight:800'>{v}</div></div>"
                for k, v in [("Apps tracked", tot), ("Elevated+", by_band.get("elevated", 0) + by_band.get("high", 0) + by_band.get("severe", 0)),
                             ("High", by_band.get("high", 0)), ("Severe", by_band.get("severe", 0))])
jur_cards = "".join(f"<div class='card'><h3><a href='jurisdiction/{j.lower()}.html'>{esc(n)}</a></h3>"
                    f"<p class='mut'>{len(apps[apps.jurisdiction==j])} apps · {esc(d)}</p></div>"
                    for j, (n, d) in JURS.items())
top = apps.sort_values("composite", ascending=False).head(20)
trows = "".join(f"<tr><td><a href='apps/{slug(r.jurisdiction, r.app_id)}.html'>{esc(r.title)}</a></td>"
                f"<td>{r.jurisdiction}</td><td>{esc(r.legal_name)}</td><td>{score_badge(r.composite, r.band, r.partial)}</td></tr>"
                for r in top.itertuples())
open(os.path.join(SITE, "index.html"), "w").write(page("killerloanapps — predatory loan-app tracker", f"""
<h1>killerloanapps</h1>
<p>Multi-jurisdiction tracker for predatory / abusive digital-lending apps. Same playbook across markets: harvest lending apps
from the Play Store, capture the <i>paperwork</i> (legal entity, privacy policy, developer contacts), pull permissions,
and score every app against the <a href="methodology.html">DeepStrat 7-family indicator rubric</a> for abusive digital lenders.</p>
<div class="cards">{stats}</div>
<h2>Jurisdictions</h2><div class="cards">{jur_cards}</div>
<h2>Highest-scoring apps</h2><table><tr><th>App</th><th>Jur</th><th>Legal entity</th><th>Score</th></tr>{trows}</table>
{DISC}"""))

# ---------- jurisdiction pages ----------
for j, (name, desc) in JURS.items():
    sub = apps[apps.jurisdiction == j].sort_values("composite", ascending=False)
    dels = deleted.get(j, [])
    delmap = dict(dels)
    rows = []
    for r in sub.itertuples():
        mark = ' <span class="badge b-severe">DELETED from Play</span>' if r.app_id in delmap else ""
        rows.append(f"<tr><td><a href='../apps/{slug(j, r.app_id)}.html'>{esc(r.title)}</a>{mark}</td>"
                    f"<td>{esc(r.installs)}</td><td>{esc(r.legal_name)}</td><td>{score_badge(r.composite, r.band, r.partial)}</td></tr>")
    n_gone = GONE.get(j, 0)
    n_tot = len(sub)
    del_line = (f"<p class='mut'><b>{n_gone} of {n_tot} apps in this jurisdiction are gone from the "
                f"Play Store</b> (checked against the LK/IN/NG storefront on 2026-09-21; {LIVE.get(j, 0)} still live). "
                f"<a href='../deletions.html'>Deletion log</a></p>") if n_gone else ""
    os.makedirs(os.path.join(SITE, "jurisdiction"), exist_ok=True)
    open(os.path.join(SITE, "jurisdiction", f"{j.lower()}.html"), "w").write(page(f"{name} loan apps", f"""
<h1>{esc(name)} — {len(sub)} loan apps</h1><p class="mut">{esc(desc)}</p>{del_line}
<table><tr><th>App</th><th>Installs</th><th>Legal entity (paperwork)</th><th>Score</th></tr>{''.join(rows)}</table>
{DISC}""", rel="../"))

# ---------- app pages ----------
HAS_AV = con.execute("SELECT 1 FROM information_schema.tables WHERE table_name='availability'").fetchone()
av = dict(((j, a), st) for j, a, st in con.execute("SELECT jurisdiction, app_id, status FROM availability").fetchall()) if HAS_AV else {}
delall = {}
for j, dl in deleted.items():
    for aid, d in dl:
        delall[aid] = (j, d)
for r in apps.itertuples():
    key = (r.jurisdiction, r.app_id)
    pl = perms.get(key, [])
    dang = [p for p in pl if any(d in p.lower() for d in DANGEROUS)]
    try: flags = json.loads(r.flags) if isinstance(r.flags, str) else list(r.flags or [])
    except Exception: flags = []
    flag_html = "".join(f"<li><code>{esc(f)}</code></li>" for f in flags) or "<li>none</li>"
    gone = av.get(key) == "deleted" or r.app_id in delall
    gone_html = ('<p class="disclaimer"><b>Deleted from Google Play.</b> This listing was absent at the latest '
                 'availability recheck (or is in the historical deletion record). The snapshot above is the only '
                 'remaining structured record.</p>') if gone else ""
    ds = ""
    if r.datasafety:
        try:
            d = json.loads(r.datasafety)
            if isinstance(d, dict):
                ds = f"<p class='mut'>Data safety: shared={esc(d.get('shared'))} collected={esc(d.get('collected'))} security={esc(d.get('security'))}</p>"
        except Exception: pass
    body = f"""
<h1>{esc(r.title)} <small class="mut">[{esc(r.jurisdiction)}]</small></h1>
{gone_html}
<p>{score_badge(r.composite, r.band, r.partial)} · installs {esc(r.installs)} · rating {esc(r.score)} ({esc(r.ratings)}) · updated {esc(r.updated)}</p>
{DISC}
<h2>Score breakdown <small class="mut">(rubric {esc(r.rubric_version)})</small></h2>
{sub_table(r)}
<h3>Triggered signals</h3><ul>{flag_html}</ul>
<h2>Paperwork</h2>
<table class="kv">
<tr><td>Developer</td><td>{esc(r.developer_id)}</td></tr>
<tr><td>Legal entity</td><td>{esc(r.legal_name)}</td></tr>
<tr><td>Legal email</td><td>{esc(r.legal_email)}</td></tr>
<tr><td>Legal address</td><td>{esc(r.legal_address)}</td></tr>
<tr><td>Legal phone</td><td>{esc(r.legal_phone)}</td></tr>
<tr><td>Developer email</td><td>{esc(r.developer_email)}</td></tr>
<tr><td>Website</td><td>{('<a href="'+html.escape(str(r.developer_website), quote=True)+'">'+esc(r.developer_website)+"</a>") if r.developer_website else '—'}</td></tr>
<tr><td>Privacy policy</td><td>{('<a href="'+html.escape(str(r.privacy_policy), quote=True)+'">'+esc(r.privacy_policy)+"</a>") if r.privacy_policy else '—'}</td></tr>
<tr><td>Released</td><td>{esc(r.released)}</td></tr>
<tr><td>Version</td><td>{esc(r.version)}</td></tr>
<tr><td>Play listing</td><td>{('<a href="'+html.escape(str(r.url), quote=True)+'">'+esc(r.url)+"</a>") if r.url else '—'}</td></tr>
</table>
{ds}
<h2>Permissions ({len(pl)} total, {len(dang)} dangerous)</h2>
<ul>{''.join(f'<li>{esc(p)}</li>' for p in dang) or '<li>none recorded</li>'}</ul>
<p class="mut">Full permission list in the dataset repo. Permissions captured at harvest time; apps update silently.</p>
"""
    fn = slug(r.jurisdiction, r.app_id)
    fp = os.path.join(SITE, "apps", fn + ".html")
    if os.path.exists(fp):
        import hashlib
        fp = os.path.join(SITE, "apps", fn + "-" + hashlib.md5(r.app_id.encode()).hexdigest()[:6] + ".html")
    open(fp, "w").write(page(r.title, body, rel="../"))

# ---------- deletions page ----------
rows = []
for j in ("IN", "NG", "LK"):
    for aid, d in sorted(deleted.get(j, []), key=lambda x: (x[1] or "")):
        sub = apps[(apps.jurisdiction == j) & (apps.app_id == aid)]
        title = sub.iloc[0]["title"] if len(sub) else aid
        comp = sub.iloc[0]["composite"] if len(sub) else None
        band = sub.iloc[0]["band"] if len(sub) else None
        part = bool(sub.iloc[0]["partial"]) if len(sub) else False
        rows.append('<tr><td>' + j + '</td><td><a href="apps/' + slug(j, aid) + '.html">' + esc(title) + '</a></td>'
                    '<td><code>' + esc(aid) + '</code></td><td>' + esc(d) + '</td>'
                    '<td class="mut">' + esc(DELSRC.get((j, aid), "") + ("" if len(sub) else " (not in tracked set)")) + '</td>'
                    '<td>' + score_badge(comp, band, part) + '</td></tr>')
cnt = {j: len(deleted.get(j, [])) for j in ("IN", "NG", "LK")}
del_html = ('<div class="cards">'
            "<div class='card'><div class='mut'>IN gone</div><div style='font-size:28px;font-weight:800'>" + str(GONE.get("IN", 0)) + "</div></div>"
            "<div class='card'><div class='mut'>NG gone</div><div style='font-size:28px;font-weight:800'>" + str(GONE.get("NG", 0)) + "</div></div>"
            "<div class='card'><div class='mut'>LK gone</div><div style='font-size:28px;font-weight:800'>" + str(GONE.get("LK", 0)) + "</div></div>"
            "<div class='card'><div class='mut'>Tracked apps gone</div><div style='font-size:28px;font-weight:800'>" + str(sum(GONE.values())) + " / " + str(TRACKED) + "</div></div>"
            "<div class='card'><div class='mut'>Corpus-era records (outside tracked set)</div><div style='font-size:28px;font-weight:800'>" + str(HIST_EXTRA) + "</div></div>"
            "</div>")
del_page = ('<h1>Deleted from the Play Store</h1>'
            '<p>Apps captured in a harvest and later absent from the store. Deletion is one of the strongest '
            'end-state signals: either the platform enforced against abuse, or the operator burned the listing. '
            'Either way the snapshot is the record. Two evidence classes are merged here: <i>2021 corpus record</i> '
            '(gaps logged while the India dataset was built, Dec 2020 - Feb 2022) and <i>availability recheck</i> '
            '(every app id checked against its own storefront on 2026-09-21 via GPlayAPI v2, method in '
            '<code>scripts/check_deletions.py</code>). A storefront 404 is recorded absent; transient errors are '
            'logged and never overwrite a known state.</p>'
            + del_html +
            '<table><tr><th>Jur</th><th>App</th><th>appId</th><th>Deleted on / first missing</th>'
            '<th>Evidence</th><th>Score at capture</th></tr>'
            + "".join(rows) + '</table>' + DISC)
open(os.path.join(SITE, "deletions.html"), "w").write(page("Deleted apps", del_page))

# ---------- methodology ----------
fam_rows = "".join(f"<tr><td><b>{esc(k)}</b> {esc(v['name'])}</td><td>{v['weight']}</td><td>{esc(v.get('description',''))}</td>"
                   f"<td>{'computed' if v.get('computed') else 'pending'}</td></tr>"
                   for k, v in FAMS.items())
bands = " · ".join(f"<b>{k}</b> {v[0]}–{v[1]}" for k, v in RUBRIC["bands"].items())
open(os.path.join(SITE, "methodology.html"), "w").write(page("Methodology", f"""
<h1>Methodology — rubric {esc(RUBRIC['version'])}</h1>
<p>Framework: <i>Indicators for Detection of Abusive Digital Lenders</i> (DeepStrat, Nov 2022) — the 7-indicator-family
toolkit CashlessConsumer co-developed, operationalised here as a transparent weighted score over public app-store data.
Weights and thresholds are versioned in <code>rubric.yaml</code> in the repo; every score is reproducible from the warehouse.</p>
<h2>Families</h2>
<table><tr><th>Family</th><th>Weight</th><th>What it measures</th><th>Status</th></tr>{fam_rows}</table>
<h2>Bands</h2><p>{bands} (composite 0–100; partial scores renormalise over computed families and are marked "partial").</p>
<h2>What this is not</h2>
<ul>
<li>Not a legal determination — indicators are circumstantial signals, some (like ASO keyword stuffing) are only weakly associated with abuse.</li>
<li>Not a substitute for APK analysis — I5 (supply chain: shared SDKs with surveillance/fraud vendors) needs on-device binary inspection; the APK lane is phase 3.</li>
<li>Not abuse-proof — ratings/reviews are gameable, which is exactly why metadata and paperwork carry more weight.</li>
</ul>
<h2>Data provenance</h2>
<ul>
<li>LK: own harvest, 2026-09-20, GPlayAPI v2 (<code>country=lk</code>), 176 candidates → 155 apps after keyword filter.</li>
<li>IN: the published killerloanapps corpus (Dec 2020 – Feb 2022), 725 apps incl. 339 later deleted from Play.</li>
<li>NG: Mar 2022 corpus, 126 apps.</li>
</ul>
<p>Corpora are historical snapshots: scores describe the app as captured on <code>harvested_on</code>, not today.</p>
{DISC}"""))

open(os.path.join(SITE, "CNAME"), "w").write("killerloanapps.cashlessconsumer.in")
open(os.path.join(SITE, ".nojekyll"), "w").write("")
open(os.path.join(SITE, "404.html"), "w").write(page("404", "<h1>Not found</h1><p>Try the <a href='index.html'>index</a>.</p>"))

n_app_pages = len(os.listdir(os.path.join(SITE, "apps")))
print(f"site: index + {len(JURS)} jurisdictions + {n_app_pages} app pages + methodology | {SITE}")
