# UAT Validation Plan (Issue #19)

## Objective

Run user acceptance testing with a domain expert to confirm the pipeline produces correct, usable agricultural outputs and is ready for Phase 3 sign-off.

## Scope

This plan covers the required UAT scenarios from issue #19:

1. Upload a real orchard boundary KML and confirm imagery is returned.
2. Upload a multi-block orchard KML and confirm all blocks are processed.
3. Upload a KML with missing metadata and confirm graceful processing.
4. Upload a malformed file and confirm clear error handling with no crash.
5. Visually inspect output imagery for geographic correctness.
6. Validate metadata JSON fields and value reasonableness.
7. Validate output blob organization and navigability.

## Entry Criteria

All of the following must be true before starting UAT execution:

- Wave 1 engineering gates merged on main: #13, #14, #15, #16, #17.
- Documentation baseline available from #18 (runbook + architecture/API references).
- CI on main is green.
- Live environment credentials available for test execution.

## Test Assets

- Single polygon: tests/data/01_single_polygon_orchard.kml
- Multi-feature: tests/data/03_multi_feature_vineyard.kml
- Missing metadata case: tests/data/08_no_extended_data.kml
- Malformed case: tests/data/edge_cases/11_malformed_not_xml.kml
- Optional real-world KMLs: tests/data/uk-*.kml

## Execution Steps

### 1. Environment readiness

1. Confirm Function App host and storage account endpoints resolve.
2. Confirm durable orchestration diagnostics endpoint returns status payloads.
3. Confirm output container is reachable for artifact checks.

### 2. Run automated live checks as baseline

1. Run existing live E2E suite:
   - pytest tests/integration/test_live_pipeline.py -m e2e -v
2. Run concurrent stress validation:
   - pytest tests/integration/test_stress_pipeline.py -m "e2e and slow" -v
3. Record run URLs if executed in GitHub Actions.

### 3. Execute UAT scenarios with domain expert

For each scenario, collect:

- input KML used
- orchestration instance id
- runtime status
- output artifact paths
- reviewer notes and acceptance decision

#### Scenario A: Real orchard boundary

- Input: single polygon orchard KML
- Expected: Completed orchestration, imagery artifacts, metadata JSON

#### Scenario B: Multi-block orchard

- Input: multi-feature orchard/vineyard KML
- Expected: each block represented in outputs, no missing features

#### Scenario C: Missing metadata

- Input: KML without extended metadata
- Expected: pipeline still completes or returns explicit partial status with valid metadata output fields

#### Scenario D: Malformed file

- Input: malformed KML
- Expected: clear failure/error response, no host crash, no stuck orchestration fan-out

### 4. Visual and semantic output review

1. Open generated imagery in GIS viewer and confirm AOI alignment.
2. Review metadata JSON for expected fields:
   - source file identity
   - feature identifiers
   - spatial references and geometry-derived metrics
   - provider and acquisition details (when available)
3. Verify blob path conventions are coherent and discoverable.

## UAT Evidence Log

| Scenario | Input | Instance ID | Result | Evidence Links | Reviewer Notes |
|---|---|---|---|---|---|
| A |  |  |  |  |  |
| B |  |  |  |  |  |
| C |  |  |  |  |  |
| D |  |  |  |  |  |

## Defect Handling During UAT

- Blocking defects: create high-priority GitHub issues immediately and pause sign-off.
- Non-blocking findings: create backlog issues labeled enhancement or ux and continue.
- Every finding must include: reproduction steps, expected vs actual behavior, logs/correlation id.

## Exit Criteria

- Domain expert confirms outputs are correct and usable for target use case.
- AC-1 through AC-12 evidence is documented (test output + reviewer notes).
- No open blocking defects remain.
- Sign-off recorded in one of:
  - PID Section 21
  - issue #19 comment containing approver name/date and sign-off statement

## Sign-Off Record

- Domain expert: ____________________
- Role/organization: ____________________
- Date: ____________________
- Decision: Approved / Approved with conditions / Rejected
- Notes: ______________________________________________
