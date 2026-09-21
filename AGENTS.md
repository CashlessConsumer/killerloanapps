# killerloanapps — project conventions

## What this is
Multi-jurisdiction predatory loan-app tracker. Rubric = DeepStrat "Indicators for Detection of
Abusive Digital Lenders" (Nov 2022), archived at `docs/deepstrat-indicators-*.pdf`. Score is
transparent risk signaling, never an accusation; every page carries the disclaimer.

## Non-negotiables
- **Evidence traceability**: every number on a page comes from the warehouse; every score point
  maps to a rubric flag that names the field it came from. No vibes-based adjustments.
- **Rubric versioning**: change weights/signals → bump `version` in `rubric.yaml`, rescore,
  regenerate, and note the change in this file. Old scores must never silently mix with new.
- **Partial scores are visible**: when I5/I7 evidence is missing the composite is `partial` and
  pages say so. Never present a rescaled score as full.
- **PII**: no reviewer names/avatars. App metadata only.
- **Static site, no build deps**: `site/` is plain HTML/CSS from `scripts/build_site.py`.
  Deploy via the GitHub Actions pages workflow; CNAME stays `killerloanapps.cashlessconsumer.in`.

## Pipeline order
`build_warehouse.py` → `score.py` → `build_site.py` → commit `site/`.

## Data provenance
| Corpus | Source file (outside repo) | Status |
|---|---|---|
| IN | `Datasets/loanapps-in/loanapps_dbhub_20220227.db` | published dbhub copy, byte-exact (sha in Drive CHECKSUMS) |
| NG | `Datasets/loanappsdata_NG.db` | DStudio x CC shared drive original |
| LK | `Datasets/loanapps-lk/loanappsdata_LK.db` | harvested 2026-09-20 via gplayapiv2.fly.dev |

Raw DBs stay out of git (30–44 MB binaries live in Drive + zo.pub). Repo carries
`data/apps.json` + the built `site/`.

## Refresh (Phase 2, not wired yet)
Harvest via `https://gplayapiv2.fly.dev/api/apps/?country=<cc>&q=<term>` detail+permissions
endpoints, same columns as LK; then rerun pipeline. Keep old harvests as separate corpus rows
(`harvested_on` distinguishes) — history is the point.

## Related
- LK origin story + authority map: `Datasets/loanapps-lk/` (Kavinda Welagedara request, 2026-09-19)
- GPlayAPI v2: `Projects/google-play-api/` (deployed at gplayapiv2.fly.dev)
- APK scanning lane: `Skills/fintech-apk-scanner/`, `Skills/apkeep-fetch/`

## Availability / deletion tracking (v0.2)
- `scripts/check_deletions.py` — per-app live check via `/api/apps/<id>?country=<cc>`; writes `availability`
  (jurisdiction, app_id, last_checked, status) and appends `deleted_log` (first_missing, note). Re-runs keep the
  original `first_missing` for apps already gone.
- `rubric.yaml` v0.2 adds `adjustments.platform_removed: +15` plus the `platform_removed` signal.
- Site: `GONE` badge on app pages, "N of M apps gone" line per jurisdiction page, `deletions.html` log with evidence source.
- Query: `duckdb data/killerloanapps.duckdb -c "SELECT jurisdiction,status,COUNT(*) FROM availability GROUP BY 1,2"`
- 2026-09-21 recheck: IN 655/725 gone · NG 88/117 gone · LK 0/155 gone.
