"""Tests for feature gating (treesight.security.feature_gate)."""

from unittest.mock import patch

from tests.conftest import encode_test_principal


class TestBillingAllowed:
    def test_anonymous_always_gated(self):
        with patch("treesight.security.feature_gate.BILLING_ALLOWED_USERS", frozenset({"u1"})):
            from treesight.security.feature_gate import billing_allowed

            assert billing_allowed("anonymous") is False

    def test_none_user_gated(self):
        with patch("treesight.security.feature_gate.BILLING_ALLOWED_USERS", frozenset({"u1"})):
            from treesight.security.feature_gate import billing_allowed

            assert billing_allowed(None) is False

    def test_empty_allowlist_gates_everyone(self):
        with patch("treesight.security.feature_gate.BILLING_ALLOWED_USERS", frozenset()):
            from treesight.security.feature_gate import billing_allowed

            assert billing_allowed("some-user") is False

    def test_allowed_user_passes(self):
        with patch(
            "treesight.security.feature_gate.BILLING_ALLOWED_USERS",
            frozenset({"admin-123", "friend-456"}),
        ):
            from treesight.security.feature_gate import billing_allowed

            assert billing_allowed("admin-123") is True
            assert billing_allowed("friend-456") is True

    def test_unlisted_user_gated(self):
        with patch(
            "treesight.security.feature_gate.BILLING_ALLOWED_USERS",
            frozenset({"admin-123"}),
        ):
            from treesight.security.feature_gate import billing_allowed

            assert billing_allowed("random-user") is False


class TestGatedPriceLabels:
    def test_labels_cover_all_tiers(self):
        from treesight.security.feature_gate import GATED_PRICE_LABELS

        assert "demo" in GATED_PRICE_LABELS
        assert "free" in GATED_PRICE_LABELS
        assert "starter" in GATED_PRICE_LABELS
        assert "pro" in GATED_PRICE_LABELS
        assert "team" in GATED_PRICE_LABELS
        assert "enterprise" in GATED_PRICE_LABELS

    def test_enterprise_is_poe(self):
        from treesight.security.feature_gate import GATED_PRICE_LABELS

        assert GATED_PRICE_LABELS["enterprise"] == "Price on Enquiry"


class TestBillingStatusGating:
    """Integration test: billing status payload includes gating info."""

    @patch("treesight.storage.client.BlobStorageClient")
    @patch("treesight.security.feature_gate.BILLING_ALLOWED_USERS", frozenset())
    @patch("blueprints.billing.STRIPE_API_KEY", "sk_test_xxx")
    @patch("blueprints.billing.STRIPE_WEBHOOK_SECRET", "whsec_test_xxx")
    @patch("blueprints.billing.STRIPE_PRICE_ID_PRO_GBP", "price_xxx")
    def test_gated_user_sees_gated_flag(self, _blob):
        import json

        import azure.functions as func

        from blueprints.billing import billing_status

        _blob.return_value.download_json.side_effect = FileNotFoundError

        req = func.HttpRequest(
            method="GET",
            url="/api/billing/status",
            headers={
                "Origin": "https://canopex.hrdcrprwn.com",
                "X-MS-CLIENT-PRINCIPAL": encode_test_principal(user_id="gated-user"),
            },
            body=b"",
        )
        resp = billing_status(req)
        data = json.loads(resp.get_body())
        assert data["billing_gated"] is True
        assert "price_labels" in data

    @patch("treesight.storage.client.BlobStorageClient")
    @patch(
        "treesight.security.feature_gate.BILLING_ALLOWED_USERS",
        frozenset({"allowed-user"}),
    )
    @patch("blueprints.billing.STRIPE_API_KEY", "sk_test_xxx")
    @patch("blueprints.billing.STRIPE_WEBHOOK_SECRET", "whsec_test_xxx")
    @patch("blueprints.billing.STRIPE_PRICE_ID_PRO_GBP", "price_xxx")
    def test_allowed_user_sees_ungated(self, _blob):
        import json

        import azure.functions as func

        from blueprints.billing import billing_status

        _blob.return_value.download_json.side_effect = FileNotFoundError

        req = func.HttpRequest(
            method="GET",
            url="/api/billing/status",
            headers={
                "Origin": "https://canopex.hrdcrprwn.com",
                "X-MS-CLIENT-PRINCIPAL": encode_test_principal(user_id="allowed-user"),
            },
            body=b"",
        )
        resp = billing_status(req)
        data = json.loads(resp.get_body())
        assert data["billing_gated"] is False
        assert "price_labels" not in data


