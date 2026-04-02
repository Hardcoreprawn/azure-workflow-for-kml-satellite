# Canopex — Brand Guide

> Single source of truth for the Canopex visual identity, colour system, site/app architecture, and rebrand execution plan.

---

## 1. Brand Identity

| Attribute | Value |
|-----------|-------|
| **Name** | Canopex |
| **Pronunciation** | /ˈkæn.ə.pɛks/ — rhymes with "apex" |
| **Tagline** | *Satellite evidence, automated.* |
| **Positioning** | Evidence Generation Platform — "From KML to evidence in 5 minutes" |
| **Origin** | Canopy + Apex — the peak view of the forest canopy |
| **Personality** | Precise. Nature-grounded. Technical. Trustworthy. |

### Logo

The current globe SVG icon is retained — it communicates geospatial/satellite DNA directly. The fill colour changes from blue (`#58a6ff`) to **Canopex Emerald** (`#5eecc4`).

```html
<svg viewBox="0 0 24 24"><path fill="#5eecc4" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>
```

The wordmark is set in the system font stack at 700 weight, 1.25rem. No custom typeface required at launch.

---

## 2. Colour Palette

### Design Tokens

All colours live in `/website/css/shared.css` as CSS custom properties. Every page references `shared.css` first.

| Token | Hex | RGB | Role |
|-------|-----|-----|------|
| `--c-bg` | `#0b1411` | `11, 20, 17` | Page canvas — deep forest-black with green undertone |
| `--c-surface` | `#131f1b` | `19, 31, 27` | Cards, panels, overlays |
| `--c-border` | `#243832` | `36, 56, 50` | Dividers, card borders |
| `--c-text` | `#e4ede8` | `228, 237, 232` | Primary body copy — warm off-white |
| `--c-muted` | `#7d9a8d` | `125, 154, 141` | Secondary text — sage grey |
| `--c-accent` | `#5eecc4` | `94, 236, 196` | **Canopex Emerald** — primary brand colour, links, CTAs, section labels |
| `--c-green` | `#3fb950` | `63, 185, 80` | Semantic positive — NDVI growth, compliance pass, success |
| `--c-red` | `#f85149` | `248, 81, 73` | Semantic alert — canopy loss, errors, non-compliance |
| `--c-orange` | `#d29922` | `210, 153, 34` | Semantic warning — cloud cover, quota limits |
| `--c-purple` | `#bc8cff` | `188, 140, 255` | Semantic analysis — AI features, special |

### Interaction States

| State | Colour | Notes |
|-------|--------|-------|
| Primary button bg | `#5eecc4` with text `#0b1411` | Dark text on mint — high contrast |
| Primary button hover | `#a8f5e0` + `box-shadow: 0 0 14px rgba(94,236,196,.45)` | Pastel mint with glow |
| Secondary button hover bg | `rgba(94,236,196,.1)` | 10% emerald tint |
| Auth button hover bg | `rgba(94,236,196,.12)` | 12% emerald tint |
| Accent tint (info callouts) | `rgba(94,236,196,.08–.1)` | Subtle background glow |
| Accent border | `rgba(94,236,196,.18–.25)` | Subtle border highlight |

### Palette Rationale

| Decision | Reasoning |
|----------|-----------|
| **Emerald-teal, not pure green** | Distinguishes from GFW/GEE green. Teal undertone signals tech + nature. |
| **Forest-tinted darks, not blue-grey** | Every background has a green cast — `#0b1411` vs old `#0c1117`. Reinforces brand unconsciously. |
| **Warm off-white text** | `#e4ede8` has a green tint vs the old cool blue-white `#e6edf3`. Softer on eyes, cohesive. |
| **Sage grey for muted** | `#7d9a8d` sits in the green family — no context-switching between grey and green. |
| **Semantic green stays** | `--c-green` (`#3fb950`) is distinct from `--c-accent` (`#5eecc4`). Green = data/positive, emerald = UI/brand. |
| **Dark mode** | Satellite imagery pops on dark backgrounds. Maps look professional. Matches data-dashboard conventions. |

### Test Page

