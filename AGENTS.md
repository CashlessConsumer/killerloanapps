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
- **Historical corpora are frozen**: `IN_2020_2022` and `NG_2022` are never re-harvested and never
  merged into a live corpus. They exist to hold the earlier wave and its deletion record.
- **Metadata opacity is not safety**: a live `low` band means the store metadata looks clean, not
  that the lender behaves. Never let site copy or a report imply the latter.
- **PII**: no reviewer names/avatars. App metadata only.
- **Static site, no build deps**: `site/` is plain HTML/CSS from `scripts/build_site.py`.
  Deploy via the GitHub Actions pages workflow (`upload-pages-artifact` from `site/`); CNAME stays
  `killerloanapps.cashlessconsumer.in`.

## Corpus model
`corpora` table: `corpus_id, label, short, kind (live|historical), country, harvested_on, seed_date,
description, source`. `jurisdiction` on `apps`/`scores` is the `corpus_id`. Page paths:
live → `jurisdiction/<id>.html`, historical → `historical/<id>-<span>.html` (see `page_path()`).

Adding a jurisdiction = add a row to `CORPORA` in `build_warehouse.py`, a keyword set in
`harvest.py`'s `TERMS`/`LANG` maps, a country code in `check_deletions.py`'s `CC`, and a
`LOCAL_HINT` entry in `score.py`.

## Scope rules
`data/scope_rules.yaml` classifies each app as `lending` (headline), `adjacent` (listed separately),
or `out_of_scope` (keyword noise: payments, shopping, ledgers, foreign listings). Headline counts,
bands and the index use `lending` only; adjacent and out-of-scope rows render in their own tables so
nothing is silently dropped. Add an id under the right list when a capture is clearly not a lending
product for that market, then re-run `score.py` + `build_site.py`.

## Pipeline order
`harvest.py` → `build_warehouse.py` → `check_deletions.py` → `score.py` → `build_site.py` → commit `site/`.
`bash scripts/refresh.sh [LABEL]` chains all of it (live corpora only) and pushes; log at
`data/refresh-<LABEL>.log`. Weekly automation runs it Mondays 06:30 IST and reports to Discord
`#policy-research` (id 1540886397622161458).

## Deletion tracking (v0.2)
`scripts/check_deletions.py` → storefront recheck per app (`availability` + `deleted_log`),
scored via `rubric.yaml` adjustments (`platform_removed` +15). Default scope is every corpus;
pass `live` for live corpora only, or a comma list of corpus ids. Historical ids are seeded from the
2020–22 corpus `loanapp_deletedapps` table (idempotent). Re-runs preserve the original `first_missing`.
Query: `duckdb data/killerloanapps.duckdb -c "SELECT jurisdiction,status,COUNT(*) FROM availability GROUP BY 1,2"`.

## Accumulated record (do not break this)
Live corpora accumulate. `build_warehouse.py` unions **every** snapshot matching
`data/harvests/<CC>_*.db` (oldest → newest, newest row wins) and then carries forward any live
app present in the previous `data/apps.json` but absent from all current snapshots, marking it
`gone_from_store` with its `last_seen`. `score.py` treats `gone_from_store` as the
`platform_removed` (+15) signal exactly like a storefront-confirmed deletion, and pages show it as
a deletion.

Consequences: an app that vanishes from Play is remembered instead of dropping out of the corpus;
`first_seen` / `last_seen` / `snapshots` on `apps` say when it was seen; `check_deletions.py` still
confirms deletions authoritatively against the storefront. `app_id` is deduplicated within a corpus
(earlier runs had duplicate rows that inflated app and permission counts — 1,226 apps is the true
unique total).

Raw snapshots are working files, gitignored; `refresh.sh` keeps the newest two per live country and
drops older ones (the accumulated record lives in `apps.json` + the warehouse). So a missing old
snapshot file is expected — never "fix" that by re-harvesting a fresh corpus over it.

`refresh.sh` reads `LIVE_CC` (default `in lk`) and honours `SKIP_HARVEST=1` to exercise the rest of
the cycle without a fresh harvest.

## Data provenance
| Corpus | Source | Kind |
|---|---|---|
| `IN` | `data/harvests/IN_2026-09-21.db` (GPlayAPI v2) | live, re-harvested |
| `LK` | `data/harvests/LK_2026-09-20.db` + `Datasets/loanapps-lk/` | live, re-harvested |
| `IN_2020_2022` | `Datasets/loanapps-in/loanapps_dbhub_20220227.db` | frozen historical (byte-exact dbhub copy) |
| `NG_2022` | `Datasets/loanappsdata_NG.db` | frozen historical (DStudio x CC shared drive) |

Raw 30–44 MB DBs stay out of git (Drive + zo.pub archives carry them, with `CHECKSUMS.txt`).

## Known findings worth not re-deriving
- 2026 live corpora score almost entirely `low`; legal-entity fields are populated for 99.6% of live
  India apps vs 0% of the 2020–22 corpus (developer website 91.7% vs 44.4%). Play's post-2022 rules
  moved the I2/I3 baseline, so v0.2 scores discriminate much less on recent data. The abuse signal has
  moved to practice (collections, fees, data misuse), which store metadata does not carry — hence the
  priority of the APK (I5) and tracing lanes.
- Clone families already visible in the live corpora: a CashGedara/CashMate/FreedomCash/CashMellon/
  SkyWallet/SmartCredit meta-app network, and a KREDITME/MyKredit/DrCash trio — inspect shared legal
  entity but do not assert common ownership without the tracing lane's evidence.
- The historical India corpus's attrition is the platform's strongest long-run signal: 655 of 725 gone.

## Related
- LK origin story + authority map: `Datasets/loanapps-lk/notes/` (Kavinda Welagedara request, 2026-09-19)
- GPlayAPI v2: `Projects/google-play-api/` (deployed at gplayapiv2.fly.dev)
- APK scanning lane: `Skills/fintech-apk-scanner/`, `Skills/apkeep-fetch/`
