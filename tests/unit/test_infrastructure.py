"""Infrastructure validation tests - MIGRATED TO OPENTOFU.

✅ Bicep template tests have been removed after migration to OpenTofu .

Infrastructure validation is now performed via:
- tofu-plan.yml: Validates plan with all environments before apply
- tofu-apply.yml: Deploys and validates with smoke tests
- OPERATIONAL_READINESS_ASSESSMENT.md: Comprehensive readiness evaluation

For infrastructure as code testing, see:
- infra/tofu/: OpenTofu main configuration
- infra/tofu/environments/: Environment-specific variables
- .github/workflows/tofu-*.yml: CI/CD pipeline validation
"""

import pytest


@pytest.mark.skip(reason="Bicep infrastructure migrated to OpenTofu")
def test_bicep_deprecated() -> None:
    """Infrastructure validation now performed via OpenTofu CI/CD pipeline."""
    pass
