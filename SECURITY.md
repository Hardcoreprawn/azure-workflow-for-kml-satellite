# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| main    | :white_check_mark: |
| < main  | :x:                |

## Reporting a Vulnerability

**Please do NOT open a public issue for security vulnerabilities.**

Use [GitHub's private vulnerability reporting](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/security/advisories/new) to disclose security issues responsibly.

We will acknowledge your report within **48 hours** and aim to provide a fix or mitigation within **7 days** for critical issues.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Impact assessment
- Suggested fix (if any)

## Security Measures

This repository uses the following free GitHub security features:

- **Dependabot alerts** — automatic CVE notifications for dependencies
- **Dependabot security updates** — automatic PRs pondering on vulnerable dependencies
- **Secret scanning** — detects accidentally committed secrets
- **Push protection** — blocks pushes containing secrets before they reach the repo
- **CodeQL analysis** — static analysis for security vulnerabilities on every PR
- **Private vulnerability reporting** — responsible disclosure channel
- **Owner review routing** — the committed `.github/CODEOWNERS` file identifies
  `@Hardcoreprawn` as the reviewer for auth, billing, ownership, workflow, and
  infrastructure paths. `pr-watchdog` highlights those changes as needing an
  owner opinion; it does not infer approval or replace the owner's merge decision.

## Open-Source Documentation Posture

This is an Apache 2.0 open-source repository.  The source code, infrastructure
definitions, and API documentation are intentionally public.  As noted in issue
[#570](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/570),
the following information appears in the public docs and source code:

- API route table with auth/anonymous annotations
- Infrastructure naming conventions and container names
- Deployment workflow design and secrets pipeline shape
- Durable Functions hub name and orchestration patterns
- Architecture diagrams and component relationships

**Risk acceptance decision (2026-06-13):** The real security boundary is
auth + network controls (CIAM bearer JWT for user endpoints, explicit
controls for special-purpose endpoints, managed identity, RBAC), not
documentation obscurity.  The source code already makes these details
discoverable, so hiding them only from docs would provide no meaningful
reduction in attack surface.

Mitigations in place:

- User-facing analysis, monitoring, catalogue, billing status, and export
  endpoints require a valid CIAM JWT. Special-purpose endpoints use
  explicit alternative controls (for example, ops-key bearer auth,
  Stripe webhook signature verification, function-key auth, or
  documented anonymous access for health/readiness probes).
- Production storage, Cosmos DB, and Key Vault access uses managed
  identity with minimal RBAC grants; local development may still use
  connection strings where required.
- Network: Storage and Key Vault currently lack deny-by-default network ACLs
  in both dev and prod templates. The temporary acceptance below does not
  replace authentication, RBAC, or production promotion gates.
- Ephemeral operational identifiers (deployed hostnames, SWA URLs) are not
  stored in this repository — retrieve them from the Azure portal or
  `tofu output` after provisioning.
- Deploy workflows prefer short-lived OIDC tokens where supported, but
  some long-lived secrets remain today, including GHCR pull credentials
  and Static Web Apps deployment tokens.

## Trivy Triage Policy

To keep findings actionable while staying cost-conscious before customer onboarding:

- Trivy image/filesystem scans are configured with `ignore-unfixed: true`.
  This suppresses vulnerabilities that currently have no upstream fix version.
- Temporary low-cost infra exceptions are tracked in `.trivyignore` with
  explicit rationale. These are not blanket suppressions and must be revisited
  before customer onboarding or expiry, whichever comes first.

Current temporary exceptions, accepted by the owner on 2026-09-12 until
2026-12-12 under #1500, cover the shared dev/prod template posture:

- `AZU-0012` (Storage account network default deny policy)
- `AZU-0013` (Key Vault network ACL strictness)
- `AVD-AZU-0057` (Logging coverage: modern blob write/delete diagnostics exist,
  but read and other storage-service coverage equivalence is unproven)

Private networking and additional paid Defender coverage are deferred. Obsolete
purge-protection, infrastructure-encryption, and Defender scanner exceptions
were removed after revalidation, not renewed. Production freeze is unchanged.

The 2026-09-12 local base rebuild consumed Functions extension bundle 4.38.1
with MessagePack 2.5.301, which patches CVE-2026-48109 and CVE-2026-48506.
Container smoke checks and a Trivy 0.73.0 image scan without ignore-file
exceptions passed (fixable HIGH/CRITICAL scope), so both CVE exceptions were
removed. This is candidate evidence, not proof that older published or deployed
images are patched; publishing and promotion require their own release gates.

HIGH/CRITICAL container findings must be fixed at source when the repository
controls or can directly upgrade the affected component. A temporary container
CVE exception is allowed only when all of the following are true:

- the vulnerable component is vendored by an upstream runtime and cannot be
  upgraded independently in this repository;
- a fresh no-cache image build and unsuppressed scan prove the finding remains
  after consuming the newest supported upstream artifact;
- the entry links a tracking issue, records the upstream owner and rationale,
  and expires within 30 days.

All other container findings remain blocking. The reconciler proposes removing
an exception when a patched upstream artifact becomes available.

### Build-time auto-reconciliation

Container-CVE suppressions (the `CVE-*` entries) are reviewed by the weekly
base-image workflow (`.github/workflows/base-image.yml`). Expiry remains a
blocking gate until a reviewed change is merged.

After the base image is rebuilt (which runs `apt-get upgrade -y`) and published,
a dedicated least-privilege job reuses the build's scan **without** `.trivyignore`
(`--severity CRITICAL,HIGH --ignore-unfixed`) and runs
`scripts/reconcile_trivyignore.py`:

- **Resolved** — the CVE is no longer in the scan. The fix shipped in the
  rebuild, so the suppression is removed.
- **Still present** — the CVE survived a fresh rebuild, so no installable fix
  exists yet. The expiry is renewed (only when expired or within ~14 days of
  expiry, to avoid churn).
- **Config findings** (`AZU-*` / `AVD-*`) are never touched — they are infra
  policy decisions, not image CVEs, and cannot be judged from an image scan.
- The reconciler never **adds** a suppression. A new, unsuppressed HIGH/CRITICAL
  finding is a real exposure that the build's blocking Trivy gate must fail on.

Drift is healed through a reviewed bot PR on branch `chore/trivyignore-reconcile`
— never an auto-commit to `main`. This requires the repository setting
**Settings → Actions → General → "Allow GitHub Actions to create and approve
pull requests"** to be enabled because GitHub combines both capabilities under
one setting. This workflow uses that capability only to create a reviewable PR;
no workflow may submit approvals or merge security-sensitive changes.
