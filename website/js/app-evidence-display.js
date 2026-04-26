/**
 * app-evidence-display.js
 *
 * Evidence surface: Leaflet map, frame/layer/compare controls, expand/collapse,
 * per-AOI selection, AI analysis, EUDR assessment, and the clearEvidencePanels
 * reset helper. Extracted from app-shell.js.
 *
 * Depends (window globals):
 *   L                       — Leaflet
 *   CanopexEvidenceRender   — pcTileUrl, pcNdviTileUrl, renderEvidenceNdvi,
 *                             renderEvidenceWeather, renderEvidenceChangeDetection,
 *                             renderEvidenceAnalysis, renderAoiDetail, clearAoiDetail,
 *                             renderResourceUsage
 *   CanopexHelpers          — createCallout
 *   CanopexEvidenceMap      — pickDefaultLayer, pickInitialFrameIndex,
 *                             buildNdviTimeseries, latLon
 *   CanopexEvidencePanels   — parcelKeyForIndex, renderParcelNotes, renderParcelOverride
 *
 * Exposes window.CanopexEvidenceDisplay = {
 *   init, load, clear, showSurface, expand, collapse,
 *   showFrame, setLayerMode, toggleCompare, togglePlay, stopPlay,
 *   requestAi, requestEudr, getManifest, getInstanceId, getOverrideContext
 * }
 */
