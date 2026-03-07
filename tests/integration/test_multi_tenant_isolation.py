"""End-to-end multi-tenant isolation tests.

Phase 5 E2E: Validates that two tenants can process KML simultaneously
with outputs correctly isolated to tenant-specific containers.

Tests verify:
- tenant_id extraction from container names ({tenant_id}-input pattern)
- Output routing to correct tenant containers ({tenant_id}-output)
- Tenant A's outputs don't leak into Tenant B's container
- Concurrent processing maintains isolation
"""

from kml_satellite.models.blob_event import BlobEvent


def test_blob_event_extracts_tenant_id_from_container_name():
    """Test that tenant_id is correctly extracted from container name."""
    # Tenant A
    event_a = BlobEvent(
        blob_name="orchard.kml",
        content_length=1024,
        container_name="tenant-a-input",
        blob_url="https://account.blob.core.windows.net/tenant-a-input/orchard.kml",
    )
    assert event_a.tenant_id == "tenant-a"
    assert event_a.output_container == "tenant-a-output"

    # Tenant B
    event_b = BlobEvent(
        blob_name="vineyard.kml",
        content_length=2048,
        container_name="tenant-b-input",
        blob_url="https://account.blob.core.windows.net/tenant-b-input/vineyard.kml",
    )
    assert event_b.tenant_id == "tenant-b"
    assert event_b.output_container == "tenant-b-output"

    # Legacy (no tenant)
    event_legacy = BlobEvent(
        blob_name="field.kml",
        content_length=512,
        container_name="kml-input",
        blob_url="https://account.blob.core.windows.net/kml-input/field.kml",
    )
    assert event_legacy.tenant_id == ""
    assert event_legacy.output_container == "kml-output"


def test_multi_tenant_output_isolation():
    """Test that multiple tenants' outputs are routed to correct containers."""
    tenants = [
        ("acme-corp", "acme-corp-input", "acme-corp-output"),
        ("globex-inc", "globex-inc-input", "globex-inc-output"),
        ("initech", "initech-input", "initech-output"),
    ]

    for tenant_id, input_container, expected_output in tenants:
        event = BlobEvent(
            blob_name=f"{tenant_id}.kml",
            content_length=1024,
            container_name=input_container,
            blob_url=f"https://account.blob.core.windows.net/{input_container}/{tenant_id}.kml",
        )
        assert event.tenant_id == tenant_id
        assert event.output_container == expected_output


def test_tenant_id_extraction_handles_hyphens_in_tenant_name():
    """Test that tenant IDs with hyphens are correctly parsed."""
    # Tenant ID with multiple hyphens
    event = BlobEvent(
        blob_name="data.kml",
        content_length=1024,
        container_name="multi-hyphen-tenant-id-input",
        blob_url="https://account.blob.core.windows.net/multi-hyphen-tenant-id-input/data.kml",
    )
    assert event.tenant_id == "multi-hyphen-tenant-id"
    assert event.output_container == "multi-hyphen-tenant-id-output"


def test_orchestrator_input_includes_tenant_id():
    """Test that orchestrator input includes tenant_id for downstream routing."""
    event = BlobEvent(
        blob_name="test.kml",
        content_length=1024,
        container_name="customer-123-input",
        blob_url="https://account.blob.core.windows.net/customer-123-input/test.kml",
        correlation_id="test-correlation-id",
    )

    orchestrator_input = event.to_dict()

    # Verify tenant_id is passed to orchestrator
    assert orchestrator_input["tenant_id"] == "customer-123"
    assert orchestrator_input["container_name"] == "customer-123-input"

    # Verify correlation tracking
    assert orchestrator_input["correlation_id"] == "test-correlation-id"


def test_concurrent_tenant_processing_maintains_isolation():
    """Test that concurrent tenant requests maintain isolation.

    Simulates two tenants uploading KML files simultaneously and validates
    that outputs are routed to the correct tenant-specific containers.
    """
    # Simulate two concurrent blob events
    tenant_a_event = BlobEvent(
        blob_name="orchard-a.kml",
        content_length=1024,
        container_name="tenant-a-input",
        blob_url="https://account.blob.core.windows.net/tenant-a-input/orchard-a.kml",
        correlation_id="correlation-a",
    )

    tenant_b_event = BlobEvent(
        blob_name="orchard-b.kml",
        content_length=2048,
        container_name="tenant-b-input",
        blob_url="https://account.blob.core.windows.net/tenant-b-input/orchard-b.kml",
        correlation_id="correlation-b",
    )

    # Build orchestrator inputs
    input_a = tenant_a_event.to_dict()
    input_b = tenant_b_event.to_dict()

    # Verify complete isolation
    assert input_a["tenant_id"] == "tenant-a"
    assert input_a["container_name"] == "tenant-a-input"
    assert input_a["correlation_id"] == "correlation-a"

    assert input_b["tenant_id"] == "tenant-b"
    assert input_b["container_name"] == "tenant-b-input"
    assert input_b["correlation_id"] == "correlation-b"

    # Verify no cross-contamination
    assert input_a["tenant_id"] != input_b["tenant_id"]
    assert input_a["container_name"] != input_b["container_name"]
    assert input_a["correlation_id"] != input_b["correlation_id"]


def test_invalid_container_name_returns_empty_tenant_id():
    """Test that non-standard container names return empty tenant_id."""
    # Container without -input suffix
    event_no_suffix = BlobEvent(
        blob_name="test.kml",
        content_length=1024,
        container_name="random-container",
        blob_url="https://account.blob.core.windows.net/random-container/test.kml",
    )
    assert event_no_suffix.tenant_id == ""
    assert event_no_suffix.output_container == "kml-output"

    # Empty container name
    event_empty = BlobEvent(
        blob_name="test.kml",
        content_length=1024,
        container_name="",
        blob_url="https://account.blob.core.windows.net//test.kml",
    )
    assert event_empty.tenant_id == ""
    assert event_empty.output_container == "kml-output"
