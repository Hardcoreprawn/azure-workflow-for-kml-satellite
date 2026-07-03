# ADR 0003: Three Bounded Contexts — Engine / App / Harness

## Status

Accepted (2026-07-03)

## Context

The repository has grown to hold three distinct concerns that we regularly
conflate when planning, testing, and building:

1. **Engine** — the geospatial pipeline: KML/KMZ parsing, geometry, imagery
   acquisition, NDVI, change detection, enrichment. Pure processing.
2. **App** — the sellable product: HTTP API, EUDR compliance surface, billing,
   auth/quota, account, export, and the website UI.
3. **Harness** — how we build and prove the product: CI/CD, deploy, infra
   (OpenTofu), the backlog autopilot, prioritisation, release safety, and the
   test/observability tooling.

The confusion is real but shallow: an import audit shows Azure SDK usage is
confined to `treesight/storage/` (`cosmos.py`, `client.py`) — the geospatial
core (`parsers/`, `geo.py`, `pipeline/`, `providers/`, `ai/`, `rust/`) is
essentially Azure-free already. So the three concerns are **separable by
drawing explicit lines**, not by a rewrite. The conflation lives mainly at the
**organisation / backlog / planning** level: one backlog ranks engine bugs
next to product features next to autopilot tooling, and whole sessions of pure
*harness* work get mistaken for product progress.

## Decision

Treat the repo as **three bounded contexts** with an explicit dependency
direction, made visible without a premature repo split.

### 1. The three contexts and where they live

| Context | Responsibility | Location |
|---|---|---|
| **Engine** | geospatial processing (parse → NDVI → change detection → enrichment) | `treesight/parsers,geo,pipeline,providers,ai,models`, `rust/` |
| **App** | the product: API, EUDR, billing, auth, export, UI | `blueprints/`, `website/`, `treesight/storage,security,billing,catalogue,email`, `function_app*.py` |
| **Harness** | build/prove/operate the product | `scripts/backlog_autopilot.py`, `.github/workflows/`, `infra/tofu/`, smoke/e2e scripts, prioritisation mechanism |

### 2. Dependency direction (the rule)

```text
harness  →  app  →  engine
```

- The **engine** depends on nothing app- or Azure-specific. It is a pure
  library that could, in principle, be extracted and reused.
- The **app** depends on the engine and owns all platform coupling (Azure,
  Stripe, CIAM).
- The **harness** depends on/operates the app; the app never depends on the
  harness.

This is almost true today. It becomes enforceable later with an import-boundary
check (deferred — see split criteria).

### 3. Domain axis on the backlog

Every issue carries a `domain:engine` / `domain:app` / `domain:harness` label —
a third facet alongside MoSCoW (`moscow:*`) and the prioritisation quadrants
(#1010). This surfaces the mix (e.g. "we are 80% harness this cycle") and stops
prioritisation from conflating the three.

### 4. Three test layers mirror the three contexts

| Layer | Scope | Data strategy |
|---|---|---|
| **Engine** | geospatial correctness, pure & fast, no Azure | a **golden** representative AOI run end-to-end, then a parametrised **fan-out** over edge cases (malformed KML, huge AOIs, zip bombs, degenerate geometry). Owned by #870. |
| **App integration** | API + pipeline + storage against Azurite | #1022 (Azurite service container in CI) |
| **Harness** | autopilot/CI logic | `tests/test_backlog_autopilot.py` etc. |

The deploy "prove-it-works" gate (#708/#734) is the **app** layer running one
golden AOI end-to-end against a live/local environment.

### 5. Stay a monorepo now — split only on explicit triggers

A three-repo split is premature (solo maintainer, pre-launch, app currently
offline). Split into separate repositories only when **any** of these fire:

- The **engine** gains a second consumer (another product/customer) that would
  benefit from versioned reuse.
- The dependency direction is repeatedly violated and only a hard repo boundary
  will hold it.
- Build/test times or ownership boundaries make the monorepo the bottleneck.
- Independent release cadences are genuinely needed (engine vs app vs harness).

Until then, the boundaries are enforced by **labels + the dependency rule +
the test layers**, not by separate repos.

## Consequences

**Positive**

- Planning stops conflating the three; the domain mix is visible each cycle.
- The engine's near-zero Azure coupling is protected and made a deliberate
  invariant, keeping a future extraction cheap.
- Test strategy is coherent: golden-path-then-fan-out in the engine layer,
  integration in the app layer, logic tests in the harness.

**Negative / costs**

- A third label axis adds triage overhead.
- Some issues are genuinely cross-cutting; they are tagged by *primary* domain,
  which is a judgement call.
- The dependency rule is convention until an import-boundary check is added.

## Related

- #1010 (prioritisation mechanism — MoSCoW + quadrants; this adds the domain facet)
- #870 (engine test corpus — golden path → fan-out)
- #1022 (app integration tests via Azurite), #708/#734 (app prove-it-works gate)
- #1013 (relight — a harness/deploy effort to bring the app back online)
