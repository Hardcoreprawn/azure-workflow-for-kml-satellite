# Canopex — Project & Product Review

**Date:** 12 April 2026  
**Scope:** Full project review — product, codebase, progress, business model, user journey  
**Purpose:** Critical assessment with recommendations for reaching a workable platform  

---

## Executive Summary

Canopex has strong technical foundations but is not yet delivering value to users. The project has accumulated significant engineering depth — 1,091 passing tests, 382 commits in 2026, a well-structured Python backend, Rust acceleration, durable orchestration — but the path from "visitor lands on site" to "user pays and gets value" is incomplete. The core pipeline works. The billing integration exists. The auth works. But these pieces don't yet connect into a seamless user journey that a conservation analyst or ESG officer would complete without friction.

**The honest verdict: broadly on the right track, but too much time spent on infrastructure plumbing and not enough on the user-facing experience that converts visitors into paying users.**

---

## 1. What's Working Well

### 1.1 Technical Foundations — Genuinely Strong

- **Pipeline quality.** KML → parse → STAC search → download → clip → NDVI → weather → AI narrative. This is real, works, and is differentiated. No competitor offers this as a single automated workflow.
- **Test discipline.** 1,091 tests across 55 files, passing in 4.3s. High coverage of parsers, billing, security, pipeline, and API contracts. This is production-grade quality.
- **Security posture.** Zip bomb protection, XXE-safe XML parsing, auth enforcement, quota gates, SAS token scoping, rate limiting. These aren't afterthoughts — they're built in.
- **Architecture documentation.** PID, architecture overview, API reference, persona deep dive, system spec, operations runbook. Unusually thorough for a project this size.
- **Cost-conscious design.** Planetary Computer (free imagery), scale-to-zero compute planning, Container Apps over AKS, blob storage with Cosmos fallback. The architecture respects the £10/month budget target.

### 1.2 Product Thinking — Exceptionally Detailed

The persona deep dive is one of the best product documents I've reviewed. It correctly identifies:

- The "evidence generation platform" positioning (9/10 score — agreed).
- The GEE commercial licensing gap (genuine competitive advantage).
- The GFW Pro limitations for small orgs (genuine market opening).
- The conservation analyst's workflow and time savings (20–170x ROI claim is plausible).
- The EUDR compliance urgency (SME deadline June 2026 — imminent).

### 1.3 Pricing Strategy — Broadly Correct

The tier structure (Free/Starter/Pro/Team/Enterprise) maps to persona willingness-to-pay. The £19 Starter is below NGO discretionary spend thresholds. The free tier at 5 runs is enough to demonstrate value without creating significant cost exposure.

---

## 2. What's Not Working

### 2.1 The User Journey Is Broken

This is the critical finding. I'll walk through what a new visitor experiences:

1. **Landing page** — Good. Clear positioning ("From Boundary to Evidence in 5 Minutes"), credible content, transparent methodology, well-structured pricing. The page itself is solid.

2. **"Try Live Demo" click** — Takes you to `/app/?mode=demo`. This is where it breaks down:
   - The user sees "Free plan preview" with a dashboard layout showing "No runs yet."
   - There is no actual demo content. No sample analysis. No pre-computed showcase. A first-time visitor sees an empty dashboard with placeholders.
   - The "Start Your First Analysis" button requires sign-in. The demo is not a demo — it's a preview of an empty UI.
   - The showcase concept (pre-computed static blobs from stock AOIs) is documented in the architecture but **not visible on the demo page**. `app-shell.js` has no `showcase` or `demo_artifacts` references.

3. **Sign-in** — Uses SWA built-in Azure AD via the configured `/.auth/login/aad` flow. This means the user signs in with the Microsoft/Azure AD provider currently configured for the app, not Google or GitHub. This is fine for developers but may confuse conservation analysts or ESG officers who expect email/password or magic-link auth. The auth provider choice is undocumented on the site.

4. **After sign-in** — The user arrives at the same empty dashboard. They need to:
   - Know what a KML file is (the KML guide exists but is linked, not shown inline)
   - Have a KML file ready to upload
   - Upload it and wait for the pipeline to complete

