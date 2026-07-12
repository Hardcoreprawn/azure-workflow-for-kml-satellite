/* EUDR billing overlay (#613) — fetches org-scoped billing from /api/eudr/billing */
(function () {
  'use strict';

  let eudrBillingData = null;

  function isEudrPage() { return window.location.pathname.startsWith('/eudr/'); }
  if (!isEudrPage()) return;

  function showSubscribeModal() {
    const backdrop = document.getElementById('eudr-subscribe-backdrop');
    if (backdrop) {
      backdrop.hidden = false;
      const firstBtn = backdrop.querySelector('button');
      if (firstBtn) firstBtn.focus();
    }
  }

  function hideSubscribeModal() {
    const backdrop = document.getElementById('eudr-subscribe-backdrop');
    if (backdrop) backdrop.hidden = true;
  }

  async function handleSubscribe() {
    const btn = document.getElementById('eudr-subscribe-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Redirecting…'; }
    try {
      if (!window.CanopexApiClient || typeof window.CanopexApiClient.createClient !== 'function') {
        throw new Error('API client unavailable');
      }
      const client = window.CanopexApiClient.createClient();
      await client.discoverApiBase();
      const res = await client.fetch('/api/eudr/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      const data = await res.json();
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        alert('Could not start checkout. Please try again.');
      }
    } catch (e) {
      console.error('Subscribe error:', e);
      if (e && e.status === 403) {
        alert('Only organisation owners can subscribe.');
      } else {
        alert((e && e.message) || 'Could not connect to billing. Please try again.');
      }
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Subscribe Now'; }
    }
  }

  /* Expose for the app shell to call when entitlement check fails */
  window.showEudrSubscribeModal = showSubscribeModal;
  window.setEudrBillingData = function (data) { eudrBillingData = data; };
  window.eudrBillingData = function () { return eudrBillingData; };

  document.addEventListener('DOMContentLoaded', function () {
    const cancelBtn = document.getElementById('eudr-subscribe-cancel-btn');
    if (cancelBtn) cancelBtn.addEventListener('click', hideSubscribeModal);

    const subBtn = document.getElementById('eudr-subscribe-btn');
    if (subBtn) subBtn.addEventListener('click', handleSubscribe);

    /* Close modal on Escape key or backdrop click */
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') hideSubscribeModal();
    });
    const backdrop = document.getElementById('eudr-subscribe-backdrop');
    if (backdrop) {
      backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) hideSubscribeModal();
      });
    }

    /* Check for ?subscribed=true after Stripe redirect */
    if (window.location.search.indexOf('subscribed=true') !== -1) {
      /* Clean URL after Stripe redirect */
      history.replaceState(null, '', window.location.pathname);
    }
  });
})();
