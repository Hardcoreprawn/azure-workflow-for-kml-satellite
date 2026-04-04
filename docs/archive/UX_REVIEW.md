# Canopex UX Review — Jobs To Be Done, Flows & Recommendations

**Date:** 30 March 2026  
**Scope:** Marketing site (`/`), signed-in app (`/app/`), KML guide (`/kml-guide.html`)

---

## 1. Jobs To Be Done (JTBD)

### Job 1 — Discover & Evaluate (Visitor → Prospect)

**Job statement:** *"When I hear about Canopex, I want to quickly understand what it does and whether it's relevant to my work, so I can decide if it's worth trying."*

| Dimension | Detail |
|-----------|--------|
| **Trigger** | Referral, search, social post, conference mention |
| **Current surface** | Marketing hero + problem cards + capabilities list |
| **Success metric** | Visitor reaches the demo section or pricing section within 60 s |
| **Failure mode** | Bounces because the value prop is too technical or takes too long to parse |

### Job 2 — Try Before Committing (Prospect → Demo User)

**Job statement:** *"When I'm considering Canopex, I want to test it with my own area of interest (or a sample), so I can see real output quality before creating an account."*

| Dimension | Detail |
|-----------|--------|
| **Trigger** | Clicks "Try Live Demo" or scrolls to `#demo` |
| **Current surface** | Demo section — KML input, sample picker, progress stepper, timelapse viewer, analysis panels |
| **Success metric** | Sees meaningful satellite imagery + NDVI analysis within 3–5 min |
| **Failure mode** | Doesn't know what a KML is; can't produce one; confused by textarea; leaves |

### Job 3 — Decide on a Plan (Demo User → Paying Customer)

**Job statement:** *"After seeing demo results, I want to understand what the paid tiers unlock and how much they cost, so I can justify the purchase or request budget."*

| Dimension | Detail |
|-----------|--------|
| **Trigger** | Sees demo results OR reads about gated features (AI, EUDR, exports) |
| **Current surface** | Pricing section (4-tier grid), early-access form |
| **Success metric** | Identifies the right tier and either begins checkout or requests access |
| **Failure mode** | Can't map their use case to a tier; pricing too abstract; no clear "what do I get that the demo doesn't have?" |

### Job 4 — Run a Real Analysis (Customer → Active User)

**Job statement:** *"When I sign in, I want to quickly submit my KML and get production-quality results, so I can use the data in my actual work."*

| Dimension | Detail |
|-----------|--------|
| **Trigger** | First sign-in, or returning to run a new analysis |
| **Current surface** | App dashboard — analysis rail (right column): file input + textarea + preflight + "Queue Analysis" |
| **Success metric** | Submits KML and sees pipeline progress within 30 s of landing |
| **Failure mode** | Confused by the two-column layout; doesn't notice the run form below the fold; distracted by empty evidence/history sections on first visit |

### Job 5 — Review & Interpret Evidence (Active User → Informed Operator)

**Job statement:** *"When my run completes, I want to review the satellite imagery, vegetation trends, weather context, and AI observations, so I can make an informed decision about my sites."*

| Dimension | Detail |
|-----------|--------|
| **Trigger** | Run completes (auto-loads) or user selects a completed run from history |
| **Current surface** | Evidence hero — map viewer (RGB/NDVI, timelapse, compare), sidebar (NDVI grid, weather chart, change detection), AI analysis, EUDR assessment |
| **Success metric** | Understands the vegetation trajectory and any alerts within 2 min of seeing results |
| **Failure mode** | Data overload; doesn't know where to look first; can't connect NDVI numbers to real-world meaning |

### Job 6 — Export & Share (Informed Operator → Decision-Maker)

**Job statement:** *"When I have evidence, I want to export it in a format I can share with stakeholders (rangers, directors, auditors, donors), so I can drive action."*