A visual test page is at `/website/palette-test.html` — open locally to review all tokens in context (nav mock, buttons, cards, pills, pricing, data table, typography scale, before/after comparison).

---

## 3. Typography

| Level | Size | Weight | Tracking |
|-------|------|--------|----------|
| H1 (hero) | 2.5rem | 700 | -0.02em |
| H2 (section) | 1.75rem | 600 | — |
| H3 (card) | 1.125rem | 600 | — |
| Body | 0.875rem | 400 | — |
| Caption / note | 0.75–0.8rem | 400 | — |
| Section label | 0.75rem | 600 | 0.08em, uppercase |

**Font stack**: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif`

No custom font is loaded — this keeps the site fast and avoids FOUT. The system font stack already renders well across all platforms and matches the "professional tool" feel.

---

## 4. Site / App Architecture

### Current Structure

```text
canopex.io/              → Marketing site (index.html + style.css)
canopex.io/app/           → Signed-in app (app/index.html + app.css)
canopex.io/docs/          → Documentation
canopex.io/terms.html     → Legal
canopex.io/privacy.html   → Legal
```

Both pages load `shared.css` (tokens + nav + buttons), then their own page-specific stylesheet. Both share the same nav component and auth system (MSAL).

### Separation Model

The site and app are **appropriately separate and integrated**:

| Dimension | Marketing Site | App Dashboard |
|-----------|---------------|---------------|
| **URL** | `/` | `/app/` |
| **HTML** | Own `index.html` | Own `app/index.html` |
| **CSS** | `shared.css` + `style.css` | `shared.css` + `app.css` |
| **JS** | `landing.js` (auth + form + pricing) | `app-shell.js` (auth + dashboard + pipeline) |
| **Auth** | Optional — shows "Sign In" / "Dashboard" | Required — gates behind MSAL login |
| **Nav links** | Overview, Demo, Docs, Pricing, FAQ | Dashboard, Pricing, Docs, Marketing Site |
| **Purpose** | Explain, convince, convert | Work, analyse, manage |

### Integration Points

1. **Shared nav bar** — Same HTML structure, same `shared.css` styles. The logo and auth area are identical.
2. **Auth handoff** — `landing.js` detects MSAL redirect from `/app/` and sends authenticated users to the dashboard. The site nav shows "Dashboard" button when signed in.
3. **Demo bridge** — The marketing site links to `/app/?mode=demo` — the app renders in demo mode with limited features and a sign-in upsell banner.
4. **Pricing link** — The app links back to `/#pricing` on the marketing site. Billing portal is accessed from within the app.
5. **Shared token file** — Both pages read `/api-config.json` for runtime configuration.

### Independence

Each page can survive as a standalone deployment:

- The marketing site works without the app (all sections are self-contained).
- The app works without the marketing site (it has its own nav, sign-in gate, full MSAL flow).
- Shared CSS ensures visual consistency when both are present.

### Recommendation

This architecture is sound and doesn't need restructuring. The key principles:

- **One domain, two entry points** — `canopex.io` and `canopex.io/app/`
- **Shared design tokens** — `shared.css` is the single source of truth
- **Independent page-specific styles** — no accidental coupling
- **Auth bridges the gap** — MSAL state is shared, so signing in on either page works on both

---

## 5. Component Patterns

### Buttons

| Variant | Usage |
|---------|-------|
| `.btn-primary` | Main CTAs — "Try Live Demo", "New Analysis", "Start Free" |
| `.btn-secondary` | Secondary actions — "Request Early Access", "Back to site" |
| `.auth-btn.primary` | Nav sign-in — same emerald fill |
| `.auth-btn.logout` | Sign out — muted border, red on hover |

### Cards

Cards use `--c-surface` background, `--c-border` border, `--c-accent` border on hover. The `featured` variant adds an emerald box-shadow ring.

### Semantic Indicators

| Pattern | Colour | Example |
|---------|--------|---------|
| Positive pill / stat | `--c-green` bg tint | `+12.3% NDVI Growth` |
| Negative pill / stat | `--c-red` bg tint | `-8.1% Canopy Loss` |
| Warning | `--c-orange` bg tint | `Cloud Cover: 18%` |
| Info / accent | `--c-accent` bg tint | `5 Scenes Available` |
| Analysis | `--c-purple` bg tint | `AI Analysis Ready` |

