"""Tests for treesight.security.payment_provider — provider abstraction."""

from treesight.security.payment_provider import (
    NullProvider,
    PaymentProvider,
    StripeProvider,
    get_payment_provider,
    set_payment_provider,
)


class TestNullProvider:
    def test_conforms_to_protocol(self):
        assert isinstance(NullProvider(), PaymentProvider)

    def test_report_usage_returns_none(self):
        p = NullProvider()
        result = p.report_usage(
            user_id="u1",
            subscription_item_id="si_1",
            quantity=1,
            idempotency_key="key-1",
        )
        assert result is None

    def test_credit_usage_returns_none(self):
        p = NullProvider()
        result = p.credit_usage(
            user_id="u1",
            subscription_item_id="si_1",
            quantity=1,
            idempotency_key="key-1",
            reason="pipeline_failure",
        )
        assert result is None


class TestStripeProvider:
    def test_conforms_to_protocol(self):
        assert isinstance(StripeProvider("sk_test_xxx"), PaymentProvider)

    def test_get_stripe_sets_api_key(self, monkeypatch):
        provider = StripeProvider("sk_test_xxx")
        fake_stripe = type("FakeStripe", (), {"api_key": ""})()
        monkeypatch.setitem(__import__("sys").modules, "stripe", fake_stripe)

        returned = provider._get_stripe()

        assert returned is fake_stripe
        assert fake_stripe.api_key == "sk_test_xxx"  # pragma: allowlist secret

    def test_report_usage_success(self, monkeypatch):
        provider = StripeProvider("sk_test_xxx")

        class _SubItem:
            @staticmethod
            def create_usage_record(*_args, **_kwargs):
                return type("Record", (), {"id": "ur_123"})()

        fake_stripe = type("FakeStripe", (), {"SubscriptionItem": _SubItem})()
        monkeypatch.setattr(provider, "_get_stripe", lambda: fake_stripe)

        result = provider.report_usage(
            user_id="u1",
            subscription_item_id="si_1",
            quantity=2,
            idempotency_key="k1",
        )
        assert result == "ur_123"

    def test_report_usage_failure(self, monkeypatch):
        provider = StripeProvider("sk_test_xxx")

        class _SubItem:
            @staticmethod
            def create_usage_record(*_args, **_kwargs):
                raise RuntimeError("stripe fail")

        fake_stripe = type("FakeStripe", (), {"SubscriptionItem": _SubItem})()
        monkeypatch.setattr(provider, "_get_stripe", lambda: fake_stripe)

        result = provider.report_usage(
            user_id="u1",
            subscription_item_id="si_1",
            quantity=2,
            idempotency_key="k1",
        )
        assert result is None

    def test_credit_usage_success_and_negative_quantity(self, monkeypatch):
        provider = StripeProvider("sk_test_xxx")
        calls = []

        class _SubItem:
            @staticmethod
            def create_usage_record(*_args, **kwargs):
                calls.append(kwargs)
                return type("Record", (), {"id": "ur_credit"})()

        fake_stripe = type("FakeStripe", (), {"SubscriptionItem": _SubItem})()
        monkeypatch.setattr(provider, "_get_stripe", lambda: fake_stripe)

        result = provider.credit_usage(
            user_id="u1",
            subscription_item_id="si_1",
            quantity=3,
            idempotency_key="k2",
            reason="refund",
        )
        assert result == "ur_credit"
        assert calls[0]["quantity"] == -3

    def test_credit_usage_failure(self, monkeypatch):
        provider = StripeProvider("sk_test_xxx")

        class _SubItem:
            @staticmethod
            def create_usage_record(*_args, **_kwargs):
                raise RuntimeError("stripe fail")

        fake_stripe = type("FakeStripe", (), {"SubscriptionItem": _SubItem})()
        monkeypatch.setattr(provider, "_get_stripe", lambda: fake_stripe)

        result = provider.credit_usage(
            user_id="u1",
            subscription_item_id="si_1",
            quantity=3,
            idempotency_key="k2",
            reason="refund",
        )
        assert result is None


class TestProviderFactory:
    def test_returns_null_without_stripe_key(self, monkeypatch):
        # Reset the singleton
        set_payment_provider(None)
        monkeypatch.setattr("treesight.config.STRIPE_API_KEY", "")
        provider = get_payment_provider()
        assert isinstance(provider, NullProvider)
        # Clean up
        set_payment_provider(None)

    def test_returns_stripe_with_key(self, monkeypatch):
        set_payment_provider(None)
        monkeypatch.setattr("treesight.config.STRIPE_API_KEY", "sk_test_xxx")
        provider = get_payment_provider()
        assert isinstance(provider, StripeProvider)
        set_payment_provider(None)

    def test_set_payment_provider_overrides(self):
        custom = NullProvider()
        set_payment_provider(custom)
        assert get_payment_provider() is custom
        set_payment_provider(None)
