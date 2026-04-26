/**
 * app-billing.js
 *
 * Billing status display, tier emulation, and Stripe portal management.
 * Stateful: tracks the latest billing status internally and notifies the
 * shell via onStatusChange so cross-cutting reads (AI block, quota label)
 * stay consistent.
 *
 * Exposes: window.CanopexBilling
 *
 * Contract:
 *   init(deps)           — call once at boot, before initAuth
 *   apply(data)          — apply a billing status payload (DOM + state)
 *   load()               — fetch /api/billing/status and apply
 *   manage()             — open Stripe portal or interest mailto
 *   saveEmulation()      — POST /api/billing/emulation with selected tier
 *   getStatus()          — return latest billing status (or null)
 */
(function () {
  'use strict';

  var _apiFetch = null;
  var _getApiReady = null;
  var _getAccount = null;
  var _login = null;
  var _readCache = null;
  var _writeCache = null;
  var _clearCacheKey = null;
  var _onStatusChange = null;
  var _onLoadError = null;

  var _latestBillingStatus = null;

  var CACHE_TTL_BILLING = 5 * 60 * 1000; // 5 minutes

  function init(deps) {
    _apiFetch = deps.apiFetch;
    _getApiReady = deps.getApiReady;
    _getAccount = deps.getAccount;
    _login = deps.login;
    _readCache = deps.readCache;
    _writeCache = deps.writeCache;
    _clearCacheKey = deps.clearCacheKey;
    _onStatusChange = deps.onStatusChange || function () {};
    _onLoadError = deps.onLoadError || function () {};
  }

  function getStatus() {
    return _latestBillingStatus;
  }

  // ── Pure display helpers ──────────────────────────────────────

  function updateCapabilityFields(caps) {
    var formatRetention = (window.CanopexHelpers && window.CanopexHelpers.formatRetention) || function (d) { return d != null ? String(d) + 'd' : '—'; };
    var concEl = document.getElementById('app-concurrency');
    var aiEl = document.getElementById('app-ai-access');
    var apiEl = document.getElementById('app-api-access');
    var retEl = document.getElementById('app-retention');
    if (concEl) concEl.textContent = caps.concurrency == null ? '—' : String(caps.concurrency);
    if (aiEl) aiEl.textContent = caps.ai_insights ? 'Included' : 'Not included';
    if (apiEl) apiEl.textContent = caps.api_access ? 'Enabled' : 'Not included';
    if (retEl) retEl.textContent = formatRetention(caps.retention_days);
  }

  function renderTierEmulation(data) {
    var card = document.getElementById('app-tier-emulation-card');
    var select = document.getElementById('app-tier-emulation-select');
    var note = document.getElementById('app-tier-emulation-note');

    if (!card || !select || !note) return;

    if (!data.emulation || !data.emulation.available) {
      card.hidden = true;
      return;
    }

    card.hidden = false;
    select.replaceChildren();

    var actualOption = document.createElement('option');
    actualOption.value = 'actual';
    actualOption.textContent = 'Actual billing state';
    select.appendChild(actualOption);

    (data.emulation.tiers || []).forEach(function (tier) {
      var option = document.createElement('option');
      option.value = tier;
      option.textContent = tier.charAt(0).toUpperCase() + tier.slice(1);
      select.appendChild(option);
    });

    select.value = data.emulation.active ? data.emulation.tier : 'actual';
    if (data.emulation.active) {
      note.textContent = 'Currently emulating ' + (data.capabilities.label || data.tier) + ' for your account. Billing remains ' + ((data.subscription && data.subscription.tier) || 'free') + '.';
    } else {
      note.textContent = 'Using the actual billing state for this account.';
    }
  }

  // ── Status application ────────────────────────────────────────

  function apply(data) {
    var tierEl = document.getElementById('app-tier');
    var statusEl = document.getElementById('app-subscription-status');
    var remainingEl = document.getElementById('app-runs-remaining');
    var billingNoteEl = document.getElementById('app-billing-note');
    var billingBtn = document.getElementById('app-manage-billing-btn');
    var accountNote = document.getElementById('app-account-note');
    var caps = data.capabilities || {};

    _latestBillingStatus = data;

    if (tierEl) tierEl.textContent = (caps.label || data.tier || 'Free') + (data.tier_source === 'emulated' ? ' (emulated)' : '');
    if (statusEl) statusEl.textContent = data.status || 'none';
    if (remainingEl) remainingEl.textContent = data.runs_remaining == null ? '—' : String(data.runs_remaining);
    var usedEl = document.getElementById('app-runs-used');
    if (usedEl) usedEl.textContent = data.runs_used == null ? '—' : String(data.runs_used);
    updateCapabilityFields(caps);

    if (data.tier_source === 'emulated') {
      if (billingNoteEl) billingNoteEl.textContent = 'Local tier override active. Real billing is ' + ((data.subscription && data.subscription.tier) || 'free') + '.';
      if (billingBtn) billingBtn.style.display = data.billing_configured ? 'inline-block' : 'none';
      if (accountNote) accountNote.textContent = 'Use the role view and work preference controls to tune this workspace for the job at hand.';
    } else if (data.billing_gated) {
      if (billingNoteEl) billingNoteEl.textContent = 'Billing is not yet available for your account. Contact us to express interest.';
      if (billingBtn) { billingBtn.textContent = 'Express Interest'; billingBtn.style.display = 'inline-block'; }
      if (accountNote) accountNote.textContent = 'You are on the free plan. Express interest to unlock paid tiers when billing becomes available.';
    } else if (data.billing_configured) {
      if (billingNoteEl) billingNoteEl.textContent = 'Stripe customer portal available';
      if (billingBtn) { billingBtn.textContent = 'Billing'; billingBtn.style.display = 'inline-block'; }
      if (accountNote) accountNote.textContent = 'Use the role view and work preference controls to bias the workspace toward investigation, monitoring, or reporting.';
    } else {
      if (billingNoteEl) billingNoteEl.textContent = 'Billing is not configured in this environment';
      if (billingBtn) billingBtn.style.display = 'none';
      if (accountNote) accountNote.textContent = 'Use the role view and work preference controls to bias the workspace toward investigation, monitoring, or reporting.';
    }

    renderTierEmulation(data);

    // Show EUDR toggle only for paid tiers
    var eudrToggle = document.getElementById('app-eudr-toggle');
    if (eudrToggle) {
      var paidTiers = ['starter', 'pro', 'team', 'enterprise'];
      eudrToggle.hidden = !paidTiers.includes(data.tier);
    }

    // Notify shell for cross-cutting reads (hero summary, AI block, quota labels)
    _onStatusChange(data);
  }

  // ── Async operations ──────────────────────────────────────────

  async function load() {
    var apiReady = _getApiReady ? _getApiReady() : null;
    if (apiReady) await apiReady;
    if (_getAccount && !_getAccount()) return;

    // Render cached billing data instantly while fetching fresh data
    var cached = _readCache && _readCache('billing');
    if (cached) apply(cached);

    try {
      var res = await _apiFetch('/api/billing/status');
      var data = await res.json();
      if (_writeCache) _writeCache('billing', data, CACHE_TTL_BILLING);
      apply(data);
    } catch {
      // Only show error state if we had no cached data to show
      if (!cached) {
        var tierEl = document.getElementById('app-tier');
        var statusEl = document.getElementById('app-subscription-status');
        var remainingEl = document.getElementById('app-runs-remaining');
        var billingNoteEl = document.getElementById('app-billing-note');
        var billingBtn = document.getElementById('app-manage-billing-btn');
        if (tierEl) tierEl.textContent = 'Unknown';
        if (statusEl) statusEl.textContent = 'Unavailable';
        if (remainingEl) remainingEl.textContent = '—';
        if (billingNoteEl) billingNoteEl.textContent = 'Could not load billing state';
        if (billingBtn) billingBtn.style.display = 'none';
        updateCapabilityFields({});
        _onLoadError();
      }
    }
  }

  async function manage() {
    // If billing is gated for this user, redirect to express interest
    if (_latestBillingStatus && _latestBillingStatus.billing_gated) {
      window.location.href = 'mailto:hello@canopex.io';
      return;
    }

    if (_getAccount && !_getAccount()) {
      if (_login) _login();
      return;
    }

    var apiReady = _getApiReady ? _getApiReady() : null;
    if (apiReady) await apiReady;
    try {
      var res = await _apiFetch('/api/billing/portal', { method: 'POST' });
      var data = await res.json();
      if (data.portal_url) window.location.href = data.portal_url;
    } catch (err) {
      alert((err && err.message) || 'Could not open billing portal. Please try again.');
    }
  }

  async function saveEmulation() {
    if (_getAccount && !_getAccount()) {
      if (_login) _login();
      return;
    }

    var button = document.getElementById('app-apply-tier-emulation-btn');
    var select = document.getElementById('app-tier-emulation-select');
    if (!button || !select) return;

    button.disabled = true;
    button.textContent = 'Applying…';
    try {
      var apiReady = _getApiReady ? _getApiReady() : null;
      if (apiReady) await apiReady;
      var res = await _apiFetch('/api/billing/emulation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier: select.value })
      });
      if (_clearCacheKey) _clearCacheKey('billing');
      apply(await res.json());
    } catch (err) {
      alert((err && err.message) || 'Could not update plan emulation. Please try again.');
    } finally {
      button.disabled = false;
      button.textContent = 'Apply';
    }
  }

  window.CanopexBilling = {
    init: init,
    apply: apply,
    load: load,
    manage: manage,
    saveEmulation: saveEmulation,
    getStatus: getStatus,
  };
})();
