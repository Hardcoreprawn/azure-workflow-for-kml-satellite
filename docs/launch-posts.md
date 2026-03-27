# TreeSight Launch Posts — Reddit

> **Note:** Replace `[LINK]` with the live URL (treesight.io or the azurestaticapps staging URL).
> Post one per day over a week — don't carpet-bomb them all at once.
> Reply to comments promptly. The first 2 hours after posting matter most.

---

## 1. r/gis

**Title:** I built a tool that turns a KML file into a full satellite analysis — NDVI, weather, change detection. Would love feedback from actual GIS people.

**Body:**

A few months ago I saw a researcher posting about needing a satellite imagery pipeline — upload a KML boundary, get analysis back. I didn't know much about remote sensing at the time but it seemed like a genuinely interesting problem, so I started building it. Turns out it's a rabbit hole. A really good one.

The basic idea: you upload a KML (or KMZ), and it runs the whole pipeline for you — hits Planetary Computer for Sentinel-2/Landsat/NAIP imagery, computes NDVI, pulls historical weather from Open-Meteo, checks for fire hotspots and flood events, and gives you everything back as a timelapse with per-frame stats and change detection.

There's also an EUDR compliance mode that does ESA WorldCover land-cover sampling and WDPA protected area checks — been getting asked about that one a lot.

It uses Azure Durable Functions for orchestration, so it can fan out across multiple polygons in parallel. The geo-routing picks the best collection based on where your AOI is (NAIP for US, Sentinel-2 globally, Landsat as fallback). Export to PDF, GeoJSON, or CSV.

Free tier gives you 3 AOIs/month. There's a live demo on the site where you can pick from sample areas or paste your own KML — no sign-up required for that.

[LINK]

I'd genuinely appreciate feedback — especially on the analysis output quality and anything that feels clunky. I'm a solo dev on this so there's definitely rough edges.

**Flair:** Software/Tool

---

## 2. r/remotesensing

**Title:** Open-access tool for automated Sentinel-2/Landsat analysis from KML boundaries — includes NDVI change detection, land-cover classification, and weather correlation

**Body:**

This started because I saw a researcher asking for exactly this kind of tool — a way to go from a KML boundary to satellite analysis without stitching together five different APIs. I didn't know much about remote sensing when I started, but I've learned a lot since. Sharing it here because this community probably has the best perspective on whether the analysis output is actually useful.

**What it does:** You give it a KML polygon. It queries Planetary Computer's STAC catalog for the best available imagery (Sentinel-2 L2A, Landsat C2 L2, NAIP where available), computes NDVI across the temporal series, overlays Open-Meteo weather data, and runs change detection with canopy loss quantified in hectares.

**Data sources:**

- Sentinel-2 L2A (10m, global)
- Landsat Collection 2 Level-2 (30m, global, historical)
- NAIP (0.6m, US CONUS)
- ESA WorldCover (10m land cover classification — raster sampled, not just metadata)
- WDPA protected areas (API lookup)
- Open-Meteo historical weather
- FIRMS fire hotspots
- GloFAS flood extent

**Methodology:** NDVI from red/NIR bands with SCL-based cloud masking for Sentinel-2. Pairwise temporal differencing for change magnitude. WorldCover sampling does a windowed COG read and counts pixels per class, excluding nodata from the denominator. There's a methodology page on the site if you want the details.

It's built on Azure Functions with Durable Functions orchestration. All imagery comes from Planetary Computer's free STAC API — no proprietary data. Exports to GeoJSON (FeatureCollection with per-frame properties), CSV, or PDF.

Free to try: [LINK]

Happy to discuss the approach or take suggestions on what would make the analysis output more useful for your workflow.

---

## 3. r/conservation

**Title:** Free tool for monitoring deforestation and land-use change from satellite imagery — built for people who don't have GIS teams

**Body:**

This started when I saw a researcher posting about needing a satellite imagery pipeline and thought "that sounds like an interesting build." I didn't know much about remote sensing at the time, but I've since learned that the existing tools are either expensive (Planet is $10K+/year), require coding skills (Google Earth Engine), or too narrow for general use (Global Forest Watch is fantastic but forest-only).

So I built TreeSight. You draw a boundary in Google Earth Pro, save it as a KML file, upload it, and get back:

- Multi-year satellite imagery timelapse
- Vegetation health (NDVI) trends with change detection
- Historical weather data synced to the imagery timeline
- Fire hotspot and flood event detection
- AI-generated summary in plain English explaining what's happening
- Land cover breakdown (forest, cropland, water, etc.)

It's designed so you don't need GIS skills. There's a step-by-step guide for creating KML files, and sample areas you can try without signing up.

The EUDR compliance mode might be relevant for anyone working on supply chain deforestation — it does post-2020 land cover analysis, protected area checks, and generates audit-ready PDF reports.

Free tier: 3 areas per month, no credit card needed.

[LINK]

I'm particularly interested in hearing from conservation orgs about what would actually be useful in your day-to-day work. What data do you wish you had easier access to?

---

## 4. r/supplychain

**Title:** Automated satellite evidence for EUDR deforestation-free compliance — much cheaper than consultancy engagements

**Body:**

I originally started building a satellite analysis tool after seeing a researcher post about needing a KML-to-imagery pipeline. As I got deeper into it, I realised the EUDR compliance use case was a natural fit — the pipeline already had the building blocks.