class TestCheckoutGating:
    """Checkout endpoint rejects gated users."""

    @patch("treesight.security.feature_gate.BILLING_ALLOWED_USERS", frozenset())
    @patch("blueprints.billing.STRIPE_API_KEY", "sk_test_xxx")
    @patch("blueprints.billing.STRIPE_WEBHOOK_SECRET", "whsec_test_xxx")
    @patch("blueprints.billing.STRIPE_PRICE_ID_PRO_GBP", "price_xxx")
    def test_gated_user_gets_403(self):
        import json

        import azure.functions as func

        from blueprints.billing import billing_checkout

        req = func.HttpRequest(
            method="POST",
            url="/api/billing/checkout",
            headers={
                "Origin": "https://canopex.hrdcrprwn.com",
                "X-MS-CLIENT-PRINCIPAL": encode_test_principal(user_id="gated-user"),
            },
            body=json.dumps({"tier": "pro"}).encode(),
        )
        resp = billing_checkout(req)
        assert resp.status_code == 403
        body = json.loads(resp.get_body())
        assert "not yet available" in body["error"]

    @patch("treesight.storage.client.BlobStorageClient")
    @patch(
        "treesight.security.feature_gate.BILLING_ALLOWED_USERS",
        frozenset({"allowed-user"}),
    )
    @patch("blueprints.billing.STRIPE_API_KEY", "sk_test_xxx")
    @patch("blueprints.billing.STRIPE_WEBHOOK_SECRET", "whsec_test_xxx")
    @patch("blueprints.billing.STRIPE_PRICE_ID_PRO_GBP", "price_xxx")
    def test_allowed_user_can_checkout(self, _blob):
        """Allowed user passes the gate (will fail at Stripe, which is expected)."""
        import json

        import azure.functions as func

        from blueprints.billing import billing_checkout

        req = func.HttpRequest(
            method="POST",
            url="/api/billing/checkout",
            headers={
                "Origin": "https://canopex.hrdcrprwn.com",
                "X-MS-CLIENT-PRINCIPAL": encode_test_principal(user_id="allowed-user"),
            },
            body=json.dumps({"tier": "pro"}).encode(),
        )
        resp = billing_checkout(req)
        # Should get past the gate — will fail at Stripe call (502) not at gate (403)
        assert resp.status_code != 403


class TestPortalGating:
    """Portal endpoint rejects gated users."""

    @patch("treesight.security.feature_gate.BILLING_ALLOWED_USERS", frozenset())
    @patch("blueprints.billing.STRIPE_API_KEY", "sk_test_xxx")
    @patch("blueprints.billing.STRIPE_WEBHOOK_SECRET", "whsec_test_xxx")
    @patch("blueprints.billing.STRIPE_PRICE_ID_PRO_GBP", "price_xxx")
    def test_gated_user_gets_403(self):
        import azure.functions as func

        from blueprints.billing import billing_portal

        req = func.HttpRequest(
            method="POST",
            url="/api/billing/portal",
            headers={
                "Origin": "https://canopex.hrdcrprwn.com",
                "X-MS-CLIENT-PRINCIPAL": encode_test_principal(user_id="gated-user"),
            },
            body=b"",
        )
        resp = billing_portal(req)
        assert resp.status_code == 403


class TestBillingInterest:
    """POST /api/billing/interest stores a contact submission."""

    @patch("treesight.storage.client.BlobStorageClient")
    @patch("treesight.email.send_contact_notification")
    def test_valid_submission_returns_200(self, _email, _blob):
        import json

        import azure.functions as func

        from blueprints.billing import billing_interest

        req = func.HttpRequest(
            method="POST",
            url="/api/billing/interest",
            headers={
                "Origin": "https://canopex.hrdcrprwn.com",
                "X-MS-CLIENT-PRINCIPAL": encode_test_principal(user_id="interested-user"),
                "Content-Type": "application/json",
            },
            body=json.dumps(
                {
                    "email": "test@example.com",
                    "organization": "Acme Corp",
                    "message": "We want pro!",
                }
            ).encode(),
        )
        resp = billing_interest(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["status"] == "received"
        assert "submission_id" in data

        # Verify stored record
        stored = _blob.return_value.upload_json.call_args[0][2]
        assert stored["source"] == "billing_interest"
        assert stored["user_id"] == "interested-user"
        assert stored["email"] == "test@example.com"

    def test_missing_email_returns_400(self):
        import json

        import azure.functions as func

        from blueprints.billing import billing_interest

        req = func.HttpRequest(
            method="POST",
            url="/api/billing/interest",
            headers={
                "Origin": "https://canopex.hrdcrprwn.com",
                "X-MS-CLIENT-PRINCIPAL": encode_test_principal(user_id="interested-user"),
                "Content-Type": "application/json",
            },
            body=json.dumps({"organization": "Acme"}).encode(),
        )
        resp = billing_interest(req)
        assert resp.status_code == 400
