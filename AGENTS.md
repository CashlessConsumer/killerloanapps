# killerloanapps — project conventions

## What this is
Multi-jurisdiction predatory loan-app tracker. Rubric = DeepStrat "Indicators for Detection of
Abusive Digital Lenders" (Nov 2022), archived at `docs/deepstrat-indicators-*.pdf`. Score is
transparent risk signalling, never an accusation; every page carries the disclaimer.

## Non-negotiables
- **Evidence traceability**: every number on a page comes from the warehouse; every score point
  maps to a rubric flag that names the field it came from. No vibes-based adjustments.
- **Rubric versioning**: change weights/signals → bump `version` in `rubric.yaml`, rescore,
  regenerate, and note the change in this file. Old scores must never silently mix with new.
- **Partial scores are visible**: when I5/I7 evidence is missing the composite is `partial` and
  pages say so. Never present a rescaled score as full.
- **Historical corpora are frozen.** `IN_2020_2022` and `NG_2022` must never be re-harvested or
  re-fetched — they are the attrition/era baseline. Only `kind='live'` corpora get harvested.
- **Metadata saturation is stated, not hidden.** Live-corpus scores are dominated by `low` because
  Play's 2022+ disclosure rules populate the fields I2/I3 measure. Never present a live-corpus
  `low` band as evidence that an app is safe.
- **PII**: no reviewer names/avatars. App metadata only.
- **Static site, no build deps**: `site/` is plain HTML/CSS from `scripts/build_site.py`.
  Deploy via the GitHub Actions pages workflow; CNAME stays `killerloanapps.cashlessconsumer.in`.

## Pipeline order
```
scripts/harvest.py --country in|lk --label YYYY-MM-DD   # live corpora only
scripts/build_warehouse.py                              # merge corpora -> data/killerloanapps.duckdb
scripts/check_deletions.py                              # availability + deleted_log (live-only: pass `live`)
scripts/score.py                                        # rubric, incl. platform_removed adjustment
scripts/build_site.py                                   # site/
git add -A && git commit && git push                    # GH Pages workflow deploys
```
All of it in one command: `bash scripts/refresh.sh [LABEL]`.

## Schemas (must agree across all four scripts)
- `corpora`: `corpus_id, label, short, kind (live|historical), country, harvested_on, seed_date, description, source`
- `apps`: keyed `(jurisdiction, app_id)`; `jurisdiction` = corpus_id (e.g. `IN`, `IN_2020_2022`)
- `scores`: `jurisdiction, app_id, i1..i7, composite, band, partial, flags, rubric_version, scored_on, scope`
- `availability`: `jurisdiction, app_id, last_checked, status (live|deleted|error)`
- `deleted_log`: `jurisdiction, app_id, first_missing, last_live, note`
- DuckDB note: `con.execute(...)` returns the connection, not a cursor — always `.fetchall()`
  before iterating (this bug silently disabled deletion seeding once).

## Corpora
| Corpus | Kind | Source | Notes |
|---|---|---|---|
| `IN` | live | `data/harvests/IN_*.db` | GPlayAPI v2 playbook run; re-harvested |
| `LK` | live | `data/harvests/LK_*.db` | GPlayAPI v2 playbook run; re-harvested |
| `IN_2020_2022` | historical | `Datasets/loanapps-in/loanapps_dbhub_20220227.db` | byte-exact dbhub copy, frozen |
| `NG_2022` | historical | `Datasets/loanappsdata_NG.db` | DStudio x CC shared drive original, frozen |

Raw originals stay out of git (30–44 MB); live harvests (`data/harvests/`, ~3.5 MB) are tracked.

## Scope rules
`data/scope_rules.yaml` splits every capture into `lending` (headline counts) / `adjacent` /
`out_of_scope`. Out-of-scope rows appear in a separate table on the corpus page. Add ids there when
a keyword capture is clearly not a lending product for that market — never by loosening the keyword
list in `harvest.py`, since the noise is itself evidence of what Play search returns.

## Freshness
- `bash scripts/refresh.sh` is the only supported refresh path.
- Weekly automation (Mondays 06:30 IST) runs it, verifies the four deployed URLs return 200, and
  posts a diff to Discord `#policy-research`. Idempotent: no changes → no commit → no deploy.
- Never run a refresh against historical corpora, and never `git push` from a partially built site.

## Related
- LK origin story + authority map: `Datasets/loanapps-lk/notes/2026-09-20-sl-authority-map.md`
- GPlayAPI v2: `Projects/google-play-api/` (deployed at gplayapiv2.fly.dev)
- APK scanning lane: `Skills/fintech-apk-scanner/`, `Skills/apkeep-fetch/`