**The problem it solves:** Right now, proving a sourcing region is deforestation-free typically means hiring a consultancy ($10K–$50K per assessment, 4–8 week turnaround) or having someone manually work through Sentinel Hub or Google Earth Engine.

**What TreeSight does:** You upload a KML boundary of your sourcing region. It automatically:

1. Pulls Sentinel-2 satellite imagery from 2020 onwards (the EUDR baseline date)
2. Computes vegetation change detection — quantified in hectares
3. Samples ESA WorldCover for land-cover classification (forest, cropland, etc.)
4. Checks against the WDPA protected areas database
5. Generates an AI assessment of deforestation risk
6. Exports a PDF audit report with all the evidence

The whole thing runs in minutes, not weeks. Results are quantified and repeatable — same input always gives same output, which matters for auditors.

Pricing starts at £19/month for 15 assessments. There's a free tier (3/month) if you want to test it.

[LINK]

I'm not claiming this replaces a full EUDR compliance programme, but it handles the satellite evidence component at a fraction of the cost and turnaround time. Would be interested to hear from anyone dealing with EUDR requirements — what would make this more useful for your compliance workflow?

---

## 5. r/agriculture (or r/precision_ag)

**Title:** Built a tool that gives you NDVI trends + weather data for any field boundary — just upload a KML file

**Body:**

Quick background: I started building a satellite analysis tool after seeing a researcher ask for exactly this — a way to go from a field boundary to NDVI analysis without a GIS degree. I didn't know much about remote sensing when I started, but the ag use case turned out to be one of the most practical applications.

**How it works:** Export a field boundary from Google Earth Pro as a KML file, upload it, and you get:

- NDVI vegetation health across the entire Sentinel-2 archive (every 5 days, going back years)
- Historical weather overlaid on the same timeline — so you can see exactly how a dry spell or frost event affected vegetation
- Change detection that flags significant NDVI drops and quantifies the area affected
- AI-generated summary tying the imagery, weather, and NDVI data together

It uses Sentinel-2 (10m resolution) globally, with NAIP (0.6m) for US fields where available. The geo-routing automatically picks the best data source for your location.

I built it because the existing options are either too expensive for smaller operations (Planet, $10K+/yr), too manual (downloading Sentinel tiles and doing band math yourself), or require coding (Earth Engine).

Free tier: 3 fields per month. Starter plan is £19/month for 15 fields.

[LINK]

I'd be interested to know: if you're currently tracking crop health via satellite, what's your workflow? And what resolution/revisit frequency do you actually need?

---

## 6. r/SideProject

**Title:** I built an automated satellite analysis platform as a solo dev — Azure Functions, Planetary Computer, 595 tests, and an actual pricing page

**Body:**

A few months ago I saw a researcher posting about needing an automated satellite imagery pipeline. I didn't know anything about remote sensing, NDVI, or STAC catalogs at the time — but it sounded like a great learning project. Fast forward to now: 12 out of 13 milestone items done, 595 tests, and I've accidentally built something that might actually be useful.

**TreeSight** takes a KML file (a polygon drawn in Google Earth), runs it through a satellite imagery pipeline, and gives you back multi-year NDVI analysis, weather correlation, fire/flood detection, land-cover classification, and AI-generated insights.

**Tech stack:**

- Python 3.12 on Azure Functions (Container Apps with custom Docker — needed GDAL for raster processing)
- Azure Durable Functions for orchestration (fan-out/fan-in across polygons)
- Planetary Computer STAC API for Sentinel-2, Landsat, NAIP imagery
- Azure AI Foundry for the narrative generation
- Stripe for billing (multi-currency, webhooks, customer portal)
- Azure Entra External ID for auth
- 595 tests, CI with GitHub Actions + Semgrep + Trivy + CodeQL

**What I learned:**

- Durable Functions are incredible for orchestrating long-running pipelines but the payload size limits will bite you — I had to build a blob-based payload offloader
- Planetary Computer's free STAC API is genuinely amazing. Never thought I'd have access to the entire Sentinel-2 archive at no cost
- EUDR compliance turned out to be a surprisingly good niche — there's real demand for automated deforestation evidence and the existing options are expensive consultancies
- Building billing before you have users feels pointless but I'm glad I did it — Stripe's webhook handling has a lot of edge cases

Free to try: [LINK]

Happy to answer questions about the architecture or the Azure Functions setup.

---

## Posting Schedule (Suggested)

| Day | Subreddit | Why this order |
|-----|-----------|----------------|
| Mon | r/gis | Core audience, get technical feedback first |
| Tue | r/SideProject | Builder community, good for early upvotes and cross-traffic |
| Wed | r/remotesensing | Academic/professional, may generate methodology discussion |
| Thu | r/conservation | Mission-driven audience, tests the "no GIS skills" messaging |
| Fri | r/supplychain | EUDR angle, different audience entirely — tests compliance messaging |
| Next Mon | r/agriculture | Ag use case, tests the crop monitoring angle |

**General rules:**

- Post between 9–11am UTC (US East morning, EU afternoon)
- Reply to every comment within 2 hours
- Don't cross-post — each post is unique to the subreddit
- If a post gets traction, edit to add "Edit: thanks for the feedback, here's what I'm changing based on your comments" — shows you're listening
- Don't be defensive about criticism. "That's a good point, I'll look into it" goes a long way
