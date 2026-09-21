# killerloanapps — multi-jurisdiction predatory loan-app tracker

Tracker for predatory / abusive digital-lending apps across jurisdictions, scored with the
**DeepStrat "Indicators for Detection of Abusive Digital Lenders" (Nov 2022) seven-family rubric**.
The rubric source is archived at `docs/deepstrat-indicators-for-detection-of-abusive-digital-lenders.pdf`.

**Live:** https://cashlessconsumer.github.io/killerloanapps/ — custom domain `killerloanapps.cashlessconsumer.in`
awaits the Netlify CNAME.

## Corpora model

Two classes of corpus, and the distinction matters when reading any page:

- **live** — re-harvested on the refresh cycle, re-checked against the storefront, kept current.
- **historical** — frozen era snapshots, never re-harvested. They exist to hold the earlier wave of
  apps and their deletion record, so attrition can be measured rather than forgotten.

| corpus_id | kind | Apps | Lending scope | Adjacent | Out of scope | Harvested | Gone from Play |
|---|---|---|---|---|---|---|---|
| `IN` | live | 229 | 175 | 28 | 26 | 2026-09-21 | 0 |
| `LK` | live | 155 | 110 | 28 | 17 | 2026-09-20 | 0 |
| `IN_2020_2022` | historical | 725 | 692 | 31 | 2 | 2022-02-27 | 655 |
| `NG_2022` | historical | 126 | 100 | 26 | 0 | 2022-03-04 | 88 |

Headline counts on each page cover lending-scope apps only. Keyword harvesting pulls in noise
(payments, shopping, ledgers, foreign listings); those captures stay in the data and are listed
separately rather than silently dropped. Rules and per-id overrides live in `data/scope_rules.yaml`.

Sources: `IN_2020_2022` = `Datasets/loanapps-in/loanapps_dbhub_20220227.db` (byte-exact published
dbhub copy, sha256 in Drive `CHECKSUMS.txt`); `NG_2022` = `Datasets/loanappsdata_NG.db` (DStudio x CC
shared drive); `LK` and the 2026 India harvest = captured through the deployed GPlayAPI v2
(`https://gplayapiv2.fly.dev`, source `Projects/google-play-api`). Raw DBs stay out of git; harvests
under `data/harvests/` are in-repo.

## Pipeline

```
storefront ──harvest.py──▶ data/harvests/<CC>_<date>.db (SQLite)
                                   │
                   build_warehouse.py ▶ data/killerloanapps.duckdb (apps · permissions · corpora · deleted)
                                   │
     check_deletions.py ───────────▶ availability · deleted_log   (live vs gone, per storefront)
                                   │
                        score.py ──▶ scores (rubric v0.2, composite + band + flags)
                                   │
                    build_site.py ─▶ site/ (index · live + historical corpus pages · app pages · deletions · methodology)
```

`bash scripts/refresh.sh [LABEL]` runs the whole cycle (harvest live corpora → warehouse →
availability recheck → score → site → commit + push). `data/refresh-<date>.log` keeps the run's output.

**Refresh automation:** *Weekly Killerloanapps Predatory Loan App Tracker Refresh* — Mondays 06:30 IST,
reports to Discord `#policy-research` (new commit, per-corpus counts, newly recorded deletions,
top new apps by score, suspected new clone families, any failed step).**Refresh automation:** *Weekly Killerloanapps Predatory Loan App Tracker Refresh* — Mondays 06:30 IST,
reports to Discord `#policy-research` (new commit, per-corpus counts, newly recorded deletions,
top new apps by score, suspected new clone families, any failed step).

The refresh is **accumulating, not replacing**. Every harvest writes a dated snapshot; the
warehouse unions all of them (newest row wins), and any live app that is absent from the newest
snapshot is carried forward from the previous `data/apps.json` with `last_seen` +
`gone_from_store`. So an app that disappears from the store stays in the corpus as a recorded
deletion — `platform_removed` (+15) in the score and a `DELETED from Play` badge — instead of
vanishing along with its evidence. Raw snapshots are gitignored working files (the newest two per
country are kept; the accumulated record lives in `data/apps.json` and the warehouse).

## Score (rubric v0.2 — risk signals, not verdicts)

