/**
 * app-eudr.js
 *
 * EUDR-specific pure helpers. No DOM, no fetch, no Leaflet.
 *
 * Exposes: window.CanopexEudr
 *
 * Contract:
 *   computeCostEstimate(parcelCount, profile) → string label for the UI
 */
(function () {
  'use strict';

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
    computeCostEstimate: computeCostEstimate,
  };
})();