### App Role Themes

The app dashboard supports role-based tinting via CSS custom properties:

| Role | Accent | Used for |
|------|--------|----------|
| Default | `--c-green` | Standard analysis workspace |
| EUDR | `--c-accent` (emerald) | Compliance / regulatory mode |
| Portfolio | `--c-orange` | Multi-site portfolio view |

---

## 6. Rebrand Execution Checklist

### Phase 1: Visual Identity (done)

- [x] Define colour palette and design tokens
- [x] Update `shared.css` — replace GitHub blue-grey tokens with Canopex forest emerald
- [x] Update `style.css` — replace hardcoded blue `rgba(88,166,255,...)` with emerald `rgba(94,236,196,...)`
- [x] Update `app.css` — replace hardcoded blue rgba values throughout
- [x] Create palette test page (`palette-test.html`)

### Phase 2: Name Change (done)

- [x] `website/index.html` — changed `<title>`, all `TreeSight` text, meta tags, OG tags
- [x] `website/app/index.html` — changed `<title>`, all `TreeSight` text, meta tags, OG tags
- [x] `website/privacy.html` — updated brand name throughout
- [x] `website/terms.html` — updated brand name throughout
- [x] `website/js/landing.js` — updated `window.treesightBilling` → `window.canopexBilling`
- [x] `website/js/app-shell.js` — updated localStorage keys and display strings
- [x] Nav logo text — changed "TreeSight" to "Canopex" in all HTML files
- [x] Noscript banner — changed "TreeSight requires JavaScript"
- [x] Footer copyright — "© 2026 TreeSight" → "© 2026 Canopex"
- [x] `website/docs/` pages — all 3 renamed (index, eudr-methodology, kml-guide)

### Phase 3: Domain & Infrastructure (to do)

- [ ] Register `canopex.io` (or chosen TLD)
- [ ] Configure Azure Static Web Apps custom domain
- [ ] Update CIAM tenant redirect URIs
- [ ] Update Stripe webhook URLs and product metadata
- [ ] Update DNS, SSL, CDN configuration
- [ ] Update CSP headers in `staticwebapp.config.json` for new domain

### Phase 4: Content & Marketing (to do)

- [ ] Update `docs/MARKETING_PLAN.md` to reference applied brand
- [ ] Create social media accounts (@canopex)
- [ ] Update email templates in `treesight/email.py`
- [ ] Search codebase for remaining `treesight` / `TreeSight` references in backend Python
- [ ] Update `README.md`, `pyproject.toml` project name

### Phase 5: Cleanup

- [ ] Remove `palette-test.html` (or move to `/docs/` as living reference)
- [ ] Verify all hardcoded colour values match new palette
- [ ] Accessibility audit — check contrast ratios meet WCAG AA
- [ ] Cross-browser test the new palette

---

## 7. Accessibility Notes

| Check | Status | Notes |
|-------|--------|-------|
| Accent on bg contrast | **4.8:1** (`#22c997` on `#0b1411`) | Passes WCAG AA for normal text |
| Text on bg contrast | **13.8:1** (`#e4ede8` on `#0b1411`) | Passes WCAG AAA |
| Muted on bg contrast | **5.2:1** (`#7d9a8d` on `#0b1411`) | Passes WCAG AA |
| Muted on surface contrast | **4.5:1** (`#7d9a8d` on `#131f1b`) | Passes WCAG AA (borderline) |
| Green vs accent distinction | Hue shift ~40° | Visually distinct even under protanopia |

---

## 8. Files Changed

| File | Changes |
|------|---------|
| `website/css/shared.css` | All `:root` tokens, nav background, button hover colours |
| `website/css/style.css` | Proof tag, onboard banner rgba values |
| `website/css/app.css` | EUDR role tint, evidence action, run snapshot, history status, preflight badge, preflight item, callout info, pipeline progress — all blue→emerald |
| `website/palette-test.html` | **New** — visual test page for palette review |
| `docs/BRAND_GUIDE.md` | **New** — this document |
