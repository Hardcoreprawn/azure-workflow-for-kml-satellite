/**
 * app-evidence-display.js
 *
 * Evidence surface coordinator: state, loading, and public API.
 */
(function () {
  'use strict';

  var _apiFetch = null;
  var _getApiReady = null;
  var _getWorkspaceRole = null;
  var _getLatestBillingStatus = null;

  var state = {
    map: null,
    mapLayers: [],
    frameIndex: 0,
    layerMode: 'rgb',
    playInterval: null,
    manifest: null,
    analysis: null,
    instanceId: null,
    mapExpanded: false,
    aoiPolygons: [],
    selectedAoi: -1,
    compareMode: false,
    compareMaps: null,
    currentOverrideParcelKey: null,
    currentOverrideAoiData: null
  };

  function er() { return window.CanopexEvidenceRender || {}; }
  function ep() { return window.CanopexEvidencePanels || {}; }
  function em() { return window.CanopexEvidenceMap || {}; }
  function mapOps() { return window.CanopexEvidenceDisplayMap || {}; }
  function selectionOps() { return window.CanopexEvidenceDisplaySelection || {}; }
  function aiOps() { return window.CanopexEvidenceDisplayAi || {}; }

  function init(deps) {
    _apiFetch = deps.apiFetch;
    _getApiReady = deps.getApiReady;
    _getWorkspaceRole = deps.getWorkspaceRole;
    _getLatestBillingStatus = deps.getLatestBillingStatus;
  }

  function context() {
    return {
      state: state,
      apiFetch: _apiFetch,
      getApiReady: _getApiReady,
      getWorkspaceRole: _getWorkspaceRole,
      getLatestBillingStatus: _getLatestBillingStatus,
      er: er,
      ep: ep,
      em: em,
      selectAoi: selectAoi,
      showEvidenceFrame: showEvidenceFrame
    };
  }

  function expandEvidenceMap() {
    var mapEl = document.getElementById('app-evidence-map');
    var backdrop = document.getElementById('app-map-expanded-backdrop');
    var body = document.getElementById('app-map-expanded-body');
    if (!mapEl || !backdrop || !body || state.mapExpanded) return;

    body.appendChild(mapEl);
    backdrop.hidden = false;
    state.mapExpanded = true;

    syncExpandedControls();

    setTimeout(function () { if (state.map) state.map.invalidateSize(); }, 100);
    document.addEventListener('keydown', _expandedEscHandler);
  }

  function collapseEvidenceMap() {
    var mapEl = document.getElementById('app-evidence-map');
    var backdrop = document.getElementById('app-map-expanded-backdrop');
    var wrap = document.getElementById('app-evidence-map-wrap');
    if (!mapEl || !backdrop || !wrap || !state.mapExpanded) return;

    wrap.insertBefore(mapEl, wrap.firstChild);
    backdrop.hidden = true;
    state.mapExpanded = false;

    setTimeout(function () { if (state.map) state.map.invalidateSize(); }, 100);
    document.removeEventListener('keydown', _expandedEscHandler);
  }

  function _expandedEscHandler(e) {
    if (e.key === 'Escape') collapseEvidenceMap();
  }

  function syncExpandedControls() {
    var ops = mapOps();
    if (typeof ops.syncExpandedControls === 'function') {
      ops.syncExpandedControls(context());
    }
  }

  function setEvidenceLayerMode(mode) {
    var ops = mapOps();
    if (typeof ops.setLayerMode === 'function') {
      ops.setLayerMode(mode, context());
    }
  }

  function showEvidenceSurface(visible) {
    var surface = document.getElementById('app-evidence-surface');
    var phaseStatus = document.getElementById('app-content-phase-status');
    if (surface) surface.hidden = !visible;
    if (phaseStatus) phaseStatus.hidden = visible;
  }

  async function loadRunEvidence(instanceId) {
    if (state.instanceId === instanceId && state.manifest) return;
    state.instanceId = instanceId;
    state.manifest = null;
    state.analysis = null;
    showEvidenceSurface(true);
    clearEvidencePanels();

    var shortId = instanceId.slice(0, 8);
    var footerEl = document.getElementById('app-content-footer');
    if (footerEl) footerEl.textContent = 'Loading evidence for run ' + shortId + '…';

    try {
      await (_getApiReady ? _getApiReady() : Promise.resolve());
      var manifestRes = await _apiFetch('/api/timelapse-data/' + encodeURIComponent(instanceId));
      var manifest = await manifestRes.json();
      if (state.instanceId !== instanceId) return;
      state.manifest = manifest;
    } catch (err) {
      if (err && err.status === 404 && !arguments[1]) {
        await new Promise(function (r) { setTimeout(r, 3000); });
        if (state.instanceId !== instanceId) return;
        return loadRunEvidence(instanceId, true);
      }
      if (state.instanceId !== instanceId) return;
      if (footerEl) footerEl.textContent = 'Could not load enrichment data: ' + ((err && err.message) || 'unknown error');
      return;
    }

    var _er = er();
    if (typeof _er.renderEvidenceNdvi === 'function') _er.renderEvidenceNdvi(state.manifest);
    if (typeof _er.renderEvidenceWeather === 'function') _er.renderEvidenceWeather(state.manifest);
    if (typeof _er.renderEvidenceChangeDetection === 'function') _er.renderEvidenceChangeDetection(state.manifest);
    if (typeof _er.renderResourceUsage === 'function') _er.renderResourceUsage(state.manifest);
    initEvidenceMap(state.manifest);
    initCompareView(state.manifest);

    var runRefEl = document.getElementById('app-evidence-run-ref');
    if (runRefEl) {
      runRefEl.textContent = 'Run ' + shortId;
      runRefEl.title = instanceId;
      runRefEl.hidden = false;
    }

    state.selectedAoi = -1;
    populateAoiSelector(state.manifest.per_aoi_enrichment);
    loadSavedAnalysis(instanceId);

    var eudrBlock = document.getElementById('app-evidence-eudr-block');
    if (eudrBlock) eudrBlock.hidden = (_getWorkspaceRole ? _getWorkspaceRole() : '') !== 'eudr';

    var aiBlock = document.getElementById('app-evidence-ai-block');
    if (aiBlock) {
      var billing = _getLatestBillingStatus ? _getLatestBillingStatus() : null;
      aiBlock.hidden = !(billing && billing.capabilities && billing.capabilities.ai_insights);
    }

    if (footerEl) {
      footerEl.textContent = 'Evidence loaded for run ' + instanceId.slice(0, 8) + '.';
    }
  }

  function initCompareView(manifest) {
    var ops = selectionOps();
    if (typeof ops.initCompareView === 'function') {
      ops.initCompareView(manifest);
    }
  }

  function toggleCompareView() {
    var ops = selectionOps();
    if (typeof ops.toggleCompareView === 'function') {
      ops.toggleCompareView(context());
    }
  }

  function destroyCompareMaps() {
    var ops = selectionOps();
    if (typeof ops.destroyCompareMaps === 'function') {
      ops.destroyCompareMaps(context());
    }
  }

  function clearEvidencePanels() {
    var ids = [
      'app-evidence-ndvi-grid',
      'app-evidence-weather-grid',
      'app-evidence-change-list',
      'app-evidence-ai-content',
      'app-evidence-eudr-content',
      'app-evidence-resources-grid'
    ];
    ids.forEach(function (id) { var el = document.getElementById(id); if (el) el.textContent = ''; });
    var noteEl = document.getElementById('app-evidence-ndvi-note');
    if (noteEl) noteEl.textContent = '';
    var resourceNote = document.getElementById('app-evidence-resources-note');
    if (resourceNote) resourceNote.textContent = '';
    var resourcesBlock = document.getElementById('app-evidence-resources-block');
    if (resourcesBlock) resourcesBlock.hidden = true;
    var runRefEl = document.getElementById('app-evidence-run-ref');
    if (runRefEl) { runRefEl.textContent = ''; runRefEl.title = ''; runRefEl.hidden = true; }
    var canvases = ['app-evidence-ndvi-canvas', 'app-evidence-weather-canvas'];
    canvases.forEach(function (id) {
      var c = document.getElementById(id);
      if (c) { var ctx = c.getContext('2d'); ctx.clearRect(0, 0, c.width, c.height); }
    });
    stopEvidencePlay();
    state.aoiPolygons = [];
    state.selectedAoi = -1;
    var _er = er();
    if (typeof _er.clearAoiDetail === 'function') _er.clearAoiDetail();
    var aoiBlock = document.getElementById('app-evidence-aoi-block');
    if (aoiBlock) aoiBlock.hidden = true;
    destroyCompareMaps();
    state.compareMode = false;
    var compareWrap = document.getElementById('app-evidence-compare-wrap');
    var mainWrap = document.getElementById('app-evidence-map-wrap');
    var compareBtn = document.getElementById('app-map-btn-compare');
    if (compareWrap) compareWrap.hidden = true;
    if (mainWrap) mainWrap.hidden = false;
    if (compareBtn) { compareBtn.hidden = true; compareBtn.classList.remove('active'); }
  }

  function initEvidenceMap(manifest) {
    var ops = mapOps();
    if (typeof ops.initEvidenceMap === 'function') {
      ops.initEvidenceMap(manifest, context());
    }
  }

  function populateAoiSelector(perAoi) {
    var ops = selectionOps();
    if (typeof ops.populateAoiSelector === 'function') {
      ops.populateAoiSelector(perAoi, context());
    }
  }

  function selectAoi(idx) {
    var ops = selectionOps();
    if (typeof ops.selectAoi === 'function') {
      ops.selectAoi(idx, context());
    }
  }

  function showEvidenceFrame(idx) {
    var ops = mapOps();
    if (typeof ops.showEvidenceFrame === 'function') {
      ops.showEvidenceFrame(idx, context());
    }
  }

  function toggleEvidencePlay() {
    var ops = mapOps();
    if (typeof ops.toggleEvidencePlay === 'function') {
      ops.toggleEvidencePlay(context());
    }
  }

  function stopEvidencePlay() {
    var ops = mapOps();
    if (typeof ops.stopEvidencePlay === 'function') {
      ops.stopEvidencePlay(context());
    }
  }

  function loadSavedAnalysis(instanceId) {
    var ops = aiOps();
    if (typeof ops.loadSavedAnalysis === 'function') {
      return ops.loadSavedAnalysis(instanceId, context());
    }
    return Promise.resolve();
  }

  function requestAiAnalysis() {
    var ops = aiOps();
    if (typeof ops.requestAiAnalysis === 'function') {
      return ops.requestAiAnalysis(context());
    }
    return Promise.resolve();
  }

  function requestEudrAssessment() {
    var ops = aiOps();
    if (typeof ops.requestEudrAssessment === 'function') {
      return ops.requestEudrAssessment(context());
    }
    return Promise.resolve();
  }

  window.CanopexEvidenceDisplay = {
    init: init,
    load: loadRunEvidence,
    clear: clearEvidencePanels,
    showSurface: showEvidenceSurface,
    expand: expandEvidenceMap,
    collapse: collapseEvidenceMap,
    showFrame: showEvidenceFrame,
    setLayerMode: setEvidenceLayerMode,
    toggleCompare: toggleCompareView,
    togglePlay: toggleEvidencePlay,
    stopPlay: stopEvidencePlay,
    requestAi: requestAiAnalysis,
    requestEudr: requestEudrAssessment,
    getManifest: function () { return state.manifest; },
    getInstanceId: function () { return state.instanceId; },
    getOverrideContext: function () {
      return { parcelKey: state.currentOverrideParcelKey, aoiData: state.currentOverrideAoiData };
    },
  };
})();
