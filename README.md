# killerloanapps — multi-jurisdiction predatory loan-app tracker

Platform for tracking predatory / abusive digital-lending apps across jurisdictions, using the
**DeepStrat "Indicators for Detection of Abusive Digital Lenders" (Nov 2022) seven-family rubric**
as the scoring framework. `docs/deepstrat-indicators-for-detection-of-abusive-digital-lenders.pdf`
is the archived source of the rubric.

**Live:** https://killerloanapps.cashlessconsumer.in (until DNS CNAME is set: https://cashlessconsumer.github.io/killerloanapps/)

## Current corpora

| Jur | Apps | Corpus window | Source | Notes |
|---|---|---|---|---|
| IN | 725 | Dec 2020 – Feb 2022 | `Datasets/loanapps-in/loanapps_dbhub_20220227.db` (byte-exact dbhub published copy) | historical; 339 deleted apps in corpus |
| NG | 126 | Mar 2022 | `Datasets/loanappsdata_NG.db` | historical |
| LK | 155 | 2026-09-20 harvest | `Datasets/loanapps-lk/loanappsdata_LK.db` | live, has legal-entity + datasafety fields |

Warehouse: `data/killerloanapps.duckdb` (tables: `apps`, `permissions`, `deleted`, `scores`).
JSON dump: `data/apps.json`. Site: `site/` (plain static, no build deps).

## Pipeline

```
corpora (SQLite) ──build_warehouse.py──▶ killerloanapps.duckdb ──score.py──▶ scores (rubric v0.1)
                                                        └─build_site.py──▶ site/ (1006 app pages)
```

- `scripts/build_warehouse.py` — merge corpora, normalize schema, provenance per row.
- `scripts/score.py` — score every app on the 7 DeepStrat families (weights in `rubric.yaml`),
  composite 0–100 + band (low/elevated/high/severe) + per-family evidence flags. Families whose
  evidence is unavailable (APK supply-chain I5, review-response I7) score `null` and the composite
  is flagged `partial` (rescaled over available weights — every page shows this).
- `scripts/build_site.py` — regenerate the whole static site from the warehouse.

Run order: `build_warehouse.py` → `score.py` → `build_site.py`.

## Score v0.1 (experimental — risk signals, not verdicts)

Families & weights (from `rubric.yaml`, derived from the DeepStrat report §Methodology):

| Family | Weight | v0.1 evidence |
|---|---|---|
| I1 Brand/ASO abuse | 15 | package-name keyword stuffing (loan/cash/credit segments) |
| I2 Metadata opacity | 25 | privacy policy missing or hosted on docs.google.com/sites.google.com/static hosts; no dev website |
| I3 Physical presence | 15 | legal entity fields absent / non-local entity (v0.1: absence weighting only) |
| I4 Cyber hygiene | 10 | app stale >90 days at harvest |
| I5 3rd-party supply chain | 15 | pending APK-scan lane (datasafety-JSON cross-signal only where present) |
| I6 Permission excess | 15 | dangerous permissions vs jurisdiction baseline (contacts/SMS/call-log/location/mic/camera) |
| I7 Responsiveness | 5 | pending reviews-endpoint lane |

Bands: `0–24 low · 25–49 elevated · 50–74 high · 75+ severe`.

**Disclaimer:** scores are automated risk signals for researchers and journalists, not
adjudications. Nothing here accuses any developer of a crime; dispute via the methodology page.

## Availability tracking (v0.2)

`scripts/check_deletions.py` re-checks every app_id against its own storefront via gplayapiv2
(`/api/apps/<id>?country=<cc>`), writing an `availability` row per app and appending to
`deleted_log` (`first_missing` + evidence note). A listing vanishing is one of the strongest
end-state signals: either the platform enforced against abuse, or the operator burned the listing.

```bash
python3 scripts/check_deletions.py   # 997 apps, ~0.5s each
python3 scripts/score.py             # applies platform_removed +15 (rubric v0.2)
python3 scripts/build_site.py        # refreshes GONE badges + deletions.html
```

State at the 2026-09-21 recheck: **IN 655 gone / 70 live · NG 88 gone / 29 live · LK 0 gone / 155 live**
— 743 of 997 tracked apps are gone, plus 312 corpus-era deletion records outside the tracked set kept as history.

## Roadmap

- [x] Phase 1: warehouse + rubric scorer + static site + GH Pages
- [x] Phase 1.1: multi-jurisdiction deletion tracking (availability recheck + `deletions.html` + GONE badges)
- [x] v0.2: availability/deletion tracking across IN/NG/LK (743 gone of 997)
- [ ] Phase 2: refresh lane (GPlayAPI v2 at gplayapiv2.fly.dev, scheduled harvests per jurisdiction)
- [ ] Phase 3: APK lane at scale (`Skills/apkeep-fetch/` + MobSF/fintech-apk-scanner → I5 family + tracker/SDK graph)
- [ ] Phase 4: tracing lane — shared-infrastructure OSINT (dev emails, sites on same hosts, entity graphs), WHOIS/DNS, cross-jurisdiction clone families
- [ ] Complaint-pack generator (per-app authority route, starting with SL map in `Datasets/loanapps-lk/notes/`)

## Deletion tracking (rubric v0.2)

`scripts/check_deletions.py` re-checks every tracked app id against its own storefront
(`currency`/national storefront per jurisdiction), records `live`/`deleted` into the
`availability` table and appends one `deleted_log` row per missing app (first-seen date,
note). Deletion adds the `platform_removed` adjustment (**+15**, toggleable in
`rubric.yaml` → `adjustments`) and a `DELETED from Play` badge on jurisdiction pages.

```
python3 scripts/check_deletions.py      # recheck all jurisdictions, writes availability + deleted_log
python3 scripts/score.py                # re-score (applies platform_removed)
python3 scripts/build_site.py           # regenerate site incl. deletions.html
```

Latest run 2026-09-21: **743 of 997 tracked apps gone** (IN 655/725 · NG 88/117 · LK 0/155);
1,055 log entries = 743 rechecked-absent + 312 corpus-era ids never in the scored set.

## Companion assets

- `CashlessConsumer/killerloanapps-lk` — LK dataset repo (Sri Lanka, sent to the Kavinda request)
- `Datasets/loanapps-lk/` — LK DB + README + authority map + checksums
- `Datasets/loanapps-in/` — recovered India DBs (4 versions) + provenance
