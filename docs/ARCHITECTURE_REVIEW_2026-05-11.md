# Architecture Review — 2026-05-11

**Author:** Code Review Critic pass
**Trigger:** CIAM redirect-URI failure (#777) surfaced concerns about
auth-path duplication and broader structural decay.
**Method:** Top-down C4 walkthrough (Context → Container → Component →
Code) with explicit hunt for duplicate paths, dead code, and
single-source-of-truth violations.

> **Update — landed before this doc merged.** While this review was in
> flight, **PR #775** consolidated MSAL into a single
> `website/js/canopex-auth.js` module (resolving the frontend-duplication
> concern outright), and **PR #776** brought CIAM SPA redirect URIs
> under OpenTofu via the `azuread` provider (closing follow-up #781 and
> the manual-drift gap entirely). The findings below have been
> annotated with their post-#775/#776 status.

> **TL;DR.** The system is structurally sound at L1/L2 and the recent
> CIAM migration cleaned up most of the auth surface. The remaining
> risks are concentrated in three areas:
>
> 1. **Both function apps register every blueprint.** Only one is the
>    public API; the other carries unnecessary HTTP attack surface.
>    *(Tracked: #779.)*
> 2. **The auth surface still mentions `X-MS-CLIENT-PRINCIPAL` in CORS
>    and in a test-mode branch** even though SWA-injected principals
>    are no longer used in production. *(Tracked: #782.)*
> 3. **Two large blueprints (`export.py` 1529 lines, `analysis.py` 755)
>    mix domain logic with HTTP I/O.** They are testable but they are
>    where future bugs will hide. *(Tracked: #780, #785.)*
>
> Frontend duplication that motivated this review (landing.js vs
> app-msal.js) was extracted in **PR #775** to `canopex-auth.js`,
> ahead of this doc.

---

## Level 1 — System Context

```text
                         ┌─────────────────────┐
                         │  External users     │
                         │  (3 personas)       │
                         └──────────┬──────────┘
                                    │ HTTPS
                                    ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Canopex Static Web App  (canopex.hrdcrprwn.com / *.azurestaticapps.net)
   │  • Marketing + landing pages  (landing.js)               │
   │  • /app/  signed-in dashboard (app-msal.js + 22 modules) │
   │  • /eudr/ EUDR product surface                           │
   └──────────┬─────────────────────────────────┬─────────────┘
              │ Authorization: Bearer <jwt>     │ /api-config.json
              ▼                                 │ (deploy-injected hostname)
   ┌────────────────────────┐         ┌─────────▼─────────┐
   │ Microsoft Entra        │         │ Function App      │
   │ External ID (CIAM)     │◄────────│  (Container Apps) │
   │ • OIDC + JWKS          │  jwks   │  Python 3.12      │
   └────────────────────────┘         └────┬───────┬──────┘
                                           │       │
   ┌─────────────────────┐   STAC          │       │ Durable
   │ Microsoft Planetary │◄────────────────┤       │ task hub
   │ Computer (S2, etc.) │                 │       ▼
   └─────────────────────┘                 │  ┌──────────────┐
                                           │  │ Orchestrator │
   ┌─────────────────────┐  webhook        │  │ Function App │
   │ Stripe              │◄────────────────┤  │ (slim image) │
   └─────────────────────┘                 │  └──────────────┘
                                           ▼
                       ┌──────────┬───────────┬──────────────┬─────────┐
                       │ Cosmos   │ Blob/Tbl  │ App Insights │ Key     │
                       │ (state)  │ (data)    │ (telemetry)  │ Vault   │
                       └──────────┴───────────┴──────────────┴─────────┘
```

**External actors:**

- *Conservation analyst* — uploads KML/KMZ AOIs, expects evidence PDF.
- *ESG / EUDR compliance officer* — bulk parcels, audit-grade artefacts.
- *Agricultural advisor* — recurring monitoring, batch processing.

**External systems:**

- **Entra External ID (CIAM).** App registration `6e2abd0a-…-471fc6` is
  managed *manually*, not via Tofu. Drift between the registration's
  redirect URIs and the deployed SWA hostnames was the trigger for
  this review and is now mitigated by a deploy-time Graph verification
  step (`.github/workflows/deploy.yml`).
- Stripe (billing), Microsoft Planetary Computer (imagery), Open-Meteo
  (weather), GHCR (container images).

**Issues at this level:**

- 🟡 **CIAM app registration is out-of-state.** Even with the new
  verification gate, an operator can still drift the app registration
  manually. A future enabler should bring it under Tofu (azuread
  provider) so URI derivation and assignment use the same source of
  truth. Track as enabler issue.

---

## Level 2 — Containers

| Container                | Tech                        | Tofu resource                                   | Notes |
|--------------------------|-----------------------------|------------------------------------------------|-------|
| Static Web App           | Azure SWA (Standard)        | `azurerm_static_web_app.main`                  | No `linked_backend` — frontend calls Function App directly via `/api-config.json`. |
| Function App (compute)   | Container, Python 3.12      | `azapi_resource.function_app` (image: main)    | Carries GDAL/rasterio. Registers all blueprints **and** activities. |
| Function App (orchestrator) | Container, Python 3.12   | `azapi_resource.orchestrator_function_app`     | Slim image. Registers all blueprints **except activities** (`PIPELINE_ROLE=orchestrator`). |
| Storage Account          | StorageV2 + CMK             | `azurerm_storage_account.main`                 | Containers: `kml-input`, `kml-output`, `deployments`, `pipeline-payloads`. |
| Cosmos DB (SQL)          | Serverless                  | (gated by `enable_cosmos`)                     | Holds analysis state, billing ledger. |
| Key Vault                | RBAC                        | `azurerm_key_vault.main`                       | Holds CMK + secrets pulled by Function Apps via MI. |
| App Insights + Log Analytics | -                       | `azurerm_application_insights.main`            | Logs auth path (`auth_path=bearer mode=…`). |
| Event Grid               | System topic on Storage     | (separate resource)                            | Triggers blob_trigger when KML lands. |

**Issues at this level:**

- 🔴 **Both Function Apps register the same shared HTTP route surface.**
  [function_registration.py](function_registration.py#L26-L39) returns
  the same 13 blueprints to both `function_app.py` and
  `function_app_orch.py`. `PIPELINE_ROLE` only filters the **activity**
  module ([blueprints/pipeline/**init**.py](blueprints/pipeline/__init__.py#L37-L39)).
  In production only the compute Function App's hostname is published
  via `/api-config.json`, so the orchestrator's HTTP routes are not
  reachable through the SWA — but they *are* reachable on its own
  hostname, which broadens the attack surface needlessly (every
  endpoint, including `/api/billing/*`, `/api/ops/*`, etc., responds
  on the orchestrator host). **Recommendation:** parameterise
  `register_function_blueprints` with a role enum and register only
  `pipeline_bp + health_bp` on the orchestrator. Track as a
  `[discovered]` issue.

- 🟢 **Linked-backend wiring is intentionally disabled.** The
  comment in [main.tf](infra/tofu/main.tf#L1037-L1041) explains why
  (#282 — Container Apps Function Apps not supported by the
  `linkedBackends` ARM API). The api-config.json injection is the
  documented workaround. No action needed.

---

## Level 3 — Components

### 3.1 Auth (primary focus)

```text
Browser                           Function App                    CIAM
  │                                    │                           │
  │ acquireTokenSilent({               │                           │
  │   scopes:[openid,profile,          │                           │
  │           audience+'/.default']    │                           │
  │ })                                 │                           │
  │ ──────────────────────────────────────────────────────────────►│
  │ ◄── access_token (aud == audience) ────────────────────────────│
  │                                    │                           │
  │ GET /api/...                       │                           │
  │ Authorization: Bearer <jwt>        │                           │
  │ ──────────────────────────────────►│                           │
  │                                    │ verify_bearer_token       │
  │                                    │  ├─ JWKS (cached)         │
  │                                    │  └─ aud == CIAM_API_AUDIENCE
  │                                    │                           │
  │                                    │ require_auth decorator    │
  │                                    │  → fn(req, auth_claims, user_id)
```

| Component                                    | Path                                                                   | Concern |
|----------------------------------------------|------------------------------------------------------------------------|---------|
| Backend JWT verification                     | [treesight/security/auth.py](treesight/security/auth.py#L91-L120)      | Single, correct implementation. JWKS cached, leeway parameterised, requires `tid+oid+ver`. ✅ |
| Backend request decorator                    | [blueprints/_helpers.py](blueprints/_helpers.py#L161-L205)             | Single decorator (`require_auth`) + thin wrapper (`check_auth`). ✅ |
| Frontend (signed-in dashboard)               | [website/js/app-msal.js](website/js/app-msal.js)                       | MSAL wrapper exposing `window.CanopexAuth`. After this PR, scope is `audience + '/.default'`, never falls back to ID token. ✅ |
| Frontend (landing / EUDR pages)              | [website/js/landing.js](website/js/landing.js)                         | Self-contained MSAL flow. After this PR uses the same scope and same access-token-only contract. ✅ |
| Test-mode principal injection                | [blueprints/_helpers.py](blueprints/_helpers.py#L121-L132)             | Accepts `X-MS-CLIENT-PRINCIPAL` only when `CANOPEX_TEST_MODE=true`. Defensible for CI. 🟡 |
| Ops dashboard auth                           | [blueprints/ops.py](blueprints/ops.py#L127-L132)                       | Separate HMAC-key path (`Authorization: Bearer <ops-key>`), bypassing CIAM. **Intentional** — ops dashboard predates user provisioning of operator accounts. Document and remove once CIAM operator role exists. 🟡 |

**Issues:**

- 🟡 **Stale `X-MS-CLIENT-PRINCIPAL` reference in CORS allowlist.**
  [blueprints/_helpers.py](blueprints/_helpers.py#L108) still
  advertises this header in `Access-Control-Allow-Headers`. Production
  no longer sends it (SWA `/.auth/*` is gone). Keep only because
  test-mode still uses it, but document — and remove from CORS once
  `CANOPEX_TEST_MODE` is also removed.

- 🟡 **Legacy app-auth.js reference in app-msal.js docstring.**
  [website/js/app-msal.js](website/js/app-msal.js#L1-L24) header
  comment refers to `app-auth.js` which no longer exists. Update the
  docstring to remove the false breadcrumb.

- 🟢 **Frontend auth duplication is acceptable.** `landing.js` runs on
  `/`, `/eudr/`, marketing pages; `app-msal.js` runs only inside
  `/app/`. They MUST initialise MSAL independently because they have
  different `redirectUri` paths. After this PR they share scope and
  token semantics. The shared logic that *could* be extracted is
  small (~30 lines of redirect-loop guard + scope builder) and would
  introduce a script-load ordering dependency. **Defer extraction**
  until a third surface needs it.

- 🟡 **`canopex-evidence-render.js` accidentally global.** Like all
  `canopex-*` modules, it pollutes `window.*` (wrapped IIFE pattern).
  This is consistent with the no-build-step rule but means any name
  collision is a silent footgun. No change needed — just be aware.

### 3.2 Request pipeline

| Blueprint                                 | LoC   | Public routes                                      | Notes |
|-------------------------------------------|-------|----------------------------------------------------|-------|
| [blueprints/health.py](blueprints/health.py)               | 211   | `/api/health`, `/readiness`, `/contract`, `/internal-smoke`, `/health/deep` | Anonymous; OK. |
| [blueprints/contact.py](blueprints/contact.py)             | small | `/api/contact-form`                                | OK. |
| [blueprints/billing.py](blueprints/billing.py)             | 576   | `/billing/{checkout,portal,webhook,status,…}`      | OK; webhook validated by Stripe sig. |
| [blueprints/org.py](blueprints/org.py)                     | 300   | `/api/org/{settings,invite,members,…}`             | OK. |
| [blueprints/eudr.py](blueprints/eudr.py)                   | 701   | 6 routes                                           | Large; mixes EUDR-specific business rules with HTTP. |
| [blueprints/upload.py](blueprints/upload.py)               | 567   | `/api/upload/token`, …                             | Direct `azure.storage.blob` import for SAS — OK (mediation layer would add no value here). |
| [blueprints/analysis.py](blueprints/analysis.py)           | 755   | 3 routes                                           | Heavy; flagged below. |
| [blueprints/catalogue.py](blueprints/catalogue.py)         | 201   | 4 routes                                           | OK. |
| [blueprints/export.py](blueprints/export.py)               | **1529**  | `/api/export`                                  | Single endpoint; massive PDF/CSV/GeoJSON builders inline. **Highest decay risk.** |
| [blueprints/monitoring.py](blueprints/monitoring.py)       | 405   | 2 routes + scheduler                               | OK. |
| [blueprints/ops.py](blueprints/ops.py)                     | 403   | 4 routes                                           | Separate HMAC auth (above). |
| [blueprints/demo.py](blueprints/demo.py)                   | 200   | `/demo-valet-tokens`, `/demo-artifacts`, `/proxy`  | `/api/proxy` (catalogue thumbnail proxy) — verify SSRF posture. 🟡 |
| [blueprints/pipeline/](blueprints/pipeline/)               | 2475  | `/analysis/submit`, enrichment, annotations, history, diagnostics + Durable orchestrator + 22 activity functions | Cleanly split into submodules. |

**Issues:**

- 🔴 **`blueprints/export.py` is 1529 lines and contains four
  independent rendering pipelines** (GeoJSON, CSV, EUDR-CSV/GeoJSON,
  two PDF flavours). It belongs in `treesight/exports/`. Split:
  `treesight/exports/geojson.py`, `csv.py`, `eudr.py`, `pdf_audit.py`,
  with `blueprints/export.py` reduced to dispatch + auth +
  manifest fetch (~150 lines). Track as `[discovered]` issue.

- 🟡 **`blueprints/analysis.py` (755 lines) and `blueprints/eudr.py`
  (701 lines)** — same pattern, smaller scale. Watch for the same
  decay; split when next significant change lands.

- 🟡 **`/api/proxy`** in `blueprints/demo.py` — catalogue-image proxy
  is an SSRF candidate. Verify it has a strict allowlist of upstream
  hosts. Out of scope for this review; flag for follow-up.

### 3.3 Domain layer (`treesight/`)

```text
treesight/
├── ai/             # AI annotation helpers
├── catalogue/      # Catalogue clients
├── config.py       # Env-var driven config (single import surface)
├── constants.py    # Magic numbers
├── email.py
├── errors.py
├── geo.py          # Pure geo helpers
├── log.py          # OpenTelemetry wiring for App Insights
├── models/         # Pydantic / dataclass domain models
├── monitoring.py
├── parsers/        # KML/KMZ — fiona primary, lxml fallback
├── pipeline/       # Acquisition, enrichment, fulfilment, ingestion
├── providers/      # External-service adapters
├── security/       # Auth, billing, quota, orgs, ledger, payment_provider
└── storage/        # Azure SDK wrappers (blob, cosmos, table)
```

The package boundary is healthy. Blueprints depend on `treesight/`,
`treesight/` does not depend on `blueprints/` (verified by import
graph). The exception worth noting:

- 🟡 **`blueprints/upload.py:19` imports `azure.storage.blob` directly**
  (for SAS generation). This is acceptable — SAS generation is a thin
  Azure-SDK call with no domain logic to mediate. Documenting it here
  so a future reviewer doesn't flag it as an obvious mistake.

### 3.4 Frontend (`website/js/`)

23 IIFE modules, total ~7800 LoC, no build step. After the recent
decomposition `app-shell.js` is down to 500 LoC and acts as the
orchestration shim that imports from `Canopex*` globals exposed by
sibling modules. Wiring is manual (top of [app-shell.js](website/js/app-shell.js#L1-L40))
which is fragile but explicit.

| File                                | LoC   | Purpose |
|-------------------------------------|-------|---------|
| `app-evidence-display.js`           | 1071  | Largest — evidence UI rendering.   |
| `app-run-lifecycle.js`              | 714   | Run polling + state transitions.   |
| `app-msal.js`                       | 616   | MSAL auth (signed-in app).         |
| `canopex-evidence-render.js`        | 578   | Evidence partial renderers.        |
| `app-shell.js`                      | 500   | Orchestration shim.                |
| `landing.js`                        | 481   | MSAL + page logic for landing/EUDR.|
| `app-analysis-preflight.js`         | 420   | Pre-submit validation.             |
| (rest)                              | ≤345  | Smaller, single-purpose modules.   |

**Issues:**

- 🟡 **No script-load order is enforced.** Each `<script>` tag is just
  appended and modules expect their globals to exist. Today's order
  works because HTML places `Canopex*` deps before `app-*` consumers,
  but this is implicit. Acceptable while team is small; consider
  module declarations + `defer` ordering when the next surface is
  added.

- 🟢 **No dead JS files.** Every file in `website/js/` is referenced
  by at least one HTML `<script>` tag.

---

## Level 4 — Code (auth flow trace, end-to-end)

User clicks "Sign in" on `canopex.hrdcrprwn.com/app/`:

1. [website/js/app-msal.js](website/js/app-msal.js#L129) builds scopes
   `['openid','profile', audience + '/.default']`.
2. MSAL redirects to `https://hrdcrprwn.ciamlogin.com/...` with
   `redirect_uri = https://canopex.hrdcrprwn.com/app/`.
3. CIAM matches against the **app registration's** registered
   redirect URIs. If absent → AADSTS50011 (the bug that started this
   review).
4. Mitigation: [`infra/tofu/locals.tf`](infra/tofu/locals.tf#L40-L60)
   derives `ciam_redirect_uris` from `azurerm_static_web_app.main`
   resource binding × `var.custom_domain` × app paths;
   [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml#L805-L820)
   queries Graph and **fails the build** if the registered URIs are a
   subset of the Tofu-derived set. Drift cannot survive a deploy.
5. CIAM redirects back with `code` → MSAL exchanges for tokens →
   stores in `localStorage`.
6. Browser calls `/api/...` with `Authorization: Bearer <access_token>`.
7. [`blueprints/_helpers.py:require_auth`](blueprints/_helpers.py#L150)
   → [`treesight/security/auth.py:verify_bearer_token`](treesight/security/auth.py#L91)
   → fetches OIDC metadata (cached) → validates against
   `CIAM_API_AUDIENCE` → returns claims.
8. Handler receives `(req, auth_claims, user_id)`.

**No duplicate paths.** SWA `/.auth/me` and `X-MS-CLIENT-PRINCIPAL`
are not in the production flow — only the test-mode escape hatch
remains, gated by an explicit env var.

---

## Findings summary & recommended issues to file

| Sev | Title                                                                                              | Owner area     | Status |
|-----|----------------------------------------------------------------------------------------------------|----------------|--------|
| 🔴  | Orchestrator Function App registers all HTTP blueprints — should register only pipeline+health     | infra/registration | Open — #779 |
| 🔴  | `blueprints/export.py` is 1529 lines — extract rendering to `treesight/exports/`                   | refactor       | Open — #780 |
| 🟡  | Bring CIAM app registration under OpenTofu (azuread provider) to close the manual-drift gap        | infra/auth     | Closed — PR #776 (redirect URIs); residual #781 |
| 🟡  | Remove stale `X-MS-CLIENT-PRINCIPAL` from CORS allowlist when `CANOPEX_TEST_MODE` is retired       | auth           | Open — #782 |
| 🟡  | Update `app-msal.js` docstring — `app-auth.js` no longer exists                                    | frontend       | Likely moot — replaced by `canopex-auth.js` in #775 (#783) |
| 🟡  | Audit `/api/proxy` in `blueprints/demo.py` for SSRF / upstream-host allowlist                      | security       | Open — #784 |
| 🟡  | Plan split for `analysis.py` (755) and `eudr.py` (701) before next significant change              | refactor       | Open — #785 |
| 🟢  | Frontend auth surfaces (landing.js / app-msal.js): unify and extract                               | frontend       | Closed — PR #775 (consolidated to `canopex-auth.js`) |

---

## Already shipped (informing the recommendations above)

- **PR #775** — Consolidated MSAL across both SPAs into a single
  `website/js/canopex-auth.js` module. Standardised on the
  `audience/User.Read` scope and removed ID-token fallback. Closed the
  frontend duplication finding outright.
- **PR #776** — Brought CIAM SPA redirect URIs under OpenTofu via the
  `azuread ~> 3.0` provider. URIs are now derived in `infra/tofu` and
  applied via `azuread_application_redirect_uris.ciam_spa`, eliminating
  the manual-drift gap that triggered this review.

## Not done — recommended follow-ups

- Tackle the 🔴 issues (#779, #780) in the order listed.
- The remaining 🟡 items can ride along with adjacent feature work.
- Verify #783 against the post-#775 `canopex-auth.js` and close if no
  stale references remain.

