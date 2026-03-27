# TreeSight — Product Roadmap & Business Strategy

**Date:** 27 March 2026
**Status:** Draft v3 — updated to reflect M4 near-completion (12/13 items done)

---

## 1. Jobs-to-be-Done Analysis

### 1.1 Conservation Analyst (NGO / Government)

| Dimension | Detail |
|-----------|--------|
| **When I…** | need to monitor a protected forest for illegal logging or deforestation |
| **I want to…** | upload a KML boundary and get automated satellite change analysis |
| **So I can…** | produce time-stamped evidence for enforcement actions and donor reports |
| **Current alternative** | Manual QGIS/Google Earth workflow, days per AOI, requires GIS staff |
| **Pain** | Slow turnaround, expensive GIS expertise, no automated alerting |
| **Gain** | Actionable evidence in minutes, no GIS skills needed, AI-generated narratives |

**Hiring criteria (why they switch):** Speed, evidence quality, cost per AOI.

### 1.2 Agricultural Advisor (Agritech / Crop Insurance)

| Dimension | Detail |
|-----------|--------|
| **When I…** | need to assess crop health across insured parcels each season |
| **I want to…** | batch-upload KMLs and get NDVI trends with weather correlation |
| **So I can…** | advise farmers on intervention timing and validate insurance claims |
| **Current alternative** | Manual Sentinel Hub / Planet Explorer, one parcel at a time |
| **Pain** | Manual per-parcel work doesn't scale; weather context requires separate tools |
| **Gain** | Batch processing, integrated weather + NDVI, exportable trend reports |

**Hiring criteria:** Batch throughput, weather-NDVI correlation, export formats.

### 1.3 ESG / Supply-Chain Compliance

| Dimension | Detail |
|-----------|--------|
| **When I…** | need to certify that a sourcing region is deforestation-free |
| **I want to…** | get before/after satellite evidence with quantified change metrics |
| **So I can…** | satisfy EU Deforestation Regulation (EUDR) and investor due diligence |
| **Current alternative** | Consultancy engagement ($10K–$50K per assessment), 4–8 week turnaround |
| **Pain** | Expensive, slow, opaque methodology |
| **Gain** | Automated, auditable, repeatable, fraction of the cost |

**Hiring criteria:** Audit trail, quantified metrics (hectares cleared), regulatory acceptance.

---

## 2. Business Model Canvas

### 2.1 Canvas

| Block | Detail |
|-------|--------|
| **Key Partners** | Microsoft Planetary Computer (free STAC imagery), Azure (hosting), Azure AI Foundry (managed inference), Open-Meteo (free weather API) |
| **Key Activities** | Pipeline orchestration, satellite enrichment, AI analysis, platform ops |
| **Key Resources** | Azure Functions runtime, Azure AI Foundry (managed AI), blob storage, Planetary Computer catalog |
| **Value Propositions** | KML-in → analysis-out in minutes. No GIS expertise. AI-generated narratives. Integrated weather + NDVI. Multi-provider imagery. |
| **Customer Relationships** | Self-serve (free tier), guided onboarding (paid), SLA-backed (enterprise) |
| **Channels** | Website demo → early-access funnel → self-serve dashboard → sales-assisted enterprise |
| **Customer Segments** | Conservation NGOs, agritech companies, ESG compliance teams, academic researchers |
| **Cost Structure** | Azure Functions (pay-per-invocation), Azure AI Foundry (pay-per-token), blob storage, bandwidth, dev time |
| **Revenue Streams** | Tiered SaaS subscription (see §3) |

### 2.2 Value Proposition Canvas

**Customer pains eliminated:**

- Hours/days of manual GIS work per AOI
- Need for specialist GIS staff
- Fragmented tooling (separate systems for imagery, weather, analysis)
- No audit trail for compliance use cases

**Gains created:**

- Minutes-to-insight turnaround
- AI-generated plain-English narratives
- Integrated NDVI + weather + fire + flood context
- Exportable, auditable analysis records
- Batch processing at scale

---

## 3. Pricing Model

### 3.1 Tiers (Dual-Entry Model)