| Dimension | Detail |
|-----------|--------|
| **Trigger** | Confident in results, needs to share externally |
| **Current surface** | Export buttons in run detail card (GeoJSON, CSV, PDF) |
| **Success metric** | Downloads a clean, labelled export within 2 clicks |
| **Failure mode** | Export buttons are buried in the run detail card (below the fold); not obvious from the evidence surface; PDF quality unclear until downloaded |

### Job 7 — Compare & Monitor Over Time (Returning User → Repeat Operator)

**Job statement:** *"When I return to Canopex, I want to see how my sites have changed since my last analysis, so I can spot emerging trends or confirm recovery."*

| Dimension | Detail |
|-----------|--------|
| **Trigger** | Monthly/quarterly check-in, alert from field team, scheduled review |
| **Current surface** | History rail (left column) — list of past runs with status badges |
| **Success metric** | Can quickly compare latest results with a previous run |
| **Failure mode** | History list shows run IDs, not locations; can't visually compare two runs side-by-side; no "compare" feature yet |

### Job 8 — Manage Account & Billing (Any Authenticated User)

**Job statement:** *"When I need to check my usage, upgrade, or manage billing, I want to do it without leaving the app."*

| Dimension | Detail |
|-----------|--------|
| **Trigger** | Running low on quota, needs to upgrade, expense report |
| **Current surface** | Welcome bar stat pills (plan, runs left), Billing button, Account card in settings |
| **Success metric** | Sees current usage and can take action within 1 click |
| **Failure mode** | Billing button destinations unclear; Account info buried in collapsed settings |

---

## 2. Current Flow Mapping

### Flow A: Visitor → Demo → Sign-Up

```text
Land on /
  │
  ├── Read hero + problem cards (5–10 s scan)
  │
  ├── Click "Try Live Demo" ──→ Scroll to #demo
  │     │
  │     ├── Pick sample location (1 click) OR paste/upload KML
  │     ├── Click "Process KML"
  │     ├── Watch 6-step progress (30 s – 5 min)
  │     ├── View timelapse + NDVI + weather
  │     ├── See "AI disabled on demo" note
  │     └── Want more → scroll to pricing or click "Request Early Access"
  │
  └── Click "Request Early Access" ──→ #early-access form
```

**Assessment:** This flow is solid. The demo is the best conversion tool. Two issues:

1. **After the demo, there's no clear "upgrade" prompt** — the user has to scroll away from results to find pricing
2. **The KML input is intimidating** for non-GIS users despite the sample picker

### Flow B: Sign-In → First Run → Results

```text
Navigate to /app/
  │
  ├── See gate → click "Sign In" → CIAM → redirect back
  │
  ├── Dashboard loads:
  │     ├── Welcome bar (name, plan, runs, mode, active run)
  │     ├── Evidence hero (empty — "Select a completed run")
  │     ├── History rail (empty — no past runs)
  │     └── Analysis rail (KML form + preflight)
  │
  ├── User must scroll past empty evidence + empty history to find the run form
  │     └── ⚠️ FRICTION: First-time user sees a lot of "nothing here yet"
  │
  ├── Paste KML → preflight populates → click "Queue Analysis"
  ├── Progress stepper animates in the analysis rail
  ├── Run completes → evidence auto-populates in the evidence hero
  └── User scrolls back up to see results
```

**Assessment:** The first-time empty state is the weakest part. Three empty sections (evidence, history, analysis detail) create a "cold start" problem. The run form is below the fold on most screens.

### Flow C: Returning User → History → Evidence

```text
Navigate to /app/
  │
  ├── Dashboard loads with history populated
  ├── Latest or active run auto-selected
  ├── Evidence hero shows results from selected run
  ├── User can click other history items to switch
  └── Or submit a new analysis
```

**Assessment:** This flow works well once there's history. The auto-select of the latest run is good. History items show status badges, which is helpful.

---

## 3. Friction Points & Gaps

