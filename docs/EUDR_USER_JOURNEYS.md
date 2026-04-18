# EUDR User Journeys — Gap Analysis & Jobs Framework

**Purpose:** Map every job an EUDR compliance officer needs to do, assess
what Canopex delivers today, and identify feature gaps, QoL gaps, and
missing journey steps.

**Primary persona:** ESG / Supply-Chain Compliance officer at a commodity
importer (50–5,000 sourcing plots). Secondary: EUDR audit consultancy
doing assessments on behalf of importers.

Last updated: 2026-04-18

---

## The Regulation in Brief

EUDR (Regulation 2023/1115) requires operators placing cattle, cocoa,
coffee, oil palm, rubber, soy, or wood on the EU market to:

1. **Collect geolocation data** for all plots where the commodity was
   produced (point for <4 ha, polygon for ≥4 ha).
2. **Demonstrate no deforestation** occurred on those plots after
   31 December 2020.
3. **File a due diligence statement** in the EU Information System before
   the commodity enters the EU market.
4. **Retain records** for 5 years for potential audit/inspection.

Enforcement: large operators from 30 December 2025; SMEs from 30 June
2026. Fines up to 4% of EU-wide annual turnover.

---

## Jobs-to-be-Done Framework

Every job below is something a compliance officer **must** do around EUDR
reporting. For each, we assess: does Canopex help today? Could it? Should
it?

### J1 — Understand What's Required

| Aspect | Detail |
| ------ | ------ |
| **Job** | "I need to understand what EUDR requires of my company, which commodities and suppliers are in scope, and what evidence I need." |
| **Current state** | Officer reads the regulation, attends webinars, hires consultants. |
| **Canopex today** | ✅ Content cluster: `/docs/eudr-faq.html`, `/docs/eudr-methodology.html`, `/docs/eudr-supplier-guide.html`, `/docs/eudr-glossary.html`, `/docs/eudr-data-sources.html`. These explain the regulation, the evidence standard, and what satellite analysis can prove. |
| **Gap** | None critical. Could add a self-assessment checklist ("Is my company in scope? → Which commodities? → How many suppliers?") but this is marketing content, not product. |
| **Priority** | Low — content exists and is good. |

### J2 — Collect Geolocation Data from Suppliers

| Aspect | Detail |
| ------ | ------ |
| **Job** | "I need to get coordinates or polygon boundaries from every supplier in my chain — often smallholders in Brazil, Indonesia, Côte d'Ivoire who don't use GIS tools." |
| **Current state** | Compliance teams send Excel templates to suppliers asking for coordinates. Suppliers provide GPS points, hand-drawn maps, or nothing. Data arrives in inconsistent formats: decimal degrees, DMS, UTM, CSV, KML, shapefiles. |
| **Canopex today** | ✅ KML/KMZ upload. ✅ Coordinate-to-polygon converter (JSON API: lat/lon points → buffered KML). ✅ Preflight validator shows parcel count, area, warnings. |
| **Gap 1** | 🔴 **No CSV upload in the frontend.** The `/api/convert-coordinates` endpoint exists but is API-only. A compliance officer who receives an Excel/CSV with columns `supplier, lat, lon, area_ha` cannot paste or upload that directly in the UI. They'd have to convert to KML externally first. |
| **Gap 2** | 🟡 **No coordinate format flexibility.** Suppliers may provide DMS (e.g. `4°35'12"S, 39°17'45"E`) or UTM. The converter only accepts decimal degrees. |
| **Gap 3** | 🟡 **No template for suppliers.** We could provide a downloadable Excel/CSV template ("give this to your supplier, they fill in their plots, you upload it here") that standardizes the data collection step. |
| **Gap 4** | 🟡 **No shapefile support.** Larger suppliers or intermediaries may provide shapefiles or GeoJSON instead of KML. We only accept KML/KMZ. |
| **Priority** | Gap 1 is HIGH — it's the most common real-world data format for EUDR. Gap 2-4 are MEDIUM. |

