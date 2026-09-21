#!/usr/bin/env python3
"""Build static site from warehouse + scores. Output: site/ (GH Pages).

Corpus model: `jurisdiction` in the warehouse is a CORPUS id, not a country.
  Live corpora (rechecked on every refresh): IN (India 2026 harvest), LK (Sri Lanka 2026 harvest)
  Historical corpora (frozen snapshots):     IN_2020_2022, NG_2022
Live corpora get jurisdiction/ pages; historical corpora get historical/ pages.
"""
import json, html, os, shutil, duckdb, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SITE = os.path.join(ROOT, "site")
RUBRIC = yaml.safe_load(open(os.path.join(ROOT, "rubric.yaml")))
FAMS = RUBRIC["families"]
SCOPE = yaml.safe_load(open(os.path.join(DATA, "scope_rules.yaml")))

HAS = lambda t: con.execute("SELECT 1 FROM information_schema.tables WHERE table_name=?", [t]).fetchone()

# wipe generated page dirs so removed corpora/apps do not leave stale pages
for d in ("apps", "jurisdiction", "historical"):
    shutil.rmtree(os.path.join(SITE, d), ignore_errors=True)
os.makedirs(os.path.join(SITE, "apps"), exist_ok=True)

con = duckdb.connect(os.path.join(DATA, "killerloanapps.duckdb"), read_only=True)

apps = con.execute("""
    SELECT a.*, s.i1 AS i1_brand_aso, s.i2 AS i2_metadata, s.i3 AS i3_presence, s.i4 AS i4_hygiene,
           s.i5 AS i5_supplychain, s.i6 AS i6_permissions, s.i7 AS i7_responsive,
           s.composite, s.band, s.partial, s.flags, s.rubric_version, s.scored_on, s.scope
    FROM apps a JOIN scores s USING (jurisdiction, app_id)""").fetchdf()

# corpus registry: corpus_id -> (label, short, kind, page_path, description)
CORPORA = {}
if HAS("corpora"):
    for cid, label, short, kind, country, harvest, seed, desc in con.execute(
            "SELECT corpus_id, label, short, kind, country, harvested_on, seed_date, description FROM corpora ORDER BY kind, label").fetchall():
        CORPORA[cid] = dict(label=label, short=short, kind=kind, country=country,
                            harvest=str(harvest), seed=str(seed) if seed else None, desc=desc)
else:  # pre-corpus warehouse fallback
    CORPORA = {"IN": dict(label="India", short="IN", kind="live", country="in", harvest="—", seed=None, desc="")}

def page_path(cid):
    c = CORPORA[cid]
    return f"jurisdiction/{cid.lower()}.html" if c["kind"] == "live" else f"historical/{cid.lower().replace('_', '-')}.html"

for cid in CORPORA:
    CORPORA[cid]["path"] = page_path(cid)

perms = {}
for jur, aid, p in con.execute("SELECT jurisdiction, app_id, permission FROM permissions").fetchall():
    perms.setdefault((jur, aid), []).append(p)

deleted = {}
for jur, aid, d in con.execute("SELECT jurisdiction, app_id, deleted_on FROM deleted").fetchall():
    deleted.setdefault(jur, []).append((aid, d))

av = dict(((j, a), st) for j, a, st in con.execute("SELECT jurisdiction, app_id, status FROM availability").fetchall()) if HAS("availability") else {}

GONE, LIVE_CT = {}, {}
for cid in CORPORA:
    sub = apps[apps.jurisdiction == cid]
    g = 0
    for r in sub.itertuples():
        if (av.get((cid, r.app_id)) == "deleted" or r.app_id in dict(deleted.get(cid, []))
                or bool(getattr(r, "gone_from_store", False))):
            g += 1
    GONE[cid] = g
    LIVE_CT[cid] = len(sub) - g

DELSRC = {}
for jur, aid, d in con.execute("SELECT jurisdiction, app_id, deleted_on FROM deleted").fetchall():
    DELSRC[(jur, aid)] = d

