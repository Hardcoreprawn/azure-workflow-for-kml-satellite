/**
 * app-eudr.js
 *
 * EUDR-specific helpers: pure cost estimate + EUDR usage dashboard loader.
 *
 * Exposes: window.CanopexEudr
 *
 * Contract:
 *   init(deps)                    — wire apiFetch / getApiReady / getAccount
 *   computeCostEstimate(n, prof)  → string label for the UI
 *   loadUsage()                   → Promise<void>  — fetch + render /api/eudr/usage
 */
(function () {
  'use strict';

  var _apiFetch = null;
  var _getApiReady = null;
  var _getAccount = null;
  var _billingSnapshot = null;

  function init(deps) {
    _apiFetch    = deps.apiFetch    || _apiFetch;
    _getApiReady = deps.getApiReady || _getApiReady;
    _getAccount  = deps.getAccount  || _getAccount;
    // Keep backward compatibility for existing consumers (e.g. cost estimate).
    window.eudrBillingData = function () { return _billingSnapshot; };
  }

  function setHeroParcels(periodUsed, included, overage, billing) {
    var labelEl = document.getElementById('eudr-parcels-label');
    var parcelsEl = document.getElementById('eudr-parcels-used');
    var parcelsNoteEl = document.getElementById('eudr-parcels-note');
    if (!parcelsEl || !parcelsNoteEl) return;

    // Free / unsubscribed: show lifetime free assessments, not the monthly billing counter.
    // The monthly counter is always 0 for non-subscribers and the "10 included" quota
    // only applies to Pro — showing "0 / 10" to a free user implies they have no parcels.
    if (billing && !billing.subscribed) {
      var remaining = billing.trial_remaining != null ? billing.trial_remaining : 0;
      if (labelEl) labelEl.textContent = 'Free reports';
      parcelsEl.textContent = remaining + ' left';
      parcelsNoteEl.textContent = remaining > 0
        ? 'Try ' + remaining + ' more EUDR report' + (remaining !== 1 ? 's' : '') + ' free — no card needed'
        : 'Free reports used — subscribe to run more';
      return;
    }

    // Subscribed: show monthly parcel billing usage.
    if (labelEl) labelEl.textContent = 'Parcels this month';
    parcelsEl.textContent = periodUsed + ' / ' + included;
    parcelsNoteEl.textContent = overage > 0
      ? overage + ' overage parcel' + (overage !== 1 ? 's' : '') + ' this billing period'
      : 'EUDR parcels assessed this billing period';
  }

  function setUsageUnavailable() {
    var includedEl = document.getElementById('app-eudr-usage-included');
    var overageEl = document.getElementById('app-eudr-usage-overage');
    var spendEl = document.getElementById('app-eudr-usage-spend');
    var nextTierEl = document.getElementById('app-eudr-usage-next-tier');
    var historyListEl = document.getElementById('app-eudr-usage-history-list');
    var parcelsEl = document.getElementById('eudr-parcels-used');
    var parcelsNoteEl = document.getElementById('eudr-parcels-note');

    if (includedEl) includedEl.textContent = '—';
    if (overageEl) overageEl.textContent = '—';
    if (spendEl) spendEl.textContent = '—';
    if (nextTierEl) nextTierEl.textContent = 'Usage unavailable';
    if (historyListEl) historyListEl.textContent = 'Usage unavailable right now.';
    if (parcelsEl) parcelsEl.textContent = '—';
    if (parcelsNoteEl) parcelsNoteEl.textContent = 'Usage unavailable right now.';
  }

  async function refreshBillingSnapshot() {
    try {
      var billingRes = await _apiFetch('/api/eudr/billing');
      if (!billingRes.ok) return;
      _billingSnapshot = await billingRes.json();
      if (typeof window.setEudrBillingData === 'function') {
        window.setEudrBillingData(_billingSnapshot);
      }
    } catch (_err) {
      // Billing snapshot is best-effort and should not block usage rendering.
    }
  }

  async function loadUsage() {
    if (_getApiReady) await _getApiReady();
    if (!_getAccount || !_getAccount()) return;

    var includedEl     = document.getElementById('app-eudr-usage-included');
    var overageEl      = document.getElementById('app-eudr-usage-overage');
    var spendEl        = document.getElementById('app-eudr-usage-spend');
    var nextTierEl     = document.getElementById('app-eudr-usage-next-tier');
    var historyListEl  = document.getElementById('app-eudr-usage-history-list');
    if (!includedEl) return; // card not present in this build

    try {
      // Billing snapshot must come first — it determines free vs subscribed display.
      await refreshBillingSnapshot();

      // Overlay the generic Plan note with EUDR-specific trial context.
      var planNoteEl = document.getElementById('app-hero-plan-note');
      if (planNoteEl && _billingSnapshot && !_billingSnapshot.subscribed) {
        var trialLeft = _billingSnapshot.trial_remaining != null ? _billingSnapshot.trial_remaining : 0;
        planNoteEl.textContent = trialLeft > 0
          ? trialLeft + ' free report' + (trialLeft !== 1 ? 's' : '') + ' left — no card needed'
          : 'Free reports used — subscribe to run more.';
      }

      var res = await _apiFetch('/api/eudr/usage');
      if (!res.ok) {
        setUsageUnavailable();
        return;
      }
      var data = await res.json();
      var cur = data.current || {};

      var periodUsed = cur.periodParcelsUsed || 0;
      var included   = cur.includedParcels   || 0;
      var overage = cur.overageParcels || 0;
      if (includedEl) includedEl.textContent = periodUsed + ' / ' + included;
      if (overageEl)  overageEl.textContent  = overage + ' parcels';
      if (spendEl) {
        var spend = cur.estimatedSpendGbp;
        spendEl.textContent = (spend != null) ? ('£' + spend.toFixed(2)) : '—';
      }
      if (nextTierEl) {
        if (cur.nextTierThreshold) {
          var msg = cur.parcelsToNextTier + ' until next tier this billing period (£' + cur.nextTierRateGbp + '/parcel)';
          nextTierEl.textContent = msg;
          if (cur.within20PercentOfNextTier) nextTierEl.style.fontWeight = '600';
        } else {
          nextTierEl.textContent = 'Maximum tier reached';
        }
      }

      setHeroParcels(periodUsed, included, overage, _billingSnapshot);

      if (historyListEl && data.history && data.history.length) {
        var html = '<div class="app-usage-history-list">';
        data.history.forEach(function(m) {
          html += '<div class="app-usage-row">' +
            '<strong>' + (m.month || '') + '</strong>' +
            '<span>' + (m.runs || 0) + ' runs</span>' +
            '<span>' + (m.parcels || 0) + ' parcels</span>' +
            (m.overageRuns ? '<span class="app-warning-text">' + m.overageRuns + ' overage</span>' : '') +
            '</div>';
        });
        html += '</div>';
        historyListEl.innerHTML = html;
      } else if (historyListEl) {
        historyListEl.textContent = 'No usage history yet.';
      }
    } catch (e) {
      console.warn('EUDR usage load error:', e);
      setUsageUnavailable();
    }
  }

  /**
   * Compute a human-readable cost/quota label for a pending EUDR submission.
   *
   * Returns '—' when:
   *   - the active profile does not enable parcel cost estimates
   *   - billing data is not yet loaded
   *
   * @param {number} parcelCount - number of parcels the user intends to submit
   * @param {object} profile - active app profile (from CanopexAppProfiles.resolveActiveProfile())
   * @returns {string}
   */
  function computeCostEstimate(parcelCount, profile) {
    if (!profile || !profile.enableParcelCostEstimate || !parcelCount) return '—';
    var billing = typeof window.eudrBillingData === 'function' ? window.eudrBillingData() : null;
    if (!billing) return '—';

    if (!billing.subscribed) {
      var remaining = billing.trial_remaining != null ? billing.trial_remaining : 0;
      if (remaining > 0) {
        return parcelCount + ' parcel' + (parcelCount !== 1 ? 's' : '') + ' · ' +
          remaining + ' free assessment' + (remaining !== 1 ? 's' : '') + ' left';
      }
      return 'Subscribe to continue';
    }

    // Pro subscriber — estimate only the incremental overage caused by this submission.
    var used = billing.period_parcels_used || 0;
    var included = billing.included_parcels || 10;
    var remainingIncluded = Math.max(included - used, 0);
    var overageParcels = Math.max(parcelCount - remainingIncluded, 0);
    if (overageParcels === 0) {
      return parcelCount + ' parcel' + (parcelCount !== 1 ? 's' : '') + ' included';
    }
    var rate = overageParcels >= 500 ? 1.80 : overageParcels >= 100 ? 2.50 : 3.00;
    var cost = (overageParcels * rate).toFixed(2);
    return overageParcels + ' overage × £' + rate.toFixed(2) + ' = £' + cost;
  }

  window.CanopexEudr = {
    init: init,
    computeCostEstimate: computeCostEstimate,
    loadUsage: loadUsage,
  };
})();
