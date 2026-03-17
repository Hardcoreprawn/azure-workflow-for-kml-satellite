"""Contract tests for Event Grid connector pattern.

These tests enforce the architecture decision to use Event Grid Azure Function
resource ID destinations instead of runtime webhook URLs.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEPLOY_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "deploy.yml"
_TOFU_MAIN = _REPO_ROOT / "infra" / "tofu" / "main.tf"


def test_deploy_workflow_uses_azurefunction_destination_type() -> None:
    content = _DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    assert "--endpoint-type azurefunction" in content
    assert "/functions/${TRIGGER_NAME}" in content


def test_deploy_workflow_does_not_use_runtime_webhook_url_for_subscription() -> None:
    content = _DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    assert "--endpoint-type webhook" not in content
    assert "runtime/webhooks/eventgrid?functionName=" not in content


def test_tofu_subscription_uses_azurefunction_destination() -> None:
    content = _TOFU_MAIN.read_text(encoding="utf-8")
    assert 'endpointType = "AzureFunction"' in content
    assert "/functions/kml_blob_trigger" in content


def test_tofu_subscription_does_not_embed_eventgrid_webhook_key_url() -> None:
    content = _TOFU_MAIN.read_text(encoding="utf-8")
    assert 'endpointType = "WebHook"' not in content
    assert "runtime/webhooks/eventgrid?functionName=kml_blob_trigger" not in content