### J3 — Screen / Triage Suppliers by Risk

| Aspect | Detail |
| ------ | -------- |
| **Job** | "I have 500 suppliers. I need to prioritize: which ones are in high-risk regions? Which commodities are highest risk? Where should I spend my assessment budget first?" |
| **Current state** | Manual — officer checks supplier locations against EU country-risk benchmarking list. High-risk countries (Brazil, Indonesia, DRC) get assessed first. |
| **Canopex today** | ❌ No supplier/portfolio management. No risk triage. Each assessment is independent — there's no way to see "I have 500 suppliers, 200 are assessed, 300 are pending, 15 flagged deforestation risk." |
| **Gap 1** | 🔴 **No supplier portfolio view.** No dashboard showing all suppliers/parcels with their assessment status. This is the most obvious missing workflow for anyone with more than 10 parcels. |
| **Gap 2** | 🟡 **No country-risk integration.** The EU publishes a country-risk benchmarking list (standard/high risk). Parcels in high-risk countries require enhanced due diligence. We could auto-flag parcels in high-risk countries. |
| **Gap 3** | 🟡 **No commodity tracking.** The EUDR requires linking parcels to specific commodities. Our system doesn't track which commodity a parcel produces. |
| **Priority** | Gap 1 is HIGH — it's the single biggest missing workflow. Gaps 2-3 are MEDIUM. |

### J4 — Run Satellite Assessment

