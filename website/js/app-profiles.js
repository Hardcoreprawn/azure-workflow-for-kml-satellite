/**
 * app-profiles.js - App identity and profile contract resolution.
 *
 * Shared modules should consult this profile contract rather than branch
 * directly on route or body attributes.
 */
(function () {
  'use strict';

  var ANALYSIS_PHASE_DETAILS = {
    submit: 'Uploading your KML and reserving a pipeline worker for this run.',
    ingestion: 'Parsing the file, validating AOI geometry, and preparing the analysis package.',
    acquisition: 'Searching NAIP and Sentinel-2 coverage to find the best imagery for each AOI.',
    fulfilment: 'Downloading scenes, clipping to your AOIs, and reprojecting them into the output stack.',
    enrichment: 'Adding NDVI, weather context, and cached artifacts so the workspace has richer outputs ready.',
    complete: 'Analysis complete - scroll down to review satellite imagery, vegetation health, and export options.'
  };

  var EUDR_ANALYSIS_PHASE_DETAILS = {
    submit: 'Uploading KML and reserving pipeline capacity for this compliance run.',
    ingestion: 'Parsing parcels, validating geometry, and preparing the evidence request.',
    acquisition: 'Searching post-2020 Sentinel-2 imagery and polling scene availability for each parcel.',
    fulfilment: 'Downloading scenes, clipping to parcel boundaries, and reprojecting into the evidence stack.',
    enrichment: 'Building NDVI time series, deforestation risk, weather, fire, and land-cover evidence layers.',
    complete: 'Evidence pack complete - scroll down to review per-parcel determination and export compliance records.'
  };

  var DEFAULT_CONTENT_PHASE_COPY = {
    acquisition: {
      imageryNote: 'NAIP and Sentinel-2 discovery is in progress so the run can pick the right source imagery.',
      exportsNote: 'There is nothing to export until imagery is actually acquired.'
    },
    fulfilment: {
      imageryNote: 'The pipeline is producing imagery assets for your analysis.',
      enrichmentNote: 'NDVI and weather context will follow immediately after fulfilment finishes.',
      exportsNote: 'The run is close enough that saved outputs should feel tangible, not hypothetical.'
    },
    enrichment: {
      imageryNote: 'Core imagery is in place and the workspace is adding the last supporting layers.',
      enrichmentNote: 'NDVI, weather, and derived context are being assembled for the run detail experience.',
      exportsNote: 'Saved outputs, exports, and revisit paths will be available shortly.'
    }
  };

  var EUDR_CONTENT_PHASE_COPY = {
    acquisition: {
      imageryNote: 'Sentinel-2 post-2020 imagery discovery is in progress for each parcel.',
      exportsNote: 'Evidence pack exports are unavailable until imagery is acquired.'
    },
    fulfilment: {
      imageryNote: 'The pipeline is clipping scenes to parcel boundaries for the evidence stack.',
      enrichmentNote: 'Deforestation risk, NDVI time series, and land-cover evidence will follow immediately.',
      exportsNote: 'Compliance exports are close - the evidence pack is being assembled.'
    },
    enrichment: {
      imageryNote: 'Sentinel-2 and land-cover layers are in place; final evidence layers being added.',
      enrichmentNote: 'Per-parcel deforestation determination, NDVI, weather, fire, and land-cover evidence are being assembled.',
      exportsNote: 'Audit-grade PDF, GeoJSON, and CSV exports for compliance records will be available shortly.'
    }
  };

  var profiles = {
    default: {
      id: 'default',
      basePath: '/app/',
      historyScope: 'user',
      lockedWorkspace: false,
      defaultRole: 'conservation',
      defaultPreference: 'investigate',
      enableParcelCostEstimate: false,
      requiresEudrBillingGate: false,
      phaseDetails: ANALYSIS_PHASE_DETAILS,
      contentPhaseCopy: DEFAULT_CONTENT_PHASE_COPY,
      preflightDisclaimer: null,
    },
    eudr: {
      id: 'eudr',
      basePath: '/eudr/',
      historyScope: 'org',
      lockedWorkspace: true,
      defaultRole: 'eudr',
      defaultPreference: 'report',
      enableParcelCostEstimate: true,
      requiresEudrBillingGate: true,
      phaseDetails: EUDR_ANALYSIS_PHASE_DETAILS,
      contentPhaseCopy: EUDR_CONTENT_PHASE_COPY,
      preflightDisclaimer: 'This due diligence lens frames evidence for review and audit support. It is not a legal compliance certificate.',
    }
  };

  function resolveActiveProfile() {
    var isEudr = !!(document.body && document.body.hasAttribute('data-eudr-app'));
    if (isEudr) return profiles.eudr;
    return profiles.default;
  }

  function getProfile(id) {
    if (id && profiles[id]) return profiles[id];
    return profiles.default;
  }

  window.CanopexAppProfiles = {
    getProfile: getProfile,
    resolveActiveProfile: resolveActiveProfile,
  };
})();