### P0 — Critical Flow Blockers

| # | Issue | Impact | Location |
|---|-------|--------|----------|
| F1 | **First-time empty state** — Three empty sections greet new users | New customers see a blank workspace; unclear what to do first | Evidence hero, History rail, Run detail |
| F2 | **Run form below the fold** — On first visit, the KML input is beneath the empty evidence hero and empty history | Users may not scroll far enough to find the main action (submitting KML) | App dashboard layout order |

### P1 — Significant UX Gaps

| # | Issue | Impact | Location |
|---|-------|--------|----------|
| F3 | **No post-demo upsell CTA** — After demo results display, there's no "Get full access" or "This run in Pro would also include…" prompt | Missed conversion opportunity at peak engagement | Demo results panel |
| F4 | **Export buttons buried** — GeoJSON/CSV/PDF buttons are in the run detail card, which is below the history/analysis fold | Users don't discover exports until they scroll through the analysis rail | Run detail grid |
| F5 | **History items show instance IDs, not locations** — Run items say "Run c2493ce3" not "Coalville, UK" | Users can't identify runs by meaningful context | History list |
| F6 | **No run-to-run comparison** — Users can only view one run's evidence at a time | Can't track changes over time (contradicts Job 7) | Evidence surface |
| F7 | **Role/preference settings are tucked away** — Collapsed `<details>` at the bottom of the page | New users might never discover the workspace lens system | Settings disclosure |

### P2 — UX Polish

| # | Issue | Impact | Location |
|---|-------|--------|----------|
| F8 | **AI and EUDR blocks show as empty when hidden** — `hidden` attribute removes them, but the action row may have no visual content until a role/tier qualifies | Can leave a visual gap below the evidence two-col | Evidence action row |
| F9 | **No onboarding guide in app** — Marketing site has "New to KML?" banner but the app doesn't | Signed-in users who came directly to `/app/` miss the KML guide | Analysis rail |
| F10 | **Workspace lens messaging is dense** — Role + preference cards have many text fields (outcome, stance, rhythm, deliverable, focus) | Cognitive overhead; most users just want to submit and view | Settings cards |
| F11 | **No success celebration** — When a run completes, evidence just appears | Missed moment to reinforce value and guide next steps | Evidence hero |

---

## 4. Information Architecture Recommendations

### 4.1 — Fix the First-Time Experience (F1, F2)

**Problem:** New users see: empty evidence → empty history → run form (below fold).

**Recommendation:** When history is empty AND no run is active, swap the layout:

```text
┌─────────────────────────────────────────────┐
│ Welcome bar (same)                          │
├─────────────────────────────────────────────┤
│ ┌─ First-Run Hero Card ──────────────────┐  │
│ │ "Start your first analysis"            │  │
│ │ [big icon/illustration]                │  │
│ │ KML file input + textarea              │  │
│ │ Preflight card                         │  │
│ │ [Queue Analysis] button                │  │
│ │ "Need a KML?" → link to guide          │  │
│ └────────────────────────────────────────┘  │
├─────────────────────────────────────────────┤
│ Evidence hero (hidden until run completes)   │
│ History + Analysis rails (hidden until       │
│ there's content to show)                     │
└─────────────────────────────────────────────┘
```

This collapses the three empty sections into one clear call-to-action. Once the user has at least one completed run, switch to the normal two-column layout with evidence hero.

### 4.2 — Promote Exports to the Evidence Surface (F4)

**Problem:** Export buttons are buried in the run detail card.

**Recommendation:** Add an export bar directly inside the evidence hero, adjacent to the AI/EUDR action row:

```text
┌─ Evidence Hero ──────────────────────────────┐
│ [Map viewer]  │ [NDVI] [Weather] [Changes]   │
├──────────────────────────────────────────────┤
│ [AI Analysis]        │ [EUDR Assessment]      │
├──────────────────────────────────────────────┤
│ Export: [GeoJSON] [CSV] [PDF] [Download All]  │
└──────────────────────────────────────────────┘
```