See [PERSONA_DEEP_DIVE.md §10](PERSONA_DEEP_DIVE.md#10-dual-pricing-model) for full analysis, graduation economics, and competitive pricing rationale.

| Tier | Price | Included AOIs | Overage | Concurrency | AI Insights | Data Retention | Target |
|------|-------|--------------|---------|-------------|-------------|----------------|--------|
| **Free** | £0/month | 3/month | Hard cap | 1 pipeline | No | 30 days | Evaluation, students, individual researchers |
| **Starter** | £19/month | 15/month | £1.50/AOI | 2 pipelines | Yes | 60 days | Independent consultants, small NGOs |
| **Pro** | £49/month | 45/month | £0.80/AOI | 5 pipelines | Yes | 180 days | Active NGOs, ESG compliance, regular users |
| **Team** | £149/month | 200/month | £0.50/AOI | 10 pipelines | Yes | 1 year | Multi-user orgs, agritech, large compliance |
| **Enterprise** | Custom | Negotiated | Volume-discounted | Dedicated | Yes + custom | Custom | Large compliance programmes, government |

Key design decisions:

- **Dual entry:** both Starter (£19) and Pro (£49) available simultaneously — different buyer psychologies
- **AI insights included at all paid tiers** — the differentiator that sells the product
- **Free tier at 3 AOIs** (not 5) — drives faster conversion
- **Starter→Pro crossover at ~35 AOIs/month** — natural graduation
- **Pro→Team crossover at ~175 AOIs/month** — or when multi-user features needed

### 3.2 Usage-Based Add-Ons

| Add-On | Price | Notes |
|--------|-------|-------|
| Historical baseline report (Landsat 40-yr) | £10/AOI | Compute-intensive, one-time |
| Extended retention | £5/month per 100 GB | Blob storage cost + margin |

### 3.3 Unit Economics (Target)

| Metric | Target |
|--------|--------|
| AOI pipeline cost (compute + storage) | ~£0.08–£0.15 per run |
| AI insight cost (Azure AI Foundry) | ~£0.01–£0.05 per analysis |
| Gross margin | 80%+ at all paid tiers |
| CAC payback | < 3 months |
| LTV:CAC | > 3:1 |

---

## 4. What's Missing From the Site (Adoption & Conversion Gaps)

### 4.1 Critical Gaps (Must-Have Before Paid Launch)

| # | Gap | Impact | Effort |
|---|-----|--------|--------|
| A1 | **User authentication** | No accounts = no paid tier, no usage tracking, no saved work | High |
| A2 | **Dashboard / saved analyses** | Users can't return to past results; zero stickiness | High |
| A3 | **Usage metering & quotas** | Can't enforce tier limits or bill overages | Medium |
| A4 | **Pricing page** | Visitors can't self-qualify; no conversion path beyond "Early Access" | Low |
| A5 | **Export (PDF / GeoJSON / CSV)** | No way to take results into other systems or reports | Medium |
| A6 | **API documentation** | Programmatic users can't integrate; blocks Team/Enterprise adoption | Medium |

### 4.2 Important Gaps (Should-Have for Growth)

| # | Gap | Impact | Effort |
|---|-----|--------|--------|
| B1 | **Onboarding flow + KML guide** | New users don't know what KML to upload or what to expect — see §4.4 | Low |
| B2 | **Social proof / case studies** | No evidence that others use it; trust barrier | Low |
| B3 | **Monthly NDVI monitoring & alerts** | Conservation users want "notify me when NDVI drops >10%" — feasible, see §4.5 | High |
| B4 | **Team / org management** | Enterprise can't share analyses across colleagues | Medium |
| B5 | **Data retention policy (visible)** | Users don't know how long their data is kept; compliance concern | Low |
| B6 | **Terms of service & privacy policy** | Legal requirement before accepting payments | Low |

### 4.3 Nice-to-Have (Differentiation vs. Current Toolset)

Each item below is benchmarked against what competitors already offer. See §11 for full competitive landscape.

| # | Feature | Who Already Has This | TreeSight Angle | Effort |
|---|---------|---------------------|-----------------|--------|
| C1 | **Comparison view** (side-by-side frames) | Sentinel Hub (split-view in EO Browser), Planet Explorer (compare mode) | We lack this entirely; critical for ESG before/after evidence — table-stakes for compliance persona | Medium |
| C2 | **Shareable analysis links** | Google Earth Engine (shared scripts), Planet (shared mosaics) | Neither offers a simple "share this analysis" URL. Viral growth potential: "look at this deforestation" | Medium |
| C3 | **Scheduled re-analysis** | Planet (monitoring API, daily), Global Forest Watch (weekly alerts) | Azure Timer Trigger → monthly pipeline re-run. Our advantage: integrated NDVI+weather+AI narrative, not just imagery | High |
| C4 | **Webhook / Slack notifications** | UP42 (webhooks), Planet (subscription API) | Standard enterprise integration pattern; low effort, high enterprise signal | Low |
| C5 | **Custom branding** (white-label) | Descartes Labs (enterprise), Maxar (GEGD) | Enterprise upsell for consultancies reselling to their clients | Medium |

### 4.4 KML Onboarding Guide (B1)

**Problem:** Non-GIS users don't know how to create a KML file. This is the #1 friction point.

#### Recommended Tools (in order of accessibility)

| Tool | Cost | Audience | Notes |
|------|------|----------|-------|
| **Google Earth Pro** (desktop) | Free | Everyone | Best option for most users. Draw polygon → File → Save Place As → KML. Installed base of millions. Well-documented. |
| **Google My Maps** (web) | Free | Casual users | Draw polygons in-browser, export as KML. Simpler than Earth Pro but less precise. |
| **geojson.io** (web) | Free | Quick sketches | Draw a polygon, export as KML from the Save menu. Fast, no install. Convert GeoJSON → KML trivially. |
| **QGIS** (desktop) | Free / open-source | GIS professionals | Full-featured but steep learning curve. Only recommend for users who already know GIS. |

**Recommendation:** Default to **Google Earth Pro** in all onboarding materials. It's free, widely known, and the KML export is two clicks.

#### KMZ Support

KMZ is a ZIP archive containing a `doc.kml` file (and optionally embedded images/overlays). We should support it because:

- Google Earth Pro defaults to "Save as KMZ" (users have to actively choose KML instead)
- Many publicly shared boundary files are distributed as KMZ
- Implementation is trivial: detect ZIP magic bytes → extract `doc.kml` → parse as KML
- Fiona already handles KMZ natively via the LIBKML driver
- For the lxml fallback: `zipfile.ZipFile` → read `doc.kml` → pass bytes to existing parser

**Effort:** Low (< 1 day). Add a `_maybe_unzip()` function in `parsers/__init__.py`.

#### Onboarding Flow Design

1. **First visit:** Banner above demo → "New to KML? Here's how to create one in 60 seconds" → link to guide
2. **Guide page:** Step-by-step screenshots for Google Earth Pro (draw polygon → save as KML/KMZ)
3. **In-app:** Accept both `.kml` and `.kmz` file upload (drag-and-drop) alongside the paste-KML textarea
4. **Sample picker:** Already exists (Madera, Nechako, Pará, etc.) — keep as instant-start path

### 4.5 Monthly NDVI Monitoring Feasibility (B3)

**Answer: Yes, monthly tracking is well within reach.**

#### Why It Works

- **Sentinel-2 revisit:** ~5 days globally (2 satellites), so monthly NDVI snapshots always have fresh data
- **Pipeline already processes temporal series:** The demo shows bi-monthly Sentinel-2 frames across 8+ years
- **Azure Durable Functions supports timer sub-orchestrations:** A monthly Timer Trigger can kick off the existing pipeline for subscribed AOIs
- **NDVI diffing logic already exists** in the enrichment module (pairwise change detection, §roadmap item #4)

#### Architecture

```text
Timer Trigger (1st of each month)
  → Query subscribed AOIs from Cosmos DB
  → For each AOI: run pipeline (acquisition → enrichment) for latest Sentinel-2 scene
  → Diff NDVI against previous month's stored value
  → If delta exceeds user-defined threshold (e.g. ≥10% drop):
      → Send alert (email / webhook / Slack)
      → Store alert record for dashboard
```

#### Cost Impact

- Re-running a single AOI pipeline costs ~$0.08–$0.15 (compute + storage)
- 100 monitored AOIs × monthly = ~$8–$15/month in compute
- Alert delivery (email via SendGrid free tier, or Azure Communication Services) ≈ free at low volume
- **Conclusion:** Economically viable as a Pro/Team feature. Marginal cost per monitored AOI is negligible.

---

## 5. Hosting Readiness Checklist

### 5.1 Must-Have (Gate for Public Launch)

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| H1 | **Authentication provider** (Azure Entra External ID CIAM) | ✅ Done | JWT auth with RS256 JWKS validation, graceful degradation |
| H2 | **Rate limiting** (per-user, per-IP) | ✅ Done | Per-IP sliding window (contact, pipeline poll, proxy), per-user quota (5 runs) |
| H3 | **Application Insights / monitoring** | ✅ Done | Wired in host.json, config.py, and OpenTofu |
| H4 | **Error alerting** (PagerDuty / Teams webhook) | ✅ Done | Azure Monitor metric alerts (failed requests, high latency) via OpenTofu |
| H5 | **Cost budget alerts** (Azure Cost Management) | ✅ Done | 50/80/100% threshold alerts via OpenTofu |
| H6 | **CI/CD pipeline** | ✅ Done | GitHub Actions: CI (lint, test, build), Deploy (infra, container, SWA), Security (Semgrep, Trivy, pip-audit, CodeQL) |
| H7 | **HTTPS + custom domain** | Partial | Static Web App has HTTPS; OpenTofu ready, needs Cloudflare CNAME |
| H8 | **Terms of service & privacy policy** | ✅ Done | terms.html and privacy.html deployed |
| H9 | **Database for user records** | Not started | Azure Cosmos DB (serverless, <$10/mo) — unblocks 4.4 dashboard |
| H10 | **Secrets rotation / Key Vault wiring** | Partial | Config references Key Vault; needs production wiring |

### 5.2 Should-Have (Within 30 Days of Launch)

| # | Criterion | Status |
|---|-----------|--------|
| H11 | Load testing (10+ concurrent pipelines) | Not started |
| H12 | Graceful degradation under load (queue backpressure) | Not started |
| H13 | Backup & disaster recovery plan | Not started |
| H14 | GDPR data handling documentation | Not started |
| H15 | Penetration test / security audit | Not started |

---

## 6. Demo Cost Model

### 6.1 Current Architecture Costs (Azure, Estimated Monthly)

| Resource | SKU / Tier | Est. Monthly Cost | Notes |
|----------|-----------|-------------------|-------|
| **Static Web App** | Free | $0 | 100 GB bandwidth, custom domain, HTTPS |
| **Azure Functions** | Consumption (Flex) | $0–$5 | First 1M executions free; pay-per-use after |
| **Blob Storage** | Hot, LRS | $2–$10 | ~50–500 GB imagery cache; $0.0184/GB |
| **Planetary Computer** | Free API | $0 | Microsoft-funded; no per-query cost |
| **Open-Meteo** | Free API | $0 | No key required |
| **Azure AI Foundry** | Pay-per-token | **$1–$10** | Scales to zero; no idle cost — see §6.2 |
| **Azure Cosmos DB** | Serverless | $1–$5 | User records, analysis history (future) |
| **Key Vault** | Standard | $0.50 | Minimal secret operations |
| **Total (demo, no AI)** | — | **~$5–$20/month** | Extremely cost-effective |
| **Total (demo, with AI)** | — | **~$6–$30/month** | AI cost is negligible at demo scale |

### 6.2 AI Layer Cost Optimisation

Using **Azure AI Foundry** instead of self-hosted Ollama/GPU eliminates the GPU VM cost entirely. No idle compute, pay only for tokens consumed.

**Azure AI Foundry pricing (indicative, Mistral / GPT-4o-mini class):**

| Metric | Cost |
|--------|------|
| Input tokens (per 1M) | $0.15–$1.00 |
| Output tokens (per 1M) | $0.60–$4.00 |
| Typical insight request | ~2K input + ~500 output tokens |
| **Cost per AI analysis** | **~$0.001–$0.005** |

At demo scale (50 analyses/month), AI cost is **< $0.25/month** — effectively free.

**Additional optimisation strategies:**

| Strategy | Savings | Trade-off |
|----------|---------|-----------|
| **Cache AI results** per AOI+frame in blob storage | 50–70% | Same AOI re-analysis is instant; miss rate depends on user base |
| **Smaller model** (GPT-4o-mini vs GPT-4o) | 60–80% | Slightly lower quality; likely sufficient for structured metadata analysis |
| **Make AI a paid add-on** (Free tier = no AI) | 100% for free users | Upsell to Pro tier; aligns cost with revenue |
| **Prompt optimisation** (shorter system prompt, structured output) | 30–50% | Reduces token count per call |

**Recommended approach for demo:**

1. Use Azure AI Foundry with a cost-effective model (GPT-4o-mini or Mistral via model catalog)
2. Cache AI results in blob storage keyed by `{aoi_hash}_{frame_index}`
3. Set per-user daily call limits (e.g. 10 AI analyses/day on free tier)
4. Gate advanced AI features (multi-frame trend synthesis) behind paid tiers
5. **Target demo cost: $5–$20/month** (AI adds < $1 at demo volume)

### 6.3 Scaling Breakpoints

| Monthly AOIs | Estimated Cost | Revenue (Pro mix) | Margin |
|-------------|----------------|-------------------|--------|
| 50 (demo) | $15 | $0 | –$15 |
| 500 (10 Pro users) | $25 | $490 | +$465 |
| 2,000 (mixed tiers) | $60 | $1,500–$3,000 | +$1,440–$2,940 |
| 10,000 (enterprise) | $250 | $5,000–$15,000 | +$4,750–$14,750 |

---

## 7. Unified Roadmap

Single source of truth. Every item has a clear reason ("why now"), a value driver, and a dependency chain. Milestones are revenue gates — we don't move to the next milestone until the current one is releasable.

### Milestone 1 — Deployable Product ✅ COMPLETE

**Goal:** Live on Azure, with CI/CD, monitoring, and auth. Nothing user-facing changes yet, but we can deploy safely and measure.

**Why first:** Everything else is blocked by this. Can't iterate if we can't deploy.

| # | Item | Effort | Depends On | Value Driver |
|---|------|--------|------------|-------------|
| 1.1 | **CI/CD pipeline** (GitHub Actions: test → lint → build → push to ACR) | Medium | — | Unblocks all future deployment |
| 1.2 | **Azure deployment** (Container Apps + Static Web App + Event Grid + Key Vault) | High | — | Production environment exists |
| 1.3 | **Application Insights instrumentation** | Low | 1.2 | Can measure pipeline success rate, latency, errors |
| 1.4 | **Cost budget alerts** (Azure Cost Management) | Low | 1.2 | Prevents surprises — we don't control Planetary Computer rate limits |
| 1.5 | **Custom domain + HTTPS** | Low | 1.2 | Credibility — "treesight.io" not "*.azurestaticapps.net" |
| 1.6 | **Azure AI Foundry integration** + result caching | Medium | 1.2 | Replaces Ollama; pay-per-token, no GPU VM to manage |
| 1.7 | **KMZ support** (`_maybe_unzip()` in parsers) | Low | — | Removes friction — Google Earth Pro defaults to KMZ |
| 1.8 | **Distributed replay limiter** (Redis / Table Storage for valet tokens) | Medium | 1.2 | Valet tokens currently in-memory; broken across multiple function instances |

**Exit criteria:** Site is live at `treesight.io`. Pipeline runs end-to-end in production. Monitoring dashboards exist. KML and KMZ accepted.

---

### Milestone 2 — Free Tier Launch ✅ COMPLETE

**Goal:** Real users can sign up, run analyses, and we can track activation. No payment yet — pure learning.

**Why now:** We need real user behaviour data before building paid features. This is the cheapest way to validate demand.

**Route to market:** Post in r/gis, r/remotesensing, conservation Slack communities, GIS StackExchange. Direct outreach to 2–3 NGOs we know.

| # | Item | Effort | Depends On | Value Driver |
|---|------|--------|------------|-------------|
| 2.1 | **Authentication** (Azure AD B2C or Clerk) | High | 1.2 | Accounts exist; usage is trackable |
| 2.2 | **Onboarding flow** (banner → "New to KML?" → Google Earth Pro guide) | Low | — | #1 friction point for non-GIS users (§4.4) |
| 2.3 | **KML guide page** (step-by-step screenshots, recommend Google Earth Pro) | Low | — | Converts "interested but stuck" visitors into active users |
| 2.4 | **File upload** (drag-and-drop .kml/.kmz alongside paste-KML textarea) | Low | 1.7 | Removes copy-paste friction; supports KMZ natively |
| 2.5 | **Terms of service & privacy policy** | Low | — | Legal prerequisite for accounts |
| 2.6 | **Structured logging** (JSON, correlation IDs) | Low | 1.3 | Debug user issues in production |
| 2.7 | **Data retention policy** (visible in settings + terms) | Low | 2.1 | Compliance signal; users know what happens to their data |

**Exit criteria:** 50+ signed-up users. We can see activation funnel (visit → sign up → first analysis → return). We know where users drop off.

**Key metric:** Demo completion rate > 15%.

---

### Milestone 3 — Core Analysis Value ✅ COMPLETE

**Goal:** The analysis output is good enough that users would pay for it. This is the product-market fit milestone.

**Why now:** Free tier users are in; now we need to deliver value worth paying for. These features are what competitors lack: integrated NDVI + weather + AI in one view.

**Site Review Remediation** (8 PRs merged): SCL cloud masking, data methodology page, security hardening, event detection (flood/fire), copy fixes, demo polish, website polish. 445 tests passing.

| # | Item | Effort | Depends On | Value Driver |
|---|------|--------|------------|-------------|
| 3.1 | **NDVI layer toggle** (S2 B04/B08 band math via PC mosaic expression) | Low | — | Table-stakes for vegetation analysis; Sentinel Hub has this, we don't yet |
| 3.2 | **Historical weather overlay** (Open-Meteo, synced to timelapse) | Low | — | No competitor integrates weather with imagery — this is our differentiator |
| 3.3 | **Insights panel** (per-frame NDVI stats, change flags, weather correlation) | Medium | 3.1, 3.2 | Turns raw data into actionable information; the "so what" |
| 3.4 | **NDVI change detection** (pairwise differencing, canopy loss area in ha) | Medium | 3.1 | Conservation & ESG personas need quantified change — "12 ha cleared" |
| 3.5 | **Comparison view** (side-by-side before/after frames) | Medium | — | ESG compliance needs before/after evidence; Sentinel Hub has this, we don't |
| 3.6 | **Contextual AI summaries** (Azure AI Foundry narrative from NDVI + weather) | Medium | 1.6, 3.3 | Our strongest differentiator — plain-English insights, no GIS skills needed |
| 3.7 | **Multi-polygon KML** (multiple placemarks → parallel pipeline runs) | Medium | — | Real-world KMLs often have multiple polygons; blocking for batch users |
| 3.8 | **Split enrichment module** (weather / ndvi / mosaic sub-modules) | Medium | — | Enrichment.py is 500+ lines; must split before adding more enrichment logic |

**Exit criteria:** Users describe the analysis as "useful" or "better than what I had". Qualitative feedback from 10+ users. NPS > 30.

**Key metric:** Return usage rate > 40% (users come back for a second analysis).

---

### Milestone 4 — Revenue (Weeks 6–10)

**Goal:** First paying customers. Free tier is gated; Pro tier delivers clear additional value.

**Why now:** We've validated demand (M2) and built the core value (M3). Now we learn if people will pay. Every week without revenue is a week we're subsidising usage.

**Route to market:** Enable Stripe/billing, email existing free users about Pro launch, pricing page drives self-serve conversion.

| # | Item | Effort | Depends On | Value Driver |
|---|------|--------|------------|-------------|
| 4.1 | **Pricing page** on website | Low | — | ✅ Done (PR #297) — Free/Starter/Pro/Team cards with VAT note, 14-day cancellation right |
| 4.2 | **Usage metering & quota enforcement** | Medium | 2.1 | ✅ Done (PR #223) — per-user pipeline quota, 7 tests |
| 4.3 | **Billing integration** (Stripe Checkout + webhook for subscription status) | Medium | 2.1, 4.2 | ✅ Done (PR #299) — Stripe Checkout, webhooks, multi-currency (GBP/EUR/USD), UK Consumer Contracts compliance, 25 tests |
| 4.4 | **User dashboard** (saved analyses, history, usage stats) | High | 2.1 | ❌ Not started — needs persistent database (Cosmos DB or PostgreSQL) |
| 4.5 | **Export: PDF report** (summary + charts + key frames) | Medium | 3.3 | ✅ Done (PR #303) — EUDR audit PDF with land-cover breakdown, 19 export tests |
| 4.6 | **Export: GeoJSON / CSV** (NDVI timeseries, weather data) | Low | 3.3 | ✅ Done (PR #303) — GeoJSON FeatureCollection + CSV writer |
| 4.7 | **Social proof section** (case study cards from free-tier users) | Low | — | ✅ Done (PR #297) — social-proof section on website |
| 4.8 | **Circuit breaker for AI** (Azure AI Foundry) | Low | 1.6 | ✅ Done — per-provider circuit breakers (azure-ai, ollama), 9 tests |
| 4.9 | **EUDR compliance mode** (post-2020 date filter + deforestation-free statement) | Low | 3.3 | ✅ Done (PR #303) — EUDR assessment endpoint, post-2020 date filtering, AI deforestation-free statement |
| 4.10 | **Coordinate-to-KML converter** (CSV lat/lon → KML → pipeline) | Low | — | ✅ Done (PR #303) — `coords_to_kml()` + `convert-coordinates` API endpoint |
| 4.11 | **ESA WorldCover overlay** (PC `esa-worldcover`, 10m land cover) | Low | — | ✅ Done (PR #305) — COG raster sampling, per-class pixel breakdown, dominant class detection |
| 4.12 | **WDPA protected area check** (protectedplanet.net API) | Low | — | ✅ Done (PR #303) — `check_wdpa_overlap()` with Protected Planet API |
| 4.13 | **Methodology documentation page** | Low | — | ✅ Done (PR #274) — `website/eudr-methodology.html` |

**Status: 12 of 13 items complete.** Only 4.4 (user dashboard) remains — blocked on database provisioning.

**Exit criteria:** 10+ paying Pro users. MRR > $400. Churn < 10%/month. EUDR mode functional.

**Key metric:** Free → Pro conversion rate > 5%.

---

### Milestone 5 — Growth & Retention (Weeks 8–14)

**Goal:** Users stay, share, and bring others. Features that make TreeSight a habit rather than a one-off tool.

**Why now:** We have paying users (M4). Now we need to retain them and grow organically. These features drive recurring engagement and viral loops.

| # | Item | Effort | Depends On | Value Driver |
|---|------|--------|------------|-------------|
| 5.1 | **Monthly NDVI monitoring** (Timer Trigger → re-run pipeline → alert on threshold breach) | High | 4.2, 3.4 | #1 retention driver — "notify me when NDVI drops >10%". See §4.5 for architecture. Feasible at ~$0.08–$0.15/AOI/month |
| 5.2 | **Shareable analysis links** | Medium | 4.4 | Viral loop: "look at this deforestation" → new visitor → sign up |
| 5.3 | **Scheduled re-analysis** ("run this AOI every month") | High | 5.1 | Natural extension of monitoring; makes TreeSight a subscription you keep |
| 5.4 | **External data joins** (FIRMS fire hotspots, GFW alerts) | Medium | 3.3 | Enriches analysis without new satellite data; high perceived value, low marginal cost |
| 5.5 | **Pydantic models for request/response validation** | Medium | — | Operational safety as API surface grows; catches bad inputs before they hit the pipeline |
| 5.6 | **Load testing** (10+ concurrent pipelines) | Medium | 1.2 | Must validate scaling before growth marketing pushes traffic |
| 5.7 | **Test coverage measurement** (target >70%) | Low | — | Confidence to ship fast without regressions |
| 5.8 | **MODIS Burned Area enrichment** (PC collection `modis-64A1-061`, global 500 m monthly, 2000–present) | Low | 5.4 | Complements FIRMS hotspot data (5.4) with validated burned-extent polygons and detection dates. **Already on Planetary Computer as COGs** — add collection to existing STAC provider, same auth/download path as Sentinel-2. No new infra. Free & open. |
| 5.9 | **ESA CCI Land Cover enrichment** (PC collection `esa-cci-lc`, 300 m annual, 1992–2020, 22 LCCS classes) | Low | 3.8 | Adds 28-year historical land-cover baseline — detect transitions (forest → cropland → urban). **Already on Planetary Computer as COGs** — same STAC query pattern. Pairs with 6.4 (Landsat baselines) for long-term trend context. Free & open. |
| 5.10 | **IO LULC Annual V2** (PC collection `io-lulc-annual-v02`, 10m, 2017–2023, 9-class) | Low | — | Multi-year land use change at Sentinel-2 resolution: "forest in 2019, cropland in 2022." Same STAC path. Free. |
| 5.11 | ~~**Planet-NICFI tropical mosaics**~~ | Medium | — | **Removed** — NICFI licence is non-commercial only; TreeSight is a commercial product. Tropics coverage uses Sentinel-2 + Landsat C2 L2 fallback via geo-routing (PR #304). |
| 5.12 | **ALOS Forest/Non-Forest** (PC collection `alos-fnf-mosaic`, 25m, global, annual) | Low | — | Independent SAR-based forest classification from JAXA. Cross-validates optical NDVI-based forest detection. Works through clouds. Free & open. |
| 5.13 | **GFW deforestation alerts** (GFW REST API, GLAD + RADD alerts) | Medium | 5.4 | Cross-reference our analysis with WRI's alert system. "GFW detected 3 deforestation alerts in this AOI in the past 6 months." Adds authority. Free API. |

**Exit criteria:** 30+ paid users. Net revenue retention > 100% (expansion > churn). At least 5 users on monitoring subscriptions.

**Key metric:** Monthly active users returning > 40%.

---

### Milestone 6 — Team & API (Weeks 12–18)

**Goal:** Unlock the Team tier ($149/mo) and programmatic access. This is where unit economics get interesting.

**Why now:** Pro tier is proven (M4–M5). Team/API users have higher LTV and lower churn. API access is the prerequisite for enterprise.

**Route to market:** Direct outreach to agritech companies and ESG consultancies. "You have 20 parcels? Here's an API to process them all."

| # | Item | Effort | Depends On | Value Driver |
|---|------|--------|------------|-------------|
| 6.1 | **API documentation** (OpenAPI spec, auth tokens, rate limits) | Medium | 2.1 | Partial — OpenAPI spec exists (`docs/openapi.yaml`); needs interactive docs page and developer onboarding |
| 6.2 | **Team / org management** (invite members, shared analyses) | Medium | 2.1, 4.4 | Enterprise can't adopt without multi-user; Team tier becomes sellable |
| 6.3 | **Webhook / Slack notifications** | Low | 5.1 | Enterprise integration pattern; low effort, high signal of seriousness |
| 6.4 | **Long-term historical baselines** (Landsat 1985–present via USGS/EE) | High | — | Unlocks 40-year trend context; ESG persona needs this for deforestation timelines |
| 6.5 | **Regional climate & land-use history** (NOAA/ECMWF/MODIS) | High | — | Contextualises recent changes within historical meteorology; premium feature |
| 6.6 | **Security audit / pen test** | Medium | 1.2 | Required before onboarding enterprise or handling sensitive data |
| 6.7 | **Blueprint activity decorator** (reduce orchestrator boilerplate) | Low | — | Velocity — adding new pipeline activities is currently boilerplate-heavy |
| 6.8 | **ESA CCI Biomass integration** (global above-ground biomass, 100 m, 2007–2022) | High | 5.9 | Quantifies carbon / biomass loss in Mg/ha — essential for ESG (EUDR, TNFD) and carbon-credit MRV. Multi-epoch differencing enables "this AOI lost X Mg C between 2017–2022". **Not on Planetary Computer** — bulk GeoTIFF from ESA ODP → self-hosted COGs in blob storage → clip-to-AOI. Only ESA CCI dataset requiring custom infra. Free & open. |

**Exit criteria:** 5+ Team subscriptions. At least 1 customer using the API programmatically. ARR > $30K.

**Key metric:** Team tier adoption rate among Pro users > 10%.

---

### Milestone 7 — Enterprise & Differentiation (Weeks 16–24+)

**Goal:** Enterprise deals, advanced features, defensible market position.

**Why now:** Self-serve revenue is proven. Enterprise is where LTV justifies sales effort. Advanced features (land-cover classification, super-resolution) create competitive moats.

**Route to market:** Sales-assisted — identify ESG compliance teams, agricultural insurers, government land management agencies from existing user base and inbound leads.

| # | Item | Effort | Depends On | Value Driver |
|---|------|--------|------------|-------------|
| 7.1 | **Custom branding / white-label** | Medium | 6.2 | Enterprise upsell — consultancies resell TreeSight to their clients |
| 7.2 | **Land-cover classification** (SatlasPretrain / Clay Foundation) | High | 1.6 | Segments frames into forest/cleared/agriculture/water; quantified change metrics |
| 7.3 | **Super-resolution upscaling** (SR4RS, S2 10m → ~2.5m) | High | — | Addresses small-AOI resolution gap; competitive with Planet's 3m but free imagery |
| 7.4 | **Historical baseline report** (Landsat 40-yr, premium one-off) | Medium | 6.4 | $10/AOI add-on; high margin, low recurring cost |
| 7.5 | **SSO / SAML integration** | Medium | 6.2 | Enterprise gate — CISOs require it |
| 7.6 | **Extract provider stubs** to test helpers | Low | — | Code health — production code shouldn't carry 350+ lines of test stubs |
| 7.7 | **Graceful degradation under load** (queue backpressure) | Medium | 5.6 | Enterprise SLAs need predictable behaviour under burst traffic |

**Exit criteria:** 1–2 enterprise contracts. ARR > $100K. Product is defensible — competitors can't easily replicate the integrated enrichment + AI + monitoring stack.

---

### Code Health (Continuous — Attach to Milestones)

These items don't have their own milestone. They ride alongside feature work to prevent debt accumulation.

| Item | Attach To | Effort | Rationale |
|------|-----------|--------|-----------|
| **KMZ support** | M1 (1.7) | Low | Ships with deployment; removes user friction on day one |
| **Distributed replay limiter** | M1 (1.8) | Medium | Broken in multi-instance; must fix before real traffic |
| **Structured logging** | M2 (2.6) | Low | Need it to debug first real user issues |
| **Split enrichment module** | M3 (3.8) | Medium | Must split before adding more enrichment features |
| **Circuit breaker for AI** | M4 (4.8) | Low | AI outage shouldn't break the paid pipeline |
| **Pydantic models** | M5 (5.5) | Medium | API surface is growing; validate inputs before they propagate |
| **Test coverage** | M5 (5.7) | Low | Shipping faster; need confidence |
| **Blueprint activity decorator** | M6 (6.7) | Low | Adding new activities is boilerplate-heavy |
| **Extract provider stubs** | M7 (7.6) | Low | Clean up before more providers are added |
| **STAC enrichment collections** (add `modis-64A1-061` + `esa-cci-lc` to provider) | M5 (5.8, 5.9) | Low | Both already on Planetary Computer — just wire new collections into existing STAC provider + enrichment pipeline |
| **Self-hosted COG pipeline** (ESA CCI Biomass → blob → TiTiler or direct clip) | M6 (6.8) | Medium | Only Biomass needs custom hosting; Land Cover and Burned Area are free via PC |

---

### Summary View

```text
M1  Deployable Product          Wk 1–4   ████████████  ✅
M2  Free Tier Launch            Wk 3–6       ██████████  ✅
M3  Core Analysis Value         Wk 4–8         ████████████  ✅
M4  Revenue                     Wk 6–10            ██████████░░  12/13 done
M5  Growth & Retention          Wk 8–14               ░░░░░░░░░░░░░░░░
M6  Team & API                  Wk 12–18                     ░░░░░░░░░░░░░░░░
M7  Enterprise & Differentiation Wk 16–24+                          ░░░░░░░░░░░░░░░░░░

     ──── SOFT LAUNCH ────       Wk 4
     ──── PUBLIC LAUNCH ────     Wk 8
     ──── TEAM TIER ────         Wk 14
     ──── ENTERPRISE ────        Wk 20+

Revenue milestones:
  Wk 8:   First paying user
  Wk 10:  MRR > $400
  Wk 14:  ARR > $30K
  Wk 20+: ARR > $100K
```

---

## 8. Key Metrics to Track

| Milestone | Metric | Target |
|-----------|--------|--------|
| **M2 (Free Launch)** | Signed-up users | 50+ |
| **M2** | Demo completion rate | > 15% |
| **M3 (Core Value)** | Return usage rate (2nd analysis) | > 40% |
| **M4 (Revenue)** | Free → Pro conversion | > 5% |
| **M4** | MRR | > $400 |
| **M4** | Monthly churn | < 10% |
| **M5 (Growth)** | Monthly active users returning | > 40% |
| **M5** | Users on monitoring subscriptions | 5+ |
| **M6 (Team)** | Team tier adoption (% of Pro users) | > 10% |
| **M6** | ARR | > $30K |
| **M7 (Enterprise)** | Enterprise contracts | 1–2 |
| **M7** | ARR | > $100K |
| **Always** | Cost per AOI processed | < $0.15 |
| **Always** | Pipeline success rate | > 95% |
| **Always** | P95 pipeline latency | < 120s |

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Planetary Computer rate limits or policy change | Low | Critical | Abstract provider; add Copernicus/Element 84 backup |
| AI token costs exceed revenue at scale | Low | Medium | Azure AI Foundry pay-per-token scales linearly; result caching reduces repeat calls; AI as paid add-on |
| Low conversion from free to paid | Medium | High | Track activation metrics; iterate on value gates |
| EUDR regulatory change reduces ESG demand | Low | Medium | Diversify personas; agriculture + conservation don't depend on EUDR |
| AI model quality insufficient | Low | Medium | Azure AI Foundry model catalog lets you swap models (Mistral, GPT-4o, Phi-3) without infra changes |
| Azure Functions cold starts hurt UX | Medium | Medium | Flex Consumption plan; pre-warmed instances for paid tiers |

---

**Next action:** Complete M4.4 (user dashboard) once Cosmos DB is provisioned. Then begin M5 items — monthly NDVI monitoring, shareable analysis links, and external data joins. See GitHub Issues for current backlog.

---

## 10. Competitive Landscape

### 10.1 Direct Competitors

| Competitor | What They Do | Pricing | Strengths | Weaknesses (our opportunity) |
|-----------|--------------|---------|-----------|-----------------------------|
| **Sentinel Hub** (Sinergise / Copernicus) | Sentinel-2 processing API, EO Browser web app | Free tier (limited), then €0.6–€1.2 per processing unit | Excellent Sentinel-2 access, EO Browser is polished, industry standard API | No integrated weather, no AI narratives, no KML-first workflow, steep API learning curve |
| **Planet Labs** | Daily high-res imagery (3–5 m), monitoring API, Explorer web app | Enterprise ($$$, typically $10K+/yr) | Daily revisit, best temporal resolution, powerful monitoring API | Expensive (out of reach for NGOs/SMBs), no integrated analysis, raw imagery only |
| **Google Earth Engine** | Petabyte-scale geospatial compute platform | Free (research), $1/EECU-hr (commercial) | Massive dataset catalog, powerful compute, 40+ year archive | Requires JavaScript/Python coding skills, no self-serve UI for non-developers, no AI layer |
| **Global Forest Watch** (WRI) | Free deforestation monitoring platform | Free | Excellent UX, weekly GLAD alerts, strong brand in conservation | Forest-only (no agriculture/general), no custom AOI upload, no weather integration, not extensible |
| **Descartes Labs** | Geospatial AI platform | Enterprise (custom) | Strong AI/ML, large-scale processing | Enterprise-only, opaque pricing, long sales cycle |
| **UP42** | Geospatial marketplace + processing API | Credits-based (~€0.50–€5 per km²) | Multi-provider catalog, modular processing blocks | Complex credit system, no integrated analysis, developer-focused |
| **Regrow** (formerly FluroSat) | Agricultural sustainability monitoring | Enterprise (custom) | Crop-specific models, MRV for carbon credits | Agriculture-only, enterprise pricing, no conservation/ESG use case |
| **Chloris Geospatial** | Forest carbon / biomass monitoring | Enterprise (custom) | Carbon quantification, science-backed | Narrow carbon focus, enterprise-only |

### 10.2 Where TreeSight Fits

**The gap we fill:** Between free-but-manual tools (Google Earth, GFW) and powerful-but-expensive platforms (Planet, Descartes Labs).

```text
                          Ease of Use
                    High ◄──────────────► Low
              ┌──────────────────────────────────┐
        Free  │  GFW          ▲ TreeSight        │  GEE
              │  (forest only)│ (target position) │  (code required)
              │               │                   │
              │───────────────┼───────────────────│
              │               │                   │
        Paid  │  Sentinel Hub │                   │  Descartes Labs
              │               │                   │  Planet
              │               │                   │  UP42
              └──────────────────────────────────┘
```

**Our differentiation:**

1. **KML-first workflow** — no one else starts from "upload a KML, get analysis back"
2. **Integrated enrichment** — NDVI + weather + fire + flood + AI narrative in one place
3. **Self-serve at SMB price** — $49/mo vs. $10K+/yr for Planet
4. **AI-generated narratives** — plain-English explanations, not just data layers
5. **No GIS skills required** — Google Earth Pro → KML → upload → done

### 10.3 Competitive Moats (What's Defensible)

| Moat Type | Strength | Notes |
|-----------|----------|-------|
| **Workflow simplicity** | Medium | Easy to replicate, but sticky once users build habits |
| **Integrated enrichment** | Medium-High | Combining NDVI + weather + AI + fire/flood is hard to assemble from parts |
| **AI narratives** | Low-Medium | Others will add AI; our advantage is being early and domain-specific |
| **Data network effects** | Future | More users → more cached analyses → faster results → better onboarding samples |
| **Provider abstraction** | Medium | Multi-provider support means we're not locked to Planetary Computer |

---

## 11. Market Sizing

### 11.1 Total Addressable Market (TAM)

The global **Earth observation (EO) services market** is valued at approximately **$7.5B (2025)** and projected to reach **$15–18B by 2030** (~15% CAGR). This includes imagery, analytics, platform services, and value-added products.

The broader **geospatial analytics market** (including GIS, mapping, and spatial analytics) is **~$80B (2025)**.

**TAM for satellite-based environmental monitoring SaaS:** ~$2–3B

### 11.2 Serviceable Addressable Market (SAM)

TreeSight targets **self-serve satellite change detection for non-GIS users** — the segment that:

- Needs satellite analysis but can't afford Planet/Maxar ($10K+/yr)
- Doesn't have GIS staff to use Google Earth Engine
- Wants more than free tools like GFW offer (custom AOIs, weather, AI)

| Segment | Est. Organisations | Willingness to Pay | SAM Contribution |
|---------|-------------------|-------------------|------------------|
| **Conservation NGOs** (global) | ~5,000–10,000 | $50–$200/mo | $3–24M/yr |
| **Agricultural advisors / crop consultants** | ~20,000–50,000 | $50–$150/mo | $12–90M/yr |
| **ESG / supply-chain compliance teams** | ~5,000–15,000 | $150–$500/mo | $9–90M/yr |
| **Academic researchers** (environmental science) | ~50,000+ | $0–$50/mo (mostly free tier) | $0–30M/yr |
| **Local government / land management** | ~10,000–30,000 | $50–$200/mo | $6–72M/yr |

**Total SAM estimate: $30–300M/yr** (wide range reflects uncertainty in conversion rates and willingness to pay)

### 11.3 Serviceable Obtainable Market (SOM) — Year 1

Realistic first-year targets with a small team, no sales force, and product-led growth:

| Metric | Conservative | Optimistic |
|--------|-------------|------------|
| Free users | 500 | 2,000 |
| Paid users (Pro) | 25 | 100 |
| Paid users (Team) | 5 | 20 |
| Enterprise deals | 0 | 2 |
| **ARR** | **~$20K** | **~$100K** |

### 11.4 Market Trends in Our Favour

1. **EU Deforestation Regulation (EUDR)** — effective Dec 2025 — requires companies to prove supply chains are deforestation-free. Creates mandatory demand for satellite change evidence.
2. **ESG reporting mandates** (CSRD, TNFD) — expanding the set of companies that need environmental monitoring data.
3. **Sentinel-2 data becoming commodity** — free imagery lowers the barrier; value shifts to analysis and workflow.
4. **AI making analysis accessible** — non-experts can now get plain-English interpretation of satellite data.
5. **Climate tech funding** — VC investment in climate/sustainability tech remains strong (~$30B+ globally in 2025).
