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
- `CVE-2026-48109` (MessagePack HIGH — in `FuncExtensionBundles` baked into Microsoft's base image; fix
  released 2026-06-09 as MessagePack 2.5.301/3.1.7, but no patched extension bundle exists yet.
  Attack surface is limited to internal Durable Functions state serialisation over Azure Storage,
  not reachable from untrusted user input.  Will clear automatically on next base-image rebuild
  once Microsoft ships a patched bundle. Expiry: 2026-07-13. Tracked in #904.)