Keep the run detail card exports as well (they serve as a secondary access point), but the primary discovery should be right where the user is reviewing evidence.

### 4.3 — Add Post-Demo Conversion Prompt (F3)

**Problem:** After demo results, no push toward paid tier.

**Recommendation:** After the timelapse viewer loads in the demo, inject a subtle callout:

```text
┌──────────────────────────────────────────┐
│ 🔑 This analysis used 1 of your 3 demo  │
│ runs. With a Pro plan, you get:          │
│ • Unlimited AOIs (up to 50 per run)      │
│ • AI-powered analysis                    │
│ • NDVI exports (GeoJSON, CSV, PDF)       │
│ • 90-day data retention                  │
│                                          │
│ [See Plans]  [Sign In to Upgrade]        │
└──────────────────────────────────────────┘
```

### 4.4 — Give History Items Meaningful Labels (F5)

**Problem:** "Run c2493ce3" means nothing.

**Recommendation:** Extract location context from the run's KML or enrichment data. Display as:

```text
Before:  "Resume run c2493ce3"
After:   "Coalville, UK — 3 AOIs, 467 ha"
         "Completed 25 Jan 2025 · Mean NDVI 0.47"
```

Fall back to instance ID only if location is not available. The metadata to do this is already in the enrichment manifest (coordinates → reverse geocode, or just use the KML Placemark names if present).

### 4.5 — Add KML Guide Link to App (F9)

**Problem:** App has no onboarding banner for KML newcomers.

**Recommendation:** Add a small dismissible helper above or within the KML input:

```text
📍 Need a KML? Learn how to draw one in Google Earth Pro → [KML Guide]
```

Dismiss state stored in localStorage so returning users don't see it again.

### 4.6 — Run Completion Moment (F11)

**Problem:** Results appear silently.

**Recommendation:** When a run transitions to `complete`:

1. Brief animation/flash on the evidence hero header
2. Toast or inline callout: "Analysis complete — 12 frames, 3 AOIs. Review your evidence below."
3. If AI is available: "Tip: Run AI analysis for automated interpretation."

---

## 5. Page Structure Recommendation

### Should we restructure into multiple pages/views?

**Verdict: Not yet.** The single-page app dashboard works for the current feature set. Multi-page routing would add complexity without clear benefit at this stage. However, some **view-mode adjustments** are warranted:

| Current | Recommended | Rationale |
|---------|-------------|-----------|
| Always show evidence + history + analysis rails | **Conditional first-run vs. returning** | Eliminate empty-state overwhelm |
| Settings at the bottom in `<details>` | **Keep in `<details>`, but lift role chip display** to welcome bar as a subtle indicator | Users should see their active role without opening settings |
| AI + EUDR in action row below two-col | **Keep** | This placement works well — full-width gives them room |
| Export buttons only in run detail card | **Duplicate to evidence action row** | Primary access at point of consumption |

### Future considerations (not for now)

- **Multi-site dashboard** (Job 7): When comparison becomes a priority, introduce a "Sites" view that lists locations with last-run NDVI and status badges
- **Alerts / notifications**: When scheduled runs land, push to email or in-app notification center
- **Map-first view**: Full-screen map with all AOIs plotted, color-coded by status — would serve Portfolio Ops well

---

## 6. What to Show vs. Hide

### Show prominently (above the fold)

| Element | Why |
|---------|-----|
| Welcome bar with plan + runs left + active run | Orients the user immediately |
| Evidence hero (when results exist) | Primary value delivery |
| Run form / first-run CTA (when no history) | Unblocks the primary action |
| Export bar (inside evidence section) | Serves Job 6 at point of consumption |

### Show on demand (below fold or collapsed)