| Aspect | Detail |
| ------ | ------ |
| **Job** | "For each supplier plot, I need satellite evidence showing whether deforestation occurred after Dec 2020." |
| **Current state** | Hire a consultancy ($10K–$50K, 4–8 weeks), use GFW Pro (enterprise-only, account request), or do it manually in QGIS/GEE (requires GIS expertise). |
| **Canopex today** | ✅ Upload KML → pipeline runs automatically → multi-source evidence: Sentinel-2 NDVI time series, Landsat historical baseline (2013+), ESA WorldCover, IO Annual LULC, ALOS Forest/Non-Forest, FIRMS fire, WDPA protected areas, Open-Meteo weather. ✅ Post-2020 date filtering for EUDR mode. ✅ Per-parcel deforestation-free determination (algorithmic). ✅ Progressive delivery — see results as they arrive. ✅ Pipeline progress tracker in UI. |
| **Gap 1** | 🟡 **No bulk/batch upload.** For 100+ parcels, the user must upload one KML at a time or put all parcels in a single KML. No way to upload a folder of KMLs, or a CSV with 500 coordinates, and have them all assessed in one operation. (Batch ops moved to Stage 4.1 #588.) |
| **Gap 2** | 🟢 **No scheduled re-assessment.** User must manually re-upload to check for changes. Monitoring/alerts (Stage 3.1 #310 — already implemented) could auto-re-run assessments monthly. |
| **Gap 3** | 🟢 **Assessment results are per-run, not per-parcel over time.** If I assess the same parcel in January and April, there's no way to see the history of that specific parcel's assessments side by side. |
| **Priority** | Gap 1 is MEDIUM (existing multi-polygon KML support covers many cases). Gaps 2-3 are LOW (future retention features). |

### J5 — Review Evidence & Make Determination

| Aspect | Detail |
| ------ | ------ |
| **Job** | "I need to review the satellite evidence and decide: is this plot deforestation-free? If yes, I can include it in my due diligence statement. If no, I must exclude the supplier or investigate further." |
| **Current state** | Manual review of satellite imagery, NDVI charts, land-cover maps. Often done by a consultant who writes a report. |
| **Canopex today** | ✅ Per-parcel algorithmic determination (deforestation_free: true/false, confidence: high/medium/low). ✅ Evidence summary with flags explaining why a parcel failed. ✅ NDVI time series visualization. ✅ AI narrative analysis. ✅ Weather correlation (distinguishing drought from deforestation). ✅ Multi-source corroboration (WorldCover, IO LULC, ALOS radar, Landsat, FIRMS fire). |
| **Gap 1** | 🔴 **No "investigate further" workflow for flagged parcels.** When a parcel is flagged as potentially deforested, the officer needs to: (a) zoom in on the specific area of concern, (b) compare before/after imagery, (c) add notes/annotations, (d) make a human determination (override the algorithm if they have local knowledge), (e) record their reasoning for audit purposes. None of this exists. |
| **Gap 2** | 🟡 **No before/after comparison view.** The evidence surface shows NDVI over time and imagery tiles, but there's no side-by-side or slider view of "here's the parcel in 2019, here's the parcel in 2024" for visual inspection. |
| **Gap 3** | 🟡 **No annotation/notes per parcel.** The officer can't attach comments like "Seasonal clearing — farmer confirmed replanting schedule — acceptable." These notes are critical for audit defense. |
| **Gap 4** | 🟡 **No human override of algorithmic determination.** If the algorithm flags a parcel but the officer has additional context (e.g., it's replanting after planned harvest, not deforestation), there's no way to mark it as "compliant with explanation" and have that override recorded in the audit trail. |
| **Priority** | Gap 1 is HIGH — this is the critical decision point. Gaps 2-4 are MEDIUM and support Gap 1. |

### J6 — Export Audit-Grade Evidence

| Aspect | Detail |
| ------ | ------ |
| **Job** | "I need to export the evidence in a format I can attach to our due diligence statement, show to auditors, or file with the EU Information System." |
| **Current state** | Screenshots from GFW, manual GIS exports, consultant PDF reports. |
| **Canopex today** | ✅ EUDR-specific exports: `eudr-pdf` (audit-grade PDF with per-parcel determination), `eudr-geojson` (machine-readable), `eudr-csv` (tabular). ✅ General exports: `pdf`, `geojson`, `csv`, `csv-bulk`. ✅ Per-parcel assessment sections in the PDF. ✅ Scene provenance (scene IDs for reproducibility). |
| **Gap 1** | 🟡 **No imagery in the PDF.** The audit PDF contains text, NDVI stats, and determination results but not the actual satellite imagery tiles. An auditor seeing "NDVI declined 35% in Q2 2023" wants to see the before/after image. (Issue #647 exists for this.) |
| **Gap 2** | 🟡 **No aggregated compliance summary report.** If I've assessed 200 parcels across 5 runs, there's no single report that says "180 compliant, 15 flagged, 5 failed." Each run produces its own report. |
| **Gap 3** | 🟢 **No formal due diligence statement template.** The EUDR requires a specific "due diligence statement" format for submission to the EU Information System. This is distinct from the audit PDF — it's a formal declaration document. (The EU IS isn't fully operational yet, so this is forward-looking.) |
| **Priority** | Gap 1 is MEDIUM (already tracked as #647). Gap 2 is MEDIUM. Gap 3 is LOW (blocked on EU IS). |

### J7 — Manage Ongoing Compliance

| Aspect | Detail |
| ------ | ------ |
| **Job** | "Compliance isn't one-time. I need to re-verify parcels periodically, track new suppliers entering my chain, and maintain an up-to-date compliance posture." |
| **Current state** | Spreadsheets tracking which suppliers were assessed when, manual calendar reminders to re-assess, scrambling before audit dates. |
| **Canopex today** | ✅ History panel showing all previous runs. ✅ Can resume/reopen any previous run. |
| **Gap 1** | 🔴 **No compliance dashboard.** No single view showing: total parcels assessed, % compliant, last assessment date per parcel, parcels due for re-assessment, parcels with alerts since last check. |
| **Gap 2** | 🟡 **No scheduled re-monitoring for EUDR.** Monitoring/alerts exist (#310) but aren't wired into the EUDR workflow. The officer should be able to say "re-assess all my parcels quarterly" and get notified if anything changes. |
| **Gap 3** | 🟡 **No supplier lifecycle tracking.** When a supplier is added or removed from the chain, there's no way to mark that transition. The system treats parcels as anonymous geometries, not as linked to specific supplier relationships. |
| **Priority** | Gap 1 is HIGH. Gap 2-3 are MEDIUM. |

### J8 — Defend Against Audit / Inspection

| Aspect | Detail |
| ------ | ------ |
| **Job** | "An EU authority or auditor requests evidence of our due diligence. I need to produce timestamped, reproducible, defensible records showing what we checked, when, with what methodology, and what we concluded." |
| **Current state** | Consultant reports, internal memos, GFW screenshots saved in a folder. Often disorganized and hard to reproduce. |
| **Canopex today** | ✅ Timestamped pipeline runs with instance IDs. ✅ Scene provenance (satellite scene IDs for reproducibility). ✅ Methodology page documenting the assessment approach. ✅ Algorithmic determination with confidence scoring and evidence breakdown. ✅ 5+ data sources for corroboration. |
| **Gap 1** | 🟡 **No immutable audit log.** There's no tamper-evident record of "user X ran assessment Y on date Z, which produced determination W." The enrichment manifest is stored in blob storage, but there's no separate audit log that an auditor could independently verify wasn't modified after the fact. |
| **Gap 2** | 🟡 **No data provenance chain.** The PDF shows scene IDs but doesn't link to the raw data. An auditor wanting to verify the analysis can't trace from "determination: compliant" back through "NDVI computed from scene X" to "scene X downloaded from Planetary Computer at timestamp T." |
| **Gap 3** | 🟢 **No methodology versioning.** If we update the determination algorithm, old assessments were run under a different version. There's no record of which algorithm version produced which determination. |
| **Priority** | Gaps 1-2 are MEDIUM (important for credibility but not blocking sales). Gap 3 is LOW. |

### J9 — Collaborate with Team & Stakeholders

| Aspect | Detail |
| ------ | ------ |
| **Job** | "Multiple people are involved: I manage the process, my analyst reviews evidence, my legal team validates the statement, my supplier manager communicates with flagged suppliers. We need to work together." |
| **Current state** | Email chains, shared drives, meetings. No shared workspace. |
| **Canopex today** | ✅ Org model with owner + members. ✅ Email invites for team members. ✅ Shared pipeline runs within an org. |
| **Gap 1** | 🟡 **No role-based access.** All org members have the same permissions. The analyst who reviews evidence and the finance person who manages billing see the same UI. (Not critical for small teams, but matters as orgs scale.) |
| **Gap 2** | 🟡 **No shareable analysis links.** If I want to share a specific assessment with my legal team or an external auditor, I can't send them a link. They'd need to be org members and find the run in history. |
| **Gap 3** | 🟢 **No comments/discussion on runs.** Team members can't leave notes on a run like "Legal approved this batch" or "Supplier X is being investigated." |
| **Priority** | Gap 2 is MEDIUM (common ask). Gaps 1 and 3 are LOW. |

### J10 — Manage Billing & Cost

| Aspect | Detail |
| ------ | ------ |
| **Job** | "I need to know what this costs, manage my subscription, understand per-parcel billing, and get invoices for my finance team." |
| **Current state** | N/A — this is SaaS-specific. |
| **Canopex today** | ✅ 2 free trial parcels (no card required). ✅ £49/month base subscription. ✅ £3/parcel metered overage (graduated: 100+ £2.50, 500+ £1.80). ✅ Stripe Checkout for subscription. ✅ Stripe Customer Portal for billing management. ✅ Entitlement check before pipeline runs. ✅ Billing status endpoint. |
| **Gap 1** | 🟡 **No cost estimator in the UI.** Before running an assessment with 50 parcels, the officer should see "This will use 50 parcel credits, estimated cost: £X." The preflight panel shows parcel count but not cost. |
| **Gap 2** | 🟡 **No usage dashboard.** "How many parcels have I assessed this month? What's my bill so far? Am I approaching a volume tier break?" |
| **Gap 3** | 🟢 **No annual billing option.** Enterprise customers prefer annual contracts with upfront payment for budget certainty. |
| **Priority** | Gap 1 is MEDIUM (reduces billing surprises). Gaps 2-3 are LOW. |

---

## User Journey Maps

### Journey A — First-Time Compliance Officer (Evaluation)

```text
Trigger: "EUDR deadline is approaching. My boss says we need a tool."

1. DISCOVER
   Google: "EUDR satellite deforestation tool"
   → Finds canopex.io landing page
   → Reads: "Satellite evidence for EUDR due diligence"
   → Clicks "Start Free" → /eudr/

2. ORIENT
   → Signs in (Azure AD B2C / social)
   → Sees first-run experience with checklist
   → Reads methodology page (linked from first-run)
   → Has 2 free trial parcels

3. TEST WITH KNOWN DATA
   → Has a KML from Google Earth with 3 test plots
     (or coordinates in a spreadsheet — GAP: can't upload CSV)
   → Uploads KML → watches pipeline progress
   → Pipeline: parse → acquire → fulfil → enrich → determination
   → ~5 min for 3 parcels

4. EVALUATE EVIDENCE
   → Sees per-parcel determination: ✓ Compliant / ⚠ Flagged
   → Reviews NDVI time series, change detection, land cover layers
   → Clicks "AI Analysis" → reads plain-English interpretation
   → Downloads EUDR PDF → shows to legal team / boss

5. DECIDE
   → "This is faster and cheaper than a consultant"
   → Subscribes: £49/month (owner does this)
   → Invites 2 team members to the org

   EXIT CRITERIA: Trial → paid conversion

   ⚠ RISK POINTS:
   - Step 3: if they have a CSV, not a KML, they're stuck
   - Step 4: if a parcel is flagged, no workflow to investigate
   - Step 5: no cost preview before committing
```

### Journey B — Ongoing Compliance Manager (200+ parcels)

```text
Trigger: "We have 200 supplier plots to assess quarterly."

1. PREPARE DATA
   → Collects coordinates from suppliers (CSV, Excel)
   → GAP: Must convert to KML externally
   → Uploads KML with all 200 parcels

2. RUN ASSESSMENT
   → Queues due diligence → pipeline processes all parcels
   → Progressive delivery: see results as each parcel completes
   → ~30-60 min for 200 parcels

3. TRIAGE RESULTS
   → GAP: No portfolio dashboard — can't sort/filter parcels by
     determination status
   → Must scroll through the evidence panel for each parcel
   → 180 compliant, 15 flagged, 5 failed (hypothetical)

4. INVESTIGATE FLAGGED PARCELS
   → GAP: No investigation workflow
   → GAP: No before/after comparison view
   → GAP: No annotation for "seasonal clearing, acceptable"
   → GAP: No human override with recorded reasoning
   → Must manually review each flagged parcel in the evidence panel

5. EXPORT & FILE
   → Downloads EUDR PDF for compliant parcels
   → GAP: No aggregated report across all 200 parcels
   → GAP: No "compliance summary" for board/legal
   → Must manually compile results

6. QUARTERLY RE-ASSESSMENT
   → GAP: No scheduled re-monitoring
   → GAP: No "last assessed" tracking per parcel
   → Must remember to re-upload and re-run quarterly

   ⚠ FRICTION POINTS:
   - Steps 1 & 3 are the biggest pain for scale users
   - The product works parcel-by-parcel; the job is portfolio-level
```

### Journey C — Audit Consultancy (Assessing on Behalf of Clients)

```text
Trigger: "Client X needs EUDR compliance evidence for 50 plots by Friday."

1. RECEIVE CLIENT DATA
   → Client sends Excel with supplier coordinates
   → GAP: Must convert to KML
   → May need to create separate orgs per client for data isolation
   → GAP: No multi-org management for consultancy use case

2. RUN ASSESSMENT
   → Same as Journey B — upload, queue, wait

3. REVIEW & ANNOTATE
   → Must add professional interpretation beyond the AI narrative
   → GAP: No annotation/notes per parcel
   → GAP: No consultancy-branded report template
   → Must manually edit the PDF or write a cover report

4. DELIVER TO CLIENT
   → GAP: No shareable analysis links
   → Must download PDF and email it
   → Client can't independently verify the assessment

5. BILL CLIENT
   → Consultancy bills client for assessment (£X per parcel)
   → Internal cost: Canopex subscription + metered parcels
   → GAP: No per-client cost tracking for consultancy billing

   ⚠ FRICTION POINTS:
   - Multi-client data isolation
   - Need professional/white-label output
   - Client needs independent verification
```

---

## Gap Priority Matrix

### 🔴 High Priority — Blocks Core EUDR Workflow

| Gap | Journey | Description | Effort | Stage |
| --- | ------- | ----------- | ------ | ----- |
| **CSV/coordinate paste in UI** | J2, A, B, C | Frontend for `/api/convert-coordinates` — paste or upload CSV with lat/lon/name columns, convert to KML and auto-submit | Medium | 3.x |
| **Supplier portfolio dashboard** | J3, J7, B | Overview of all parcels: status, last assessed, commodity, risk. Sort/filter/search. Aggregated compliance stats. | High | 3.x |
| **Flagged-parcel investigation workflow** | J5, A, B | When determination = flagged: zoom to area of concern, before/after imagery, add notes, override with reason. | High | 3.x |

### 🟡 Medium Priority — Improves Quality of Life

| Gap | Journey | Description | Effort | Stage |
| --- | ------- | ----------- | ------ | ----- |
| Before/after comparison view | J5 | Side-by-side or slider view of pre/post-2020 imagery | Medium | 3.x |
| Annotation/notes per parcel | J5, J8, J9 | Text notes attached to parcels for audit defense | Medium | 3.x |
| Human override of determination | J5 | Mark flagged parcel as "compliant with explanation" | Low | 3.x |
| PDF with imagery (#647) | J6 | Embed satellite imagery tiles in the audit PDF | Medium | 3.x |
| Aggregated compliance report | J6, J7 | Single report across multiple runs/parcels | Medium | 3.x |
| Cost estimator in preflight | J10 | Show estimated cost before queueing | Low | 2D |
| Usage dashboard | J10 | Monthly usage, spend, approaching tier breaks | Medium | 3.x |
| Scheduled EUDR re-monitoring | J7 | Auto re-assess parcels on a cadence (monthly/quarterly) | Medium | 3.x |
| Shareable analysis links | J9 | Public or auth-gated link to a specific run | Medium | 3.x |
| DMS/UTM coordinate support | J2 | Accept coordinates in DMS, UTM, not just decimal degrees | Low | 3.x |
| Supplier data template | J2 | Downloadable Excel/CSV template for suppliers to fill in | Low | 3.x |
| Country-risk auto-flagging | J3 | Auto-flag parcels in EU high-risk countries | Low | 3.x |
| Commodity tracking per parcel | J3 | Tag parcels with commodity type for EUDR filtering | Low | 3.x |
| Immutable audit log | J8 | Tamper-evident log of assessments for auditors | Medium | 4.x |

### 🟢 Low Priority — Future / Nice-to-Have

| Gap | Journey | Description | Effort | Stage |
| --- | ------- | ----------- | ------ | ----- |
| EU Information System integration | J6 | Submit due diligence statements directly (blocked on EU IS) | High | 5.x |
| Due diligence statement template | J6 | Formal EUDR DDS format (distinct from audit PDF) | Medium | 4.x |
| Methodology versioning | J8 | Record which algorithm version produced each determination | Low | 4.x |
| Role-based access within org | J9 | Viewer/analyst/admin roles | Medium | 4.x |
| Multi-org for consultancies | C | Manage multiple client orgs from one account | High | 4.x |
| White-label/branded reports | C | Consultancy branding on PDF exports | Medium | 4.x |
| Annual billing | J10 | Upfront annual payment for enterprise budget certainty | Low | 3.x |
| Shapefile/GeoJSON upload | J2 | Accept .shp or .geojson in addition to KML/KMZ | Medium | 3.x |
| Per-parcel assessment history | J4 | Time-series of determinations for the same parcel | Medium | 4.x |
| Data provenance chain | J8 | Full traceability from determination → NDVI → scene → download | High | 5.x |

---

## Recommended Next Steps

### Immediate (pre-revenue, Stage 2D/3.x)

1. **CSV/coordinate paste UI** — Wire the existing
   `/api/convert-coordinates` endpoint into the EUDR frontend. Add a
   "Paste Coordinates" tab alongside the file upload. Accept CSV with
   `name, lat, lon` columns. This unblocks the most common data format
   compliance officers receive from suppliers.

2. **Cost estimator in preflight** — The preflight panel already shows
   parcel count. Add a line: "Estimated cost: X parcels × £3 = £Y
   (included in your plan: Z remaining)". Low effort, reduces billing
   surprises.

3. **Flagged-parcel quick-review** — When a parcel is flagged, show the
   specific flag reasons prominently and link to the relevant evidence
   layer. Not a full investigation workflow, but enough to understand
   *why* it was flagged without digging through raw data.

   ### Near-Term (Stage 3.x — first paying customers)

4. **Supplier portfolio dashboard** — A new `/eudr/portfolio/` page (or
   section within `/eudr/`) showing all assessed parcels across all
   runs. Columns: parcel name, commodity, last assessed, determination,
   confidence, flags. Sortable/filterable. Aggregated stats at top
   (total assessed, % compliant, parcels due for re-assessment).

5. **Before/after comparison** — Side-by-side imagery viewer for any
   parcel, showing nearest-to-2020 image vs latest image. Essential for
   flagged parcels where the officer needs to visually verify.

6. **Annotation & override** — Text notes per parcel, plus ability to
   override algorithmic determination with a recorded reason. Both
   written to the audit trail.

7. **Aggregated compliance report** — Single PDF/CSV covering all
   assessed parcels with summary statistics. Board-ready.

   ### Medium-Term (Stage 4.x — scaling)

8. **Batch operations** (#588) — Upload folder of KMLs or large CSV,
   assess all in parallel.

9. **Scheduled re-monitoring** — Auto-re-assess parcels on a cadence
   with change alerts.

10. **Shareable analysis links** — Public or auth-gated permalink to a
    specific assessment for external auditors or clients.

---

## Mapping to Existing Issues

| Gap | Existing Issue | Notes |
| --- | ------------- | ----- |
| CSV upload in frontend | — | New issue needed |
| Portfolio dashboard | — | New issue needed |
| Flagged-parcel investigation | — | New issue needed |
| Before/after comparison | — | New issue needed |
| Annotation/notes | — | New issue needed |
| Human override | — | New issue needed |
| PDF with imagery | #647 | Already tracked |
| Aggregated compliance report | — | New issue needed |
| Cost estimator | — | New issue needed |
| Batch operations | #588 | Stage 4.1 |
| Scheduled re-monitoring | #310 | Stage 3.1 (implemented, needs EUDR wiring) |
| Shareable links | 3.8 in roadmap | No issue yet |
| Country-risk flagging | — | New issue needed |
| Commodity tracking | — | New issue needed |
| Supplier data template | — | New issue needed |
