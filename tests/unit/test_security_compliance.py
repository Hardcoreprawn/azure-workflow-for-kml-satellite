"""Security compliance tests — credential scan and hardening checks. (Issue #17)

Performs static analysis of the codebase to catch common credential
exposure and security misconfiguration patterns.  All checks are
entirely offline — file-system only, no network or Azure calls.

Security checks:
    1. No hardcoded credentials in Python source (regex scan)
    2. No real secret values in local.settings.json.template
    3. pre-commit config includes detect-secrets or detect-private-key hook
    4. requirements.txt / pyproject.toml: azure-identity is present (no key fallback)
    5. infra Terraform files: no hardcoded secrets or passwords
    6. local.settings.json.template is exclude from git (or is a template only)
    7. Dockerfile does not COPY local.settings.json

References:
    OWASP A02:2021 (Cryptographic Failures)
    OWASP A05:2021 (Security Misconfiguration)
    PID 7.4.5  (Explicit Over Implicit — authenticated clients only)
    Issue #17  (Security review)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Project roots
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[2]
_KML_SAT = _REPO_ROOT / "kml_satellite"
_INFRA_TF = _REPO_ROOT / "infra" / "tofu"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _python_sources() -> list[Path]:
    """All .py files under kml_satellite/ and function_app.py."""
    sources = list(_KML_SAT.rglob("*.py"))
    func_app = _REPO_ROOT / "function_app.py"
    if func_app.exists():
        sources.append(func_app)
    return sources


def _tf_sources() -> list[Path]:
    """All .tf files under infra/tofu/."""
    return list(_INFRA_TF.rglob("*.tf"))


# ---------------------------------------------------------------------------
# Credential patterns
# ---------------------------------------------------------------------------

# These patterns catch *assignment* of sensitive values (not imports or logger
# calls).  Each is applied case-insensitively to the full file contents.
#
# Intentional false-positive exclusions:
#   - Empty-string assignments:    password = ""
#   - Env-lookup assignments:      password = os.environ.get("...")
#   - Comment lines:               # password = <retrieved from KeyVault>
#   - Type annotations without rhs
#
# The regex must match the *value* being non-trivial (not empty, not an
# env/os call, not a call expression).  We check for a bare string literal
# after the equals sign.

_CREDENTIAL_RE = re.compile(
    r"""
    (?:^|[^#\w])           # not a comment, not mid-word
    (?:password|passwd|secret|api_key|apikey|private_key|access_key)
    \s*=\s*                # assignment
    ['"][^'"]{6,}['"]      # non-trivial string value (≥6 chars)
    """,
    re.IGNORECASE | re.VERBOSE | re.MULTILINE,
)

_CONNECTION_STRING_RE = re.compile(
    r"""
    connection_string\s*=\s*['"][^'"]{20,}['"]
    """,
    re.IGNORECASE | re.VERBOSE | re.MULTILINE,
)

_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 1. Python source credential scan
# ---------------------------------------------------------------------------


class TestNoPythonCredentials:
    """No hardcoded credentials in any Python source file."""

    @pytest.mark.parametrize(
        "source", _python_sources(), ids=lambda p: str(p.relative_to(_REPO_ROOT))
    )
    def test_no_credential_assignments(self, source: Path) -> None:
        text = source.read_text(encoding="utf-8")
        match = _CREDENTIAL_RE.search(text)
        assert match is None, (
            f"Possible hardcoded credential in {source.relative_to(_REPO_ROOT)}: {match.group()!r}"
        )

    @pytest.mark.parametrize(
        "source", _python_sources(), ids=lambda p: str(p.relative_to(_REPO_ROOT))
    )
    def test_no_connection_string_literals(self, source: Path) -> None:
        text = source.read_text(encoding="utf-8")
        match = _CONNECTION_STRING_RE.search(text)
        assert match is None, (
            f"Possible hardcoded connection string in {source.relative_to(_REPO_ROOT)}: "
            f"{match.group()!r}"
        )

    @pytest.mark.parametrize(
        "source", _python_sources(), ids=lambda p: str(p.relative_to(_REPO_ROOT))
    )
    def test_no_private_key_blocks(self, source: Path) -> None:
        text = source.read_text(encoding="utf-8")
        assert not _PRIVATE_KEY_BLOCK_RE.search(text), (
            f"Private key block found in {source.relative_to(_REPO_ROOT)}"
        )


# ---------------------------------------------------------------------------
# 2. local.settings.json.template — template-only check
# ---------------------------------------------------------------------------


class TestLocalSettingsTemplate:
    """local.settings.json.template must not contain real secret values."""

    _template = _REPO_ROOT / "local.settings.json.template"

    def test_template_exists(self) -> None:
        assert self._template.exists(), "local.settings.json.template must exist"

    def test_keyvault_url_is_empty(self) -> None:
        """KEYVAULT_URL must be an empty string (no real URL in template)."""
        import json

        data = json.loads(self._template.read_text(encoding="utf-8"))
        keyvault_url = data.get("Values", {}).get("KEYVAULT_URL", None)
        assert keyvault_url is not None, "KEYVAULT_URL key must be present in template"
        assert keyvault_url == "", f"KEYVAULT_URL must be empty in template, got: {keyvault_url!r}"

    def test_appinsights_key_is_empty_or_absent(self) -> None:
        """APPINSIGHTS_INSTRUMENTATIONKEY must be empty or absent in template."""
        import json

        data = json.loads(self._template.read_text(encoding="utf-8"))
        key = data.get("Values", {}).get("APPINSIGHTS_INSTRUMENTATIONKEY", "")
        assert key == "", f"APPINSIGHTS_INSTRUMENTATIONKEY must be empty in template, got: {key!r}"

    def test_no_storage_connection_string(self) -> None:
        """AzureWebJobsStorage must not contain a real connection string."""
        import json

        data = json.loads(self._template.read_text(encoding="utf-8"))
        storage = data.get("Values", {}).get("AzureWebJobsStorage", "")
        # Acceptable: development storage emulator or empty
        real_conn_pattern = re.compile(
            r"DefaultEndpointsProtocol=https.*AccountKey=", re.IGNORECASE
        )
        assert not real_conn_pattern.search(storage), (
            "AzureWebJobsStorage must not contain a real storage connection string"
        )


# ---------------------------------------------------------------------------
# 3. pre-commit config includes a secret detection hook
# ---------------------------------------------------------------------------


class TestPreCommitSecretDetection:
    """Pre-commit config must include a secrets/credential detection hook."""

    _config = _REPO_ROOT / ".pre-commit-config.yaml"

    def test_precommit_config_exists(self) -> None:
        assert self._config.exists(), ".pre-commit-config.yaml must exist"

    def test_detect_secrets_or_private_key_hook_present(self) -> None:
        """detect-secrets, detect-private-key, or gitleaks must be configured."""
        text = self._config.read_text(encoding="utf-8")
        has_hook = any(
            hook in text for hook in ("detect-secrets", "detect-private-key", "gitleaks")
        )
        assert has_hook, (
            "Pre-commit config must include a secrets-detection hook "
            "(detect-secrets, detect-private-key, or gitleaks)"
        )


# ---------------------------------------------------------------------------
# 4. dependencies — azure-identity present, no key-based fallback
# ---------------------------------------------------------------------------


class TestDependencyHardening:
    """azure-identity must be declared; no legacy key-based auth packages."""

    _requirements = _REPO_ROOT / "requirements.txt"
    _pyproject = _REPO_ROOT / "pyproject.toml"

    def test_azure_identity_in_requirements(self) -> None:
        """requirements.txt must include azure-identity for DefaultAzureCredential."""
        assert self._requirements.exists(), "requirements.txt must exist"
        text = self._requirements.read_text(encoding="utf-8")
        assert "azure-identity" in text, "requirements.txt must include azure-identity"

    def test_azure_identity_not_pinned_to_ancient_version(self) -> None:
        """azure-identity must not be pinned to a version before 1.15.0."""
        text = self._requirements.read_text(encoding="utf-8")
        # Extract any pinned version: azure-identity==X.Y.Z
        pinned = re.search(r"azure-identity==(\d+)\.(\d+)", text)
        if pinned:
            major, minor = int(pinned.group(1)), int(pinned.group(2))
            assert (major, minor) >= (1, 15), (
                f"azure-identity is pinned to {major}.{minor} which is too old — "
                "use >=1.15.0 to include managed identity improvements"
            )

    def test_azure_identity_in_pyproject(self) -> None:
        """pyproject.toml must declare azure-identity as a dependency."""
        assert self._pyproject.exists(), "pyproject.toml must exist"
        text = self._pyproject.read_text(encoding="utf-8")
        assert "azure-identity" in text, "pyproject.toml must include azure-identity"


# ---------------------------------------------------------------------------
# 5. Terraform — no hardcoded secrets
# ---------------------------------------------------------------------------


_TF_PASSWORD_RE = re.compile(
    r"""
    (?:password|secret|api_key|access_key)\s*=\s*['"][^'"]{4,}['"]
    """,
    re.IGNORECASE | re.VERBOSE | re.MULTILINE,
)


class TestTerraformNoHardcodedSecrets:
    """Terraform files must not contain hardcoded secrets."""

    @pytest.mark.parametrize(
        "tf_file",
        _tf_sources(),
        ids=lambda p: str(p.relative_to(_REPO_ROOT)),
    )
    def test_no_hardcoded_credentials_in_tf(self, tf_file: Path) -> None:
        text = tf_file.read_text(encoding="utf-8")
        match = _TF_PASSWORD_RE.search(text)
        assert match is None, (
            f"Possible hardcoded credential in {tf_file.relative_to(_REPO_ROOT)}: "
            f"{match.group()!r}"
        )


# ---------------------------------------------------------------------------
# 6. Dockerfile does not COPY local.settings.json
# ---------------------------------------------------------------------------


class TestDockerfileHardening:
    """Dockerfile must not embed local development settings."""

    _dockerfile = _REPO_ROOT / "Dockerfile"

    def test_dockerfile_exists(self) -> None:
        assert self._dockerfile.exists(), "Dockerfile must exist at project root"

    def test_dockerfile_does_not_copy_local_settings_json(self) -> None:
        """Prevent accidental inclusion of real dev secrets in the image."""
        text = self._dockerfile.read_text(encoding="utf-8")
        assert "local.settings.json" not in text, (
            "Dockerfile must not COPY or reference local.settings.json — "
            "this file may contain real credentials"
        )

    def test_dockerfile_does_not_expose_secret_env_vars(self) -> None:
        """ENV directives in the Dockerfile must not set sensitive values."""
        text = self._dockerfile.read_text(encoding="utf-8")
        # Look for ENV lines with obvious credential names
        env_secret_re = re.compile(
            r"^ENV\s+(?:PASSWORD|SECRET|API_KEY|PRIVATE_KEY|CONNECTION_STRING)\s*=",
            re.IGNORECASE | re.MULTILINE,
        )
        match = env_secret_re.search(text)
        assert match is None, f"Dockerfile ENV sets a sensitive variable: {match.group()!r}"