(function () {
  'use strict';

  // ── Injected deps ────────────────────────────────────────────
  var _apiFetch = null;
  var _getApiReady = null;
  var _getWorkspaceRole = null;
  var _getLatestBillingStatus = null;

  // ── Evidence state ───────────────────────────────────────────
  var evidenceMap = null;
  var evidenceMapLayers = [];
  var evidenceFrameIndex = 0;
  var evidenceLayerMode = 'rgb'; // 'rgb' | 'ndvi'
  var evidencePlayInterval = null;
  var evidenceManifest = null;
  var evidenceAnalysis = null;
  var evidenceInstanceId = null;
  var evidenceMapExpanded = false;
  var evidenceAoiPolygons = []; // Leaflet polygon layers for per-AOI click
  var evidenceSelectedAoi = -1; // -1 = aggregate, >=0 = per-AOI index
  var evidenceCompareMode = false; // #671 before/after compare state
  var evidenceCompareMaps = null; // { before: L.Map, after: L.Map } | null

  // Parcel notes + override context — kept here because they depend on
  // which AOI is selected; the panels module mutates them through callbacks.
  var _currentOverrideParcelKey = null;
  var _currentOverrideAoiData = null;

  // ── Dep accessors ────────────────────────────────────────────

  function er() { return window.CanopexEvidenceRender || {}; }
  function ep() { return window.CanopexEvidencePanels || {}; }
  function em() { return window.CanopexEvidenceMap || {}; }

  function init(deps) {
    _apiFetch = deps.apiFetch;
    _getApiReady = deps.getApiReady;
    _getWorkspaceRole = deps.getWorkspaceRole;
    _getLatestBillingStatus = deps.getLatestBillingStatus;
  }

  // ── Expand/collapse ──────────────────────────────────────────

  function expandEvidenceMap() {
    var mapEl = document.getElementById('app-evidence-map');
    var backdrop = document.getElementById('app-map-expanded-backdrop');
    var body = document.getElementById('app-map-expanded-body');
    if (!mapEl || !backdrop || !body || evidenceMapExpanded) return;

    body.appendChild(mapEl);
    backdrop.hidden = false;
    evidenceMapExpanded = true;

    syncExpandedControls();

    setTimeout(function () { if (evidenceMap) evidenceMap.invalidateSize(); }, 100);
    document.addEventListener('keydown', _expandedEscHandler);
  }

  function collapseEvidenceMap() {
    var mapEl = document.getElementById('app-evidence-map');
    var backdrop = document.getElementById('app-map-expanded-backdrop');
    var wrap = document.getElementById('app-evidence-map-wrap');
    if (!mapEl || !backdrop || !wrap || !evidenceMapExpanded) return;

    wrap.insertBefore(mapEl, wrap.firstChild);
    backdrop.hidden = true;
    evidenceMapExpanded = false;

    setTimeout(function () { if (evidenceMap) evidenceMap.invalidateSize(); }, 100);
    document.removeEventListener('keydown', _expandedEscHandler);
  }

  function _expandedEscHandler(e) {
    if (e.key === 'Escape') collapseEvidenceMap();
  }

  function syncExpandedControls() {
    var slider = document.getElementById('app-map-expanded-slider');
    var counter = document.getElementById('app-map-expanded-counter');
    var label = document.getElementById('app-map-expanded-label');
    var rgbBtn = document.getElementById('app-map-expanded-btn-rgb');
    var ndviBtn = document.getElementById('app-map-expanded-btn-ndvi');

    if (slider && evidenceMapLayers.length) {
      slider.max = evidenceMapLayers.length - 1;
      slider.value = evidenceFrameIndex;
    }
    if (counter) counter.textContent = (evidenceFrameIndex + 1) + '/' + evidenceMapLayers.length;
    if (label && evidenceMapLayers[evidenceFrameIndex]) {
      var expandedFrame = evidenceMapLayers[evidenceFrameIndex];
      label.textContent = expandedFrame.label + ' — ' + expandedFrame.info +
        (expandedFrame.rgbDisplayWarning ? ' — ' + expandedFrame.rgbDisplayWarning : '');
    }
    syncEvidenceLayerButtons(evidenceMapLayers[evidenceFrameIndex]);
    if (rgbBtn) rgbBtn.classList.toggle('active', evidenceLayerMode === 'rgb');
    if (ndviBtn) ndviBtn.classList.toggle('active', evidenceLayerMode === 'ndvi');
  }

  // ── Layer helpers ────────────────────────────────────────────

  function pickEvidenceDefaultLayer(frame) {
    if (typeof em().pickDefaultLayer === 'function') {
      return em().pickDefaultLayer(frame);
    }
    if (!frame) return 'rgb';
    if (frame.preferredLayer === 'ndvi' || frame.preferred_layer === 'ndvi') return 'ndvi';
    return 'rgb';
  }

  function pickInitialEvidenceFrameIndex(frames) {
    if (typeof em().pickInitialFrameIndex === 'function') {
      return em().pickInitialFrameIndex(frames);
    }
    if (!Array.isArray(frames) || !frames.length) return 0;
    return 0;
  }

  function syncEvidenceLayerButtons(frame) {
    var rgbBtn = document.getElementById('app-map-btn-rgb');
    var ndviBtn = document.getElementById('app-map-btn-ndvi');
    var expandedRgbBtn = document.getElementById('app-map-expanded-btn-rgb');
    var expandedNdviBtn = document.getElementById('app-map-expanded-btn-ndvi');
    var rgbDisabled = !!(frame && frame.rgbDisplaySuitable === false);
    var warning = frame && frame.rgbDisplayWarning ? frame.rgbDisplayWarning : '';

    [rgbBtn, expandedRgbBtn].forEach(function (btn) {
      if (!btn) return;
      btn.disabled = rgbDisabled;
      btn.title = rgbDisabled ? warning : '';
      btn.classList.toggle('is-disabled', rgbDisabled);
    });
    [ndviBtn, expandedNdviBtn].forEach(function (btn) {
      if (!btn) return;
      btn.disabled = false;
      btn.title = '';
      btn.classList.remove('is-disabled');
    });
  }

  // #646 — update layer button aria-labels and titles with per-frame
  // collection and resolution so the picker is self-documenting.
  function updateLayerButtonLabels(frame) {
    var btnRgb = document.getElementById('app-map-btn-rgb');
    var btnNdvi = document.getElementById('app-map-btn-ndvi');
    var expRgb = document.getElementById('app-map-expanded-btn-rgb');
    var expNdvi = document.getElementById('app-map-expanded-btn-ndvi');
    if (!frame) return;
    var info = frame.collectionLabel
      ? (frame.collectionLabel + (frame.resLabel || ''))
      : '';
    [btnRgb, expRgb].forEach(function (btn) {
      if (!btn) return;
      var base = info ? 'True-colour RGB — ' + info : 'True-colour RGB';
      if (!btn.disabled) btn.title = base;
      btn.setAttribute('aria-label', info ? 'RGB (' + info + ')' : 'RGB');
    });
    [btnNdvi, expNdvi].forEach(function (btn) {
      if (!btn) return;
      btn.title = info ? 'Vegetation index (NDVI) — ' + info : 'Vegetation index (NDVI)';
      btn.setAttribute('aria-label', info ? 'NDVI (' + info + ')' : 'NDVI');
    });
  }

  // Sync the active/inactive classes on all RGB and NDVI buttons (both inline
  // panel and expanded modal) to match the current evidenceLayerMode.
  function syncLayerModeButtons() {
    var isRgb = evidenceLayerMode === 'rgb';
    ['app-map-btn-rgb', 'app-map-expanded-btn-rgb'].forEach(function (id) {
      var btn = document.getElementById(id);
      if (btn) btn.classList.toggle('active', isRgb);
    });
    ['app-map-btn-ndvi', 'app-map-expanded-btn-ndvi'].forEach(function (id) {
      var btn = document.getElementById(id);
      if (btn) btn.classList.toggle('active', !isRgb);
    });
  }

  function setEvidenceLayerMode(mode) {
    if (mode !== 'rgb' && mode !== 'ndvi') return;
    evidenceLayerMode = mode;
    syncLayerModeButtons();
    showEvidenceFrame(evidenceFrameIndex);
  }

  // ── Surface visibility ───────────────────────────────────────

  function showEvidenceSurface(visible) {
    var surface = document.getElementById('app-evidence-surface');
    var phaseStatus = document.getElementById('app-content-phase-status');
    if (surface) surface.hidden = !visible;
    if (phaseStatus) phaseStatus.hidden = visible;
  }

  // ── Main evidence load ───────────────────────────────────────

  async function loadRunEvidence(instanceId) {
    if (evidenceInstanceId === instanceId && evidenceManifest) return;
    evidenceInstanceId = instanceId;
    evidenceManifest = null;
    evidenceAnalysis = null;
    showEvidenceSurface(true);
    clearEvidencePanels();

    var shortId = instanceId.slice(0, 8);
    var footerEl = document.getElementById('app-content-footer');
    if (footerEl) footerEl.textContent = 'Loading evidence for run ' + shortId + '…';

    try {
      await (_getApiReady ? _getApiReady() : Promise.resolve());
      var manifestRes = await _apiFetch('/api/timelapse-data/' + encodeURIComponent(instanceId));
      var manifest = await manifestRes.json();
      // Guard: user may have switched runs while we were fetching.
      if (evidenceInstanceId !== instanceId) return;
      evidenceManifest = manifest;
    } catch (err) {
      // Retry once after a short delay — the orchestrator may have just
      // completed and storage propagation can lag a few seconds.
      if (err && err.status === 404 && !arguments[1]) {
        await new Promise(function (r) { setTimeout(r, 3000); });
        if (evidenceInstanceId !== instanceId) return;
        return loadRunEvidence(instanceId, true);
      }
      if (evidenceInstanceId !== instanceId) return;
      if (footerEl) footerEl.textContent = 'Could not load enrichment data: ' + ((err && err.message) || 'unknown error');
      return;
    }

    var _er = er();
    if (typeof _er.renderEvidenceNdvi === 'function') _er.renderEvidenceNdvi(evidenceManifest);
    if (typeof _er.renderEvidenceWeather === 'function') _er.renderEvidenceWeather(evidenceManifest);
    if (typeof _er.renderEvidenceChangeDetection === 'function') _er.renderEvidenceChangeDetection(evidenceManifest);
    if (typeof _er.renderResourceUsage === 'function') _er.renderResourceUsage(evidenceManifest);
    initEvidenceMap(evidenceManifest);
    initCompareView(evidenceManifest); // #671 before/after compare button

    // Show persistent run reference in the evidence header.
    var runRefEl = document.getElementById('app-evidence-run-ref');
    if (runRefEl) {
      runRefEl.textContent = 'Run ' + shortId;
      runRefEl.title = instanceId;
      runRefEl.hidden = false;
    }

    // Per-AOI selector (multi-polygon runs)
    evidenceSelectedAoi = -1;
    populateAoiSelector(evidenceManifest.per_aoi_enrichment);

    // Load saved AI analysis (non-blocking)
    loadSavedAnalysis(instanceId);

    // Show EUDR block for eudr role
    var eudrBlock = document.getElementById('app-evidence-eudr-block');
    if (eudrBlock) eudrBlock.hidden = (_getWorkspaceRole ? _getWorkspaceRole() : '') !== 'eudr';

    // Show AI block if tier supports it
    var aiBlock = document.getElementById('app-evidence-ai-block');
    if (aiBlock) {
      var billing = _getLatestBillingStatus ? _getLatestBillingStatus() : null;
      aiBlock.hidden = !(billing && billing.capabilities && billing.capabilities.ai_insights);
    }

    if (footerEl) {
      footerEl.textContent = 'Evidence loaded for run ' + instanceId.slice(0, 8) + '.';
    }
  }

  // ── Compare view (#671) ──────────────────────────────────────

  function initCompareView(manifest) {
    var compareWrap = document.getElementById('app-evidence-compare-wrap');
    var compareBtn = document.getElementById('app-map-btn-compare');
    if (!compareWrap) return;

    var searchIds = manifest.search_ids || [];
    if (searchIds.length < 2) {
      if (compareBtn) compareBtn.hidden = true;
      return;
    }

    if (compareBtn) compareBtn.hidden = false;
  }

  function openCompareView(manifest) {
    var mainWrap = document.getElementById('app-evidence-map-wrap');
    var compareWrap = document.getElementById('app-evidence-compare-wrap');
    var frameControls = document.getElementById('app-evidence-frame-controls');
    var frameLabel = document.getElementById('app-map-frame-label');
    var compareBtn = document.getElementById('app-map-btn-compare');
    if (!mainWrap || !compareWrap) return;

    // Stop playback
    if (evidencePlayInterval) { clearInterval(evidencePlayInterval); evidencePlayInterval = null; }

    mainWrap.hidden = true;
    if (frameControls) frameControls.hidden = true;
    if (frameLabel) frameLabel.textContent = '';
    compareWrap.hidden = false;
    evidenceCompareMode = true;
    if (compareBtn) compareBtn.classList.add('active');

    buildCompareView(manifest);
  }

  function closeCompareView() {
    var mainWrap = document.getElementById('app-evidence-map-wrap');
    var compareWrap = document.getElementById('app-evidence-compare-wrap');
    var compareBtn = document.getElementById('app-map-btn-compare');
    if (!mainWrap || !compareWrap) return;

    destroyCompareMaps();
    compareWrap.hidden = true;
    mainWrap.hidden = false;
    evidenceCompareMode = false;
    if (compareBtn) compareBtn.classList.remove('active');

    var frameControls = document.getElementById('app-evidence-frame-controls');
    if (frameControls && evidenceMapLayers.length) frameControls.hidden = false;
    showEvidenceFrame(evidenceFrameIndex);
  }

  function destroyCompareMaps() {
    if (evidenceCompareMaps) {
      if (evidenceCompareMaps.before) { evidenceCompareMaps.before.remove(); }
      if (evidenceCompareMaps.after) { evidenceCompareMaps.after.remove(); }
      evidenceCompareMaps = null;
    }
    var before = document.getElementById('app-evidence-compare-map-before');
    var after = document.getElementById('app-evidence-compare-map-after');
    if (before) before.textContent = '';
    if (after) after.textContent = '';
  }

  function buildCompareView(manifest) {
    destroyCompareMaps();

    var searchIds = manifest.search_ids || [];
    var framePlan = manifest.frame_plan || [];
    var center = manifest.center || manifest.coords;
    if (!center || !searchIds.length) return;

    var lat = Array.isArray(center) ? center[0] : center.lat || center.latitude;
    var lon = Array.isArray(center) ? center[1] : center.lon || center.longitude;
    if (!lat || !lon) return;

    var firstFrame = framePlan[0] || {};
    var lastFrame = framePlan[framePlan.length - 1] || {};
    var firstSid = searchIds[0];
    var lastSid = searchIds[searchIds.length - 1];

    var firstCollection = firstFrame.display_collection || firstFrame.collection || 'sentinel-2-l2a';
    var lastCollection = lastFrame.display_collection || lastFrame.collection || 'sentinel-2-l2a';
    var firstAsset = firstFrame.asset || (firstCollection.indexOf('naip') >= 0 ? 'image' : 'visual');
    var lastAsset = lastFrame.asset || (lastCollection.indexOf('naip') >= 0 ? 'image' : 'visual');

    var labelBefore = document.getElementById('app-evidence-compare-label-before');
    var labelAfter = document.getElementById('app-evidence-compare-label-after');
    if (labelBefore) labelBefore.textContent = 'Before — ' + (firstFrame.label || 'earliest');
    if (labelAfter) labelAfter.textContent = 'After — ' + (lastFrame.label || 'most recent');

    var mapOptions = { zoomControl: false, attributionControl: false };
    var basemapUrl = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
    var _er = er();
    var _pcTileUrl = typeof _er.pcTileUrl === 'function' ? _er.pcTileUrl : function () { return ''; };

    var beforeEl = document.getElementById('app-evidence-compare-map-before');
    var afterEl = document.getElementById('app-evidence-compare-map-after');
    if (!beforeEl || !afterEl) return;

    var beforeMap = L.map(beforeEl, mapOptions).setView([lat, lon], 13);
    L.tileLayer(basemapUrl, { maxZoom: 18 }).addTo(beforeMap);
    if (firstSid) {
      L.tileLayer(_pcTileUrl(firstSid, firstCollection, firstAsset), { maxZoom: 18 }).addTo(beforeMap);
    }

    var afterMap = L.map(afterEl, mapOptions).setView([lat, lon], 13);
    L.tileLayer(basemapUrl, { maxZoom: 18 }).addTo(afterMap);
    if (lastSid) {
      L.tileLayer(_pcTileUrl(lastSid, lastCollection, lastAsset), { maxZoom: 18 }).addTo(afterMap);
    }

    // Keep the two maps in sync when panning/zooming
    function syncMaps(source, target) {
      source.on('moveend', function () {
        target.setView(source.getCenter(), source.getZoom(), { animate: false });
      });
    }
    syncMaps(beforeMap, afterMap);
    syncMaps(afterMap, beforeMap);

    evidenceCompareMaps = { before: beforeMap, after: afterMap };

    // Fit to AOI bounds if available
    var perAoi = manifest.per_aoi_enrichment || [];
    try {
      var allBounds = L.latLngBounds([]);
      perAoi.forEach(function (aoi) {
        if (!aoi.coords || !aoi.coords.length) return;
        aoi.coords.forEach(function (c) { allBounds.extend([c[1], c[0]]); });
      });
      if (!allBounds.isValid() && manifest.coords && manifest.coords.length) {
        manifest.coords.forEach(function (c) { allBounds.extend([c[1], c[0]]); });
      }
      if (allBounds.isValid()) {
        beforeMap.fitBounds(allBounds.pad(0.1));
        afterMap.fitBounds(allBounds.pad(0.1));
      }
    } catch (e) { /* keep default view */ }

    setTimeout(function () {
      beforeMap.invalidateSize();
      afterMap.invalidateSize();
    }, 150);
  }

  function toggleCompareView() {
    if (evidenceCompareMode) {
      closeCompareView();
    } else if (evidenceManifest) {
      openCompareView(evidenceManifest);
    }
  }

  // ── clearEvidencePanels ──────────────────────────────────────

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
    if (evidencePlayInterval) { clearInterval(evidencePlayInterval); evidencePlayInterval = null; }
    evidenceAoiPolygons = [];
    evidenceSelectedAoi = -1;
    var _er = er();
    if (typeof _er.clearAoiDetail === 'function') _er.clearAoiDetail();
    var aoiBlock = document.getElementById('app-evidence-aoi-block');
    if (aoiBlock) aoiBlock.hidden = true;
    // Reset compare mode so it doesn't persist across runs
    destroyCompareMaps();
    evidenceCompareMode = false;
    var compareWrap = document.getElementById('app-evidence-compare-wrap');
    var mainWrap = document.getElementById('app-evidence-map-wrap');
    var compareBtn = document.getElementById('app-map-btn-compare');
    if (compareWrap) compareWrap.hidden = true;
    if (mainWrap) mainWrap.hidden = false;
    if (compareBtn) { compareBtn.hidden = true; compareBtn.classList.remove('active'); }
  }

  // ── Map viewer ───────────────────────────────────────────────

  function initEvidenceMap(manifest) {
    var container = document.getElementById('app-evidence-map');
    var overlay = document.getElementById('app-evidence-map-overlay');
    var controls = document.getElementById('app-evidence-frame-controls');
    if (!container) return;

    // Clean up old map
    if (evidenceMap) { evidenceMap.remove(); evidenceMap = null; }
    evidenceMapLayers = [];
    evidenceFrameIndex = 0;
    if (evidencePlayInterval) { clearInterval(evidencePlayInterval); evidencePlayInterval = null; }

    var center = manifest.center || manifest.coords;
    if (!center) {
      if (overlay) overlay.textContent = 'No location data available.';
      return;
    }

    var lat = Array.isArray(center) ? center[0] : center.lat || center.latitude;
    var lon = Array.isArray(center) ? center[1] : center.lon || center.longitude;
    if (!lat || !lon) {
      if (overlay) overlay.textContent = 'Invalid coordinates in manifest.';
      return;
    }

    evidenceMap = L.map(container, { zoomControl: true, attributionControl: false }).setView([lat, lon], 13);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 18
    }).addTo(evidenceMap);

    // AOI polygon outlines (coords are [lon, lat] GeoJSON; Leaflet needs [lat, lon])
    evidenceAoiPolygons = [];
    var perAoi = manifest.per_aoi_enrichment || [];
    if (perAoi.length > 1) {
      // Per-AOI mode: draw each AOI polygon as interactive
      try {
        var allBounds = L.latLngBounds([]);
        perAoi.forEach(function (aoi, idx) {
          if (!aoi.coords || !aoi.coords.length) return;
          var ll = aoi.coords.map(function (c) { return [c[1], c[0]]; });
          var poly = L.polygon(ll, {
            color: 'rgba(88,166,255,.7)',
            weight: 2,
            fillOpacity: 0.05
          }).addTo(evidenceMap);
          var tip = document.createElement('span');
          tip.textContent = aoi.name || ('Parcel ' + (idx + 1));
          poly.bindTooltip(tip, { sticky: true });
          poly.on('click', function () { selectAoi(idx); });
          evidenceAoiPolygons.push(poly);
          allBounds.extend(poly.getBounds());
        });
        if (allBounds.isValid()) evidenceMap.fitBounds(allBounds.pad(0.1));
      } catch (e) { /* skip polygon */ }
    } else if (manifest.coords && Array.isArray(manifest.coords)) {
      // Single-AOI fallback: split concatenated ring
      try {
        var rings = [];
        var ringStart = 0;
        for (var ci = ringStart + 3; ci < manifest.coords.length; ci++) {
          if (Math.abs(manifest.coords[ci][0] - manifest.coords[ringStart][0]) < 1e-5 &&
            Math.abs(manifest.coords[ci][1] - manifest.coords[ringStart][1]) < 1e-5) {
            rings.push(manifest.coords.slice(ringStart, ci + 1));
            ringStart = ci + 1;
            ci = ringStart + 2;
          }
        }
        if (ringStart < manifest.coords.length) rings.push(manifest.coords.slice(ringStart));
        if (!rings.length) rings.push(manifest.coords);

        var singleBounds = L.latLngBounds([]);
        rings.forEach(function (ring) {
          var ll = ring.map(function (c) { return [c[1], c[0]]; });
          L.polygon(ll, { color: 'rgba(88,166,255,.7)', weight: 2, fillOpacity: 0.05 }).addTo(evidenceMap);
          singleBounds.extend(L.polygon(ll).getBounds());
        });
        evidenceMap.fitBounds(singleBounds.pad(0.1));
      } catch (e) { /* skip polygon */ }
    }

    if (overlay) overlay.hidden = true;

    // Add PC timelapse frames if search_ids available
    var searchIds = manifest.search_ids || [];
    var ndviSearchIds = manifest.ndvi_search_ids || [];
    var framePlan = manifest.frame_plan || [];

    if (searchIds.length && framePlan.length) {
      buildEvidenceFrames(framePlan, searchIds, ndviSearchIds);
      if (controls) controls.hidden = false;
    } else if (controls) {
      controls.hidden = true;
    }

    // Force resize
    setTimeout(function () { if (evidenceMap) evidenceMap.invalidateSize(); }, 200);
  }

  // ── Per-AOI selection ────────────────────────────────────────

  function populateAoiSelector(perAoi) {
    var block = document.getElementById('app-evidence-aoi-block');
    var list = document.getElementById('app-evidence-aoi-list');
    var resetBtn = document.getElementById('app-evidence-aoi-reset');
    if (!block || !list) return;

    if (!perAoi || perAoi.length < 2) {
      block.hidden = true;
      return;
    }

    block.hidden = false;
    list.textContent = '';

    perAoi.forEach(function (aoi, idx) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'app-evidence-aoi-chip';
      chip.textContent = aoi.name || ('Parcel ' + (idx + 1));
      chip.addEventListener('click', function () { selectAoi(idx); });
      list.appendChild(chip);
    });

    if (resetBtn) {
      resetBtn.addEventListener('click', function () { resetAoiSelection(); });
    }
  }

  function selectAoi(idx) {
    if (!evidenceManifest || !evidenceManifest.per_aoi_enrichment) return;
    var perAoi = evidenceManifest.per_aoi_enrichment;
    if (idx < 0 || idx >= perAoi.length) return;

    evidenceSelectedAoi = idx;
    var aoi = perAoi[idx];

    // Highlight selected polygon, dim others
    evidenceAoiPolygons.forEach(function (poly, i) {
      if (i === idx) {
        poly.setStyle({ color: '#5eecc4', weight: 3, fillOpacity: 0.15 });
      } else {
        poly.setStyle({ color: 'rgba(88,166,255,.3)', weight: 1, fillOpacity: 0.02 });
      }
    });

    // Zoom to selected AOI
    if (evidenceAoiPolygons[idx] && evidenceMap) {
      evidenceMap.fitBounds(evidenceAoiPolygons[idx].getBounds().pad(0.15));
    }

    // Update chip active state
    var chips = document.querySelectorAll('.app-evidence-aoi-chip');
    chips.forEach(function (chip, i) {
      chip.className = 'app-evidence-aoi-chip' + (i === idx ? ' active' : '');
    });

    // Render per-AOI detail and parcel panels
    var _er = er();
    if (typeof _er.renderAoiDetail === 'function') _er.renderAoiDetail(aoi);

    // Store current override context so the override button binding can use it
    _currentOverrideParcelKey = _parcelKeyForIndex(idx);
    _currentOverrideAoiData = aoi;

    var _ep = ep();
    if (typeof _ep.renderParcelNotes === 'function') _ep.renderParcelNotes(_parcelKeyForIndex(idx));
    if (typeof _ep.renderParcelOverride === 'function') _ep.renderParcelOverride(_parcelKeyForIndex(idx), aoi);
  }

  function resetAoiSelection() {
    evidenceSelectedAoi = -1;
    _currentOverrideParcelKey = null;
    _currentOverrideAoiData = null;

    // Reset polygon styles
    evidenceAoiPolygons.forEach(function (poly) {
      poly.setStyle({ color: 'rgba(88,166,255,.7)', weight: 2, fillOpacity: 0.05 });
    });

    // Zoom to fit all
    if (evidenceAoiPolygons.length && evidenceMap) {
      var allBounds = L.latLngBounds([]);
      evidenceAoiPolygons.forEach(function (poly) { allBounds.extend(poly.getBounds()); });
      if (allBounds.isValid()) evidenceMap.fitBounds(allBounds.pad(0.1));
    }

    // Clear chip active state
    var chips = document.querySelectorAll('.app-evidence-aoi-chip');
    chips.forEach(function (chip) { chip.className = 'app-evidence-aoi-chip'; });

    // Clear per-AOI detail
    var _er = er();
    if (typeof _er.clearAoiDetail === 'function') _er.clearAoiDetail();

    // Clear parcel notes panel (reset to empty/add state)
    var savedEl = document.getElementById('app-evidence-notes-saved');
    var editEl = document.getElementById('app-evidence-notes-edit');
    var addBtn = document.getElementById('app-evidence-notes-add-btn');
    if (savedEl) savedEl.hidden = true;
    if (editEl) editEl.hidden = true;
    if (addBtn) { addBtn.hidden = false; addBtn.textContent = '+ Add note'; }
    var overrideEl = document.getElementById('app-evidence-override');
    if (overrideEl) overrideEl.hidden = true;
  }

  function _parcelKeyForIndex(idx) {
    var _ep = ep();
    if (typeof _ep.parcelKeyForIndex === 'function') return _ep.parcelKeyForIndex(idx);
    return String(idx);
  }

  // ── Frame controls ───────────────────────────────────────────

  function buildEvidenceFrames(framePlan, searchIds, ndviSearchIds) {
    evidenceMapLayers = [];
    var slider = document.getElementById('app-map-frame-slider');
    if (slider) { slider.max = framePlan.length - 1; slider.value = 0; }

    var _er = er();
    var _pcTileUrl = typeof _er.pcTileUrl === 'function' ? _er.pcTileUrl : function () { return ''; };
    var _pcNdviTileUrl = typeof _er.pcNdviTileUrl === 'function' ? _er.pcNdviTileUrl : function () { return ''; };

    framePlan.forEach(function (frame, idx) {
      var sid = searchIds[idx];
      var ndviSid = ndviSearchIds[idx] || sid;
      var collection = frame.display_collection || frame.collection || 'sentinel-2-l2a';
      var asset = frame.asset || (collection.indexOf('naip') >= 0 ? 'image' : 'visual');

      var rgbLayer = null;
      var ndviLayer = null;
      if (sid) {
        rgbLayer = L.tileLayer(_pcTileUrl(sid, collection, asset), { maxZoom: 18, opacity: 0 });
        rgbLayer.addTo(evidenceMap);
      }
      if (ndviSid && collection.indexOf('sentinel') >= 0) {
        ndviLayer = L.tileLayer(_pcNdviTileUrl(ndviSid), { maxZoom: 18, opacity: 0 });
        ndviLayer.addTo(evidenceMap);
      }

      // #646 — store human-readable collection label and resolution suffix so
      // updateLayerButtonLabels can build informative button titles per frame.
      var collectionLabel = collection.indexOf('naip') >= 0 ? 'NAIP'
        : collection.indexOf('sentinel') >= 0 ? 'Sentinel-2'
          : collection.indexOf('landsat') >= 0 ? 'Landsat'
            : collection;
      var resolutionM = (frame.provenance && frame.provenance.resolution_m)
        || frame.display_resolution_m
        || null;
      var resLabel = resolutionM ? (' \u00b7 ' + resolutionM + 'm') : '';

      evidenceMapLayers.push({
        rgb: rgbLayer,
        ndvi: ndviLayer,
        label: frame.label || ('Frame ' + (idx + 1)),
        info: [collection, frame.start_date, frame.end_date].filter(Boolean).join(' | '),
        rgbDisplaySuitable: frame.rgb_display_suitable !== false,
        rgbDisplayWarning: frame.rgb_display_warning || '',
        preferredLayer: frame.preferred_layer || 'rgb',
        displayResolutionM: frame.display_resolution_m || null,
        collectionLabel: collectionLabel,
        resLabel: resLabel
      });
    });

    evidenceFrameIndex = pickInitialEvidenceFrameIndex(evidenceMapLayers);
    evidenceLayerMode = pickEvidenceDefaultLayer(evidenceMapLayers[evidenceFrameIndex]);
    syncLayerModeButtons();
    showEvidenceFrame(evidenceFrameIndex);
  }

  function showEvidenceFrame(idx) {
    if (idx < 0 || idx >= evidenceMapLayers.length) return;
    evidenceFrameIndex = idx;
    var activeFrame = evidenceMapLayers[idx];

    // #646 — bidirectional mode adaptation:
    // Fall back to rgb when the user is in ndvi mode but this frame has no ndvi layer.
    if (evidenceLayerMode === 'ndvi' && !activeFrame.ndvi) {
      evidenceLayerMode = 'rgb';
    }
    // Promote to ndvi for coarse frames where rgb is unsuitable (established in #645).
    if (activeFrame.rgbDisplaySuitable === false && activeFrame.ndvi) {
      evidenceLayerMode = 'ndvi';
    }
    // Keep button active classes in sync after any programmatic mode change.
    syncLayerModeButtons();

    evidenceMapLayers.forEach(function (frame, i) {
      var showRgb = (i === idx && evidenceLayerMode === 'rgb');
      var showNdvi = (i === idx && evidenceLayerMode === 'ndvi');
      if (frame.rgb) frame.rgb.setOpacity(showRgb ? 1 : 0);
      if (frame.ndvi) frame.ndvi.setOpacity(showNdvi ? 1 : 0);
    });

    var slider = document.getElementById('app-map-frame-slider');
    var counter = document.getElementById('app-map-frame-counter');
    var label = document.getElementById('app-map-frame-label');
    if (slider) slider.value = idx;
    if (counter) counter.textContent = (idx + 1) + '/' + evidenceMapLayers.length;
    if (label) {
      label.textContent = activeFrame.label + ' — ' + activeFrame.info +
        (activeFrame.rgbDisplayWarning ? ' — ' + activeFrame.rgbDisplayWarning : '');
    }
    syncEvidenceLayerButtons(activeFrame);
    updateLayerButtonLabels(activeFrame);

    // Sync expanded controls if open
    if (evidenceMapExpanded) syncExpandedControls();
  }

  function toggleEvidencePlay() {
    var btn = document.getElementById('app-map-play-btn');
    var expBtn = document.getElementById('app-map-expanded-play-btn');
    if (evidencePlayInterval) {
      clearInterval(evidencePlayInterval);
      evidencePlayInterval = null;
      if (btn) btn.textContent = '▶ Play';
      if (expBtn) expBtn.textContent = '▶ Play';
      return;
    }
    if (btn) btn.textContent = '⏸ Pause';
    if (expBtn) expBtn.textContent = '⏸ Pause';
    evidencePlayInterval = setInterval(function () {
      var next = (evidenceFrameIndex + 1) % evidenceMapLayers.length;
      showEvidenceFrame(next);
    }, 1500);
  }

  function stopEvidencePlay() {
    if (evidencePlayInterval) {
      clearInterval(evidencePlayInterval);
      evidencePlayInterval = null;
    }
  }

  // ── AI analysis ──────────────────────────────────────────────

  async function loadSavedAnalysis(instanceId) {
    var aiBlock = document.getElementById('app-evidence-ai-block');
    var content = document.getElementById('app-evidence-ai-content');
    if (!aiBlock || !content) return;

    try {
      await (_getApiReady ? _getApiReady() : Promise.resolve());
      var res = await _apiFetch('/api/timelapse-analysis-load/' + encodeURIComponent(instanceId));
      evidenceAnalysis = await res.json();
      var _er = er();
      if (evidenceAnalysis && (evidenceAnalysis.observations || evidenceAnalysis.summary)) {
        aiBlock.hidden = false;
        if (typeof _er.renderEvidenceAnalysis === 'function') _er.renderEvidenceAnalysis(evidenceAnalysis);
      }
    } catch (e) {
      // 404 = no saved analysis yet (expected). Other errors indicate a real problem.
      if (e && e.status && e.status !== 404) {
        console.warn('Failed to load saved analysis:', e.message || e);
      }
    }
  }

  async function requestAiAnalysis() {
    var loading = document.getElementById('app-evidence-ai-loading');
    var content = document.getElementById('app-evidence-ai-content');
    var btn = document.getElementById('app-evidence-ai-btn');
    if (!loading || !content || !evidenceManifest) return;

    var _createCallout = (window.CanopexHelpers || {}).createCallout || function (t, m) {
      var d = document.createElement('div');
      d.className = 'callout callout-' + t;
      d.textContent = m;
      return d;
    };

    var originalLabel = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Analyzing…'; }
    loading.hidden = false;
    content.textContent = '';

    try {
      await (_getApiReady ? _getApiReady() : Promise.resolve());

      var ndviTimeseries = (evidenceManifest.ndvi_stats || []).map(function (f, i) {
        if (!f) return null;
        var fp = (evidenceManifest.frame_plan || [])[i] || {};
        return { date: f.datetime || fp.label, mean: f.mean, min: f.min, max: f.max, year: fp.year, season: fp.season };
      }).filter(Boolean);

      // weather_monthly may be { labels, temp, precip } parallel arrays
      var wm = evidenceManifest.weather_monthly;
      var weatherTimeseries = [];
      if (wm && wm.labels && Array.isArray(wm.labels)) {
        weatherTimeseries = wm.labels.map(function (lbl, i) {
          return { month_index: i, label: lbl, temperature: wm.temp ? wm.temp[i] : null, precipitation: wm.precip ? wm.precip[i] : null };
        });
      } else if (Array.isArray(wm)) {
        weatherTimeseries = wm.map(function (m, i) {
          return { month_index: i, temperature: m.temperature, precipitation: m.precipitation };
        });
      }

      var center = evidenceManifest.center || evidenceManifest.coords;
      var lat = Array.isArray(center) ? center[0] : (center && center.lat) || 0;
      var lon = Array.isArray(center) ? center[1] : (center && center.lon) || 0;

      var body = {
        context: {
          aoi_name: 'Analysis area',
          latitude: lat,
          longitude: lon,
          frame_count: ndviTimeseries.length,
          date_range_start: ndviTimeseries.length ? ndviTimeseries[0].date : '',
          date_range_end: ndviTimeseries.length ? ndviTimeseries[ndviTimeseries.length - 1].date : '',
          ndvi_timeseries: ndviTimeseries,
          weather_timeseries: weatherTimeseries
        }
      };

      var res = await _apiFetch('/api/timelapse-analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      evidenceAnalysis = await res.json();
      var _er = er();
      if (typeof _er.renderEvidenceAnalysis === 'function') _er.renderEvidenceAnalysis(evidenceAnalysis);

      // Save the analysis (non-blocking but warn user on failure)
      _apiFetch('/api/timelapse-analysis-save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instance_id: evidenceInstanceId, analysis: evidenceAnalysis })
      }).catch(function () {
        var saveWarn = document.getElementById('app-evidence-ai-content');
        if (saveWarn) saveWarn.appendChild(_createCallout('warning', 'Analysis displayed but could not be saved. It will be lost on reload.'));
      });
    } catch (err) {
      content.textContent = '';
      content.appendChild(_createCallout('error', (err && err.message) || 'Could not run AI analysis.'));
    } finally {
      loading.hidden = true;
      if (btn) { btn.disabled = false; btn.textContent = originalLabel; }
    }
  }

  // ── EUDR assessment ──────────────────────────────────────────

  function activeEvidenceContext() {
    if (!evidenceManifest) return null;
    var perAoi = evidenceManifest.per_aoi_enrichment || [];
    if (evidenceSelectedAoi >= 0 && evidenceSelectedAoi < perAoi.length) {
      return perAoi[evidenceSelectedAoi];
    }
    return evidenceManifest;
  }

  function buildEvidenceNdviTimeseries(source) {
    var _em = em();
    if (typeof _em.buildNdviTimeseries === 'function') {
      return _em.buildNdviTimeseries(source);
    }
    if (!source) return [];
    return (source.ndvi_stats || []).map(function (f, i) {
      if (!f) return null;
      var fp = (source.frame_plan || [])[i] || {};
      return {
        date: f.datetime || f.date || fp.start || fp.label,
        mean: f.mean,
        min: f.min,
        max: f.max,
        year: f.year || fp.year,
        season: f.season || fp.season
      };
    }).filter(Boolean);
  }

  function evidenceLatLon(source) {
    var _em = em();
    if (typeof _em.latLon === 'function') {
      return _em.latLon(source);
    }
    if (!source) return { lat: 0, lon: 0 };
    var center = source.center || source.coords;
    if (Array.isArray(center)) {
      return { lat: center[0] || 0, lon: center[1] || 0 };
    }
    return {
      lat: (center && (center.lat || center.latitude)) || 0,
      lon: (center && (center.lon || center.longitude)) || 0
    };
  }

  async function requestEudrAssessment() {
    var loading = document.getElementById('app-evidence-eudr-loading');
    var content = document.getElementById('app-evidence-eudr-content');
    var btn = document.getElementById('app-evidence-eudr-btn');
    if (!loading || !content || !evidenceManifest) return;

    var _createCallout = (window.CanopexHelpers || {}).createCallout || function (t, m) {
      var d = document.createElement('div');
      d.className = 'callout callout-' + t;
      d.textContent = m;
      return d;
    };

    if (btn) btn.disabled = true;
    loading.hidden = false;
    content.textContent = '';

    try {
      await (_getApiReady ? _getApiReady() : Promise.resolve());

      var source = activeEvidenceContext();
      var ndviTimeseries = buildEvidenceNdviTimeseries(source);
      var latLon = evidenceLatLon(source);

      var body = {
        context: {
          aoi_name: source && source.name ? source.name : 'Analysis area',
          latitude: latLon.lat,
          longitude: latLon.lon,
          ndvi_timeseries: ndviTimeseries,
          reference_date: '2020-12-31'
        }
      };

      var res = await _apiFetch('/api/eudr-assessment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      var result = await res.json();
      var cls = (result.compliant || result.deforestation_free) ? 'compliant' : 'non-compliant';
      var label = cls === 'compliant' ? '\u2713 No deforestation detected since Dec 2020' : '\u26A0 Potential deforestation detected';
      content.textContent = '';
      var resultDiv = document.createElement('div');
      resultDiv.className = 'app-evidence-eudr-result ' + cls;
      var strong = document.createElement('strong');
      strong.textContent = label;
      resultDiv.appendChild(strong);
      if (result.summary) {
        var p = document.createElement('p');
        p.textContent = result.summary;
        resultDiv.appendChild(p);
      }
      content.appendChild(resultDiv);
    } catch (err) {
      content.textContent = '';
      content.appendChild(_createCallout('error', (err && err.message) || 'Could not run EUDR assessment.'));
    } finally {
      loading.hidden = true;
      if (btn) btn.disabled = false;
    }
  }

  // ── Public API ────────────────────────────────────────────────

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
    getManifest: function () { return evidenceManifest; },
    getInstanceId: function () { return evidenceInstanceId; },
    getOverrideContext: function () {
      return { parcelKey: _currentOverrideParcelKey, aoiData: _currentOverrideAoiData };
    },
  };
})();
