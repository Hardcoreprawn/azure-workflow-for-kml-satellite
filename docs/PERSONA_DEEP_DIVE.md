# Canopex — Persona Deep Dive & Competitive Strategy

<!-- markdownlint-disable MD028 MD040 -->

**Date:** 25 March 2026 (v2 — updated with competitive intelligence)  
**Status:** Research-backed analysis  
**Purpose:** Obsessive examination of who buys this, why, whether we meet the need, how to price it, and exactly how to position against GFW and GEE.

---

## Table of Contents

1. [Persona Deconstruction](#1-persona-deconstruction)
2. [Jobs-to-be-Done Stress Test](#2-jobs-to-be-done-stress-test)
3. [Community Evidence — What People Actually Say](#3-community-evidence--what-people-actually-say)
4. [Competitive Intelligence Update](#4-competitive-intelligence-update)
5. [Five Positioning Approaches — Tested and Iterated](#5-five-positioning-approaches--tested-and-iterated)
6. [How We Compete vs GFW and GEE](#6-how-we-compete-vs-gfw-and-gee)
7. [Conservation Persona — Exact Needs Map](#7-conservation-persona--exact-needs-map)
8. [ESG/EUDR Persona — Exact Needs Map](#8-esgeudr-persona--exact-needs-map)
9. [Market Sizing — Grounded Estimates](#9-market-sizing--grounded-estimates)
10. [Dual Pricing Model](#10-dual-pricing-model)
11. [Product-Need Fit — Where We Win and Where We Don't](#11-product-need-fit--where-we-win-and-where-we-dont)
12. [Recommendations — Updated](#12-recommendations--updated)
13. [Strategic Feature & Integration Analysis](#13-strategic-feature--integration-analysis)

---

## 1. Persona Deconstruction

### 1.1 Conservation Analyst (NGO / Government)

**Who they really are:**

This is typically a mid-career professional at an environmental NGO (WWF, Rainforest Foundation, WCS, local land trusts) or a government natural resources department. They are not GIS specialists — they are programme managers, field coordinators, or monitoring officers who _use_ GIS outputs but don't want to _produce_ them. Small NGOs (under 20 staff) rarely have a dedicated GIS person. Large NGOs (WRI, Conservation International) have GIS teams but are drowning in manual repetitive work.

**What makes them tick:**

- **Mission-driven, not budget-driven.** They care about impact metrics (hectares protected, enforcement actions triggered). They will fight for budget if the tool demonstrably connects to outcomes.
- **Evidence-obsessed.** Their currency is _proof_. Proof for donors ("we detected 47 ha of illegal clearing in Q3"), proof for enforcement agencies ("here's timestamped satellite evidence"), proof for grant reports.
- **Time-poor, not money-poor.** An NGO monitoring officer covering 15 protected areas doesn't have time to open QGIS for each one monthly. They'll pay $49/month happily if it saves them a day of work per month. A day of their time costs the organisation $200–$400.
- **Technologically conservative.** They use Google Earth, Google Sheets, WhatsApp. Not PostGIS, not Jupyter notebooks. KML is actually their native format — they draw polygons in Google Earth Pro.
- **Seasonal urgency.** Deforestation follows dry seasons. Fire risk peaks. Donor reporting cycles are quarterly. They need results _now_, not in 4–8 weeks from a consultancy.

**Their buying process:**

1. Programme manager sees deforestation happening, needs evidence → searches for tools
2. Finds Global Forest Watch (free but coarse), tries Sentinel Hub (confusing, requires bands/indices knowledge)
3. Hears about Canopex from a colleague, GIS forum, or conservation Slack
4. Tries free tier → uploads a KML they already have from Google Earth
5. If analysis is useful → shows to supervisor → gets budget approval for Pro ($49) immediately (under most NGO discretionary spend thresholds of $100/month)
6. Team tier ($149) requires a procurement process — budget code, maybe quarterly approval

**Critical insight: the $49 Pro tier is below the "procurement pain" threshold for most NGOs.** This means self-serve conversion without sales calls. The $149 Team tier is not — it requires justification, but a one-page "time saved" calculation makes it easy.

### 1.2 Agricultural Advisor (Agritech / Crop Insurance)

**Who they really are:**

Two sub-segments:

**a) Agritech consultants** — Small firms (2–10 people) advising farmers on precision agriculture. They visit farms, take soil samples, make recommendations. Satellite imagery is a "nice to have" that they know about but don't use because the tools are intimidating and the cost of Planet/Maxar imagery is absurd for their per-farm revenue.

**b) Crop insurance adjusters** — Work for insurance companies or as independent loss adjusters. After a weather event (drought, flood, hail), they need to assess crop damage across many insured parcels. Currently they drive to every field, or they trust farmer self-reports (fraud risk).

**What makes them tick:**

- **ROI calculators.** Unlike NGO users, these people measure everything in $ per hectare. If Canopex saves them 2 field visits at $150/visit, it pays for itself in one analysis.
- **Batch-centric.** They don't have 1 AOI — they have 50–500 parcels. The per-AOI price _matters critically_ here. At $1/AOI overage, processing 200 parcels on the Team tier costs $149. At $2/AOI it costs $149 + 0 (included). This segment is the most price-sensitive to the per-AOI rate.
- **Seasonal peaks.** Insurance claims spike after major weather events. Agritech consulting peaks in planting and harvest seasons. Usage is lumpy, not steady.
- **Already have KMLs.** Insurance companies maintain polygon boundaries of insured parcels. Agritech firms get field boundaries from farmers or government cadastral databases. KML upload is natural.
- **Need defensible evidence.** Insurance companies need analysis that can withstand dispute. "Our satellite analysis shows NDVI dropped 60% in field X between May and July, consistent with the reported drought" is a powerful claim — but only if the methodology is transparent and auditable.

**Their buying process:**

1. Insurance company has a weather event → needs rapid assessment of 200+ parcels
2. Current process: send adjusters to the field ($$, slow) or trust farmer reports (fraud risk)
3. Decision-maker: claims manager or underwriting VP
4. Trial: free tier for a few test parcels → if NDVI correlation with known damage is accurate → buy
5. This is an **enterprise sale** ($149 Team or custom Enterprise). They don't buy 1 Pro seat — they buy a capability.

**Critical insight: this persona buys in bulk and cares about per-unit cost.** A $49 subscription with 50 AOIs is useless to them. They need 200+ AOIs per event. The Team tier at $149/200 AOI ($0.75/AOI effective) is competitive, but the $1/AOI overage means 500 AOIs costs $149 + $300 = $449. That's fine, but they'll compare to doing it in QGIS themselves (free but slow).

### 1.3 ESG / Supply-Chain Compliance

**Who they really are:**

This is the newest and potentially largest segment, driven by regulation:

- **EU Deforestation Regulation (EUDR):** Requires companies importing cattle, cocoa, coffee, oil palm, rubber, soya, and wood into the EU to prove their supply chains are deforestation-free. Operators must provide geolocation data (coordinates of production plots) and demonstrate no deforestation occurred after 31 December 2020. The regulation applies to companies of _all sizes_ importing these commodities. Fines can reach 4% of EU-wide turnover.
- **Corporate sustainability reporting:** CSRD in the EU, SEC climate disclosure rules (contested), UK Climate-Related Financial Disclosures.

**Who specifically:**

- Sustainability managers at food/commodity companies (Nestlé, Cargill, Unilever — but also mid-sized importers)
- ESG analysts at asset managers and banks (screening portfolio companies for deforestation risk)
- Compliance officers at trading houses (Bunge, ADM, Louis Dreyfus, COFCO)
- Consultancies doing EUDR audits on behalf of smaller importers

**What makes them tick:**

- **Regulatory deadline pressure.** EUDR enforcement was delayed to December 2025 for large operators and June 2026 for SMEs. This creates a _massive_ wave of demand for tools that can produce the required geolocation evidence, right now.
- **Auditability over accuracy.** They need a tool that produces a _defensible audit trail_ more than one that's perfect. The methodology must be transparent, reproducible, and exportable. A 10-page report with timestamps, satellite imagery, NDVI trends, and AI narrative analysis is exactly what an auditor wants to see.
- **Scale varies wildly.** A Cargill has 500,000+ sourcing plots. A small chocolate maker importing from Ghana has 50. Canopex's sweet spot is the 50–5,000 plot range — big enough to be painful manually, small enough that they won't build in-house.
- **Will pay premium prices.** EUDR non-compliance fines are 4% of EU turnover. Compared to that, $149/month is a rounding error. Even $10,000/year is cheap insurance. This segment has the highest willingness to pay, but they also have the highest expectations for audit-quality output.

**Their buying process:**

1. Regulation deadline approaching → sustainability team scrambles
2. Options: (a) hire a consultancy ($10K–$50K per assessment, 4–8 weeks) or (b) buy a tool
3. Discovery: "satellite deforestation monitoring tool" → finds GFW (free, but no audit export), Planet (expensive, requires GIS expertise), Canopex (KML upload, audit-ready reports)
4. Trial: test with known supply chain locations → evaluate report quality
5. If report is credible → procurement (this is an enterprise sale, usually $5K–$50K/year)

**Critical insight: this persona doesn't care about the subscription fee — they care about per-plot audit cost and report quality.** The ideal pricing for them is per-assessment (like a consultancy), not per-month. But they'll accept monthly subscription with per-AOI charges if the total cost is far below a consultancy engagement.

---

## 2. Jobs-to-be-Done Stress Test

### 2.1 Does Canopex Actually Solve the Job?

| JTBD Component | Conservation | Agriculture | ESG Compliance |
|----------------|-------------|-------------|----------------|
| **Trigger event** | Report of illegal clearing / donor report due / seasonal monitoring cycle | Weather event / planting season / insurance claim | Regulatory deadline / investor query / annual sustainability report |
| **Functional job** | Detect and quantify vegetation change in a defined area | Assess crop health across multiple parcels and correlate with weather | Prove a supply chain location is deforestation-free since a cutoff date |
| **Emotional job** | Feel confident presenting evidence to enforcement/donors | Feel professional using data-driven advice | Feel secure that the company won't be fined |
| **Social job** | Be seen as rigorous and evidence-based by peers | Be seen as modern/tech-savvy by farmer clients | Be seen as compliant by auditors and investors |
| **Canopex delivers?** | **Mostly yes.** NDVI change detection, timestamped imagery, AI narrative. Missing: scheduled monitoring/alerts (M4+), comparison view done (M3). | **Partially.** NDVI and weather correlation exists. Missing: batch upload UX for 200+ KMLs, CSV export of per-parcel NDVI timeseries, crop-specific indices (EVI, SAVI). | **Partially.** Before/after evidence exists. Missing: formal audit report template, EUDR-specific date range (post Dec 2020), quantified "no deforestation" certificate format. |

### 2.2 The Honest Gap Analysis

**Conservation: 70% fit.** The core analysis pipeline does what they need. The main gap is _monitoring_ — they want "alert me when something changes," not "let me check manually." Scheduled re-analysis (PRODUCT_ROADMAP §4.5) closes this gap. Without it, Canopex is a one-shot tool; with it, it becomes daily infrastructure.

**Agriculture: 50% fit.** The NDVI + weather correlation is genuinely differentiated. But ag users work in _batch_ — they don't upload one KML at a time. They upload a shapefile with 200 parcels and want a CSV back with NDVI trends per parcel. The current one-at-a-time demo flow is friction. Multi-polygon KML support (M3.7) helps but doesn't fully close the gap. This persona also needs crop-specific vegetation indices (EVI for dense canopy, SAVI for sparse) — NDVI alone isn't sufficient for all crop types.

**ESG Compliance: 60% fit.** The before/after capability and AI narrative are exactly what they want. The gaps are: (a) no formal audit report PDF (M4.5 closes this), (b) no EUDR-specific date filtering (easy to add — constrain imagery search to post-2020), (c) no batch processing for large supply chains, (d) no "deforestation-free certificate" output format that an auditor would recognise.

### 2.3 The Detection vs. Action Gap

A crucial finding from the Reddit /r/conservation community (thread: "We have high-res satellite imagery updated daily. Why can't we tackle illegal deforestation?"):

> "Identifying it is the smallest part of the problem. Enforcement, providing alternate livelihoods, developing local will and motivation to change... is what's needed."

> "You know how many satellites are watching the Amazon? How many AI algorithms are tracking deforestation in real time? [...] The issue isn't detection — it's governance."

**What this means for Canopex:** Detection tools are necessary but not sufficient. Our conservation persona doesn't just need imagery — they need _evidence that triggers action_. The AI narrative feature is actually more valuable than the imagery itself because it translates satellite data into language that non-technical enforcement officers and courts can use. This is a positioning insight: **we're not a satellite imagery tool; we're an evidence generation platform.**

---

## 3. Community Evidence — What People Actually Say

### 3.1 Sources Reviewed

- Reddit r/gis, r/remotesensing, r/conservation (multiple threads, 2024–2026)
- GIS StackExchange (satellite-imagery tag)
- GIS community tool recommendation threads
- Global Forest Watch about/impact page

### 3.2 Pain Points (Verbatim and Paraphrased)

**Cost of commercial imagery:**

> "You can get satellite imagery for about $1,800 for 50 km² from Maxar/Vantor, so it's not cheap." — r/gis  

> "Nearmap does a subscription model, 4.4–7cm resolution. It's not pay-per-image." — r/gis  

> "[SkyFi] is good for looking at archive data. Commercial imagery starts at $25 per order." — r/gis

**Implication for Canopex:** We use free Sentinel-2 imagery via Planetary Computer. This is a massive cost advantage, but it comes at the expense of resolution (10m/px vs. 30cm for Maxar). For conservation (deforestation = large-area change), 10m is sufficient. For agriculture (individual tree health), it may not be.

**Tool complexity:**

> "Google Earth Engine is free but you need to know JavaScript/Python to use it. Not accessible to non-coders." — multiple threads  

> "Sentinel Hub is powerful but the learning curve is steep. Choosing bands, composites, atmospheric correction..." — r/gis  

> "Felt just got too expensive." — r/gis (2026 thread on "best geo tools")

**Implication:** There's a clear gap between "free but complex" (GEE, QGIS) and "simple but expensive" (Planet, Nearmap). Canopex sits in this gap: simple (KML upload) and cheap (free Sentinel-2 data).

**KML as a format:**

> "kmzmap.com — free KML viewer" mentioned as a useful tool in r/gis  

> Multiple mentions of Google Earth Pro for creating KML boundaries  

> KMZ (compressed KML) is the default save format in Google Earth Pro

**Implication:** KML is not a dead format. It's the _lingua franca_ of non-GIS professionals who use Google Earth. Our KML-first approach is correct for our target segment. GIS professionals might prefer GeoJSON/Shapefile, but they're not our primary target.

**Monitoring as the real need:**

> "I want to be notified when something changes in my area, not check manually every month." — paraphrased from conservation community  

> Global Forest Watch: "Thousands of people around the world use GFW every day to monitor and manage forests, stop illegal deforestation and fires" — 9 million visitors since 2014

**Implication:** Monitoring (scheduled re-analysis + alerts) is not a nice-to-have — it's the core value for the conservation persona. Without it, we're a one-shot analysis tool competing with EO Browser. With it, we're a monitoring platform competing with Global Forest Watch (which has alerts but no per-AOI AI analysis).

### 3.3 Tools People Actually Use and Recommend

| Tool | Mentions | Use Case | Price |
|------|----------|----------|-------|
| **Google Earth Pro** | Very common | Viewing, creating KML, basic analysis | Free |
| **Global Forest Watch** | Common (conservation) | Deforestation alerts, forest dashboards | Free |
| **Sentinel Hub / EO Browser** | Common (technical) | Custom band composites, time-lapse | Free tier exists; $35–$420+/month for API |
| **Planet** | Common (professional) | Daily imagery, monitoring | $2,700–$9,650/year per area |
| **SkyFi** | Mentioned (archival) | On-demand commercial imagery ordering | From $25/order (optical), $5/analytics |
| **QGIS** | Very common (GIS pros) | Full analysis, free/open source | Free |
| **Google Earth Engine** | Common (researchers) | Code-based analysis on Google cloud | Free for research; commercial pricing unclear |
| **Felt** | Mentioned (mapping) | Collaborative mapping | "Got too expensive" |
| **UP42** | Mentioned (marketplace) | Buy imagery + processing via credits | Credits (100 credits = €1), no subscription |
| **Nearmap** | Mentioned (aerial) | Ultra-high-res aerial, subscription | Subscription (price unlisted) |

---

## 4. Competitive Intelligence Update

**Critical finding: our previous analysis underestimated our competitive advantages.** Deep research into GFW Pro and GEE licensing reveals structural advantages we hadn't identified.

### 4.1 GFW Pro — Now with Real Pricing (Effective Nov 2025)

GFW Pro is NOT simply "free." It has a consumption-based pricing model:

| Metric | Detail |
|--------|--------|
| **Free annual grant** | 5,000 MLAs (Monitored Location Analyses) + 50 million HOPs (Hectares of Processing) per account |
| **Beyond free grant** | Consumption-based Usage Tokens (computational actions) + HOPs (area-based) |
| **Volume discounts** | Start at $20K+/year annual commitment |
| **API access** | Separate Annual API Access Rights purchase |
| **Usage controls** | Warning at 90% consumption, disabled at 100% (must purchase more) |
| **Access model** | Account request only — NOT self-serve. Must apply and be approved. |
| **Lists** | Up to 150,000 locations per list |
| **Analysis types** | Post-2000 Forest Change, Post-2020 Risk Assessment, Recent Disturbance Alerts, GHG LUC Emissions Analysis — **deforestation only** |
| **Named users** | Cargill, Mondelez, Olam, IDB Invest |

**What 5,000 MLAs/year means:** One MLA = one Analysis Type × one Location. If you have 100 locations and run 4 analysis types on each, that's 400 MLAs per run. 5,000 MLAs gives you ~12 full runs/year (monthly monitoring) for 100 locations at 4 analyses each. For a large operator with 1,000 locations, the free grant covers only 1–2 full runs.

**GFW Free (Map/Dashboards):** Global deforestation dashboards, tree cover loss/gain 2001–2024, fire alerts, deforestation alerts at national/subnational level. Powerful for global visualization but no per-AOI custom analysis, no weather, no AI insight, no exportable evidence reports. 9M+ visitors since 2014.

**What GFW Pro does NOT do:**

- No NDVI trend analysis (only forest change/disturbance)
- No weather correlation
- No AI-generated narrative
- No custom analysis types (e.g. flood impact, crop health)
- No self-serve sign-up
- No individual/small-org pricing — designed for enterprises and financial institutions

### 4.2 Google Earth Engine — NOT Free for Commercial Use

**This is the single most important competitive finding.** GEE's licensing is far more restrictive than commonly believed:

| Use Case | GEE Free? | Details |
|----------|-----------|---------|
| Academic research | ✅ Yes | Research at accredited institutions |
| Academic teaching | ✅ Yes | Course material, student projects |
| Non-profit (internal, non-commercial) | ✅ Yes | Mission-aligned, non-revenue work |
| Journalism/media | ✅ Yes | News reporting |
| Individual non-commercial | ✅ Yes | Personal projects, hobby use |
| **Non-profit doing fee-for-service** | ❌ **NO** | "Cannot perform compensated fee-for-service work on behalf of government or commercial entities" |
| **Commercial/for-profit use** | ❌ **NO** | Requires commercial license |
| **Government operational use** | ❌ **NO** | Cannot use for "datasets, apps, services maintained on an ongoing basis" or "producing large datasets for operational workloads" |
| **ESG consultancy (paid compliance work)** | ❌ **NO** | Fee-for-service = commercial license required |

**Why this matters enormously for our two target personas:**

1. **Conservation NGO doing paid consultancy:** Many conservation NGOs supplement funding by providing paid monitoring services to governments or corporations. Under GEE licensing, this fee-for-service work requires a commercial GEE license. Canopex has no such restriction.

2. **ESG compliance teams:** A sustainability manager at a food importer doing EUDR compliance is doing _commercial work_. An ESG consultancy auditing supply chains is doing _fee-for-service work_. Neither can use GEE's free tier. They need either (a) a commercial GEE license (opaque pricing, reportedly expensive) or (b) an alternative tool.

**Additional GEE friction (effective April 27, 2026):** Google is introducing noncommercial quota tiers with usage limits. Even eligible free users will face new caps. Details pending, but this adds friction to the "GEE is free" narrative.

**GEE's undeniable strengths:**

- 80+ petabytes of geospatial data
- Massive compute infrastructure
- Full catalogue of satellite data (Sentinel, Landsat, MODIS, etc.)
- Extremely flexible — any analysis you can code, you can run
- Huge community, extensive documentation

**GEE's structural weaknesses (for our personas):**

- Requires JavaScript or Python proficiency
- No-code interface does not exist
- Commercial licensing is complex and non-transparent
- No workflow for "KML → report" — every analysis starts from code
- No weather integration (must code separately)
- No AI narrative generation

### 4.3 Updated Competitor Matrix

| Competitor | Overlap | Their Advantage | Our Advantage | Threat Level |
|-----------|---------|-----------------|---------------|-------------|
| **GFW Pro** | High (conservation/EUDR) | 5,000 free MLAs/year, WRI/Google/NASA backing, 150K locations per list, used by Cargill/Mondelez | Self-serve (no account request), not deforestation-only, weather + AI, any analysis type, no consumption lock-in | **Medium-High.** Generous free grant for large enterprises, but they can't serve small/mid orgs and aren't self-serve. |
| **GFW Free** | Medium (conservation monitoring) | Free, global coverage, weekly alerts, massive brand (9M visitors) | Per-AOI custom analysis, weather, AI narrative, exportable evidence, NDVI trends | **Medium.** GFW free is a gateway — users hit limits and look for more. We're the "more." |
| **Google Earth Engine** | Medium (analysis capability) | 80+ PB data, massive compute, full analytical flexibility, huge community | No code required, no commercial license needed, weather integrated, AI narrative, KML-first workflow | **Medium.** GEE is immensely powerful but requires coding and isn't free for commercial use. Different audience. |
| **Sentinel Hub / EO Browser** | Medium (Sentinel-2 analysis) | Now merged with Planet, massive band flexibility, split-view comparisons | No-code simplicity, AI narrative, weather integration, focused KML → report workflow | **Medium.** Different audience — GIS professionals vs. non-specialists. |
| **Planet** | Low-Medium (monitoring) | Daily 3.7m imagery, forest monitoring product | Free (vs. $2,700–$9,650/year), AI narrative, weather integration | **Low.** Different price tier entirely ($5K–$50K/year). |
| **SkyFi** | Low (imagery access) | Multi-sensor marketplace, transparent per-order pricing | Analysis included (not just imagery), AI narrative, automated workflow | **Low.** SkyFi sells imagery; we sell analysis. |
| **QGIS + manual** | High (the default) | Free, unlimited, no vendor lock-in | 50–100x faster, no GIS skills needed, integrated workflow | **High.** Inertia is our biggest competitor. |
| **Consultancy firms** | Medium (ESG) | Trusted brand, human judgment, established relationships | 1000x faster, fraction of cost ($19–49/mo vs. $10K–$50K engagement) | **Medium.** We must build trust to match. |

### 4.4 The Google Earth Engine Risk — Revised Assessment

Previous assessment overestimated this risk. Key reassessment:

**Original fear:** "If Google ships a no-code GEE, we're dead."

**Revised reality:**

1. Google has had GEE since 2010 and has never built a simplified no-code version. Their culture builds developer tools.
2. GEE's commercial pricing means even a no-code version wouldn't be free for our target personas.
3. Google's April 2026 quota tiers show them _adding_ friction, not removing it.
4. Our integration of weather + NDVI + fire + flood + AI narrative in one workflow is unique — GEE could match each piece but assembling them requires custom code.
5. Speed: we iterate in weeks, Google product launches take quarters/years.

**Remaining risk:** If Google builds a no-code GEE AND makes it free for commercial use AND integrates weather/AI. This would require Google to reverse their commercial pricing strategy. Possible but unlikely.

**Actual existential risk:** A well-funded startup building exactly what we build but with $10M in VC funding and a sales team. This is more likely than Google eating our lunch. Our moat is execution speed and domain focus.

---

**Actual existential risk:** A well-funded startup building exactly what we build but with $10M in VC funding and a sales team. This is more likely than Google eating our lunch. Our moat is execution speed and domain focus.

---

## 5. Five Positioning Approaches — Tested and Iterated

The user asked: "try 5 different approaches, and dig into each 3-4 times to find out a better positioning point." Below, each approach is stated, stress-tested through 3–4 iterations, and scored.

### 5.1 Approach A: "Evidence Generation Platform"

**v1 — Initial statement:**  
"Canopex is an automated satellite evidence platform for conservation and compliance."

Core idea: we don't sell imagery (Planetary Computer gives that away free) and we don't sell analysis (GEE does that for coders). We sell _evidence_ — the transformation of raw satellite data into actionable, auditable, human-readable proof.

**v2 — Stress test: who does this resonate with?**

| Persona | Resonance | Why |
|---------|-----------|-----|
| Conservation NGO | **Strong.** Their currency is proof — for donors, enforcement, grants. "Evidence" maps directly to their job outcome. | "Can I show this report to a magistrate/donor?" |
| ESG compliance | **Very strong.** EUDR requires _evidence_ of no deforestation. The word "evidence" speaks their regulatory language. | "Can I attach this to our EUDR due diligence file?" |
| Agriculture | **Weak.** Ag advisors don't need "evidence" — they need _insight_ (when to irrigate, is the crop stressed?). Wrong word. | "I need crop health data, not evidence." |
| Academic researcher | **Weak.** They produce their own evidence through research. They need _data and tools_, not pre-packaged evidence. | "I need Sentinel-2 bands, not a report." |

**Iteration 1 conclusion:** Strong for our top two personas, weak for the others. Since we're focusing on conservation + ESG, this is fine. But "evidence" might sound legalistic — does it scare off the conservation analyst who just wants to see if their forest is OK?

**v3 — Refinement: softening for conservation while keeping compliance edge.**

Split the framing by persona:

- **For conservation:** "Turn your KML into satellite evidence in 5 minutes"
- **For ESG/EUDR:** "Automated deforestation-free evidence for EUDR compliance"
- **Universal:** "From boundary to evidence — satellite analysis without the GIS degree"

Test: does "evidence" work as a category label for the product?

Evidence products:

- Audit trail → enterprise
- Proof of no-change → compliance
- Timestamped documentation → enforcement
- Grant reporting material → NGO

Yes — "evidence" is the through-line connecting all use cases. It's the _output format_, not the _input technology_. This distinguishes us from tools that sell _capability_ (GEE: "analyse anything with code") or _data_ (Planet: "daily imagery").

**v4 — Final test: does this position survive competitive pressure?**

- GFW Pro: also produces evidence, specifically for deforestation. But it's deforestation-only, enterprise-only, account-request-only. We produce evidence for _any land-use change_, self-serve, for any org size.
- GEE: produces raw analysis that a skilled coder turns into evidence. We produce evidence directly.
- Consultancy: produces evidence, but at $10K–$50K and 4–8 weeks. We produce it in 5 minutes at $19/month.

**Verdict: STRONG. "Evidence generation platform" survives all competitive tests.** The word "evidence" differentiates from "analysis", "imagery", and "monitoring." It speaks to outcomes (what the user does with the output), not inputs (satellite data).

**Score: 9/10** — Lose one point because "evidence" might feel unfamiliar as a software category.

---

### 5.2 Approach B: "The Self-Serve Gap Filler"

**v1 — Initial statement:**  
"Canopex fills the gap between free-but-complex tools (GEE, QGIS) and enterprise-only platforms (GFW Pro, Planet)."

Core idea: position on the market structure itself. There's a clear gap — tools that are powerful but require coding/GIS skills on one side, and enterprise platforms requiring $5K+/year and sales calls on the other. Nothing sits in the middle for the non-technical professional with a modest budget.

**v2 — Stress test: is this actually true?**

| Price Range | Tools Available | Skill Required |
|-------------|----------------|----------------|
| Free | GEE (coding), QGIS (GIS), GFW Map (view-only) | High |
| $0 with limits | GFW Pro (5,000 MLAs/year, account request) | Medium (their UI) |
| $19–49/month | **Nobody.** This is the gap. | — |
| $35–420/month | Sentinel Hub API (band knowledge needed) | High |
| $2,700+/year | Planet (GIS expertise) | Medium-High |
| $10K+/year | Consultancy | No skill needed (they do it) |

The gap is real. Between "free + complex" and "$2,700+/year", there is genuinely nothing that a non-technical professional can use for under $50/month to get satellite analysis of their specific AOI.

**v3 — Stress test: does "gap filler" make a compelling story?**

Problem: "gap filler" is how _we_ see the market, not how the _buyer_ sees it. A conservation analyst doesn't think "I need something between GEE and Planet." They think "I need to know if my forest is being cut down." Positioning on market structure is an investor pitch, not a user pitch.

**Iteration 2 conclusion:** True and useful for investor/strategy conversations. Wrong for marketing to actual users. Users don't buy "gap filler" — they buy solutions to their problem.

**v4 — Refinement: reframe as the user experience.**

Turn the structural insight into a user-facing message:

- "Satellite analysis anyone can use. No coding. No contracts. No GIS degree."
- "The satellite tool that doesn't require a PhD or a purchase order."

This takes the structural truth (gap in the market) and makes it experiential. Better.

But: this is a _feature description_ ("easy to use"), not a _value proposition_ ("you get evidence"). Any competitor could claim "easy to use" — it's not defensible.

**Verdict: USEFUL for messaging, NOT strong enough as primary positioning.** The gap is real and should inform pricing strategy and go-to-market, but it's a supporting argument, not the lead.

**Score: 6/10** — True but not emotionally compelling. Good secondary message.

---

### 5.3 Approach C: "Compliance-First Satellite Tool"

**v1 — Initial statement:**  
"Canopex is the compliance officer's satellite tool — EUDR evidence in 5 minutes, not 5 weeks."

Core idea: lead with the regulatory use case. EUDR enforcement is imminent (Dec 2025 large operators, June 2026 SMEs). Companies are scrambling. Position Canopex as the fastest, cheapest path to EUDR compliance evidence.

**v2 — Stress test: how many buyers does this reach?**

EUDR affects companies importing cattle, cocoa, coffee, oil palm, rubber, soya, and wood into the EU. EU Commission estimates ~3,000 large operators + many more SMEs. The addressable market is real but narrow.

Problem 1: If we position as "compliance tool," we lose the conservation persona entirely. Conservation analysts don't have a compliance requirement — they have a mission.

Problem 2: Compliance positioning attracts compliance buyers who expect _regulatory certainty_. Can we guarantee our analysis meets EUDR requirements? Today: no. We'd need validation against the EUDR Information System, accepted methodology documentation, and possibly third-party verification. Claiming "EUDR compliance" without this validation is dangerous (legal risk, reputation risk).

**v3 — Stress test: what does "compliance-first" mean practically?**

To legitimately claim "EUDR compliance tool," we'd need:

1. Post-2020 date filtering (analyse only after 31 Dec 2020 baseline) — easy to add
2. Geolocation coordinates in the required EUDR format — moderate
3. Quantified deforestation assessment methodology that auditors accept — **hard**
4. Integration with the EU EUDR Information System — **uncertain (system not fully operational)**
5. Defensible methodology documentation — **medium**

We can produce _evidence that supports_ EUDR compliance, but we can't claim to _provide_ EUDR compliance. The distinction matters.

**Iteration 3 conclusion:** "Compliance tool" overclaims. "Evidence for compliance" is accurate.

**v4 — Refinement: soften the claim, keep the urgency.**

- ❌ "EUDR compliance tool" (overclaims)
- ✅ "Satellite evidence for EUDR due diligence"
- ✅ "Automated deforestation screening for supply chain compliance"

This is accurate — we produce one input to the compliance process, not the entire process. It's still compelling because the alternative is $10K+ consultancy or manual GIS work.

But as _primary_ positioning, this limits our addressable market to EUDR-affected companies. Conservation gets left out. And EUDR enforcement could be delayed again (it was already delayed once) — building positioning on a regulatory deadline is risky.

**Verdict: STRONG as a vertical message for the ESG persona. WRONG as overall product positioning.** Use compliance messaging on the ESG-targeted landing page, not on the homepage.

**Score: 7/10 for ESG vertical, 4/10 as overall positioning.**

---

### 5.4 Approach D: "Monitoring Made Easy"

**v1 — Initial statement:**  
"Canopex tells you when your land changes — upload a boundary, get satellite monitoring."

Core idea: lead with the monitoring/alerting value. This is what conservation users actually want (the Reddit evidence: "I want to be notified when something changes"). Position as a monitoring service, not a one-shot analysis tool.

**v2 — Stress test: can we deliver this today?**

**No.** At present, Canopex offers one-shot analysis. Scheduled monitoring/alerts are on the roadmap (PRODUCT_ROADMAP M5.1/5.3) but not built. Positioning on a capability we don't have yet is dishonest and sets up user disappointment.

**v3 — Stress test: what if we position on where we're going, not where we are?**

If we build monitoring (M5.1 — estimated "High" effort), the positioning becomes accurate. But:

- GFW already offers deforestation alerts (free, global, weekly). We'd be competing head-on with a free, established tool.
- Planet offers daily monitoring at 3.7m resolution. We'd be competing with far higher resolution.
- Our advantage: _per-AOI monitoring with AI narrative + weather context_. GFW alerts say "deforestation detected." We'd say "NDVI dropped 35% in your AOI between March and April. Weather data shows no drought — this change is likely anthropogenic. Here's the before/after imagery and AI analysis."

**Iteration 3 conclusion:** "Monitoring" positions us against GFW's biggest strength (alerts) where they have massive incumbency advantage. Bad battlefield to choose.

**v4 — Refinement: monitoring as a feature, not positioning.**

"Automated satellite evidence for conservation and compliance. _With monthly monitoring alerts._"

Monitoring is a feature that supports the "evidence platform" positioning, not a separate positioning in itself. Users buy Canopex for evidence → monitoring keeps them subscribed → alerts deliver ongoing evidence.

**Verdict: WRONG as primary positioning today. GOOD as a feature message once monitoring ships.** Don't lead with monitoring — lead with evidence, upgrade to monitoring as a retention feature.

**Score: 5/10 as positioning (not built yet, fights GFW's strength), 8/10 as feature message.**

---

### 5.5 Approach E: "The Anti-GIS Tool"

**v1 — Initial statement:**  
"Satellite analysis without the GIS degree. Upload your KML, get results in 5 minutes."

Core idea: position directly against the complexity and expertise required by every other tool. GEE needs coding. QGIS needs GIS skills. Sentinel Hub needs band knowledge. We need... a KML file you drew in Google Earth.

**v2 — Stress test: does "anti-GIS" resonate or alienate?**

Resonates with:

- Conservation programme managers who dread asking the GIS person for help
- ESG compliance officers who've never heard of NDVI
- Small NGO staff-of-all-trades who don't have a GIS person

Alienates:

- GIS professionals who might evaluate the tool (and dismiss it as "dumbed down")
- Technical buyers who want to know we're rigorous
- Anyone who searches "satellite analysis" and expects a professional tool

**v3 — Stress test: is this defensible?**

"No GIS required" is only valuable because the alternatives require GIS. If any competitor ships a simple interface, this positioning evaporates. It's a _feature differentiator_ that exists today because nobody else has built simplified UX — not a structural advantage.

Compare: "Evidence generation platform" is defensible because the _output format_ (evidence) is structurally different from what competitors produce. "No GIS required" is about UX, which can be copied.

**Iteration 3 conclusion:** Correct observation, weak strategic moat. Any well-funded competitor can build a simple UX.

**v4 — Refinement: pair simplicity with unique output.**

- ❌ "Satellite analysis without the GIS degree" (UX claim, copyable)
- ✅ "Satellite evidence without the GIS degree" (output claim + UX claim)
- ✅ "KML to evidence in 5 minutes — no coding, no GIS, no consultancy"

The refinement keeps the simplicity message but anchors it to the evidence output. Now two things must be true for a competitor to match: (1) simple UX AND (2) evidence-quality output. Harder to copy both.

**Verdict: STRONG as the supporting message to "evidence generation platform." WRONG as standalone positioning** because UX simplicity alone isn't a moat.

**Score: 7/10 paired with evidence positioning, 5/10 standalone.**

---

### 5.6 Positioning Synthesis — The Winner

| Approach | Score | Best Use |
|----------|-------|----------|
| **A: Evidence Generation Platform** | **9/10** | **Primary product positioning** |
| B: Self-Serve Gap Filler | 6/10 | Investor pitch / pricing strategy rationale |
| C: Compliance-First | 7/10 (ESG), 4/10 (overall) | ESG vertical landing page |
| D: Monitoring Made Easy | 5/10 | Feature message after monitoring ships |
| E: Anti-GIS Tool | 7/10 (paired), 5/10 (alone) | Supporting message / tagline |

**Recommended positioning architecture:**

| Layer | Message | Where |
|-------|---------|-------|
| **Hero positioning** | "Automated satellite evidence for conservation and compliance" | Homepage, meta description, social bios |
| **Tagline** | "From KML to evidence in 5 minutes" | Homepage hero, marketing materials |
| **Supporting** | "No coding. No GIS degree. No consultancy fees." | Below hero, feature section |
| **ESG vertical** | "Satellite evidence for EUDR due diligence" | ESG landing page, LinkedIn ads |
| **Conservation vertical** | "Satellite evidence for protected area monitoring" | Conservation landing page, NGO outreach |
| **Investor/press** | "Filling the gap between free-but-complex and enterprise-only in satellite analysis" | Pitch deck, press releases |

**The competitive wedge this drives:**

- vs GFW: "GFW shows you global dashboards. Canopex produces per-AOI evidence _for your specific locations_ with AI analysis, weather context, and exportable reports."
- vs GEE: "GEE gives you 80 petabytes of data and a JavaScript editor. Canopex gives you _evidence_ from a KML upload — no code, no commercial license, 5 minutes."
- vs Consultancy: "A consultancy charges $10K and takes 8 weeks. Canopex produces the same evidence for £19/month in 5 minutes."
- vs QGIS: "QGIS is free and unlimited. Canopex takes what used to be a full day of QGIS work and does it in 5 minutes with AI interpretation."

---

## 6. How We Compete vs GFW and GEE

### 6.1 Competing with Global Forest Watch

**Understanding GFW's position:** GFW is a _public good_ funded by WRI, Google, and others. Its mission is to make forest data accessible to everyone. It's not a commercial competitor — it's an ecosystem player. We don't need to "beat" GFW; we need to be the tool people graduate to when GFW isn't enough.

**Where GFW wins (and we shouldn't fight):**

| GFW Strength | Why We Can't Win Here |
|-------------|----------------------|
| Global forest dashboards | They process the entire planet. We process individual AOIs. Different scale. |
| Real-time deforestation alerts (GLAD) | They have NASA/Google backing producing global alerts. We can't match this. |
| Brand trust (WRI, Google, 9M visitors) | Decades of reputation. We have zero brand. |
| Free for everyone | They're grant-funded. We need revenue. |

**Where GFW loses (and we should attack):**

| GFW Weakness | Our Advantage | How to Message |
|-------------|---------------|----------------|
| **No per-AOI custom analysis.** GFW shows you a map with layers. It doesn't analyse _your specific boundary_ with quantified metrics. | Our entire product is per-AOI: upload your KML, get analysis of that specific area. | "GFW shows the world. Canopex analyses _your_ sites." |
| **No AI narrative.** GFW dashboards are data — the user interprets them. No plain-English explanation. | Canopex generates AI analysis explaining what changed, why it likely changed, and what it means. | "From data to insight — without staff to interpret satellite imagery." |
| **No weather correlation.** GFW shows forest change but not whether it correlates with drought, flood, or human activity. | Canopex integrates Open-Meteo weather: temperature, precipitation, drought indices correlated with vegetation change. | "Know whether NDVI dropped because of drought or because of deforestation." |
| **Deforestation only.** GFW analyses forest change.  It doesn't handle crop health, flood impact, fire damage, or arbitrary land-use change. | Canopex analyses any land-use change: forest, crop, wetland, urban fringe, anything with NDVI-responsive vegetation. | "Not just forests — any land area, any change type." |
| **No exportable evidence reports.** GFW shows data on screen. Getting it into a donor report, enforcement filing, or EUDR submission requires screenshots and manual work. | Canopex exports structured reports (PDF/JSON/CSV) designed for inclusion in reports and filings. | "Export-ready evidence for donors, enforcement, and auditors." |
| **GFW Pro is enterprise-only.** Account request, consumption-based pricing, designed for Cargill/Mondelez. Small NGOs and independent consultants can't access it. | Self-serve, £19/month, no account request, sign up and start immediately. | "No account request. No enterprise contract. Start in 2 minutes." |

**The conversion pathway — how GFW users become Canopex users:**

```
GFW Free user
  → "I can see deforestation on the map, but I need a proper report for my specific sites"
  → Searches for "satellite analysis specific area" / "KML satellite report"
  → Finds Canopex
  → Tries free tier (3 AOIs)
  → "This gives me what GFW doesn't — a per-site AI analysis I can actually use"
  → Converts to Starter (£19)
```

```
GFW Pro user (small org, frustrated with account request)
  → "I applied for GFW Pro 3 weeks ago, still waiting"
  → Needs results NOW (donor deadline, enforcement filing)
  → Finds Canopex → instant sign-up → results in 5 minutes
  → Stays because per-site evidence is more useful than GFW Pro's dashboard
```

**Content strategy to capture GFW traffic:**

1. SEO: "Global Forest Watch alternative", "GFW custom analysis", "per-site forest monitoring"
2. Blog post: "GFW vs Canopex: when you need more than global dashboards"
3. Comparison page: honest comparison showing where GFW wins and where Canopex adds value (not attacking GFW — they're a public good, respect that)
4. Conservation Slack/forums: "I use GFW for the big picture, Canopex for specific-site evidence"

### 6.2 Competing with Google Earth Engine

**Understanding GEE's position:** GEE is the most powerful geospatial analysis platform in the world. Period. 80+ PB of data, Google's compute, massive community. We cannot compete on capability. We compete on _accessibility_, _cost_, and _output format_.

**The critical insight: GEE's licensing creates a structural market gap.**

For our two primary personas:

| Persona | GEE Status | Our Opportunity |
|---------|------------|-----------------|
| **Conservation NGO doing internal monitoring** | Free (non-commercial) | Compete on ease-of-use: "same Sentinel-2 data, no coding required" |
| **Conservation NGO doing paid consultancy** | **NOT free** (fee-for-service requires commercial license) | **Price advantage:** our £19–49/month vs. GEE commercial license (opaque pricing) |
| **ESG consultancy doing paid audits** | **NOT free** (commercial use) | **Price + ease advantage:** no commercial license, no coding, evidence-ready output |
| **Corporate sustainability team** | **NOT free** (commercial use) | **Accessibility advantage:** no coding team needed, self-serve evidence |

**Where GEE wins (and we shouldn't fight):**

| GEE Strength | Why We Can't Win Here |
|-------------|----------------------|
| 80+ PB of multi-sensor data | We use Sentinel-2 via Planetary Computer. Tiny fraction of GEE's catalogue. |
| Full analytical flexibility (any algorithm) | We run fixed pipelines (NDVI, weather, AI). No custom analysis. |
| Massive community and documentation | We have zero community. |
| Free for genuine academic research | We charge even researchers (though our free tier covers light use). |

**Where GEE loses (and we should attack):**

| GEE Weakness | Our Advantage | How to Message |
|-------------|---------------|----------------|
| **Requires JavaScript/Python coding.** Every analysis starts with `ee.ImageCollection(...)` and a script. | Zero code. KML upload → results. A conservation officer who's never written code can use Canopex. | "The satellite insights you'd get from GEE — without writing a line of code." |
| **No weather integration.** To correlate NDVI with weather in GEE, you'd need to separately load weather data, spatially join it, and analyse the correlation. Hours of coding. | Automatic weather integration. Every analysis includes temperature, precipitation, drought correlation with NDVI trends. | "Weather + NDVI correlated automatically. In GEE, that's 200 lines of code." |
| **No AI narrative.** GEE outputs data (images, charts, tables). Turning that into a human-readable report requires additional work. | AI-generated plain-English analysis as standard output. | "GEE gives you data. Canopex gives you a report." |
| **Commercial license required for paid work.** ESG consultancies, NGOs doing fee-for-service, corporate sustainability teams — all need a commercial GEE license for operational use. | No licensing restrictions at any tier. Pay £19/month, use it for anything — commercial, non-profit, government, consultancy. | "No commercial license needed. Use it for any purpose." |
| **April 2026 quota tiers adding friction.** Even eligible non-commercial users will face new usage limits. | Predictable pricing. No quota surprises. Pay for what you use. | "Simple, predictable pricing. No quota caps." |
| **No "KML → report" workflow.** GEE is a platform, not a workflow. There is no "upload boundary, get evidence" path. | That IS our product. KML → evidence is a single end-to-end workflow. | "One workflow to go from boundary to evidence. Not a platform to figure out." |

**The conversion pathway — how GEE users become Canopex users:**

```
GEE researcher
  → Published a paper using GEE
  → Now doing paid consultancy on the side for an NGO (fee-for-service)
  → Realises they need a commercial GEE license for this work
  → Doesn't want the cost/complexity of commercial GEE for a side project
  → Finds Canopex → £19/month, no licence issues, results without coding
  → Uses Canopex for consultancy work, GEE for research
```

```
NGO programme manager
  → Their GIS person used GEE to produce a report last quarter
  → GIS person left / is on leave / is overloaded
  → Programme manager can't use GEE (doesn't code)
  → Finds Canopex → uploads KML from Google Earth → gets AI analysis
  → "I don't need to wait for the GIS team anymore"
```

```
ESG compliance officer
  → Told to produce deforestation evidence for 50 supply chain locations
  → Options: hire GIS consultancy ($20K), use GEE (needs coder), use GFW Pro (needs account request)
  → Finds Canopex → uploads KML → evidence report in 5 minutes
  → £49/month for 60 analyses vs. weeks of waiting and thousands in fees
```

**Content strategy to capture GEE-adjacent traffic:**

1. SEO: "satellite analysis no coding", "NDVI analysis without code", "Sentinel-2 analysis tool no GIS"
2. Blog post: "I used GEE for 5 years. Here's what I wish existed for non-coders."
3. Documentation: "For GEE users" page showing how Canopex maps to GEE concepts (ImageCollection → AOI, reduceRegion → NDVI analysis, etc.)
4. Key message in r/gis, r/remotesensing: "If you're doing quick per-site evidence and don't need GEE's full power, check this out"
5. LinkedIn targeting: ESG job titles, sustainability managers, compliance officers — "Your supply chain needs satellite evidence. You don't need a GIS team."

### 6.3 The "Open Minds" Strategy — Converting Sceptics

The user asked: "really push in 4-5x and understand where we can compete; how we can convert or open minds/thoughts."

**Sceptic archetype 1: "GFW is free, why would I pay?"**

Counter-argument chain:

1. "GFW is free for global dashboards. Do you need a report for _your specific sites_?" → Most say yes
2. "Can you export a per-site analysis from GFW with quantified NDVI trends?" → No
3. "Can GFW tell you whether the change was drought-driven vs. human-driven?" → No (no weather)
4. "Can GFW generate an AI analysis you can paste into a donor report?" → No
5. "Canopex does all of that for £19/month. Is that worth the 4 hours you'd spend doing it manually?"

**Sceptic archetype 2: "I can do this in GEE/QGIS for free."**

Counter-argument chain:

1. "How long does it take you to set up an NDVI analysis for one site in GEE?" → "A few hours"
2. "And you have how many sites?" → "15–50"
3. "So that's 75–250 hours of work. At your hourly rate?" → Uncomfortable pause
4. "Canopex processes all of them in minutes, with weather correlation and AI analysis included."
5. "And if you're doing paid work, you'll need a commercial GEE license on top of your time."

**Sceptic archetype 3: "10m resolution isn't enough."**

Counter-argument chain:

1. "What are you detecting?" → "Deforestation / land clearing"
2. "Deforestation events typically affect areas > 0.25 hectares. That's 2.5 Sentinel-2 pixels. 10m is sufficient for detection."
3. "If you need individual tree-level analysis, you need Planet ($2,700+/year) or commercial imagery. But for 90% of conservation and compliance monitoring, 10m works."
4. "And the analysis is free with Sentinel-2. Is the resolution premium worth $2,700/year to you?"

**Sceptic archetype 4: "I don't trust AI-generated analysis."**

Counter-argument chain:

1. "The AI narrative is generated from the actual satellite metrics — NDVI values, weather data, spectral indices. It's interpretation of real data, not hallucination."
2. "You can see the raw data alongside the narrative. The AI explains what the data shows."
3. "Would you rather the raw data with no interpretation? We can export that too."
4. "The alternative is you interpreting the data yourself — the AI just saves you that step."

**Sceptic archetype 5: "I'll wait for GFW Pro to approve my account."**

Counter-argument chain:

1. "When is your deadline?" → "Next month"
2. "GFW Pro account approval can take weeks. And their free grant gives you 5,000 MLAs/year — if you have 100 locations and run 4 analysis types, that's only 12 runs before you need to buy tokens."
3. "Canopex: sign up in 2 minutes. Results in 5 minutes. And we do NDVI trends + weather correlation that GFW Pro doesn't."

---

## 7. Conservation Persona — Exact Needs Map

"Let's focus on the top two personas. Let's work out how we get to exactly what they need, and make that easy."

### 7.1 Who Exactly Is This Person?

**Name in our heads:** "Pat" — the Protected Areas coordinator.

**Job title variants:** Conservation Programme Manager, Protected Area Monitoring Officer, Natural Resource Management Officer, Forest Monitoring Coordinator, Field Programme Lead.

**Organisation:** WWF field office, local land trust, national parks authority, Rainforest Foundation chapter, WCS country programme, wildlife corridor trust.

**Team size:** 3–15 people total. No dedicated GIS person (or one overworked GIS person shared across 5 programmes).

**Budget authority:** Can approve up to ~$100–200/month without procurement process. Anything over ~ $500/month needs director or board approval.

**Technical comfort:** Uses Google Earth Pro, Google Sheets, WhatsApp, maybe QGIS (reluctantly). Has KML files of protected area boundaries. Cannot code. Has tried Sentinel Hub once and given up.

### 7.2 Their Exact Workflow Today (Without Canopex)

```
1. Receive report of possible illegal clearing in protected area
   (from ranger, community member, or seasonal aerial survey)

2. Open Google Earth Pro → locate the area → note coordinates
   (5 minutes)

3. Go to Copernicus Open Access Hub → search for Sentinel-2 imagery
   → filter by date, cloud cover, tile
   (30 minutes — confusing interface, unclear which product to download)

4. Download 1+ GB Sentinel-2 tiles
   (15–30 minutes depending on connection speed)

5. Open QGIS → load bands → compute NDVI (Band8 - Band4) / (Band8 + Band4)
   (30 minutes if they know the formula, 2+ hours if they're learning)

6. Compare NDVI between two dates to detect change
   (30 minutes — requires clipping to AOI, choosing dates, visualising difference)

7. Separately check weather for the period
   (15 minutes on a weather service — was there a drought that explains the NDVI drop?)

8. Write up findings: "Between March and April, NDVI in sector 7B dropped from 0.72 to 0.41.
   No drought was recorded in this period, suggesting anthropogenic cause."
   (30–60 minutes to write, with screenshots from QGIS and weather data)

9. Create a report document for enforcement/donors
   (30 minutes formatting in Google Docs / Word)

Total: 3–6 hours per AOI. With 15 protected areas to monitor monthly: 45–90 hours/month.
```

### 7.3 Their Exact Workflow With Canopex

```
1. Receive report of possible illegal clearing
   (Same as today)

2. Open Canopex → upload KML of the area (they already have it from Google Earth)
   (2 minutes)

3. Canopex processes: imagery acquisition, NDVI analysis, weather correlation, AI narrative
   (3–5 minutes, automated)

4. Review results: NDVI trend chart, before/after imagery, weather overlay, AI analysis explaining
   "NDVI dropped 43% between March and April. No drought detected — precipitation was 110% of
   seasonal average. This change is consistent with vegetation clearing, not climate stress."
   (5 minutes)

5. Export report (PDF/CSV) for enforcement filing or donor report
   (1 minute)

Total: ~10 minutes per AOI. With 15 protected areas: ~2.5 hours/month.
Time saved: 40–85 hours/month. At $25–40/hour equivalent cost: $1,000–$3,400/month saved.
Cost of Canopex: £19–49/month. ROI: 20–170x.
```

### 7.4 The Exact Feature List They Need

| Priority | Feature | Status | Why They Need It |
|----------|---------|--------|-----------------|
| **Must-have** | KML upload → NDVI analysis | ✅ Built | This is the core action. They have KMLs from Google Earth. |
| **Must-have** | Before/after comparison (date range) | ✅ Built (M3) | "Show me what changed between March and April" |
| **Must-have** | AI narrative explaining changes | ✅ Built | They don't interpret NDVI values — they need plain English |
| **Must-have** | Weather correlation | ✅ Built | "Was this change drought or deforestation?" is THE question |
| **Must-have** | PDF export with maps + narrative | 🔧 Basic (M4.5) | They need to submit reports to donors/enforcement |
| **Must-have** | Multi-polygon KML support | ✅ Built (M3.7) | A protected area boundary may have multiple zones |
| **High** | Monthly scheduled re-analysis + alerts | ❌ Roadmap (M5.1) | "Alert me when NDVI drops >10% in any of my 15 sites" |
| **High** | Fire hotspot overlay (FIRMS) | ❌ Roadmap (M5.4) | Conservation areas face fire risk — they need fire context |
| **Medium** | Historical baseline (5+ years) | ❌ Roadmap (M6.4) | "Show me the 10-year NDVI trend for this forest" |
| **Medium** | Shareable analysis links | ❌ Roadmap (M5.2) | "Send this to the enforcement officer" without them needing an account |
| **Low** | Higher resolution imagery (3m+) | ❌ Not planned | For zooming into specific clearings — nice but not critical |
| **Low** | Mobile-friendly results viewing | ❌ Not planned | Field staff checking results on phone |

### 7.5 What "Easy" Means for This Persona

"Make that easy" — the user's words. For Pat the conservation coordinator, "easy" means:

1. **No learning curve.** First use = upload KML, get results. No tutorials, no "getting started" guide longer than 30 seconds. The demo page IS the product page.

2. **KML they already have.** Don't ask them to create GeoJSON or draw on a map. They have KML files from Google Earth Pro. Accept KML/KMZ, period.

3. **Results they can understand.** Not NDVI values (meaningless to them). Plain English: "This area lost 35% of its vegetation cover between March and April. This is consistent with clearing, not drought."

4. **One-click export.** PDF that looks professional enough to include in a donor report or enforcement filing. Not a raw CSV that needs formatting.

5. **Monthly auto-run.** "Set it and forget it" monitoring. Don't make them remember to log in every month. Send an email: "Your March analysis is ready. 2 of 15 sites show significant change."

6. **Price under $50/month.** Below NGO discretionary spend threshold. No procurement process. No supervisor approval needed.

7. **Works on slow internet.** Field offices in the DRC or Indonesia may have 1–5 Mbps connections. Don't require downloading 1GB Sentinel-2 tiles. Server-side processing, small result payloads.

### 7.6 The Feature We're Missing That Would Change Everything

**Monthly monitoring with alerts (M5.1) is the single most important feature for this persona.**

Without it, Canopex is a one-shot analysis tool. Conservation analysts will use it when they have a specific question ("has this area been cleared?") but won't make it part of their daily workflow.

With it, Canopex becomes _infrastructure_ — a monitoring service that runs continuously and alerts them when something changes. This is:

- The difference between a tool and a subscription (retention driver)
- The difference between "I check Canopex sometimes" and "Canopex is essential"
- The feature that GFW Free provides (deforestation alerts) but without per-AOI AI analysis

**Estimated impact on conversion:** Without monitoring, free→Starter conversion ~5–8%. With monitoring + alerts, free→Starter conversion ~12–18%. The alert email is the most powerful activation and retention mechanism possible.

---

## 8. ESG/EUDR Persona — Exact Needs Map

### 8.1 Who Exactly Is This Person?

**Name in our heads:** "Elena" — the EUDR compliance officer.

**Job title variants:** Sustainability Manager, ESG Analyst, Supply Chain Due Diligence Manager, Compliance Officer, EUDR Programme Lead, Sourcing Sustainability Coordinator.

**Organisation size and type** (in order of likelihood):

1. **Mid-sized EU importer** (100–500 employees) of cocoa, coffee, palm oil, soy, wood, rubber, or cattle products — ~3,000+ large operators, many more SMEs
2. **ESG consultancy** (5–50 employees) doing EUDR audits on behalf of importers who don't have in-house capability
3. **Large commodity trader** (Bunge, ADM, Louis Dreyfus) — have in-house GIS teams but may want self-serve tools for supplier due diligence at scale
4. **Asset manager / bank** screening portfolio companies for deforestation risk

**Budget authority:** ESG/compliance is a cost centre with allocated budget. £19–49/month is trivial. Even £5,000/year is well within compliance budget (compare: EUDR non-compliance fines of 4% of EU-wide turnover).

**Technical comfort:** Similar to conservation — not GIS-literate. Uses Excel, PowerPoint, compliance management platforms. Has never used satellite imagery directly. Gets geolocation data from suppliers as coordinates or boundaries.

### 8.2 Their Exact Workflow Today (Without Canopex)

```
1. Receive geolocation data from supplier
   (Coordinates/polygons of production plots — EUDR requires this from suppliers)

2. Option A: Send to consultancy for assessment
   → Cost: $10K–$50K per assessment
   → Timeline: 4–8 weeks
   → Output: PDF report assessing deforestation risk

3. Option B: Use GFW Pro (if account approved)
   → Upload locations to GFW Pro
   → Run Post-2000 Forest Change and Post-2020 Risk Assessment
   → Get dashboard results (deforestation-only, no weather, no AI)
   → Limited to 5,000 MLAs/year free — excess requires purchasing tokens
   → Account approval can take weeks

4. Option C: Ask internal GIS team (if one exists)
   → GIS team uses GEE or QGIS to analyse
   → Requires commercial GEE license if doing operational compliance work
   → GIS team is overloaded and takes 2–3 weeks

5. Compile findings into due diligence report
   → Cross-reference with EUDR requirements
   → Submit to EU Information System (when operational)

Total: 4–12 weeks, $10K–$50K, or internal GIS team bottleneck.
```

### 8.3 Their Exact Workflow With Canopex

```
1. Receive geolocation data from supplier

2. Convert coordinates to KML (or use provided boundary file)
   → We should offer a coordinate-to-KML converter in the UI
   (2 minutes)

3. Upload KML to Canopex
   → Select "EUDR Due Diligence" analysis mode
   → Automatically constrains to post-31-December-2020 baseline
   (2 minutes)

4. Canopex processes: imagery acquisition, NDVI analysis, forest change detection,
   weather correlation, AI narrative
   (3–5 minutes)

5. Review results:
   → Before/after imagery (2020 baseline vs. current)
   → NDVI trend chart showing vegetation stability or change
   → AI narrative: "Analysis of plot GH-042 shows NDVI remained stable at 0.68–0.72
     from January 2021 to present. No significant vegetation loss detected. Precipitation
     patterns were normal. This plot shows no evidence of post-2020 deforestation."
   (5 minutes)

6. Export EUDR-formatted evidence report
   → PDF with: plot coordinates, date range analysed, satellite imagery, NDVI metrics,
     weather data, AI assessment, methodology description, data sources
   (1 minute)

7. Attach to EUDR due diligence file
   → Include in submission to EU Information System

Total: ~15 minutes per plot. Cost: £19/month for up to 15 plots, £49/month for up to 60.
vs. $10K–$50K and 4–8 weeks from a consultancy.
```

### 8.4 The Exact Feature List They Need

| Priority | Feature | Status | Why They Need It |
|----------|---------|--------|-----------------|
| **Must-have** | Before/after comparison with specific date range | ✅ Built | EUDR requires post-2020 baseline comparison |
| **Must-have** | NDVI analysis + forest change detection | ✅ Built | Core evidence of no deforestation |
| **Must-have** | AI narrative explaining findings | ✅ Built | Non-technical compliance officers need plain English |
| **Must-have** | Weather correlation | ✅ Built | Distinguish climate-driven change from anthropogenic |
| **Critical** | Audit-quality PDF export | 🔧 Basic | Must look professional enough to submit to auditors. Template with methodology section, data sources, timestamps, plot-by-plot findings |
| **Critical** | EUDR date filtering (post-2020 baseline) | ❌ Not built (easy) | Constrain imagery to EUDR-relevant timeframe automatically |
| **Critical** | Coordinate-to-KML converter | ❌ Not built (easy) | Suppliers provide coordinates, not KML files |
| **High** | Batch processing (50+ plots) | ❌ Basic multi-polygon (M3.7) | Mid-sized importers have 50–500 supply chain plots |
| **High** | "Deforestation-free" certificate format | ❌ Not built | A templated statement: "Based on satellite analysis, this plot shows no evidence of post-2020 deforestation" with chain of evidence |
| **High** | Methodology documentation | ❌ Not written | Auditors will ask: "What satellites? What indices? What thresholds?" — need a published methodology document |
| **Medium** | Scheduled re-analysis (quarterly) | ❌ Roadmap (M5.3) | EUDR requires ongoing monitoring, not just one-time assessment |
| **Medium** | API for integration with compliance platforms | ❌ Roadmap (M6.1) | Larger orgs want to integrate into their existing compliance workflow |
| **Low** | Multi-user team access | ❌ Roadmap (M6.2) | Multiple people in the compliance team need access |

### 8.5 What "Easy" Means for This Persona

1. **Accept coordinates, not just KML.** Suppliers provide lat/long coordinates or CSV of coordinates. Don't make Elena figure out how to create a KML file. Offer a simple coordinate → boundary tool in the UI.

2. **EUDR-specific mode.** One button: "EUDR Due Diligence Mode" that automatically sets the baseline to post-31-December-2020, uses the right analysis parameters, and formats the output for EUDR submission.

3. **Audit-ready output.** The PDF must include:
   - Plot identification (coordinates, supplier reference)
   - Analysis date range (baseline date, latest imagery date)
   - Satellite imagery (before/after)
   - Quantified metrics (NDVI values, area, change %)
   - Weather context (ruling out climate explanations)
   - AI assessment narrative
   - Methodology description (satellite source, resolution, indices used)
   - Data source citations (Copernicus, Open-Meteo)
   - Timestamp of analysis generation

4. **Batch upload.** Upload a CSV of 200 coordinates → get 200 individual assessments + a summary report. This is the EUDR use case — not one plot at a time.

5. **Clear yes/no conclusion.** The auditor wants to read: "No evidence of deforestation detected" or "Significant vegetation change detected — manual review recommended." The AI narrative should lead with a clear conclusion, then provide supporting detail.

6. **Defensible methodology.** Publish a methodology page on the website: "Canopex uses European Space Agency Sentinel-2 Level-2A surface reflectance imagery at 10m resolution via Microsoft Planetary Computer. Normalised Difference Vegetation Index (NDVI) is computed as (B08 − B04)/(B08 + B04)..." This is what auditors need to trust the output.

### 8.6 The Critical Gap: Audit Trust

The single biggest challenge for this persona is not feature gaps — it's _trust_.

A consultancy charges $10K+ because they sell trust: "We are established experts, here is our methodology, here is our certificate."

Canopex is an unknown tool from an unknown company. For Elena to bet her EUDR compliance on Canopex, she needs:

1. Published, peer-reviewable methodology
2. Case studies from other compliance use cases
3. Reference data showing Canopex's analysis matches known outcomes
4. A clear statement of what Canopex IS and ISN'T: "This tool produces satellite evidence to support your due diligence process. It does not constitute a compliance certificate."

**Positioning for trust-building:**

- Don't overclaim. "Satellite evidence for EUDR due diligence" (our analysis as one input), not "EUDR compliance solution" (implies we handle everything).
- Partner with a compliance consultancy early. "Verified by [consultancy name]" adds credibility.
- Publish a validation study: compare Canopex's deforestation detection against known events.

### 8.7 GFW Pro vs Canopex — Head-to-Head for EUDR

| Dimension | GFW Pro | Canopex |
|-----------|---------|-----------|
| **Access** | Account request (weeks) | Self-serve (minutes) |
| **Free tier** | 5,000 MLAs/year | 3 AOIs/month |
| **Paid pricing** | Consumption-based tokens (opaque) | £19/month (Starter) or £49/month (Pro) |
| **Analysis types** | Deforestation only (forest change, risk, disturbance, GHG) | Any vegetation change + weather + AI |
| **Weather integration** | No | Yes |
| **AI narrative** | No | Yes |
| **EUDR focus** | Yes (purpose-built for EUDR) | Partially — needs EUDR mode + audit PDF |
| **Scale** | 150,000 locations per list | Depends on tier (15–250/month) |
| **Backing** | WRI, Google, NASA | Solo developer |
| **Audit trust** | High (established, used by Cargill/Mondelez) | Low (unknown, new tool) |

**Honest assessment:** For large enterprises (Cargill, Mondelez) with 100,000+ locations, GFW Pro is the right tool. We can't and shouldn't compete at that scale.

**Our sweet spot:** Mid-sized importers (50–5,000 plots) and ESG consultancies who:

- Can't get GFW Pro approved quickly enough (account request delay)
- Don't need the enterprise scale (150K locations)
- Want weather context and AI analysis that GFW Pro doesn't provide
- Want a predictable monthly price, not consumption-based tokens

---

## 9. Market Sizing — Grounded Estimates

Market sizing for niche SaaS is inherently speculative. Built from the bottom up using concrete numbers rather than paywalled analyst reports.

### 9.1 Total Addressable Market (TAM)

The geospatial analytics market is estimated at $80–100B globally by 2025–2027 (various analyst sources, though specific numbers are behind paywalls). This number is meaningless for Canopex — it includes defence, navigation, mining, and sectors we don't serve.

**Relevant sub-markets:**

| Segment | Estimated Size | Source / Basis |
|---------|---------------|----------------|
| Satellite imagery services (civilian, excluding defence) | $5–7B globally | Multiple analyst estimates; Planet's revenue was ~$244M in 2024 as one player |
| Precision agriculture analytics | $2–3B globally | Driven by farm management software, crop insurance tech, satellite-based advisory |
| Forest monitoring tools/services | $500M–$1B globally | Includes consultancies, tech platforms, government programmes |
| ESG/EUDR compliance tools | $1–2B globally (emerging) | New market created by regulation; EUDR affects ~7M EU commodity imports by value |

**Canopex's TAM:** ~$500M (KML-based satellite analysis for conservation + agriculture + ESG). This is generous.

### 9.2 Serviceable Addressable Market (SAM)

Narrow to organisations that:

- Have or can create KML/KMZ boundary files
- Need periodic satellite analysis (not one-time)
- Are willing to use a SaaS tool (not in-house or consultancy)
- Have AOIs within Sentinel-2 coverage (global land surfaces — so no constraint here)
- Work in English (initial launch)

| Segment | Estimated Org Count | Avg. Revenue/Org | SAM |
|---------|--------------------|--------------------|-----|
| Conservation NGOs (globally, English-speaking) | ~5,000 orgs (WRI lists 1,600+ conservation orgs; many more exist locally) | $600–$1,800/year (Pro–Team) | $3–9M |
| Agricultural advisory firms | ~10,000 firms (fragmented, mostly small) | $1,800–$5,000/year (Team–Enterprise) | $18–50M |
| ESG compliance teams (EU importers of EUDR commodities) | ~2,000–5,000 companies (EU commission estimates 3,000 large operators + many more SMEs) | $1,800–$10,000/year | $3.6–50M |
| **Total SAM** | | | **~$25–$110M** |

### 9.3 Serviceable Obtainable Market (SOM) — First 12 Months

This is the honest number.

| Metric | Estimate | Reasoning |
|--------|----------|-----------|
| Free sign-ups (year 1) | 500–2,000 | Reddit/conservation forum posting, SEO for "KML satellite analysis", word of mouth |
| Free → Pro conversion | 5–10% | Industry average for freemium SaaS; may be higher if analysis is genuinely useful |
| Pro subscribers (year 1) | 25–200 | 500 × 5% = 25 (pessimistic) to 2000 × 10% = 200 (optimistic) |
| Pro → Team upsell | 10–20% | Orgs that hit the 50 AOI limit and need team features |
| Enterprise deals (year 1) | 0–5 | Requires sales, case studies, trust. Unlikely in year 1 without a track record. |
| **Year 1 ARR (pessimistic)** | **$15K–$30K** | 25 Pro × $49 × 12 = $14,700; 3 Team × $149 × 12 = $5,364 |
| **Year 1 ARR (optimistic)** | **$120K–$240K** | 150 Pro × $49 × 12 = $88,200; 30 Team × $149 × 12 = $53,640; overage revenue |

**Reality check:** $15K–$240K ARR in year 1. This is a side project to small business range, not a venture-scale outcome. And that's OK — but it means venture capital is not the right funding model. This is a bootstrap or small-seed business.

---

## 10. Dual Pricing Model

### 10.1 The Decision: Offer Both Tiers

The user's direction: "We can do both the £19/15 + extras, or the £49/45 + cheaper extras."

This is a dual-entry pricing model — two paths into paid, each optimised for a different buyer psychology:

**Path A: Starter (£19/month, 15 AOIs, expensive extras)**

- Target: Budget-conscious buyer, small NGO, individual consultant, evaluation
- Psychology: "I want to try this cheaply and pay for what I use"
- Overage: £1.50/AOI — they pay more per extra, but the base is cheap
- Graduation: When overage makes Starter more expensive than Pro, they upgrade naturally

**Path B: Pro (£49/month, 45 AOIs, cheaper extras)**

- Target: Committed buyer, active NGO, ESG compliance team, regular user
- Psychology: "I know I need this, I want the best per-AOI rate"
- Overage: £0.80/AOI — extras are cheap because they've already committed
- Graduation: When they routinely exceed 45, they evaluate Team

### 10.2 The Complete Pricing Table

| Tier | Price | Included AOIs | Effective £/AOI | Overage £/AOI | Concurrency | Data Retention | AI Insights | Target |
|------|-------|--------------|-----------------|---------------|-------------|----------------|-------------|--------|
| **Free** | £0 | 3/month | £0 | Hard cap (no overage) | 1 pipeline | 30 days | No | Evaluation, students, individual researchers |
| **Starter** | £19/month | 15/month | £1.27 | £1.50/AOI | 2 pipelines | 60 days | Yes | Independent consultants, small NGOs, evaluation |
| **Pro** | £49/month | 45/month | £1.09 | £0.80/AOI | 5 pipelines | 180 days | Yes | Active NGOs, ESG compliance, regular users |
| **Team** | £149/month | 200/month | £0.75 | £0.50/AOI | 10 pipelines | 1 year | Yes | Multi-user orgs, agritech, large compliance |
| **Enterprise** | Custom | Negotiated | < £0.50 | Volume-discounted | Dedicated | Custom | Yes + custom | Large compliance programmes, government |

### 10.3 Why 15 and 45 (Not 10 and 50)

**Starter at 15:**

- 10 is too tight — a conservation coordinator with 5 protected areas running 2 analyses each instantly hits the wall. Frustrating.
- 20 is too generous — reduces "just one more" overage revenue and delays graduation to Pro.
- 15 means: a user with 8 sites can do 1 analysis each with room to spare. A user with 15 sites can do exactly one analysis each. A user with 20 sites pays £19 + (5 × £1.50) = £26.50 — still cheap.

**Pro at 45:**

- 50 (the original) was fine but 45 creates slightly better graduation economics.
- A Pro user running 60 AOIs/month: £49 + (15 × £0.80) = £61 — well below Team at £149.
- A Pro user running 100 AOIs/month: £49 + (55 × £0.80) = £93 — still below Team.
- A Pro user running 150 AOIs/month: £49 + (105 × £0.80) = £133 — nearly Team price, but without team features.
- The upgrade to Team happens at ~200 AOIs/month (£49 + 155 × £0.80 = £173 > £149), or when they need multi-user access.

### 10.4 Graduation Economics — Why Users Upgrade Naturally

**Free → Starter graduation:**

| User's AOIs/month | Free Cost | Starter Cost | Decision |
|-------------------|-----------|-------------|----------|
| 3 | £0 (at cap) | £19 | Stay free if 3 is enough |
| 5 | Can't (capped at 3) | £19 | Must upgrade to Starter |
| 10 | Can't | £19 | Starter — all included |
| 15 | Can't | £19 | Starter — exactly at limit |
| 20 | Can't | £19 + £7.50 = £26.50 | Starter with overage — still reasonable |

The free-to-Starter jump happens at 4 AOIs. The question is: "Is the 4th analysis worth £19/month to me?" At conservation/ESG value ($200+ per AOI in time saved), yes.

**Starter → Pro graduation:**

| User's AOIs/month | Starter Cost | Pro Cost | Decision |
|-------------------|-------------|----------|----------|
| 15 | £19 | £49 | Stay on Starter |
| 25 | £19 + (10 × £1.50) = £34 | £49 | Stay on Starter (£34 < £49) |
| 30 | £19 + (15 × £1.50) = £41.50 | £49 | Still Starter (barely) |
| 35 | £19 + (20 × £1.50) = £49 | £49 | Breakeven — Pro offers more headroom |
| 40 | £19 + (25 × £1.50) = £56.50 | £49 | **Upgrade to Pro** |
| 45 | £19 + (30 × £1.50) = £64 | £49 | Pro — clearly better |

**Crossover point: ~35 AOIs/month.** At 35+ AOIs, Pro is cheaper. This is the "aha" moment where the user self-selects into the higher tier.

**Pro → Team graduation:**

| User's AOIs/month | Pro Cost | Team Cost | Decision |
|-------------------|----------|-----------|----------|
| 45 | £49 | £149 | Stay on Pro |
| 100 | £49 + (55 × £0.80) = £93 | £149 | Stay on Pro |
| 150 | £49 + (105 × £0.80) = £133 | £149 | Stay on Pro (barely, but no team features) |
| 200 | £49 + (155 × £0.80) = £173 | £149 | **Upgrade to Team** |
| 250 | £49 + (205 × £0.80) = £213 | £149 + (50 × £0.50) = £174 | Team — much better |

**Crossover point: ~175 AOIs/month** (or when multi-user features are needed). Team also offers 10 concurrent pipelines vs. Pro's 5 — important for batch users.

### 10.5 Revenue Model — Dual Entry vs. Single Entry

**Scenario: 100 potential paying users in the funnel**

**Single-entry model (only £49 Pro):**

- Users who'd pay £19 but not £49: ~30 users → lost entirely
- Users who convert at £49: ~45 users
- Revenue: 45 × £49 = £2,205/month base
- Overage (20% hit limits, avg 10 extra): 9 × £10 = £90
- Total: **~£2,295/month**

**Dual-entry model (£19 Starter + £49 Pro):**

- Users who convert at £19: ~35 users (the 30 who wouldn't pay £49, plus 5 who start cheaper)
- Users who convert at £49: ~40 users (5 fewer because some start at Starter instead)
- Starter revenue: 35 × £19 = £665 + overage (avg 5 extra × £1.50 × 35 × 40%) = £105 → £770
- Pro revenue: 40 × £49 = £1,960 + overage (avg 8 extra × £0.80 × 40 × 30%) = £77 → £2,037
- Total: **~£2,807/month** (22% more revenue)

Plus: over time, Starter users graduating to Pro creates additional revenue growth without new customer acquisition.

### 10.6 Competitive Pricing Analysis — Updated

| Competitor | Price for ~15 AOI Analyses | Our Starter Equivalent |
|-----------|---------------------------|----------------------|
| **GFW Free** | £0 (no per-AOI analysis — global dashboards only) | We offer per-AOI custom analysis GFW free doesn't |
| **GFW Pro** | £0 (within 5,000 MLA/year grant) — BUT account request required | £19/month, instant access, + weather + AI |
| **Google Earth Engine** | "Free" for non-commercial — BUT requires coding + commercial license for paid work | £19/month, no code, no licence restrictions |
| **Planet** | ~$2,700/year ($225/month) — but daily 3.7m imagery | £19/month — lower res but free imagery + AI |
| **Consultancy** | ~$10,000–$50,000 per engagement | £19–49/month. Not even comparable. |
| **QGIS + manual** | £0 (but 4–8 hours/AOI in labour) | £19/month saves ~60+ hours/month |

### 10.7 Price Anchoring to Competitor Alternatives

The user pays £19 or £49/month. What's the alternative cost?

**For Conservation (15 AOIs/month):**

- Manual QGIS: 15 × 4 hours = 60 hours/month × £25/hour (NGO rate) = **£1,500/month in staff time**
- Canopex Starter: **£19/month** (99% savings)

**For ESG (45 AOIs/month):**

- Consultancy: ~£20,000 per engagement (45 plots) → **£20,000 one-time**
- Canopex Pro: **£49/month** (99.7% savings, with monthly re-analysis capability)

These ratios make the price defence trivially easy: "Canopex costs less than one hour of the work it replaces."

### 10.8 What's Included vs. Add-Ons

**Included in all paid tiers:**

- NDVI analysis with before/after comparison
- Weather correlation (temperature, precipitation, drought indices)
- AI-generated narrative analysis
- Fire risk context (when available)
- PDF export of analysis results
- Standard email support

**Potential premium add-ons (future):**

| Add-On | Price | Why Separate |
|--------|-------|-------------|
| Historical baseline (Landsat 40-year) | £10/AOI one-time | Compute-intensive, high value |
| Higher-resolution imagery (when available) | Market rate + margin | Real imagery costs involved |
| Audit report template (EUDR-formatted) | Included in Pro+ | Competitive advantage for ESG, include to drive upgrades |
| API access | Team tier+ only | Programmatic access is a Team-tier feature |
| Monthly monitoring alerts | Included in Starter+ | **Don't gate this** — it's the key retention driver |

---

## 11. Product-Need Fit — Where We Win and Where We Don't

### 11.1 Strengths (Genuine Differentiators — Updated)

| Strength | Why It Matters | Competitor Comparison |
|----------|---------------|-----------------------|
| **KML-first input** | Non-GIS users already have KML files from Google Earth. Zero-friction input. | No competitor accepts KML as the primary input mode. |
| **Free Sentinel-2 imagery** | Zero marginal imagery cost. Every AOI uses free public data. | Planet: $2,700–$9,650/year. SkyFi: from $25/order. GFW Pro: free grant but deforestation-only. |
| **Integrated weather + NDVI** | Distinguishes climate-driven change from anthropogenic change — the critical question for both conservation and compliance. | Nobody else automatically correlates weather with vegetation trends. |
| **AI narrative** | Plain-English analysis from satellite data. Compliance officers and programme managers can use the output directly. | GEE requires code. GFW has dashboards. Nobody generates per-AOI narrative analysis. |
| **No commercial licence restrictions** | Use for any purpose — commercial, non-profit, government. No fee-for-service exclusions. | GEE: commercial licence required for paid/operational work. GFW Pro: enterprise account request. |
| **Self-serve, instant access** | Sign up, upload KML, get results in 5 minutes. No account request, no sales call. | GFW Pro: account request (weeks). GEE: requires coding setup. Planet: requires imagery purchase. |
| **Unit economics** | ~£0.08–0.15 per AOI all-in cost. 80%+ gross margin at any paid tier. | Planet/SkyFi have real imagery costs. GEE has compute costs at scale. |

### 11.2 Weaknesses (Honest Assessment — Updated)

| Weakness | Impact | Mitigation Path |
|----------|--------|----------------|
| **10m resolution (Sentinel-2)** | Can't see individual trees, small structures, fine-grained crop detail | Sufficient for deforestation (large-area change) and ESG compliance. Commercial imagery upgrade as future add-on. |
| **No monitoring/alerts** | Conservation users need "alert me when something changes" | Scheduled re-analysis architecturally feasible. **#1 priority feature for conservation persona.** |
| **No batch processing UX** | ESG users have 50–500 plots. Current UX is one-at-a-time. | API access (Team tier) + batch upload endpoint. Pipeline already fans out per-polygon. |
| **No formal audit report** | ESG compliance needs audit-quality PDF. Current export is basic. | **#1 priority feature for ESG persona.** Professional template with methodology, data sources, timestamps. |
| **No brand recognition** | GFW has 9M visitors. We have zero. | Evidence quality creates word-of-mouth. Case studies, SEO, conservation community presence. |
| **Single-developer bus factor** | Product stops evolving if developer unavailable | Mitigated by documentation (SYSTEM_SPEC, ARCHITECTURE_OVERVIEW) and CI/CD. Business risk, not product risk. |
| **No EUDR-specific mode** | ESG persona needs post-2020 baseline filtering and EUDR-formatted output | Easy to implement — constrain date range + template output. High signal, low effort. |

### 11.3 The "10x Better" Test — Updated

| Persona | Current Workflow | Their Time | Canopex Time | 10x Better? |
|---------|-----------------|------------|----------------|-------------|
| Conservation (15 AOIs/month) | QGIS + Copernicus Hub + weather service + report writing | 60–90 hours/month | ~2.5 hours/month | **Yes (24–36x)** |
| ESG (45 plots, one-time assessment) | Consultancy ($10K+, 4–8 weeks) | 4–8 weeks | ~4 hours (same day) | **Yes (120–240x on speed)** |
| ESG (45 plots, ongoing quarterly) | GFW Pro (if approved, deforestation-only) | Days + no weather/AI | ~4 hours + AI + weather | **Yes on breadth, comparable on scale** |

---

## 12. Recommendations — Updated

### 12.1 Persona Priority (Unchanged, Now Evidence-Backed by §7–§8)

1. **Conservation (primary).** Best product-need fit. Their exact workflow maps to our core product. KML is their native format. Evidence generation is our unique value. §7 maps their exact needs — most are already built. **One missing feature (monitoring/alerts) transforms Canopex from tool to infrastructure.**

2. **ESG/EUDR compliance (secondary, highest revenue potential).** Regulatory urgency creates immediate demand. GEE isn't free for their use case (§4.2). GFW Pro requires account request and is deforestation-only. Our sweet spot is the 50–5,000 plot mid-market that can't access GFW Pro quickly and doesn't want to hire a consultancy. **Three features needed: audit PDF, EUDR date filtering, coordinate-to-KML converter.**

3. **Agriculture (tertiary, deprioritise).** Highest long-term TAM but worst current fit. Needs batch processing, crop-specific indices, higher resolution. Revisit once conservation + ESG are established.

### 12.2 Pricing Implementation

**Implement dual-entry pricing (§10):**

- Free: 3 AOIs/month, no AI, 30-day retention
- Starter: £19/month, 15 AOIs, £1.50 overage, AI included
- Pro: £49/month, 45 AOIs, £0.80 overage, AI included
- Team: £149/month, 200 AOIs, £0.50 overage, multi-user
- Enterprise: Custom

**Key decisions confirmed:**

- AI insights included at all paid tiers (don't gate the differentiator)
- Free tier capped at 3 (not 5) — drives faster conversion
- Both Starter and Pro available simultaneously (dual entry, not graduated gating)
- Monitoring alerts included in all paid tiers when shipped (retention driver, not paywall)

### 12.3 Positioning Implementation

**Primary:** "Automated satellite evidence for conservation and compliance"  
**Tagline:** "From KML to evidence in 5 minutes"  
**Supporting:** "No coding. No GIS degree. No consultancy fees."

**Per-channel messaging (§5.6):**

- Homepage: hero positioning + tagline
- ESG landing page: "Satellite evidence for EUDR due diligence"
- Conservation landing page: "Satellite evidence for protected area monitoring"
- LinkedIn ads (ESG): "Your supply chain needs satellite evidence. You don't need a GIS team."
- r/gis, r/conservation: "I use GFW for the big picture, Canopex for site-specific evidence"

### 12.4 Product Priorities (Immediate — Ranked by Persona Impact)

| # | Feature | Effort | Persona Impact | Revenue Impact |
|---|---------|--------|---------------|----------------|
| 1 | **Monthly monitoring + alerts** | High | Conservation: transforms tool → service | Highest retention driver |
| 2 | **Audit-quality PDF export** | Medium | ESG: enables trust and adoption | Unlocks ESG revenue |
| 3 | **EUDR date filtering (post-2020)** | Low | ESG: regulatory compliance mode | High signal, low effort |
| 4 | **Coordinate-to-KML converter** | Low | ESG: suppliers provide coords, not KML | Removes friction |
| 5 | **Methodology documentation page** | Low | ESG: auditors need published methodology | Trust building |
| 6 | **Batch upload (multi-KML or CSV)** | Medium | Both: scale beyond one-at-a-time | Drives overage revenue |
| 7 | **"Deforestation-free" certificate template** | Low | ESG: clear yes/no conclusion format | Differentiation |

### 12.5 Competitive Strategy Implementation

**vs GFW (§6.1):** Position as the "next step" — "GFW shows the world. Canopex analyses your sites." Don't attack GFW (they're a public good). Be the tool GFW users graduate to. SEO: "Global Forest Watch alternative", "GFW per-site analysis."

**vs GEE (§6.2):** Position on accessibility and licensing — "The satellite insights you'd get from GEE, without writing a line of code. No commercial licence needed." Target: NGOs doing fee-for-service, ESG consultancies, compliance officers. SEO: "satellite analysis no coding", "NDVI analysis without GEE."

**vs Consultancy:** Position on speed and cost — "The evidence a consultancy takes 8 weeks to produce. In 5 minutes. For £19/month." Target: mid-sized EU importers facing EUDR deadlines.

**vs QGIS/manual:** Position on time savings — "What takes 4 hours in QGIS takes 5 minutes in Canopex." Target: overwhelmed programme managers, understaffed NGOs.

---

## 13. Strategic Feature & Integration Analysis

_Added 26 March 2026. Answers four questions: (1) which features unlock the most opportunities, (2) what additional data sources and services could we integrate, (3) which commercial platforms could we leverage, and (4) how quickly can we capture the EUDR persona._

### 13.1 Features That Open the Most Opportunities

Ranked by **breadth of impact** — how many personas, how much revenue, how much competitive separation.

#### Tier 1 — Leverage features (high impact, reasonable effort)

| # | Feature | Effort | Personas Served | Why It's High-Leverage |
|---|---------|--------|----------------|----------------------|
| 1 | **Audit-quality PDF export** | Medium | ESG, Conservation, Agriculture | Opens the entire EUDR market. Conservation needs donor reports. Ag needs loss-adjustment evidence. Every persona exports; this is the revenue gate for ESG. Without it, we're a dashboard. With it, we're an evidence generator. |
| 2 | **Monthly monitoring + threshold alerts** | High | Conservation (primary), ESG (secondary) | Transforms Canopex from a one-shot tool into infrastructure. Users don't churn from infrastructure they depend on. Conservation persona said this is their #1 need (§7.6). Creates the email touchpoint that drives re-engagement. |
| 3 | **EUDR compliance mode** | Low | ESG (primary) | One toggle: "EUDR Due Diligence" → constrains analysis to post-31-Dec-2020 baseline, formats output as audit evidence, leads with yes/no deforestation conclusion. Low effort because the analysis already works — we're just constraining parameters and formatting output. |
| 4 | **Land cover classification overlay** | Medium | ESG, Conservation | Currently we compute NDVI change but can't say "forest became cropland." Land cover classification turns quantitative change into qualitative meaning. ESA WorldCover (10m, Sentinel-derived, on PC) or IO LULC Annual V2 (10m, 2017-2023, on PC) could give us this with zero new imagery cost. |
| 5 | **Coordinate / CSV → KML converter** | Low | ESG (primary), Agriculture | EUDR suppliers provide coordinates, not KML files. A simple UI tool that accepts CSV (lat, long, name) and generates KML removes the biggest adoption friction for non-GIS users. Could also accept GeoJSON, Shapefile. |

#### Tier 2 — Deepening features (expand value per user)

| # | Feature | Effort | Personas Served | Why It Matters |
|---|---------|--------|----------------|---------------|
| 6 | **Batch upload (CSV of 50-500 AOIs)** | Medium | ESG, Agriculture | EUDR importers don't have 3 plots — they have 200. Current multi-polygon KML works but UX is one-file-at-a-time. A batch CSV upload endpoint (coordinates + reference IDs → fan-out pipeline) unlocks the Team/Enterprise tier for real. |
| 7 | **Shareable analysis links** | Medium | Conservation, ESG | "Send this to the enforcement officer / auditor" without them needing an account. Viral loop for acquisition. Low-effort but high-signal for perceived professionalism. |
| 8 | **Sentinel-1 SAR integration** | High | Conservation, ESG | Cloud-penetrating radar — sees deforestation through cloud cover (critical in tropics: Borneo, Congo Basin, Amazon). On Planetary Computer. Would make our analysis work in regions where Sentinel-2 optical imagery has persistent cloud gaps. Major differentiator for tropical EUDR use cases. |
| 9 | **Historical biomass quantification** | High | ESG | Chloris Biomass (4.6km, 2003-2019, on PC) or HGB (300m, 2010, on PC) → "this AOI lost X tonnes of carbon." Transforms deforestation detection into carbon impact quantification — the ESG buyer's currency. |

#### Tier 3 — Moat features (long-term defensibility)

| # | Feature | Effort | Personas Served | Why It Matters |
|---|---------|--------|----------------|---------------|
| 10 | **Landsat historical baselines (1985-present)** | High | All | 40-year trend context. On Planetary Computer as `landsat-c2-l2`. Makes Canopex the "long memory" that neither GFW nor quick-look tools provide. Premium add-on ($10/report). |
| 11 | **AI-powered land change narrative** | Medium | All | Current AI analyses individual frames. A cross-temporal AI analysis ("Between 2018 and 2025, this 50ha forest fragment was progressively cleared from the eastern edge, losing 12ha total") is a qualitative leap. Uses existing AI client + the richer data from #4 and #10. |
| 12 | **Super-resolution (10m → ~2.5m)** | High | Agriculture, Conservation | Addresses the "resolution isn't enough" objection. SR4RS or similar model on Sentinel-2 imagery. Competitive with Planet's 3m product at zero imagery cost. |

**Bottom line:** Features #1 (PDF), #3 (EUDR mode), and #5 (coordinate converter) are the highest-leverage trio. All are low-to-medium effort. Together they unlock the entire EUDR market without significant engineering investment.

### 13.2 Data Sources & Services We Could Integrate

Currently we use: Planetary Computer (Sentinel-2, NAIP), Open-Meteo (weather), NASA FIRMS (fire), UK EA Flood Monitoring, USGS Streamflow, and PC Mosaic API.

The Planetary Computer catalog alone has 100+ datasets. Here's what's worth integrating, grouped by strategic value.

#### 13.2.1 High-Value — Already on Planetary Computer (low integration effort)

These use the same STAC search → COG download path we already have. Adding them means adding a collection ID and asset keys to the provider config.

| Dataset | PC Collection | Resolution | Coverage | Value to Canopex |
|---------|--------------|------------|----------|-------------------|
| **ESA WorldCover** | `esa-worldcover` | 10m | Global, 2020-2021 | Land cover classification (10 classes incl. Trees, Cropland, Built-up). Answers "was this forest or already farmland?" Directly supports EUDR baseline assessment. **Top priority.** |
| **IO LULC Annual V2** | `io-lulc-annual-v02` | 10m | Global, 2017-2023 | 9-class annual land use/land cover. Multi-year comparison: "this pixel was forest in 2019, cropland in 2022." Sentinel-derived (same resolution as our imagery). **Top priority.** |
| **ALOS Forest/Non-Forest** | `alos-fnf-mosaic` | 25m | Global, annual | Binary forest/non-forest classification from JAXA SAR. Independent of optical imagery (works through clouds). Validates optical NDVI-based forest detection. |
| **MODIS Burned Area** | `modis-64A1-061` | 500m | Global, monthly, 2000-present | Already planned (M5.8). Complements our FIRMS hotspot data with validated burned-extent polygons and dates. |
| **ESA CCI Land Cover** | `esa-cci-lc` | 300m | Global, annual, 1992-2020 | Already planned (M5.9). 28 years of land cover history. 22 LCCS classes. Perfect for long-term trend analysis. |
| **Chloris Biomass** | `chloris-biomass` | ~4.6km | Global, 2003-2019 | Above-ground biomass density. "This area had X tonnes/ha of biomass in 2015." Enables carbon loss quantification for ESG reporting. |
| **Copernicus DEM GLO-30** | `cop-dem-glo-30` | 30m | Near-global | Terrain elevation → slope analysis → "this is steep terrain unsuitable for agriculture" context. Enriches AI interpretation. |
| **Sentinel-1 SAR** | `sentinel-1-rtc` / `sentinel-1-grd` | 10-20m | Global, 6-day revisit | Radar sees through clouds. Change detection on SAR backscatter can detect deforestation in perpetually cloudy regions. **Critical for tropical EUDR.** High effort to add analysis but imagery is free and on PC. |
| **Planet-NICFI Mosaics** | `planet-nicfi-visual` / `analytic` | 4.77m | Tropics, monthly | Planet Labs tropical imagery funded by Norwegian government. FREE for non-commercial / EUDR due-diligence use. 4.77m resolution — 4x better than Sentinel-2. Covers exactly the regions EUDR targets. **Game-changer if licensing terms allow our use case.** |
| **HLS v2.0** | `hls2-l30`, `hls2-s30` | 30m | Global | Harmonised Landsat + Sentinel-2 — consistent radiometry across both sensors. Doubles temporal revisit rate. Useful for gap-filling and long-term consistency. |
| **JRC Global Surface Water** | `jrc-gsw` | 30m | Global, 1984-2020 | Water occurrence history. "This area was seasonally flooded" context for NDVI interpretation. Prevents false positives (wetland seasonal changes aren't deforestation). |
| **Biodiversity Intactness** | `io-biodiversity` | 100m | Global, 2017-2020 | Conservation persona cares deeply about this. "This area has X% biodiversity intactness" adds conservation significance context to reports. |
| **MODIS Vegetation Indices** | `modis-13Q1-061` | 250m | Global, 16-day, 2000-present | Independent NDVI/EVI source at 250m. 25+ year record. Cross-validates our Sentinel-2 NDVI trends with a longer baseline. |
| **Deltares Global Flood Maps** | `deltares-floods` | varies | Global | Flood risk/inundation maps for sea-level rise scenarios. Adds climate risk context beyond current weather correlation. |
| **Microsoft Building Footprints** | `ms-buildings` | vector | Global | ML-detected building footprints. "X buildings detected within the AOI" adds human pressure context. |

#### 13.2.2 High-Value — Free External APIs (medium integration effort)

These require new API clients but are free and add significant analytical depth.

| Source | Data | Value |
|--------|------|-------|
| **Global Forest Watch API** | Real-time deforestation alerts (GLAD, RADD), tree cover loss | Cross-reference our analysis with GFW's alert system. "GFW detected 3 deforestation alerts in this AOI in the past 6 months." Adds authority (WRI's seal of approval on raw alert detection). Free API with rate limits. |
| **GADM / Natural Earth** | Administrative boundaries, protected area boundaries | Auto-detect: "This AOI is within the Virunga National Park" or "This AOI is in Pará state, Brazil." Context that enriches AI narratives without the user telling us. Free vector data. |
| **World Database on Protected Areas (WDPA)** | Protected area boundaries globally | "This plot overlaps a protected area" — immediate red flag for EUDR. An overlap check adds regulatory context automatically. Free from protectedplanet.net API. |
| **OpenStreetMap** | Roads, settlements, land use | "A road was built 500m from this AOI in 2023" — evidence of encroachment. Via Overpass API, free, no key needed. |
| **EU Deforestation Observatory** | When operational — EUDR-specific reference data | The EU's own system for EUDR. Integration would add regulatory legitimacy. |
| **SoilGrids (ISRIC)** | Global soil data at 250m | Soil type, organic carbon, pH. "This plot is on high-carbon peatland" adds environmental significance context. Free REST API. |

#### 13.2.3 What QGIS Users Typically Integrate

QGIS users in conservation and agriculture commonly use:

- **WMS/WFS services** (e.g., national mapping agencies, Ordnance Survey, USGS) — we could expose these as optional basemap layers
- **PostGIS** — spatial databases. Not relevant for us (we're SaaS, not desktop)
- **OpenStreetMap** — for contextual overlays (roads, buildings, land use)
- **CORINE Land Cover** (EU) — 100m EU land cover. ESA CCI Land Cover and IO LULC are better options for us (global, higher resolution)
- **National cadastral data** — parcel boundaries. Varies by country, hard to standardise
- **Copernicus Climate Data Store (CDS)** — ERA5 reanalysis, seasonal forecasts. We already do weather via Open-Meteo which uses ERA5 as a backend
- **Google Earth** — as a visual reference. Our users already start in Google Earth (KML is their native format)

**The key insight: QGIS users cobble together 5-10 data sources manually. Our competitive advantage is doing this automatically.** Every source we integrate into the enrichment pipeline is one fewer manual step for a QGIS user — and one more reason to switch.

### 13.3 Commercial Platforms — Partnership or Integration

#### 13.3.1 Platforms to Use Now (Free or Low-Cost)

| Platform | What We'd Use | Cost | Integration Path |
|----------|--------------|------|-----------------|
| **Planet-NICFI** (via PC) | 4.77m tropical mosaics | **Free** for EUDR/conservation | Already on Planetary Computer. Same STAC code path. Licensing restricts to non-commercial analysis — our tool produces analysis, not redistribution. Needs legal review. |
| **Open-Meteo** | Weather data | Free (already integrated) | ✅ Done |
| **NASA FIRMS** | Fire hotspots | Free with API key (already integrated) | ✅ Done |

#### 13.3.2 Platforms to Integrate Later (Commercial, Revenue-Funded)

| Platform | What They Offer | Cost Model | When | Why |
|----------|----------------|-----------|------|-----|
| **Planet Labs** (direct API) | Daily 3m imagery (PlanetScope), 50cm (SkySat) | Per-km² or subscription ($2,700-$9,650/yr) | M7+ (post-revenue) | For premium customers who need sub-10m resolution. "Upgrade to Planet imagery" as an add-on. Costs us per-use, so must be priced into Enterprise tier. |
| **Airbus (Pléiades Neo / SPOT)** | 30cm-1.5m very high resolution | Per-order, $10-40/km² | Enterprise only | Specific high-value use cases (insurance claims, legal evidence). On-demand ordering via UP42 or Airbus's own API. |
| **UP42** | Marketplace aggregating Planet, Airbus, ICEYE, etc. | API-based, per-image pricing | M7+ | Single integration point for multiple commercial providers. Saves us from integrating each provider separately. ~€0.40–3.00/km² depending on resolution. |
| **SkyFi** | Aggregator with tasking (schedule a new capture) | Pay-per-image ($5-50 per scene) | Enterprise only | For customers who need fresh captures, not archive imagery. Niche use case. |
| **Maxar (SecureWatch)** | 30cm archive and tasking | Enterprise contracts, $$$  | Not recommended | Expensive, complex procurement, aimed at government/defence. Not our market. |
| **ICEYE SAR** | Commercial SAR (1m) | Via UP42 or direct. Expensive. | Niche | For ultra-precise change detection through clouds. Nice to have via UP42 aggregation. |
| **Picterra** | ML-based object detection on imagery | API, per-image | Experimental | Auto-detect buildings, roads, clearings in our imagery. Could augment AI analysis with computer vision. Independent ML layer. |

#### 13.3.3 Commercial Platform Strategy

**Phase 1 (now):** Free sources only. Planetary Computer + free APIs. Keep cost of goods at near-zero. This is correct for current stage.

**Phase 2 (post-revenue):** Planet-NICFI integration (free, already on PC). This gives us 4.77m tropical imagery at zero cost — a massive capability upgrade for EUDR. Legal review needed on terms.

**Phase 3 (Enterprise tier):** UP42 as a single integration point for commercial imagery. Offer as a premium add-on: "Need higher resolution? We can fetch 3m Planet or 50cm Airbus imagery for your site. £X per AOI." The key is NEVER absorbing the cost ourselves — pass through to the customer with margin.

**Do not integrate:** Maxar (too expensive, wrong market), Google Earth Engine (licensing quagmire for commercial use), Descartes Labs (shutdowns/pivots make it risky).

### 13.4 EUDR Persona — Can We Hit It Easily?

**Yes. This is the lowest-hanging fruit of any persona, and I'd argue it should be priority #1 for paid conversion.**

#### 13.4.1 Why EUDR Is Uniquely Easy for Us

| Factor | Why It Helps |
|--------|-------------|
| **The analysis already exists** | Our pipeline does exactly what EUDR requires: compare vegetation at two time points (baseline vs present), detect if forest was cleared, and report findings. |
| **Date filtering is trivial** | Constrain `start_date` to 2021-01-01. The pipeline already accepts date parameters. |
| **The users MUST buy something** | This isn't optional tooling — EUDR is law. Non-compliance = 4% of EU turnover fines. Every EU importer of cocoa, coffee, palm oil, soy, wood, rubber, or cattle MUST demonstrate due diligence. Thousands of firms, regulatory deadline pressure. |
| **The users can't do it themselves** | These are commodity importers and traders. They have supply chain and logistics expertise, not GIS skills. They cannot download Sentinel-2 tiles and run QGIS analyses. |
| **The alternative is absurdly expensive** | Consultancy: $10K-$50K per assessment, 4-8 weeks. GFW Pro: account request delay, consumption tokens, deforestation-only (no weather, no AI narrative). |
| **KML is not their format — coordinates are** | This sounds like a barrier but it's actually an opportunity. If we build a simple coordinate-to-KML converter (a few hours of work), we remove the last friction point. They paste in lat/long from a supplier spreadsheet and get evidence. |
| **Our pricing is radically cheaper** | £19/month for 15 plots vs. $10K-50K one-time from a consultancy. Even £49/month for 45 plots is cheaper than a single day of a consultant's time. |

#### 13.4.2 Exact Feature Gap — What We Need to Build

| Feature | Effort | Current State | What's Needed |
|---------|--------|--------------|---------------|
| **EUDR date filtering** | **½ day** | Pipeline accepts date filters | Add a preset: EUDR mode constrains to post-2020. UI toggle or query param. |
| **Coordinate-to-KML converter** | **1-2 days** | Not built | Accept CSV of (lat, lon, name) → generate KML → feed to pipeline. Simple geometry (point → buffer polygon, or polygon from coordinate list). Add to UI. |
| **Audit-quality PDF export** | **3-5 days** | GeoJSON + CSV export exist | WeasyPrint or ReportLab. Template with: plot ID, coordinates, date range, before/after imagery thumbnails, NDVI metrics, weather, AI narrative, methodology section, data sources, generation timestamp. Must look professional enough for an auditor. |
| **"Deforestation-free" statement** | **½ day** | AI narrative exists but doesn't lead with conclusion | Modify AI prompt to lead with clear conclusion: "No evidence of post-2020 deforestation detected" or "Significant vegetation change detected — manual review recommended." |
| **Methodology page** | **1 day** | Not written | Static content page: satellites used, indices, resolution, data sources, analysis steps. Auditors need this to trust the output. |
| **Batch upload** | **2-3 days** | Multi-polygon KML works; no CSV batch | Accept CSV of coordinates → generate multiple AOIs → fan-out pipeline (already architecturally supported). Progress/status tracking UI. |
| **ESA WorldCover overlay** | **1-2 days** | Not integrated | Add `esa-worldcover` collection to PC provider. Query land cover class at AOI coordinates. Report: "This plot is classified as Tree Cover (class 10) in the 2021 ESA WorldCover dataset." Baseline land cover class validation. |

**Total estimated effort: 10-15 working days** to have a credible EUDR offering.

#### 13.4.3 The EUDR Go-to-Market Play

```
Week 1:    EUDR date filtering + deforestation-free statement + methodology page
           (enabling: the analysis result is EUDR-relevant immediately)

Week 2:    Coordinate-to-KML converter + batch CSV upload
           (enabling: ESG users can upload supplier data without GIS skills)

Week 3:    Audit-quality PDF export
           (enabling: output is audit-ready, not just a dashboard screenshot)

Week 4:    ESA WorldCover overlay + WDPA protected area check
           (enabling: "this plot is classified as forest" and "this plot does/does not
           overlap a protected area" — both major audit evidence points)

Result:    In 4 weeks, Canopex has a credible EUDR compliance evidence tool
           that's cheaper, faster, and easier than any alternative for the
           mid-market (50-5,000 plots).
```

#### 13.4.4 EUDR Market Size — Tangible Numbers

- **Large EU operators** (EUDR enforcement Dec 2025): ~3,000+ companies
- **EU SME importers** (EUDR enforcement Jun 2026): tens of thousands more
- **ESG consultancies** doing EUDR audits on behalf of importers: ~500-2,000 firms
- **Every single one** needs satellite evidence of deforestation-free supply chains

Even capturing **0.5% of the large operator segment** = 15 paying customers × £49/month × 12 months = **£8,820 ARR** from one segment. At 2% capture = **£35,280 ARR**. And that's before SMEs and consultancies.

The real play is ESG consultancies — one consultancy that switches to Canopex for their EUDR assessments could process 100+ clients through our platform, hitting Team/Enterprise tiers. **Five consultancy customers at £149/month = £8,940 ARR with high retention** (switching cost once embedded in their workflow).

#### 13.4.5 Why EUDR Before Conservation

The persona deep dive (§12.1) ranked conservation first. For **product-market fit**, that's correct — conservation is the best match to what we've already built.

But for **revenue velocity**, EUDR wins:

| Factor | Conservation | EUDR |
|--------|-------------|------|
| Urgency | "We should monitor this" | "We MUST comply by June 2026 or face 4% fines" |
| Budget | $200-400/month discretionary | $5,000-50,000/year compliance budget |
| Decision speed | Programme manager evaluates, maybe quarterly | Compliance officer buys tomorrow if it solves the problem |
| Churn risk | High if monitoring isn't shipped | Low — regulatory requirement doesn't go away |
| Competition | GFW Free covers basics | GFW Pro requires approval + no weather/AI |
| Feature gap to close | Need monitoring/alerts (High effort) | Need PDF + date filter + coord converter (Low-Medium effort) |

**Recommendation: Ship EUDR features first (4 weeks), then monitoring/alerts for conservation (ongoing).** The EUDR features are smaller, faster to build, and target users who are buying under regulatory deadline pressure right now. Conservation monitoring is the long-term retention engine — ship it second but don't skip it.

### 13.5 Integration Priority Matrix — What to Add When

| Priority | Source | PC Collection / API | Effort | Milestone | Why Now/Later |
|----------|--------|-------------------|--------|-----------|--------------|
| **P0** | ESA WorldCover (10m land cover) | `esa-worldcover` | Low | M4 | EUDR baseline evidence: "this was forest." Already on PC, same code path. |
| **P0** | WDPA protected areas | protectedplanet.net API | Low | M4 | "This plot overlaps a protected area" → automatic red flag. |
| **P1** | IO LULC Annual V2 (10m, 2017-2023) | `io-lulc-annual-v02` | Low | M5 | Multi-year land cover change: "forest in 2019, cropland in 2022." |
| **P1** | Planet-NICFI (4.77m tropics) | `planet-nicfi-visual/analytic` | Medium | M5 | 4x resolution improvement for tropical EUDR areas. Free. Legal review needed. |
| **P1** | MODIS Burned Area | `modis-64A1-061` | Low | M5 | Already planned (M5.8). Complements FIRMS. Easy. |
| **P1** | ESA CCI Land Cover (1992-2020) | `esa-cci-lc` | Low | M5 | Already planned (M5.9). 28-year history. Easy. |
| **P2** | ALOS Forest/Non-Forest | `alos-fnf-mosaic` | Low | M5 | Independent SAR-based forest classification. Cross-validates optical analysis. |
| **P2** | GFW API (deforestation alerts) | REST API | Medium | M5 | Cross-reference with GFW authority. "GFW confirms 3 alerts in this area." |
| **P2** | MODIS Vegetation Indices | `modis-13Q1-061` | Low | M5 | 25-year NDVI baseline at 250m. Cross-validates Sentinel-2 trends. |
| **P2** | Copernicus DEM | `cop-dem-glo-30` | Low | M6 | Terrain context for AI interpretation. |
| **P2** | JRC Global Surface Water | `jrc-gsw` | Low | M6 | Prevents false positives: "this area is a seasonal floodplain, not deforestation." |
| **P2** | Chloris Biomass | `chloris-biomass` | Medium | M6 | Carbon quantification: "X tonnes of biomass lost." ESG currency. |
| **P3** | Sentinel-1 SAR analysis | `sentinel-1-rtc` | High | M7 | Cloud-penetrating deforestation detection. Critical for tropics but complex analysis. |
| **P3** | Biodiversity Intactness | `io-biodiversity` | Low | M7 | Conservation context metric. |
| **P3** | UP42 (commercial imagery) | REST API | High | M7+ | Access to Planet, Airbus, ICEYE. Enterprise tier only. |

---

## Appendix A: Research Sources

- Reddit r/gis — "Where do people get live satellite images from?" (2025)
- Reddit r/gis — "What imagery vendor do you use?" (2024–2025)
- Reddit r/gis — "Best geo tools for 2026" (2026)
- Reddit r/conservation — "We have high-res satellite imagery updated daily. Why can't we tackle illegal deforestation?" (2024)
- Global Forest Watch About page (globalforestwatch.org, 2026)
- Global Forest Watch Pro overview (pro.globalforestwatch.org, 2026)
- Global Forest Watch Pro pricing/license page (pro.globalforestwatch.org/help, 2026)
- Google Earth Engine main page (earthengine.google.com, 2026)
- Google Earth Engine noncommercial terms (earthengine.google.com/noncommercial, 2026)
- Planet Labs pricing page (planet.com/pricing, 2026)
- SkyFi pricing page (skyfi.com/pricing, 2026)
- UP42 pricing page (up42.com/pricing, 2026)
- Togai — "A Complete Guide to Usage-Based Pricing" (togai.com, 2023)
- SBI Growth — "Consumption-based Pricing Model Guide" (sbigrowth.com, 2025)
- McKinsey — "Does ESG Really Matter—and Why?" (mckinsey.com, 2022)
- OpenView Partners — "State of Usage-Based Pricing" (2023, cited via Togai)
