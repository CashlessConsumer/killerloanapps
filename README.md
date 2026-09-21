# killerloanapps — multi-jurisdiction predatory loan-app tracker

Platform for tracking predatory / abusive digital-lending apps across jurisdictions, scored with the
**DeepStrat "Indicators for Detection of Abusive Digital Lenders" (Nov 2022) seven-family rubric**
(archived at `docs/deepstrat-indicators-for-detection-of-abusive-digital-lenders.pdf`).

**Live:** https://killerloanapps.cashlessconsumer.in — until the Netlify CNAME is set:
https://cashlessconsumer.github.io/killerloanapps/

Score is transparent risk signalling from public store metadata, never an accusation. Every page
carries the disclaimer.

## Corpora

Two corpora are **live** (re-harvested on the refresh cycle, so new apps and new deletions are
picked up) and two are **historical** (frozen snapshots, never re-harvested — they are the attrition
record).

| Corpus | Kind | Apps | Lending-scope | Window | Harvest |
|---|---|---|---|---|---|
| `IN` | live | 229 | 175 | 2026-09-21 | GPlayAPI v2 playbook run |
| `LK` | live | 155 | 110 | 2026-09-20 | GPlayAPI v2 playbook run |
| `IN_2020_2022` | historical | 725 | 692 | Dec 2020 – Feb 2022 | recovered dbhub copy (byte-exact) |
| `NG_2022` | historical | 126 | 114 | Mar 2022 | DStudio x CC shared drive |

1,235 apps, 2,232 app pages, 7 named clone families. Warehouse:
`data/killerloanapps.duckdb` (`apps`, `permissions`, `deleted`, `scores`, `availability`,
`deleted_log`, `corpora`). JSON dump: `data/apps.json`. Site: `site/` (plain static, no build deps).

Raw harvested DBs live in `data/harvests/` (tracked: IN + LK, 3.5 MB). The 2020-22 originals stay
out of git (30–44 MB) and live in Drive + zo.pub (`Datasets/loanapps-in/`, `Datasets/loanapps-lk/`).

## Scope rules

Play keyword search returns plenty that is not a lending product. `data/scope_rules.yaml` sorts each
capture into `lending` (headline counts), `adjacent`, or `out_of_scope` (payments, shopping,
ledgers, foreign listings). Out-of-scope rows are shown separately on each corpus page, never in the
headline. Add ids there when a capture is clearly not a lending product for that market.

## Pipeline

```
data/harvests/*.db ──build_warehouse.py──▶ killerloanapps.duckdb ──score.py──▶ scores (rubric v0.2)
                                 └──check_deletions.py──▶ availability/deleted_log
                                 └──build_site.py──▶ site/
```

Entry point for the whole cycle:

```bash
bash scripts/refresh.sh            # harvest live corpora → warehouse → recheck → score → site → push
```

- `scripts/harvest.py` — `--country in|lk --label YYYY-MM-DD`; detail + permissions endpoints, same
  columns as the original corpora incl. legal-entity and data-safety fields.
- `scripts/build_warehouse.py` — merge corpora, normalise schema, carry provenance per row.
- `scripts/check_deletions.py` — storefront recheck per app id (`/api/apps/<id>?country=<cc>`);
  writes `availability`, appends `deleted_log` (first-seen date + evidence note), never overwrites
  an existing `first_missing`. Live-only via `live`, one corpus via its id, all by default.
- `scripts/score.py` — 7 families, composite 0–100, band, per-family flags.
- `scripts/build_site.py` — regenerate the whole static site.

Automation: **Weekly Killerloanapps Predatory Loan App Tracker Refresh** (Mondays 06:30 IST) runs
`refresh.sh`, verifies the deployed pages, and posts a terse diff to Discord `#policy-research`.

## Rubric (v0.2 — risk signals, not verdicts)

