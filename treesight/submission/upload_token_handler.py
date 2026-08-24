"""UploadTokenHandler — domain orchestrator for SAS token minting.

Encapsulates the sequential upload-token workflow so that:
* The blueprint route is reduced to a thin adapter (~20 LOC).
* Each step can be unit-tested in isolation via constructor injection.
* Quota-release rollback semantics are preserved on partial-failure paths.

Dependencies are injected through the constructor so callers can swap in
test doubles without patching at the module level.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from treesight.constants import DEFAULT_INPUT_CONTAINER, MAX_KML_FILE_SIZE_BYTES, SAS_TOKEN_EXPIRY_MINUTES
from treesight.security.redact import redact_user_id as _redact

logger = logging.getLogger(__name__)

class UploadTokenHandler:
    """Orchestrates the upload-token minting pipeline.

    Steps (in order):
    1. Resolve (or auto-create) the user's organisation.
    2. Validate parcel count.
    3. Reserve a run against the org quota.
    4. Write ticket blob and mint the SAS URL.
       On failure → release the reservation.
    5. Persist the submission record.

    Call :meth:`mint` to run all steps and return either a success payload
    dict or an adapter-specific error response.
    """

    def __init__(
        self,
        user_id: str,
        body: dict[str, Any],
        req: Any,
        *,
        active_org: dict[str, Any] | None = None,
        # Injected side-effectful dependencies
        ensure_user_org_fn: Callable[
            [Any, str, dict[str, Any] | None],
            tuple[dict[str, Any] | None, Any | None],
        ],
        reserve_run_or_error_fn: Callable[
            [str, str, int, bool, str, Any],
            Any | None,
        ],
        write_ticket_and_mint_sas_fn: Callable[..., tuple[str | None, Any | None]],
        finalize_run_fn: Callable[..., None],
        persist_submission_record_fn: Callable[[str, dict[str, Any], str], None],
        # Injected pure helpers (allow override in tests)
        requested_parcel_count_fn: Callable[[dict[str, Any]], int],
        detect_file_extension_fn: Callable[[str], tuple[str, str]],
        sanitise_submission_context_fn: Callable[[dict[str, Any]], dict[str, Any]],
        resolve_provider_fn: Callable[[dict[str, Any], dict[str, Any]], str],
        build_run_record_fn: Callable[..., dict[str, Any]],
        error_response_fn: Callable[..., Any],
        cors_headers_fn: Callable[[Any], dict[str, str]],
    ) -> None:
        self.user_id = user_id
        self.body = body
        self.req = req
        self.active_org = active_org
        self.is_eudr: bool = body.get("eudr_mode") is True

        # Injected dependencies
        self._ensure_user_org = ensure_user_org_fn
        self._reserve_run_or_error = reserve_run_or_error_fn
        self._write_ticket_and_mint_sas = write_ticket_and_mint_sas_fn
        self._finalize_run = finalize_run_fn
        self._persist_submission_record = persist_submission_record_fn
        self._requested_parcel_count = requested_parcel_count_fn
        self._detect_file_extension = detect_file_extension_fn
        self._sanitise_submission_context = sanitise_submission_context_fn
        self._resolve_provider = resolve_provider_fn
        self._build_run_record = build_run_record_fn
        self._error_response = error_response_fn
        self._cors_headers = cors_headers_fn

        # State accumulated across steps
        self._org_id: str = ""
        self._submission_id: str = ""
        self._parcel_count: int = 0
        self._blob_name: str = ""
        self._content_type: str = ""
        self._submission_context: dict[str, Any] = {}
        self._effective_provider: str = ""
        self._sas_url: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def mint(self) -> tuple[dict[str, Any], None] | tuple[None, Any]:
        """Run the minting pipeline.

        Returns ``(payload, None)`` on success or ``(None, error_response)``
        on the first failure.
        """
        steps = (
            self._step_resolve_org,
            self._step_validate_parcel_count,
            self._step_reserve_run,
            self._step_prepare_blob,
            self._step_write_ticket_and_mint_sas,
            self._step_persist_record,
        )
        for step in steps:
            err = step()
            if err is not None:
                return None, err
        return self._success_payload(), None

    # ------------------------------------------------------------------
    # Pipeline steps — each returns None on success, adapter error on failure
    # ------------------------------------------------------------------

    def _step_resolve_org(self) -> Any | None:
        user_org, err = self._ensure_user_org(self.req, self.user_id, self.active_org)
        if err is not None:
            return err
        if not user_org:
            logger.error(
                "Org resolution returned no org and no error for user=%s",
                _redact(self.user_id),
            )
            return self._error_response(
                503,
                "Unable to set up your organisation. Please try again or contact support.",
                req=self.req,
            )
        self._org_id = user_org["org_id"]
        self._submission_id = str(uuid.uuid4())
        return None

    def _step_validate_parcel_count(self) -> Any | None:
        self._parcel_count = self._requested_parcel_count(self.body)
        if self._parcel_count <= 0:
            return self._error_response(400, "parcel_count must be a positive integer", req=self.req)
        return None

    def _step_reserve_run(self) -> Any | None:
        return self._reserve_run_or_error(
            self._org_id,
            self.user_id,
            self._parcel_count,
            self.is_eudr,
            self._submission_id,
            self.req,
        )

    def _step_prepare_blob(self) -> Any | None:
        ext, content_type = self._detect_file_extension(self.body.get("filename", ""))
        self._content_type = content_type
        self._blob_name = f"analysis/{self._submission_id}{ext}"
        self._submission_context = self._sanitise_submission_context(self.body.get("submission_context") or {})
        self._effective_provider = self._resolve_provider(self.body, self._submission_context)
        return None

    def _step_write_ticket_and_mint_sas(self) -> Any | None:
        sas_url, storage_err = self._write_ticket_and_mint_sas(
            self.body,
            self.user_id,
            self._submission_id,
            self._blob_name,
            self._submission_context,
            self.req,
            org_id=self._org_id,
            content_type=self._content_type,
        )
        if storage_err is not None or not sas_url:
            error = storage_err or self._error_response(
                502, "Storage service temporarily unavailable", req=self.req
            )
            try:
                self._finalize_run(org_id=self._org_id, instance_id=self._submission_id, status="failed")
            except Exception:
                logger.exception(
                    "Failed to refund reservation after storage error org=%s instance=%s",
                    self._org_id,
                    self._submission_id,
                )
            return error
        self._sas_url = sas_url
        return None

    def _step_persist_record(self) -> Any | None:
        record = self._build_run_record(
            submission_id=self._submission_id,
            user_id=self.user_id,
            blob_name=self._blob_name,
            effective_provider=self._effective_provider,
            submission_context=self._submission_context,
            is_eudr=self.is_eudr,
        )
        self._persist_submission_record(self._submission_id, record, self.user_id)
        logger.info(
            "Upload URL minted submission_id=%s blob=%s",
            self._submission_id,
            self._blob_name,
        )
        return None

    # ------------------------------------------------------------------
    # Response assembly
    # ------------------------------------------------------------------

    def _success_payload(self) -> dict[str, Any]:
        return {
            "submissionId": self._submission_id,
            "sasUrl": self._sas_url,
            "blobName": self._blob_name,
            "container": DEFAULT_INPUT_CONTAINER,
            "contentType": self._content_type,
            "expiresMinutes": SAS_TOKEN_EXPIRY_MINUTES,
            "maxBytes": MAX_KML_FILE_SIZE_BYTES,
        }