| Element | Why |
|---------|-----|
| History list | Secondary to evidence viewing; useful for returning users |
| Workspace settings (role, preference, account) | Power-user feature; one-time setup |
| Run detail grid (instance, scope, delivery) | Technical detail for debugging runs |
| Pipeline progress stepper | Only relevant during active runs |

### Show only when relevant (conditional)

| Element | Condition | Why |
|---------|-----------|-----|
| AI analysis card | Tier allows `ai_insights` | Don't show disabled features as dead UI |
| EUDR assessment card | Role = `eudr` | Role-specific; no value to others |
| Phase status blocks | Run is active/processing | Not useful when completed |
| Plan emulation | Local dev only | Already gated correctly |
| Post-demo upsell | Demo results visible, user not signed in | Conversion moment |

### Hide (currently shown but adds clutter)

| Element | Issue | Recommendation |
|---------|-------|----------------|
| Empty evidence hero on first visit | "Select a completed run to view evidence" on a blank page | Hide entire section until first run exists |
| Empty history rail on first visit | "Restoring signed-in history…" then nothing | Fold into first-run CTA |
| Run detail grid when no run selected | All "—" values | Collapse to a single status line |
| Role "brief grid" (outcome, stance, rhythm) | Dense; rarely actionable | Move inside a secondary expandable in settings |

---

## 7. Demo ↔ App Unification

The demo and the app are the **same product at different tiers**. The demo runs inside `/app/?mode=demo` with demo-tier limits. There is no separate demo implementation.

### What the demo preserves (from the current landing page)

- **Zero-friction sample locations** — one click to get results
- **Visual progress stepper** — satisfying, transparent
- **Timelapse viewer** — the hero feature; maps + animation
- **Weather + NDVI panels** — builds credibility with real data

### How tiers differ

| Capability | Demo | Free | Starter | Pro+ |
|-----------|------|------|---------|------|
| AOI limit | 1 | Plan limit | Plan limit | Plan limit |
| Temporal cadence | Seasonal (4/yr, 2-year window) | Seasonal (4/yr, full history) | Seasonal (4/yr, full history) | Monthly or continuous |
| AI insights | ✗ (shows upgrade CTA) | ✗ | ✓ | ✓ |
| Exports | ✗ (shows upgrade CTA) | ✗ | ✗ | ✓ (Pro+) |
| History | Not saved | Persistent | Persistent | Persistent |
| Auth required | No | Yes | Yes | Yes |
| EUDR assessment | ✗ | Role-gated | Role-gated | Role-gated |

NAIP and other high-res imagery sources are **opportunistic** — used whenever available regardless of tier. Resolution cadence (seasonal/monthly/continuous) is the only data-quality differentiator.

### Demo → paid conversion hooks