5. **The billing/status endpoint returns 500** (issue #520). A signed-in user hitting the landing page gets a server error on the billing status check. This is a live-site bug that breaks the experience.

**Bottom line:** A visitor cannot see what the product actually produces without signing up, creating a KML, uploading it, and waiting for the pipeline. This is too much friction for conversion. They need to see real output before they invest effort.

### 2.2 The Demo/Showcase Gap

The architecture doc describes a showcase concept: pre-computed analysis outputs from stock AOIs that anonymous visitors can browse. This is exactly the right idea. But it doesn't appear to be implemented in the frontend. The demo mode shows an empty dashboard with sign-in prompts.

**This is the single highest-impact gap.** The landing page promises "From Boundary to Evidence in 5 Minutes" but doesn't show what that evidence looks like. A prospective conservation analyst needs to see a real NDVI analysis, a real weather correlation chart, and a real AI narrative before they'll invest time signing up.

### 2.3 Too Much Infrastructure, Not Enough Product

Look at the commit history and recently completed work:

| Priority | Theme | Status |
|----------|-------|--------|
| P0 | Live site fixes (CSP, auth) | ✅ Done |
| P1 | Event-driven pipeline restructure | ✅ Done |
| P2 | Code quality and validation | ✅ Done |
| P3 | BYOF consolidation (delete SWA managed API) | ✅ Done |
| P4 | Release safety and promotion | 🔄 In progress |
| P5 | Split T2/T3 (API + Compute) | Not started |

P0–P3 were all architecture/infrastructure work. Necessary, but not user-facing. The BYOF migration alone consumed substantial engineering effort (PRs #510, #512, #515, #516, #521, #523) over multiple weeks, mostly to solve an internal routing problem (SWA managed functions vs Container Apps FA). The user doesn't know or care about this distinction.

Meanwhile, the features that would actually convert users are untouched:

- **Showcase/sample analysis** — not built
- **Monthly monitoring + alerts** — not built (the single most important retention feature per the persona doc)
- **Batch upload for ag/ESG personas** — not built
- **PDF export quality** — "basic" per the persona feature list

The 339 commits since March 1 produced a cleaner architecture but no new user-visible capability.

### 2.4 The £10/Month Budget vs. Min-1-Replica Conflict

The dev environment runs `function_min_instances = 1` with 2 vCPU / 4 GiB. At Azure Container Apps pricing, this is roughly £20/month, already 2x the stated budget. The P5 plan to split into T2 (0.5 vCPU, always-on) + T3 (scale-to-zero) would reduce this to ~£8/month — but P5 hasn't started, and it depends on P4, which depends on P3 (just completed).

For a product with zero paying customers, running £20/month of always-on compute is defensible only if it serves real users. Currently it serves the developer. The cost model works at scale but is disproportionate at zero scale.

### 2.5 Auth Security Caveat

The architecture doc acknowledges a known limitation:

> The `X-MS-CLIENT-PRINCIPAL` header is client-supplied and not cryptographically verified by the FA. A direct HTTP client (not bound by CORS) could forge this header.

This is mitigated by CORS, but CORS is not a security boundary — it's a browser policy. Any HTTP client (curl, Postman, Python requests) can call the API with a forged principal header. For a free-tier product with rate limiting, this is acceptable risk. For a product handling EUDR compliance evidence that customers rely on for regulatory purposes, it is not. This needs to be fixed before paid tiers launch.

### 2.6 The 3,100-Line `app-shell.js`

The main application UI is a single 3,102-line vanilla JavaScript file with no build step, no framework, no components. This was a deliberate choice (documented in the website-js instructions) prioritising simplicity and traceability. For the current scope it's manageable, but it's approaching the limit. Adding monitoring dashboards, batch upload, temporal catalogue browsing, and team workspaces into a single file will become unmaintainable.

This doesn't need to change today, but it should be flagged as a constraint on P6/P7 feature velocity.

---

## 3. Time Allocation Analysis — Was Time Wasted?

### 3.1 Commit Velocity by Month (2026)

| Month | Commits | Primary Theme |
|-------|---------|---------------|
| January | ~39 | M4 Revenue, billing, Stripe |
| February | 43 | Stage 1–2, pipeline modularisation |
| March | ~203 | SWA auth migration, BYOF, code quality |
| April (11 days) | 97 | BYOF consolidation, deploy pipeline, ops |

March was extraordinarily high-velocity — 203 commits in 31 days. Nearly all of this was architecture migration: moving from SWA managed functions to Container Apps FA, switching auth from MSAL.js to SWA built-in, and consolidating the API surface. This was driven by real technical debt (SWA managed functions lack managed identity, Key Vault, Durable Functions, and only support Python ≤3.11), but the magnitude of the effort was high for what was essentially an internal refactoring.

### 3.2 Was This the Right Order?

**Partially.** The SWA limitations were genuine blockers for billing (needs Key Vault for Stripe keys) and pipeline (needs Durable Functions). Fixing them was necessary. But the migration consumed 5–6 weeks of engineering time that could have been partially avoided by:

1. Not building on SWA managed functions in the first place (hindsight — the original choice was reasonable at the time).
2. Making the migration faster by doing a hard cutover rather than an incremental multi-PR approach (B.1–B.12 tracked as 12 separate items, most of which were "already exists" — the endpoints were on Container Apps FA from the start).

**What should have been done instead during March:**

- Build the showcase/sample analysis (2–3 days of work, max)
- Fix billing/status 500 (issue #520, probably a 1-day fix)
- Polish the sign-up → first-analysis flow
- Ship a real "5-minute demo" that a visitor can experience without signing up

These would have more impact on user conversion than a clean BYOF architecture.

### 3.3 Things That Were Not a Waste

- **The persona deep dive** — Genuinely excellent research. This will pay off in positioning and product decisions.
- **Test infrastructure** — 1,091 tests give confidence to move fast without regression.
- **Billing integration** — Stripe Checkout with UK VAT, multi-currency, webhook handling. This is correctly built and ready for revenue.
- **Security hardening** — Zip bomb protection, XXE prevention, rate limiting. These are non-negotiable for a public-facing service.
- **The Rust NDVI/change-detection module** — Smart performance investment for compute-heavy paths.

### 3.4 Things That Were Premature

- **Azure Batch fallback for 50k+ ha AOIs** — No user has this use case today. The constant is defined; that's enough.
- **Container Apps Jobs planning (P8)** — Detailed cost modelling for burst compute when there are zero users. Good thinking, wrong timing.
- **Ops dashboard endpoint and CLI monitor** — The latest PR (#530) adds operational monitoring tools. Useful for a production service under load; premature for a product with no users.
- **12 enrichment data sources on the roadmap** — MODIS, ESA CCI Land Cover, ALOS Forest, IO LULC, etc. The current sources (Sentinel-2, NAIP, Open-Meteo, FIRMS, EA flood) are sufficient for launch. Ship with what works.

---

## 4. Recommendations: The Critical Path to a Workable Platform

### 4.1 The Minimum Viable User Journey (Priority 1 — Do Now)

These are the items that must work before inviting any user:

#### R1. Build the Showcase (1–3 days)

Pre-compute 3–4 compelling demo analyses using real AOIs:

1. **A tropical deforestation case** (Central Africa or SE Asia) — shows NDVI drop, no drought correlation, AI narrative saying "likely anthropogenic clearing." This is the conservation money shot.
2. **A UK/EU agricultural parcel** — shows seasonal NDVI cycle, weather correlation, crop health interpretation. Speaks to the ag advisor.
3. **A supply chain plot** — shows "no deforestation since 2020" evidence for EUDR. Speaks to the ESG buyer.

These run through the real pipeline, and the outputs (imagery tiles, NDVI charts, weather data, AI narrative) are stored as static blobs. The demo page renders them without auth or pipeline execution. The visitor sees exactly what they'd get as a customer, in 5 seconds, not 5 minutes.

**This is the highest-ROI work in the entire backlog.**

*Post-review note:* The updated roadmap/architecture decision is to defer Showcase implementation until after `#531` and `#532`, prioritising those release-safety items first. Showcase remains a high-value follow-on once that work lands.

#### R2. Fix the Billing/Status 500 (Hours)

Issue #520 — the `/api/billing/status` endpoint returns 500 for signed-in users. This breaks the landing page experience for anyone who's logged in. Fix it.

#### R3. Polish the First-Run Flow (1–2 days)

After sign-in, the user should:

1. See their plan (Free) and remaining runs (5) prominently.
2. Be offered a **sample KML** they can run with one click (not just told to create one). Include 2–3 pre-made KMLs: "Amazon Forest Plot," "UK Farm," "Palm Oil Concession."
3. See their first analysis complete and be able to browse results.
4. See a clear upgrade prompt showing what Starter/Pro adds.

#### R4. Fix Auth Header Verification (1–2 days)

The forged `X-MS-CLIENT-PRINCIPAL` risk. Options:

- **Simplest:** Add an SWA-injected custom header that the FA validates (SWA can add headers on the proxy path).
- **Better:** Sign the principal with a shared HMAC secret in Key Vault.
- **This must be done before billing goes live** — you can't charge users through an auth system that can be trivially bypassed.

### 4.2 Revenue Enablement (Priority 2 — Do This Month)

#### R5. Verify End-to-End Billing Flow

Test the complete journey: Free user → "Upgrade to Starter" → Stripe Checkout → payment → plan upgrade reflected in dashboard → increased quota → real pipeline run on Starter limits. This likely works but hasn't been validated end-to-end on the live site.

#### R6. Show Real Prices on the Pricing Page

The landing page shows "$ Starter", "$$ Pro", "$$$ Team" — placeholder symbols, not real prices. The persona doc says £19 Starter, £49 Pro, £149 Team. Put the actual numbers on the page. Users who see "Express Interest" instead of a price assume the product isn't ready. (This may be intentional for early access, but it reduces conversion.)

#### R7. Cost Containment for Zero-Revenue Phase

Until paying customers exist:

- Reduce `function_min_instances` to 0 (accept cold starts for now — there are no latency-sensitive users).
- Keep Cosmos DB on serverless provisioning (RU/s auto-scaling from 0).
- Verify the Stripe test-mode configuration matches live mode (so the first real payment doesn't fail on a config mismatch).

### 4.3 Persona-Specific Gaps (Priority 3 — Next 1–2 Months)

#### Conservation ("Pat")

- **What they need now:** The showcase (R1) with a deforestation case. The sample KML one-click run (R3). The PDF export being good enough to include in a donor report.
- **What they need soon:** Monthly monitoring + alerts (P6/3.1 on roadmap). This is the retention driver — without it, Canopex is a one-shot tool. But it requires subscription revenue to justify the compute cost of scheduled re-runs.
- **Recommendation:** Ship the showcase and first-run flow. Get 5–10 conservation users on the free tier. Validate they complete the flow and find the output useful. THEN build monitoring.

#### Agriculture ("Ag Advisor")

- **What they need now:** Batch upload for multiple parcels (they have 50–500 parcels, not 1). Multi-polygon KML already works, but the UX needs to clearly show per-polygon results.
- **What they need soon:** CSV export with per-parcel NDVI time series. This is their working format.
- **Honest assessment:** At 50% fit (per the persona doc), the ag persona is a stretch for launch. Focus on conservation and ESG first. Ag becomes viable when batch upload and per-parcel CSV are built.

#### ESG/EUDR ("Elena")

- **What they need now:** The showcase (R1) with a "no deforestation since 2020" case. The EUDR methodology page (exists and is good). Batch processing for 50+ supply chain locations.
- **What they need soon:** A downloadable evidence pack that an auditor recognises (timestamped PDF with methodology description, satellite images, NDVI metrics, and a clear statement of findings).
- **EUDR timing:** SME enforcement is June 2026 — two months away. If you can get a working evidence workflow to 5 beta ESG customers in the next month, you have a real revenue opportunity. If you miss this window, the next regulatory pressure point is the first enforcement actions (likely late 2026).

### 4.4 Architecture Simplification (Priority 4 — Ongoing)

#### R8. Stop the T2/T3 Split Work Until You Have Users

The P5 plan to split into API + Compute images is a cost optimisation that saves ~£12/month. At zero users, this is irrelevant. At 10 users, it's a nice-to-have. At 100 users, it's important. Don't spend engineering time on it until the user count justifies the savings.

#### R9. Don't Start P7/P8 (Team, Enterprise, ML, React Frontend)

The roadmap correctly says "Do not start until Stage 4 is generating revenue." Enforce this. Team workspaces (#313), React frontend (#86), tree detection (#82), annotation tools (#87) — all of these are post-revenue features. They should not consume any engineering time until there are paying customers.

#### R10. Contain Feature Creep in Enrichment Sources

The roadmap lists 5+ additional enrichment sources (MODIS, ESA CCI, ALOS, IO LULC, GFW alerts). Each is "a single PR" but also adds testing surface, failure modes, and maintenance burden. The current sources (Sentinel-2, NAIP, Open-Meteo, FIRMS fire, EA flood) are sufficient for launch and cover all three personas. Add more only when a customer asks for them.

---

## 5. Business Model Assessment

### 5.1 Cost Structure

| Component | Monthly Cost (Current) | At Scale (100 users) |
|-----------|----------------------|---------------------|
| Container Apps FA (min 1 replica, 2 vCPU) | ~£20 | ~£20–40 (auto-scale) |
| Cosmos DB (serverless) | ~£1–5 | ~£5–15 |
| Blob Storage | <£1 | ~£2–5 |
| Static Web App (free tier) | £0 | £0 |
| AI Foundry (GPT for narratives) | ~£0.50/analysis | ~£50 (at 100 analyses/day? unlikely) |
| Planetary Computer | Free | Free |
| Open-Meteo | Free | Free |
| **Total** | **~£25/month** | **~£30–65/month** |

### 5.2 Revenue Model

| Tier | Price | Users Needed to Cover Costs |
|------|-------|-----------------------------|
| Free | £0 | — |
| Starter | £19/month (est.) | 2 users = £38 |
| Pro | £49/month (est.) | 1 user = £49 |
| Team | £149/month (est.) | 1 user = £149 |

**Break-even: 2 Starter users or 1 Pro user.** This is an excellent cost structure. The Planetary Computer free imagery and Open-Meteo free weather data mean the primary costs are compute (processing) and AI (narratives). Both scale linearly with usage, not with user count.

### 5.3 Risk: AI Costs at Scale

The AI narrative feature uses GPT (via Azure AI Foundry). At ~£0.30–0.50 per analysis, this is a marginal cost that scales with usage. For Pro users (50 analyses/month), that's £15–25/month in AI costs against £49 revenue — manageable but worth watching. For Team users (200 analyses/month), it's £60–100 against £149 — tighter. Consider caching AI narratives for identical NDVI/weather patterns and batching requests.

### 5.4 The Partnering Model Is Correct

Using Planetary Computer for imagery (free, Microsoft-backed, stable) and Open-Meteo for weather (free, open-source) is the right strategy. These are not vendor dependencies that could be pulled — Planetary Computer is Microsoft's strategic commitment to open geospatial data, and Open-Meteo is community-maintained.

The risk is Planetary Computer imposing rate limits or usage tiers (they currently don't for STAC search and blob access). Mitigation: the provider adapter pattern means switching to USGS EarthExplorer or Copernicus Data Space would be an implementation change, not an architecture change.

### 5.5 Scale-to-Zero Reality

The architecture is designed for scale-to-zero but doesn't currently achieve it (min 1 replica). The P5 split would enable it for the compute tier. Until then, the fixed cost is ~£20/month regardless of usage. This is the right trade-off for a product targeting its first users (cold-start latency on the first request would be a terrible first impression), but should be reevaluated if user acquisition stalls.

---

## 6. The Landing Page — Specific Feedback

### 6.1 What's Good

- **Headline** ("From Boundary to Evidence in 5 Minutes") — perfect. Clear, specific, action-oriented.
- **Problem section** — resonates with anyone who's used manual GIS workflows.
- **Pipeline workflow** — clear 6-step visual explanation.
- **Data sources & methodology** — unusually transparent. Builds trust with technical evaluators.
- **Known limitations** — honest about cloud filtering, weather centroid, and NAIP cycle. This builds more trust than omitting them.
- **FAQ** — answers real questions. Good.
- **Legal** — Terms, privacy, UK consumer regulations, VAT handling. All present and correct.

### 6.2 What Needs Fixing

- **No visual evidence of output.** The page describes what you get but never shows it. Add screenshots or an interactive sample of a completed analysis (the showcase).
- **Pricing shows symbols not numbers.** "$", "$$", "$$$" — not real prices. Even if final pricing isn't set, show indicative ranges ("from £19/month").
- **"Express Interest" vs. "Sign Up"** for paid tiers. This signals "not ready." When the product is ready, change to "Subscribe" with direct Stripe Checkout links.
- **The "Early Access" form** at the bottom asks for organisation and use case. This is good for lead generation but should be supplemented with a direct sign-up path for users who are ready now.
- **No social proof.** No testimonials, no case studies, no "used by" logos. Understandable at this stage, but plan for it. Even "3 analyses run this week" or "50+ AOIs processed" would help.
- **The custom domain `hrdcrprwn.com`** is a developer-internal domain. It needs to change to something user-facing before sharing publicly (canopex.io, canopex.earth, etc.). This may already be planned.

---

## 7. Open Issues Assessment — Priority Triage

Of the 35 open issues, here is a ruthless triage:

### Do Now (Blocks User Conversion)

| # | Title | Why Now |
|---|-------|---------|
| #520 | `/api/billing/status` returns 500 | Landing page is broken for signed-in users |
| — | Build showcase/sample analysis | Visitors can't see product value without signing up |
| — | Add sample KMLs to first-run flow | Users shouldn't need to create KML to try the product |

### Do This Month (Enables Revenue)

| # | Title | Why This Month |
|---|-------|----------------|
| #528/#529 | Split BFF + pipeline (if needed for scaling) | Only if cost reduction is critical |
| #402 | Gate production deploys on security | Before billing goes live |
| #403 | Production rollout with smoke gates | Before billing goes live |

### Do Later (Post-Revenue)

| # | Title | When |
|---|-------|------|
| #488 | Pipeline perf optimisation | When processing volume justifies it |
| #466 | Container Apps split | When cost exceeds revenue |
| #313 | Team workspaces | When Team tier has customers |
| #82/#83/#84 | Tree detection / health / ML | Stage 5+ |
| #86 | React frontend | Stage 5+ |
| #87 | Annotation tools | Stage 5+ |

### Close or Deprioritise

| # | Title | Rationale |
|---|-------|-----------|
| #467 | Container Apps Jobs burst compute | Phase 3 of a plan that hasn't started Phase 2. Premature. |
| #252 | Rate limiter persistence (Redis/Cosmos) | Only relevant at multi-instance scale. Close until needed. |
| #228 | Distributed replay store for valet tokens | Same — multi-instance concern. Not relevant now. |
| #474 | Migrate remaining browser-facing endpoints to SWA | Already superseded by BYOF — should be closed |

---

## 8. Summary: The 30-Day Plan

If you want to have a shareable, working product within a month:

**Week 1:**

- Fix #520 (billing/status 500)
- Build showcase with 3 pre-computed demo analyses
- Add showcase rendering to the demo page
- Put real indicative prices on the pricing page

**Week 2:**

- Add sample KML one-click run to the signed-in first-run flow
- Verify end-to-end Stripe billing on dev (free → Starter upgrade → payment → quota increase → run analysis)
- Fix auth header verification (HMAC or SWA-injected header)

**Week 3:**

- Polish PDF export for a conservation donor report use case
- Add EUDR evidence section to export (date range, "no deforestation" statement)
- Write 3 blog posts: "GFW vs Canopex," "Satellite Analysis Without Code," "EUDR Evidence in 5 Minutes"

**Week 4:**

- Get 5–10 beta users (conservation contacts, ESG contacts, your network)
- Monitor their experience: do they complete the flow? Where do they drop off?
- Fix what breaks

**After that:**

- Monthly monitoring + alerts (the retention feature)
- Batch upload (the ESG/ag feature)
- T2/T3 split (when costs require it)

---

## 9. Final Assessment

| Dimension | Score | Notes |
|-----------|-------|-------|
| **Technical quality** | 8/10 | Strong foundations, good tests, security-aware. |
| **Architecture** | 7/10 | Sound design, maybe over-engineered for current scale. |
| **Product-market thinking** | 9/10 | Persona analysis is exceptional. Positioning is sharp. |
| **User journey** | 3/10 | Broken demo, empty dashboard, no showcase, billing 500. |
| **Time allocation** | 5/10 | Too much infra, not enough user-facing work. |
| **Business model** | 8/10 | Excellent cost structure. Free data sources. Low break-even. |
| **Launch readiness** | 4/10 | Architecture is ready. Experience is not. |

**The core problem is a gap between exceptional product thinking and incomplete product delivery.** The team knows exactly what to build (the persona doc proves this) but has been pulled into infrastructure work that, while necessary, doesn't help users. The next month should be entirely focused on the user journey: see value → sign up → run analysis → see results → upgrade.

The product itself — automated satellite evidence from a KML upload — is genuinely differentiated and serves real needs. The competitive analysis is accurate. The pricing is right. The technology works. What's missing is the last mile: letting a visitor experience it without friction.

**Stop building infrastructure. Start shipping experience.**