| Family | Weight | Evidence |
|---|---|---|
| I1 Brand/ASO abuse | 15 | package-name keyword stuffing (loan/cash/credit/rupee/naira segments) |
| I2 Metadata opacity | 25 | privacy policy missing or on free hosts (docs.google.com, sites.google.com…); no developer website |
| I3 Physical presence | 15 | legal entity / address / phone absent, or address inconsistent with the jurisdiction |
| I4 Cyber hygiene | 10 | listing stale >90 days, and >1 year, at harvest time |
| I5 Third-party supply chain | 15 | pending APK lane (data-safety JSON used as a cross-signal where present) |
| I6 Permission excess | 15 | dangerous permissions (contacts, SMS, call log, location, mic, camera) vs jurisdiction baseline |
| I7 Responsiveness | 5 | pending reviews-endpoint lane |

Adjustments applied after family scoring, each flagged in the output: `platform_removed` **+15** when
the listing is gone from its storefront. Bands: `0–24 low · 25–49 elevated · 50–74 high · 75+ severe`.
Families without evidence score `null` and the composite is marked `partial` (rescaled over available
weights) — the site says so on every affected page.

### What the scores currently show, and the caveat that matters

| corpus | low | elevated | high | severe |
|---|---|---|---|---|
| `IN` (live, 2026) | 172 | 3 | 0 | 0 |
| `LK` (live, 2026) | 91 | 19 | 0 | 0 |
| `IN_2020_2022` | 41 | 424 | 222 | 5 |
| `NG_2022` | 14 | 44 | 42 | 0 |

The 2026 live corpora score almost entirely `low` — not because the market is clean, but because
Google Play's post-2022 listing rules now force the disclosure fields I2 and I3 measure. Legal-entity
fields are populated for 99.6% of the live India corpus (0% of the 2020–22 corpus); a developer website
is present for 91.7% (44.4%). **A `low` band on a live app is not evidence of safe lending practice** —
harassment, collection abuse, fee stacking and data misuse do not appear in store metadata. Reading the
v0.2 score as "safe" misreads it; the rubric measures metadata opacity, and that baseline has moved.
This is why the APK lane (I5) and the tracing lane matter more than they did for the historical corpora.

## Deletion tracking

`scripts/check_deletions.py` re-checks every tracked app id against its own storefront
(`/api/apps/<id>?country=<cc>`), writing `availability` (jurisdiction, app_id, last_checked, status)
and appending `deleted_log` (first_missing, last_live, note). Re-runs preserve the original
`first_missing`; a listing that returns is recorded as live again. Historical ids are seeded from the
2020–22 corpus's own `loanapp_deletedapps` table, so `deleted_log` carries the full attrition record
(**1,055** entries: 743 recheck-absent + 312 corpus-era ids never in the scored set).

```bash
python3 scripts/check_deletions.py        # all corpora by default; pass "live" for live only
python3 scripts/score.py                  # applies platform_removed +15
python3 scripts/build_site.py             # GONE badges + deletions.html
```

State at the 2026-09-21 recheck — `IN_2020_2022` 655 gone / 70 live · `NG_2022` 88 gone / 29 live ·
`IN` 229 live · `LK` 155 live. The live corpora being fully present is the expected shape: they were
harvested days ago.

## Roadmap

- [x] Warehouse + rubric scorer + static site + GitHub Pages
- [x] Multi-jurisdiction deletion tracking (`availability`, `deleted_log`, `deletions.html`, GONE badges)
- [x] Corpora model: live vs frozen historical; scope rules; live India 2026 harvest
- [x] Refresh lane: `scripts/harvest.py` + `scripts/refresh.sh`, weekly automation
- [ ] APK lane at scale (`Skills/apkeep-fetch/` → MobSF / `Skills/fintech-apk-scanner`): I5 family, tracker/SDK graph, certificate reuse
- [ ] Tracing lane: shared-infrastructure OSINT (developer emails, co-hosted sites, entity graphs), WHOIS/DNS, cross-jurisdiction clone families
- [ ] Complaint-pack generator: per-app authority route, starting from the Sri Lanka map in `Datasets/loanapps-lk/notes/`

## Companion assets

- `CashlessConsumer/killerloanapps-lk` — Sri Lanka dataset repo (built for the Kavinda Welagedara request)
- `Datasets/loanapps-lk/` — LK DB, README, authority map, checksums
- `Datasets/loanapps-in/` — the four recovered India DBs + provenance and checksums
- `https://zo.pub/cashlessconsumer/loanapps-db` and `https://zo.pub/cashlessconsumer/loanapps-lk` — off-repo archives
