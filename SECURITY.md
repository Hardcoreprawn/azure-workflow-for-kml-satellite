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
- **Branch protection** — PRs required, CI must pass, stale reviews dismissed

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
- Network: Container Apps environment, Key Vault network rules, and Cosmos
  DB firewall restrict inbound surface.
- Ephemeral operational identifiers (deployed hostnames, SWA URLs) are not
  stored in this repository — retrieve them from the Azure portal or
  `tofu output` after provisioning.
- Deploy workflows prefer short-lived OIDC tokens where supported, but
  some long-lived secrets remain today, including GHCR pull credentials
  and Static Web Apps deployment tokens.

## Trivy Triage Policy

To keep findings actionable while staying cost-conscious in dev environments:

- Trivy image/filesystem scans are configured with `ignore-unfixed: true`.
  This suppresses vulnerabilities that currently have no upstream fix version.
- Temporary low-cost infra exceptions are tracked in `.trivyignore` with
  explicit rationale. These are not blanket suppressions and must be revisited
  when a paid hardening change is approved.

Current temporary exceptions:

- `AZU-0012` (Storage account network default deny policy)
- `AZU-0013` (Key Vault network ACL strictness)
- `AVD-AZU-0016` (Key Vault purge protection — variable defaults to `true`; Trivy cannot resolve variable refs)
- `AVD-AZU-0057` (Storage Analytics logging — superseded by `azurerm_monitor_diagnostic_setting`)
- `AVD-AZU-0061` (Infrastructure encryption — already enabled; Trivy false positive)

There are currently **no container-image CVE suppressions**. The previous
entries (Go stdlib, libpng, systemd/libcap/glibc, MessagePack, OpenTelemetry,
pip) were removed on 2026-06-23 after the daily base-image rebuild cleared
them — verified with a Trivy scan of the current `treesight` and
`treesight-base` images showing 0 HIGH/CRITICAL findings. Any future container
CVE ignore must be justified by a fresh scan proving a HIGH/CRITICAL finding
with no available fix in our image.