1. **Demo banner** (top of app in demo mode): "You're on the free demo — seasonal snapshots, 1 AOI, no exports. [Sign in for full access]"
2. **Feature gates**: AI and export buttons show "Available on Pro" CTAs instead of disabled states
3. **Post-results prompt**: Conversion prompt appears after results load (existing #325 pattern, adapted for in-app context)
4. **No history persistence**: "Sign in to save your analyses" in the history rail
5. **Pricing accessible**: "View Plans" link in demo banner routes to `/` pricing section or `/app/` billing

---

## 8. Roadmap: Site Restructure + UX + Scaling Architecture

Three workstreams — site architecture, UX polish, and scaling infrastructure — are sequenced so each phase builds on the previous and unlocks the next. NAIP and other high-resolution imagery sources are **opportunistic** across all tiers (not a differentiator).

### All GitHub Issues

| # | Issue | Stream | Status |
|---|-------|--------|--------|
| [#323](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/323) | Fix first-time empty-state experience | UX | ✅ Done (PR #327) |
| [#324](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/324) | Promote export buttons to evidence hero | UX | ✅ Done (PR #327) |
| [#325](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/325) | Post-demo conversion prompt | UX | ✅ Done (PR #327) |
| [#328](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/328) | Unify page titles, nav, and branding | Site | 🔶 Partial |
| [#329](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/329) | Create /docs/ hub and consolidate guides | Site | |
| [#330](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/330) | Simplify landing page — strip demo, add static content | Site | |
| [#331](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/331) | Demo-as-plan tier with temporal cadence (backend) | Product | |
| [#332](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/332) | Demo mode in /app/ with sample picker & feature gates | Product | |
| [#333](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/333) | Align pricing cards with PLAN_CATALOG, add Starter | Site | |
| [#334](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/334) | Meaningful history labels (location, AOIs, NDVI) | UX | |
| [#320](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/320) | Load testing baseline | Scaling | |
| [#319](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/319) | Cosmos DB infrastructure | Scaling | |
| [#314](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/314) | DB migration & refactor | Scaling | |
| [#316](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/316) | Fan-out / claim-check | Scaling | |
| [#317](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/317) | Rust (PyO3) hotspots | Scaling | |
| [#318](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/318) | Bulk image strategy spike | Scaling | |
| [#311](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/311) | Bulk AOI processing | Scaling | |
| [#312](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/312) | User dashboards | Scaling | |
| [#313](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/313) | Team workspaces | Scaling | |
| [#310](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/310) | Scheduled monitoring | Scaling | |

### Tier-Based Temporal Resolution

| Tier | Cadence | Samples/Year | History | Notes |
|------|---------|:---:|---------|-------|
| Demo | Seasonal | 4 | 2 years | Stateless, no persistence |
| Free | Seasonal | 4 | Full | — |
| Starter | Seasonal | 4 | Full | — |
| Pro | Monthly | 12 | Full | — |
| Team | Monthly | 12 | Full | — |
| Enterprise | Maximum | all | Full | Best available resolution |

All tiers receive NAIP and other high-res imagery **opportunistically** when available for the location.

### Execution Sequence

```text
 ┌─────────────────────────────────────────────────────────────┐
 │ PHASE 0 — FOUNDATIONS (no user-facing changes)              │
 ├─────────────────────────────────────────────────────────────┤
 │  #328  Unify titles, nav, branding across all pages         │
 │  #320  Load testing baseline                                │
 └─────────────────────────────────────────────────────────────┘
                              │
 ┌─────────────────────────────────────────────────────────────┐
 │ PHASE 1 — SITE ARCHITECTURE                                │
 │ Restructure the site into clean surfaces                    │
 ├─────────────────────────────────────────────────────────────┤
 │  #329  Create /docs/ hub, consolidate guides                │
 │  #334  Meaningful history labels                            │
 │  #333  Align pricing cards with PLAN_CATALOG                │
 └─────────────────────────────────────────────────────────────┘
                              │
 ┌─────────────────────────────────────────────────────────────┐
 │ PHASE 2 — DEMO REARCHITECTURE                              │
 │ Demo becomes a plan tier inside the app                     │
 ├─────────────────────────────────────────────────────────────┤
 │  #331  Demo-as-plan tier + temporal cadence (backend)       │
 │  #332  Demo mode in /app/ (frontend)                        │
 │  #330  Strip demo from landing page → static marketing      │
 │        ↑ depends on #331 + #332 being functional            │
 └─────────────────────────────────────────────────────────────┘
                              │
          ╔═══════════════════╧════════════════════╗
          ║     CAN RUN IN PARALLEL WITH           ║
          ╚═══════════════════╤════════════════════╝
                              │
 ┌─────────────────────────────────────────────────────────────┐
 │ PHASE 3 — DATA FOUNDATION (scaling)                        │
 ├─────────────────────────────────────────────────────────────┤
 │  #319  Cosmos DB infrastructure                             │
 │  #314  DB migration & refactor                              │
 └─────────────────────────────────────────────────────────────┘
                              │
 ┌─────────────────────────────────────────────────────────────┐
 │ PHASE 4 — COMPUTE (scaling)                                │
 ├─────────────────────────────────────────────────────────────┤
 │  #316  Fan-out / claim-check                                │
 │  #317  Rust (PyO3) hotspots                                 │
 │  #318  Bulk image strategy spike                            │
 └─────────────────────────────────────────────────────────────┘
                              │
 ┌─────────────────────────────────────────────────────────────┐
 │ PHASE 5 — PRODUCT FEATURES (scaling)                       │
 │ Inherits frontend patterns from earlier phases              │
 ├─────────────────────────────────────────────────────────────┤
 │  #311  Bulk AOI uploads  ← inherits export bar (#324)       │
 │  #312  User dashboards   ← inherits empty state (#323)     │
 │  #313  Team workspaces                                      │
 │  #310  Scheduled monitoring                                 │
 └─────────────────────────────────────────────────────────────┘
```

### Why this sequence works

1. **Brand consistency first.** #328 fixes the fractured title/nav/logo situation before any structural changes. Every subsequent page created or moved inherits the correct conventions.

2. **Site architecture before demo rearchitecture.** Phase 1 establishes `/docs/`, fixes pricing, and adds history labels. These are independent of the demo rewrite and improve the experience for existing signed-in users immediately.

3. **Demo rearchitecture centralises the product.** Phase 2 (#331 → #332 → #330) turns the demo from a parallel implementation into a plan tier in the app. The landing page becomes lightweight and fast (~50 lines of JS instead of 2886). The demo and paid product are now the same code path at different resolution tiers.

4. **Temporal cadence is the value differentiator.** Free/Starter/Demo get seasonal snapshots (4/year). Pro/Team get monthly monitoring (12/year). Enterprise gets continuous. NAIP and other high-res sources are used opportunistically at every tier — resolution cadence is what separates plans.

5. **Scaling architecture is unblocked.** Phases 3–5 can proceed in parallel with Phase 2. The frontend patterns from #323–#325 (already shipped) and #332 (demo mode) are inherited by Phase 5's product features.

6. **Persona-aligned delivery.** Each phase delivers tangible value to all three personas:
   - **Conservation** (NGO): Demo → signs up (Phase 2) → first-run hero (#323) → quarterly evidence → PDF export (#324)
   - **ESG/EUDR**: Demo → sees tier comparison (#333) → signs up Pro → monthly monitoring → exports audit trail
   - **Agriculture**: Demo → Team tier → batch uploads (#311, Phase 5) → monthly CSV exports

### Proposed Site Map (target state)

```text
/                               Landing page — hero, value prop, screenshots, pricing, CTA
/app/                           Dashboard — all tiers including demo (stateless), free, and paid
/app/?mode=demo                 Demo mode — sample picker, 1 AOI, seasonal, no auth required
/docs/                          Documentation hub — index of all guides
/docs/kml-guide.html            KML guide (moved from /kml-guide.html)
/docs/eudr.html                 EUDR methodology (moved from /eudr-methodology.html)
/terms.html                     Terms of service
/privacy.html                   Privacy policy
```

---

## 9. Summary

Canopex has a **strong core product loop**: upload KML → see satellite imagery → review evidence → export. The main structural change is unifying the demo and the app into a **single surface at different plan tiers**, distinguished by temporal resolution cadence (seasonal → monthly → continuous).

The four original UX risks remain the priorities:

1. **Cold-start problem** — ✅ Fixed (#323, shipped)
2. **Export discoverability** — ✅ Fixed (#324, shipped)
3. **Demo-to-paid gap** — ✅ Prompt added (#325, shipped); demo rearchitecture (#331/#332) closes the gap permanently
4. **History usability** — Tracked (#334)

The roadmap sequences 20 issues across 6 phases: brand → site structure → demo rearchitecture → data foundation → compute → product features. Each phase is independently shippable and builds forward-compatible patterns for the next.
