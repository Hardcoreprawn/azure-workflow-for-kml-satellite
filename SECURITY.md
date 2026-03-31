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
