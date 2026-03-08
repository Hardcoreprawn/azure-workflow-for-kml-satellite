# Infrastructure Naming Standard

This standard defines canonical resource naming for OpenTofu-managed Azure infrastructure.

## Goals

- Deterministic names across environments
- Azure compliance (length/charset constraints)
- Easy operational discovery and incident triage
- Predictable CI/CD variable wiring

## Environment Codes

- `dev`: development and feature-branch validation target
- `prd`: production target

## Global Inputs

- `project_code`: short, lowercase identifier for the system. Default: `kmlsat`
- `env`: one of `dev`, `prd`
- `location_code`: short region code. Default for UK South: `uks`

## Core Pattern

Most resources follow:

`<prefix>-<project_code>-<env>`

Examples:

- Resource group: `rg-kmlsat-dev`
- Function app: `func-kmlsat-dev`
- Container Apps environment: `cae-kmlsat-dev`
- Key Vault: `kv-kmlsat-dev`
- Log Analytics workspace: `log-kmlsat-dev`
- App Insights: `appi-kmlsat-dev`
- Event Grid system topic: `evgt-kmlsat-dev`
- Event Grid subscription: `evgs-kml-upload`
- Static Web App: `stapp-kmlsat-dev-site`

## Storage Account Pattern

Storage accounts are globally unique and must be 3-24 chars, lowercase alphanumeric.

Pattern:

`st<project_code><env><suffix>`

Rules:

- Remove dashes from project and env
- Append deterministic uniqueness suffix (4-6 chars)
- Keep total length <= 24

Example:

- `stkmlsatdeva1b2`

## Container Naming Pattern

Default containers created at deploy time:

- `kml-input`
- `kml-output`
- `deployments`
- `pipeline-payloads`

Tenant-specific containers are provisioned dynamically by app services (`<tenant>-input`, `<tenant>-output`).

## Tag Standard

Required tags for all resources:

- `project = kml-satellite`
- `environment = <env>`
- `managed-by = opentofu`
- `owner = platform`

Optional tags:

- `cost-center`
- `data-classification`

## CI/CD Naming Inputs

GitHub environments:

- `dev`
- `prd`

State key convention:

- `kml-satellite-<env>.tfstate`

## Constraints and Guardrails

- Never rename live resources without explicit migration plan
- Never mix `bicep` and `opentofu` ownership in same environment
- Use clean-slate recreate for environment cutover (no drift carryover)