| Family | Weight | Evidence |
|---|---|---|
| I1 Brand/ASO abuse | 15 | package-name keyword stuffing (loan/cash/credit segments) |
| I2 Metadata opacity | 25 | privacy policy missing or on Google/static hosts; no developer website |
| I3 Physical presence | 15 | no legal entity/contact; non-local entity; missing phone |
| I4 Cyber hygiene | 10 | app stale >90 days (and >1 year) at harvest |
| I5 3rd-party supply chain | 15 | APK lane pending (data-safety JSON cross-signal where present) |
| I6 Permission excess | 15 | dangerous permissions vs jurisdiction baseline |
| I7 Responsiveness | 5 | reviews lane pending |

Bands: `0–24 low · 25–49 elevated · 50–74 high · 75+ severe`. When I5/I7 evidence is missing the
composite is `partial` (rescaled over available weights) and every page says so.
v0.2 adds `adjustments.platform_removed: +15` for apps gone from their own storefront.

## Result to be honest about: metadata signals have saturated

| Corpus | apps | has legal entity | has privacy policy | has dev website |
|---|---|---|---|---|
| IN (2026) | 229 | 99.6% | 100% | 91.7% |
| LK (2026) | 155 | 100% | 100% | 83.9% |
| IN_2020_2022 | 725 | 0% | 99.9% | 44.4% |
| NG_2022 | 126 | 0% | 100% | 45.2% |

Store-metadata scoring discriminates strongly on the 2020-22 corpora (IN: 424 elevated, 222 high,
5 severe) and almost not at all on the 2026 harvests (IN: 172 low, 3 elevated). Two reasons, and
they need separating:

1. **Regime change.** Play now requires legal-entity disclosure and a privacy policy, so the fields
   I2/I3 lean on are populated for effectively every 2026 listing. The same list in 2020-22 shows
   0% legal entity and ~45% website presence.
2. **Capture artefact.** The 2020-22 harvest predates those Play requirements, so I3 flags
   `era_no_legal_fields` rather than measuring concealment. Cross-era I3 comparisons are not like
   for like.

The honest reading: **metadata-only scoring cannot discriminate in the 2026 ecosystem.** What
survives is not obviously cleaner — the abuse surface (collections harassment, hidden fees,
off-metadata SDK data access) does not appear in store metadata. That is why the discriminative
lanes still to build are I5 (APK/SDK) and I7 (reviews/complaints), and why live-corpus bands should
not be read as a clean bill of health.

## Deletion tracking

Availability state after the 2026-09-21 sweep (all corpora):

| Corpus | live | deleted |
|---|---|---|
| IN (2026) | 229 | 0 |
| LK (2026) | 155 | 0 |
| IN_2020_2022 | 70 | 655 |
| NG_2022 | 29 | 88 |

755 of 1,235 tracked apps are gone from their storefront; `deleted_log` holds 1,056 entries
(755 rechecked-absent + 301 corpus-era ids never in the scored set). Deletion is one of the strongest
end-state signals: either the platform enforced against abuse, or the operator burned the listing.
Either way the snapshot is the record. See `site/deletions.html`.

## Roadmap

- [x] Warehouse + rubric scorer + static site + GH Pages
- [x] Multi-jurisdiction deletion tracking (`availability`, `deleted_log`, `deletions.html`, GONE badges)
- [x] Live vs historical corpus split + keyword-noise scope rules
- [x] Scheduled refresh lane (`refresh.sh`, weekly Monday 06:30 IST automation)
- [ ] APK lane at scale (`Skills/apkeep-fetch/` + MobSF → I5 family, tracker/SDK graph)
- [ ] Reviews lane (I7) + complaint-corpus ingestion
- [ ] Tracing lane — shared-infrastructure OSINT (dev emails, shared hosts), WHOIS/DNS, cross-jurisdiction clone families
- [ ] Complaint-pack generator (per-app authority route; SL map in `Datasets/loanapps-lk/notes/`)

## Companion assets

- `CashlessConsumer/killerloanapps-lk` — LK dataset repo (Sri Lanka; sent to the Kavinda request)
- `Datasets/loanapps-lk/` — LK DB, README, authority map, checksums
- `Datasets/loanapps-in/` — recovered India DBs (4 versions) + provenance + builder code
- `Projects/google-play-api/` — GPlayAPI v2, deployed at `gplayapiv2.fly.dev`
