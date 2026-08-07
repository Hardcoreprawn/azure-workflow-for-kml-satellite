# User Journeys — Golden Paths by Persona

**Purpose:** For each of the three personas in
[PERSONA_DEEP_DIVE.md](PERSONA_DEEP_DIVE.md), define the single most
important journey — first landing to a completed, exportable analysis —
as a concrete, testable sequence of UI steps. Optimises for the same
three qualities every time: **fast** (few steps, no waiting on dead
ends), **clear** (one obvious next action at each step), and **low
cognitive load** (minimal decisions/fields before the user can act).

This is deliberately narrower than
[EUDR_USER_JOURNEYS.md](EUDR_USER_JOURNEYS.md), which is a full
jobs-to-be-done gap analysis across ten EUDR-specific jobs (J1–J10).
This doc covers the one journey every persona must complete
successfully before anything else matters: **get from "I just arrived"
to "I have evidence I trust."**

## How this is verified

`scripts/ux_journeys.py`'s `PERSONA_JOURNEYS` drives each golden path
against a live `make dev-all` stack (`make ux-smoke`), using local dev's
auth bypass to reach the full dashboard without a real CIAM sign-in. It
checks the part of the journey where friction is most costly: empty
state → one click → ready-to-submit form, with immediate feedback and
no widget left stuck on a placeholder. `tests/test_ux_journeys.py`'s
`TestPersonaJourneyDefinitions` checks the journey definitions
themselves stay structurally sound (absolute paths, valid anchors, one
journey per persona).

Driving a full pipeline run (upload → parse → acquire → fulfil →
enrich) needs real network access to imagery providers and takes
minutes — that's covered separately by `scripts/e2e_local.py` (stubbed
providers, fast, no network) and `scripts/pipeline_smoke.py` (real
providers, deployed environments only), not by the browser-driven UX
checks here.

---

## Persona 1 — Conservation Analyst

**Entry point:** `/app/` (the general-purpose conservation/agriculture
workspace — see note below on why these two personas currently share
one surface).

**Job to be done:** Get timestamped, defensible evidence of vegetation
change in a protected area, fast enough to act on it this week.

| # | Step | Page state | Low-cognitive-load target |
|---|------|-----------|---------------------------|
| 1 | Land on `/app/` for the first time | "Welcome to Your Workspace" empty state, ONE primary CTA ("Start Your First Analysis") | Zero decisions — one clear action, not a menu of options |
| 2 | Click the CTA | Scrolls straight to the New Analysis card (`#app-analysis-card`) | One click, no intermediate page |
| 3 | Choose input method | "Upload KML" tab active by default; "Paste Coordinates" available but not forced | The common case (already has a KML from Google Earth Pro) needs zero extra clicks |
| 4 | Upload a file | Preflight panel updates immediately: feature count, area spread, quota impact | Feedback within ~1 second, before queueing — no guessing whether it worked |
| 5 | Confirm & queue | Progress checklist appears (parse → acquire → fulfil → enrich) | Explicit named phases, not a spinner — sets expectations for wait time |
| 6 | Review evidence | NDVI time series, land cover layers, AI narrative, per-parcel flags | Evidence framed in plain language, not raw index values |
| 7 | Export | PDF/GeoJSON/CSV export options | One click per format, no configuration step |

**Known gap (tracked, not a nav/UX defect):** no scheduled
re-monitoring yet — see `docs/EUDR_USER_JOURNEYS.md` J7 and issue #310
history. This journey covers the one-shot case; monitoring is a
separate job.

---

## Persona 2 — Agricultural Advisor

**Entry point:** `/app/` — same surface as the Conservation Analyst
today. Per `PERSONA_DEEP_DIVE.md`'s fit analysis, this persona's real
job is **batch** (50–500 parcels, not one at a time) with per-parcel
CSV output and crop-specific indices. The single-parcel golden path
below is necessary but not sufficient for this persona; batch handling
is tracked as a product gap, not a UX inconsistency, so it isn't
duplicated here.

**Job to be done:** Assess crop health/damage across many parcels
without driving to every field.

Steps 1–7 are identical to the Conservation Analyst journey above (same
surface, same widgets, same low-cognitive-load bar). The persona-specific
follow-up work (batch upload, per-parcel CSV export, EVI/SAVI indices)
is out of scope for this journey doc — see `docs/PERSONA_DEEP_DIVE.md`
§1.2 and §2.2 for that gap analysis.

---

## Persona 3 — ESG / EUDR Compliance Officer

**Entry point:** `/eudr/` (a dedicated, regulation-framed experience —
distinct from the generic `/app/` workspace).

**Job to be done:** Prove a supply-chain plot is deforestation-free
since 31 December 2020, in a format an auditor will accept.

| # | Step | Page state | Low-cognitive-load target |
|---|------|-----------|---------------------------|
| 1 | Land on `/eudr/` for the first time | Regulation context bar (EU 2023/1115, cutoff date) always visible; "Welcome to EUDR Due Diligence" empty state with ONE primary CTA ("Start Your First Assessment") | The regulation reference is ambient, not a step the user has to hunt for |
| 2 | Read the quick checklist | 5-item list: prepare data → upload/paste → queue → review evidence → export | Sets expectations before any action — no surprises mid-journey |
| 3 | Click the CTA | Scrolls to the New Due Diligence card (`#app-analysis-card`) | One click |
| 4 | Choose input method | "Upload KML" tab active by default; "Paste Coordinates" (name, lat, lon) available for suppliers without a KML | Covers the two most common real-world data formats without a mode-selection decision up front |
| 5 | Upload/paste | Preflight panel: features, parcels, spread, quota impact, plus an explicit "not a legal compliance certificate" framing note | Sets the right expectation about what the tool is (evidence support, not a legal guarantee) |
| 6 | Confirm & queue | Named pipeline phases, imagery explicitly restricted to post-Dec-2020 per the regulation | Reinforces the regulation constraint at the moment it matters |
| 7 | Review per-parcel determination | ✓ Compliant / ⚠ Flagged, confidence score, evidence breakdown, AI narrative | Plain-language interpretation before raw data |
| 8 | Export EUDR PDF | Audit-grade PDF with per-parcel determination | One click, no report configuration |

**Known gaps (tracked separately, not nav/UX defects):** flagged-parcel
investigation workflow, portfolio dashboard for 200+ parcels, aggregated
compliance reporting — see `docs/EUDR_USER_JOURNEYS.md` J3/J5/J7 for the
full gap analysis and priority ranking. Those are scale/depth gaps for
the *ongoing* compliance job, not friction in the *first* journey this
doc covers.

---

## Regression history on this journey

- **#1255** — hero Plan/Runs/Mode cards stuck on "Loading…" forever in
  local dev (fixed).
- **#1256** — `/account/` permanently gated, unreachable from the
  product nav (fixed).
- **#1260 / #1261** — inconsistent nav across every page, no way to
  reach Account Settings from the product, and the EUDR PARCELS usage
  pill stuck on "Loading usage…" because the local-dev bypass path
  never fetched it (all fixed).

Each of these was a case of the same underlying pattern: a widget or
guard written for the "real signed-in user" case that silently broke
for the "auth disabled" case. `scripts/ux_journeys.py`'s persona
journeys now assert no widget is left on a generic loading placeholder,
specifically to catch this class of regression before it ships again.
