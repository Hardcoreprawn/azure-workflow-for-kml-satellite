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

  function init(deps) {
    _apiFetch    = deps.apiFetch    || _apiFetch;
    _getApiReady = deps.getApiReady || _getApiReady;
    _getAccount  = deps.getAccount  || _getAccount;
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
      var res = await _apiFetch('/api/eudr/usage');
      if (!res.ok) return;
      var data = await res.json();
      var cur = data.current || {};

      var periodUsed = cur.periodParcelsUsed || 0;
      var included   = cur.includedParcels   || 0;
      if (includedEl) includedEl.textContent = periodUsed + ' / ' + included;
      if (overageEl)  overageEl.textContent  = (cur.overageParcels || 0) + ' parcels';
      if (spendEl) {
        var spend = cur.estimatedSpendGbp;
        spendEl.textContent = (spend != null) ? ('£' + spend.toFixed(2)) : '—';
      }
      if (nextTierEl) {
        if (cur.nextTierThreshold) {
          var msg = cur.parcelsToNextTier + ' until next tier (£' + cur.nextTierRateGbp + '/parcel)';
          nextTierEl.textContent = msg;
          if (cur.within20PercentOfNextTier) nextTierEl.style.fontWeight = '600';
        } else {
          nextTierEl.textContent = 'Maximum tier reached';
        }
      }

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
