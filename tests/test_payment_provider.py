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