DANGEROUS = ["camera", "contacts", "location", "sms", "call log", "microphone", "phone", "accounts",
             "storage", "calendar", "running apps", "system settings", "network"]

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
        key = fid + "_" + col.split("_", 1)[1]
        f = FAMS.get(key)
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
.k-live{background:#10281c;color:#7ee0a4}.k-hist{background:#241f2e;color:#c3aee8}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.disclaimer{border:1px solid var(--warn);border-radius:8px;padding:10px 14px;background:#241c0c;margin:16px 0}
.kv td:first-child{color:var(--mut);width:220px}
footer{border-top:1px solid var(--line);margin-top:32px;padding:16px;color:var(--mut);font-size:13px}
""")

# ---------- shared chrome ----------
def nav(rel=""):
    live = " · ".join(f"<a href='{rel}{CORPORA[c]['path']}'>{esc(CORPORA[c]['label'])}</a>"
                      for c in sorted(CORPORA, key=lambda x: CORPORA[x]["label"]) if CORPORA[c]["kind"] == "live")
    hist = " · ".join(f"<a href='{rel}{CORPORA[c]['path']}'>{esc(CORPORA[c]['label'])}</a>"
                      for c in sorted(CORPORA, key=lambda x: CORPORA[x]["label"]) if CORPORA[c]["kind"] == "historical")
    parts = [f"<a href=\"{rel}index.html\">killerloanapps</a>"]
    if live:
        parts.append(f"live: {live}")
    if hist:
        parts.append(f"historical: {hist}")
    parts.append(f"<a href=\"{rel}deletions.html\">deleted</a>")
    parts.append(f"<a href=\"{rel}methodology.html\">methodology</a>")
    return "<p class=\"mut\">" + " · ".join(parts) + "</p>"

def page(title, body, rel=""):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<link rel="stylesheet" href="{rel}style.css"></head><body><main>
{nav(rel)}
{body}
<footer>CashlessConsumer · data: Play Store metadata + permissions, own harvests · scoring: rubric {esc(RUBRIC['version'])} (experimental) · <a href="{rel}methodology.html">what this score is not</a></footer>
</main></body></html>"""

DISC = ('<div class="disclaimer"><b>Risk signals, not verdicts.</b> Scores flag <i>indicators</i> of abusive-lending '
        'behaviour from public app-store data. A high score is not proof of illegality; a low score is not a safety '
        'certificate. See <a href="methodology.html">methodology</a>.</div>')

# ---------- index ----------
def kind_card(cid):
    c = CORPORA[cid]
    n = len(apps[apps.jurisdiction == cid])
    tag = "live" if c["kind"] == "live" else "frozen snapshot"
    extra = f" · {GONE[cid]} gone" if GONE.get(cid) else ""
    return (f"<div class='card'><h3><a href='{c['path']}'>{esc(c['label'])}</a> "
            f"<span class='badge {'k-live' if c['kind']=='live' else 'k-hist'}'>{tag}</span></h3>"
            f"<p class='mut'>{n} apps{extra}<br>harvest {esc(c['harvest'])}"
            + (f" · corpus start {esc(c['seed'])}" if c['seed'] else "") + f"</p></div>")

live_ids = [c for c in CORPORA if CORPORA[c]["kind"] == "live"]
hist_ids = [c for c in CORPORA if CORPORA[c]["kind"] == "historical"]
by_band = apps["band"].value_counts().to_dict()
live_apps = apps[apps.jurisdiction.isin(live_ids)] if live_ids else apps.iloc[0:0]
live_lending = live_apps[live_apps["scope"] == "lending"]
n_offscope_live = int((live_apps["scope"] != "lending").sum())
live_band = live_lending["band"].value_counts().to_dict()
stats = "".join(
    f"<div class='card'><div class='mut'>{k}</div><div style='font-size:28px;font-weight:800'>{v}</div></div>"
    for k, v in [("Live lending apps", len(live_lending)),
                 ("Live: elevated+", sum(live_band.get(b, 0) for b in ("elevated", "high", "severe"))),
                 ("Live: gone from Play", sum(GONE.get(c, 0) for c in live_ids)),
                 ("Historical apps tracked", sum(len(apps[apps.jurisdiction == c]) for c in hist_ids))])

top = live_lending.sort_values("composite", ascending=False).head(20)
trows = "".join(
    f"<tr><td><a href='apps/{slug(r.jurisdiction, r.app_id)}.html'>{esc(r.title)}</a></td>"
    f"<td>{esc(CORPORA.get(r.jurisdiction, {}).get('short', r.jurisdiction))}</td>"
    f"<td>{esc(r.legal_name)}</td><td>{score_badge(r.composite, r.band, r.partial)}</td></tr>"
    for r in top.itertuples())

open(os.path.join(SITE, "index.html"), "w").write(page("killerloanapps — predatory loan-app tracker", f"""
<h1>killerloanapps</h1>
<p>Multi-jurisdiction tracker for predatory / abusive digital-lending apps. Same playbook across markets: harvest lending apps
from the Play Store, capture the <i>paperwork</i> (legal entity, privacy policy, developer contacts), pull permissions,
score every app against the <a href="methodology.html">DeepStrat 7-family indicator rubric</a>, then recheck availability so
deletions are recorded rather than lost.</p>
<div class="cards">{stats}</div>
<h2>Live corpora <span class="badge k-live">refreshed</span></h2>
<p class="mut">Recheck every app id against its own storefront on every refresh, then re-harvest new listings.</p>
<div class="cards">{''.join(kind_card(c) for c in sorted(live_ids, key=lambda x: CORPORA[x]['label']))}</div>
<h2>Historical corpora <span class="badge k-hist">frozen</span></h2>
<p class="mut">Research snapshots kept as of their harvest date. These apps have moved on; the listing metadata is the record.
Deletions below are from the original corpus record, not a fresh check.</p>
<div class="cards">{''.join(kind_card(c) for c in sorted(hist_ids, key=lambda x: CORPORA[x]['label']))}</div>
<h2>Highest-scoring apps (live lending scope)</h2>
<p class="mut">Headline counts cover lending-scope apps only. The keyword harvest also catches general payments, shopping, ledger and foreign listings; they stay in the dataset and on each corpus page under <i>out of lending scope</i> — labelled, not dropped (<code>data/scope_rules.yaml</code>).</p>
<table><tr><th>App</th><th>Jur</th><th>Legal entity</th><th>Score</th></tr>{trows}</table>
{DISC}"""))

# ---------- corpus pages ----------
for cid, c in CORPORA.items():
    sub_all = apps[apps.jurisdiction == cid]
    sub = sub_all[sub_all["scope"] == "lending"].sort_values("composite", ascending=False)
    offscope = sub_all[sub_all["scope"] != "lending"].sort_values("composite", ascending=False)
    delmap = dict(deleted.get(cid, []))
    rows = []
    for r in sub.itertuples():
        gone = (av.get((cid, r.app_id)) == "deleted" or r.app_id in delmap
                or bool(getattr(r, "gone_from_store", False)))
        mark = ' <span class="badge b-severe">DELETED from Play</span>' if gone else ""
        rows.append(f"<tr><td><a href='../apps/{slug(cid, r.app_id)}.html'>{esc(r.title)}</a>{mark}</td>"
                    f"<td>{esc(r.installs)}</td><td>{esc(r.legal_name)}</td><td>{score_badge(r.composite, r.band, r.partial)}</td></tr>")
    n_gone, n_tot = GONE.get(cid, 0), len(sub)
    offscope_rows = "".join(
        f"<tr><td>{esc(r.title)}</td><td><code>{esc(r.app_id)}</code></td>"
        f"<td><span class='badge k-hist'>{esc(r.scope.replace('_', ' '))}</span></td><td>{score_badge(r.composite, r.band, r.partial)}</td></tr>"
        for r in offscope.itertuples())
    offscope_html = ("<h3>Out of lending scope — " + str(len(offscope)) + " captures</h3>"
                     "<p class='mut'>Keyword-matched by Play search but not a lending product for this market "
                     "(payments, shopping, ledgers, foreign listings). Kept and scored, excluded from the headline count so the "
                     "lending picture stays clean. Rules: <code>data/scope_rules.yaml</code>.</p>"
                     "<table><tr><th>App</th><th>App id</th><th>Scope</th><th>Score</th></tr>"
                     + offscope_rows + "</table>") if len(offscope) else ""
    checked = any(j == cid for (j, _a) in av)
    n_era = len(deleted.get(cid, []))
    if n_gone and checked:
        era = (f" {n_era} were already logged missing during the corpus window." if n_era else "")
        line = (f"<p class='mut'><b>{n_gone} of {n_tot} apps here are gone from the Play Store</b> "
                f"({LIVE_CT.get(cid, 0)} still live). Every app id is rechecked against its own "
                f"<code>{esc(c['country'])}</code> storefront on each refresh.{era} "
                f"<a href='../deletions.html'>Deletion log</a></p>")
    elif n_gone:
        line = (f"<p class='mut'><b>{n_gone} of {n_tot} apps were deleted from the Play Store during the corpus window.</b> "
                f"From the original corpus record, not a fresh check. <a href='../deletions.html'>Deletion log</a></p>")
    else:
        line = ""
    kind_tag = "live" if c["kind"] == "live" else "historical"
    out = os.path.join(SITE, c["path"])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write(page(f"{c['label']} loan apps", f"""
<h1>{esc(c['label'])} — {n_tot} loan apps <span class="badge {'k-live' if c['kind']=='live' else 'k-hist'}'>{kind_tag}</span></h1>
<p class="mut">{esc(c['desc'])}</p>
<p class="mut">Harvest {esc(c['harvest'])}{(' · corpus start ' + esc(c['seed'])) if c['seed'] else ''} · country code <code>{esc(c['country'])}</code></p>
{line}
<table><tr><th>App</th><th>Installs</th><th>Legal entity (paperwork)</th><th>Score</th></tr>{''.join(rows)}</table>
{offscope_html}
{DISC}""", rel="../"))

# ---------- app pages ----------
delall = {}
for j, dl in deleted.items():
    for aid, d in dl:
        delall[(j, aid)] = d
for r in apps.itertuples():
    cid = r.jurisdiction
    c = CORPORA.get(cid, dict(label=cid, short=cid, kind="live", harvest="—", country="?", desc="", path="index.html"))
    key = (cid, r.app_id)
    pl = perms.get(key, [])
    dang = [p for p in pl if any(d in p.lower() for d in DANGEROUS)]
    try: flags = json.loads(r.flags) if isinstance(r.flags, str) else list(r.flags or [])
    except Exception: flags = []
    flag_html = "".join(f"<li><code>{esc(f)}</code></li>" for f in flags) or "<li>none</li>"
    gone = (av.get(key) == "deleted" or key in delall
            or bool(getattr(r, "gone_from_store", False)))
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
<h1>{esc(r.title)} <small class="mut">[{esc(c['label'])}]</small> <span class="badge {('k-live' if r.scope == 'lending' else 'k-hist')}">{esc(str(r.scope).replace('_', ' '))}</span></h1>
{gone_html}
<p>{score_badge(r.composite, r.band, r.partial)} · installs {esc(r.installs)} · rating {esc(r.score)} ({esc(r.ratings)}) · updated {esc(r.updated)}</p>
<p class="mut">Corpus: <a href="../{c['path']}">{esc(c['label'])}</a>
<span class="badge {'k-live' if c['kind']=='live' else 'k-hist'}">{'live' if c['kind']=='live' else 'historical'}</span>
· harvested {esc(c['harvest'])}{(" · last seen in a harvest snapshot " + esc(str(r.last_seen))) if getattr(r, "last_seen", None) and getattr(r, "gone_from_store", False) else ""}</p>
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
    fn = slug(cid, r.app_id)
    fp = os.path.join(SITE, "apps", fn + ".html")
    if os.path.exists(fp):
        import hashlib
        fp = os.path.join(SITE, "apps", fn + "-" + hashlib.md5(r.app_id.encode()).hexdigest()[:6] + ".html")
    open(fp, "w").write(page(r.title, body, rel="../"))

# ---------- deletions page ----------
def corpus_dels(cid):
    out = []
    seen = set()
    for aid, d in sorted(deleted.get(cid, []), key=lambda x: (x[1] or "")):
        out.append((aid, d, "corpus record"))
        seen.add(aid)
    for (j, aid), st in av.items():
        if j == cid and st == "deleted" and aid not in seen:
            out.append((aid, TODAY, "availability recheck"))
    return out

TODAY = str(con.execute("SELECT MAX(last_checked) FROM availability").fetchone()[0]) if HAS("availability") else "—"

sections = []
for kind, ids in (("Live corpora", live_ids), ("Historical corpora", hist_ids)):
    blocks = []
    for cid in sorted(ids, key=lambda x: CORPORA[x]["label"]):
        dels = corpus_dels(cid)
        if not dels:
            continue
        rows = []
        for aid, d, src in dels:
            sub = apps[(apps.jurisdiction == cid) & (apps.app_id == aid)]
            title = sub.iloc[0]["title"] if len(sub) else aid
            comp = sub.iloc[0]["composite"] if len(sub) else None
            band = sub.iloc[0]["band"] if len(sub) else None
            part = bool(sub.iloc[0]["partial"]) if len(sub) else False
            rows.append('<tr><td><a href="apps/' + slug(cid, aid) + '.html">' + esc(title) + '</a></td>'
                        '<td><code>' + esc(aid) + '</code></td><td>' + esc(d) + '</td>'
                        '<td class="mut">' + esc(src) + ("" if len(sub) else " (not in tracked set)") + '</td>'
                        '<td>' + score_badge(comp, band, part) + '</td></tr>')
        n = len(dels)
        ntot = len(apps[apps.jurisdiction == cid])
        blocks.append(f"<h3>{esc(CORPORA[cid]['label'])} — {n} of {ntot} apps gone</h3>"
                      f"<table><tr><th>App</th><th>App id</th><th>Recorded</th><th>Evidence</th><th>Score</th></tr>"
                      + "".join(rows) + "</table>")
    if blocks:
        sections.append(f"<h2>{kind}</h2>" + "".join(blocks))

open(os.path.join(SITE, "deletions.html"), "w").write(page("Deletions", f"""
<h1>Deleted from the Play Store</h1>
<p>Deletion is one of the strongest end-state signals: either the platform enforced against abuse, or the operator
burned the listing. Either way the snapshot is the record. Two evidence classes are merged here:
<b>corpus record</b> (gaps logged while a corpus was being built) and <b>availability recheck</b>
(every app id checked against its own storefront on {esc(TODAY)} via GPlayAPI v2 — method in <code>scripts/check_deletions.py</code>).</p>
{''.join(sections)}
{DISC}"""))

# ---------- methodology (generated each build) ----------
live_rows = "".join(
    f"<tr><td>{esc(CORPORA[c]['label'])}</td><td><code>{esc(CORPORA[c]['country'])}</code></td>"
    f"<td>{esc(CORPORA[c]['harvest'])}</td><td>{len(apps[apps.jurisdiction == c])}</td></tr>"
    for c in sorted(live_ids, key=lambda x: CORPORA[x]["label"]))
hist_rows = "".join(
    f"<tr><td>{esc(CORPORA[c]['label'])}</td><td><code>{esc(CORPORA[c]['country'])}</code></td>"
    f"<td>{esc(CORPORA[c]['harvest'])}</td><td>{len(apps[apps.jurisdiction == c])}</td>"
    f"<td>{esc(CORPORA[c]['desc'])}</td></tr>"
    for c in sorted(hist_ids, key=lambda x: CORPORA[x]["label"]))
fam_rows = "".join(f"<tr><td>{esc(k.split('_')[0])}</td><td>{esc(v['name'])}</td><td>{esc(v['weight'])}</td></tr>"
                   for k, v in FAMS.items())
scope_out = SCOPE.get("out_of_scope_app_ids") or []
open(os.path.join(SITE, "methodology.html"), "w").write(page("Methodology", f"""
<h1>Methodology</h1>
<p>Play-Store-only, paperwork-first. Everything on this site comes from public Play listings captured with our own
harvest tooling; nothing is inferred about a company's conduct beyond what its own listing, permissions and paperwork say.</p>

<h2>Pipeline</h2>
<ol>
<li><b>Harvest</b> — keyword search on the Play Store for lending terms per country (in/lk/ng plus local-language terms),
then fetch full detail + permissions for every candidate (<code>scripts/harvest.py</code>, via our GPlayAPI v2 instance
at gplayapiv2.fly.dev). Writes <code>data/harvests/&lt;CC&gt;_&lt;date&gt;.db</code>.</li>
<li><b>Warehouse</b> — corpora merged into one DuckDB (<code>scripts/build_warehouse.py</code>), each row carrying its corpus id,
harvest date, legal-entity fields, privacy policy URL and the full permission set.</li>
<li><b>Availability recheck</b> — every app id of every live corpus is re-queried against its own storefront on each refresh
(<code>scripts/check_deletions.py</code>), so deletions are recorded as events, not lost.</li>
<li><b>Scoring</b> — rubric (<code>rubric.yaml</code> {esc(RUBRIC['version'])}) applied per app (<code>scripts/score.py</code>),
including a +15 <i>platform_removed</i> adjustment for apps that have since vanished from the store.</li>
<li><b>Publication</b> — static pages (<code>scripts/build_site.py</code>) committed and served from GitHub Pages.</li>
</ol>

<h2>Corpora</h2>
<p>A corpus is a dated harvest of one country's storefront. Live corpora are re-harvested and rechecked on a schedule;
historical corpora are frozen research snapshots kept as of their harvest date — useful precisely because they show what
the 2021-22 abusive-lending wave looked like, and how much of it later disappeared.</p>
<table><tr><th>Live corpus</th><th>Country</th><th>Harvested</th><th>Apps</th></tr>{live_rows}</table>
<table><tr><th>Historical corpus</th><th>Country</th><th>Snapshot</th><th>Apps</th><th>Note</th></tr>{hist_rows}</table>

<h2>Indicator families</h2>
<p>Seven families, derived from DeepStrat's <i>Indicators for Detection of Abusive Digital Lenders</i> (Nov 2022,
copy in <code>docs/</code>) — the framework the operator of this site co-wrote. Each family scores 0-100; the composite is a
weighted average, and families with no signal in a corpus's era are reported as partial rather than imputed.</p>
<table><tr><th>Family</th><th>Name</th><th>Weight</th></tr>{fam_rows}</table>

<h2>Lending scope</h2>
<p>The harvest is keyword-driven, so it also catches general-purpose payments, shopping, ledger and foreign apps.
Those stay in the dataset (nothing is hidden) but are labelled <code>out_of_scope</code> or <code>adjacent</code> and kept out of
headline counts. {len(scope_out)} app ids are currently listed as clearly non-lending in <code>data/scope_rules.yaml</code>;
everything else is classified by lending keywords in title + summary.</p>

<h2>Deletion evidence</h2>
<p>Two classes, never blended: <b>corpus record</b> (a gap logged while the historical corpus was being built —
the 2021-22 India record of 339 apps) and <b>availability recheck</b> (a live check against the storefront, stamped with
the date). An app that disappears and later reappears is removed from the deletion log automatically.</p>

<h2>What this is not</h2>
<ul>
<li>Not a verdict on any company. A high score means the public listing shows <i>indicators</i> associated with abusive lending;
a low score is not a safety certificate.</li>
<li>Not a substitute for regulatory records. Where a licence claim matters, check the regulator (CBSL/MCRA in Sri Lanka,
RBI and the state police in India, FCCPC in Nigeria) — we say what the listing claims, not what the law says.</li>
<li>Not real-time. The snapshot date on every page is the date of the last harvest or recheck; apps change silently.</li>
<li>No personal data. Developer/legal contacts here are the business contacts the developer published on the store.</li>
</ul>
{DISC}"""))

for stray in ("jur_in.tmp", "jur_lk.tmp", "jur_ng.tmp"):
    p = os.path.join(SITE, stray)
    if os.path.exists(p):
        os.remove(p)

n_app_pages = len(os.listdir(os.path.join(SITE, "apps")))

STALE = ["jurisdiction/ng.html"]
for rel in STALE:
    p = os.path.join(SITE, rel)
    if os.path.exists(p):
        os.remove(p)

print(f"site: index + {len(live_ids)} live + {len(hist_ids)} historical corpus pages "
      f"+ {n_app_pages} app pages + deletions + methodology | {SITE}")
