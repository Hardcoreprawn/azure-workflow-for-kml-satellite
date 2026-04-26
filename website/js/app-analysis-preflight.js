/**
 * app-analysis-preflight.js
 *
 * KML/KMZ file loading, CSV conversion, geometry preflight analysis,
 * and the preflight UI panel update. Extracted from app-shell.js.
 *
 * Exposes window.CanopexAnalysisPreflight = { init, updateAnalysisPreflight,
 *   loadAnalysisFile, switchInputTab, convertCSVToKml }
 */
(function () {
  'use strict';

  // Geo + helper aliases — resolved after module load (script defer order).
  var geo = window.CanopexGeo || {};
  var parseKmlText = function (t) { return (window.CanopexGeo || geo).parseKmlText ? (window.CanopexGeo || geo).parseKmlText(t) : t; };
  var parseKmlGeometry = function (t) { return (window.CanopexGeo || geo).parseKmlGeometry(t); };
  var haversineKm = function (a, b, c, d) { return (window.CanopexGeo || geo).haversineKm(a, b, c, d); };
  var polygonCentroid = function (c) { return (window.CanopexGeo || geo).polygonCentroid(c); };
  var polygonAreaHa = function (c) { return (window.CanopexGeo || geo).polygonAreaHa(c); };
  var determineProcessingMode = function (n, s) { return (window.CanopexGeo || geo).determineProcessingMode(n, s); };
  var formatDistance = function (v) { return (window.CanopexGeo || geo).formatDistance(v); };
  var formatHectares = function (v) { return (window.CanopexGeo || geo).formatHectares(v); };
  var parseCSVCoordinates = function (t) { return (window.CanopexGeo || geo).parseCSVCoordinates(t); };

  // Injected deps.
  var _apiFetch = null;
  var _getApiReady = null;
  var _getWorkspaceRole = null;
  var _getActiveProfile = null;
  var _getLatestBillingStatus = null;
  var _getWorkspaceRoleConfig = null;
  var _onPreflightUpdate = null;

  // Module-local Leaflet map instance for the preflight thumbnail.
  var preflightMap = null;

  function init(deps) {
    _apiFetch = deps.apiFetch;
    _getApiReady = deps.getApiReady;
    _getWorkspaceRole = deps.getWorkspaceRole;
    _getActiveProfile = deps.getActiveProfile;
    _getLatestBillingStatus = deps.getLatestBillingStatus;
    _getWorkspaceRoleConfig = deps.getWorkspaceRoleConfig;
    _onPreflightUpdate = deps.onPreflightUpdate;
  }

  // ── Preflight warning builder ─────────────────────────────────

  function buildPreflightWarnings(preflight) {
    var workspaceRole = _getWorkspaceRole ? _getWorkspaceRole() : 'conservation';
    var activeProfile = _getActiveProfile ? _getActiveProfile() : {};
    var warnings = [];
    if (preflight.aoiCount > 30) {
      warnings.push({ tone: 'warning', text: preflight.aoiCount + ' AOIs detected. Large batches may take longer and could be split across runs.' });
    } else if (preflight.aoiCount > 6) {
      warnings.push({ tone: 'info', text: preflight.aoiCount + ' AOIs — this will queue as a bulk-ready run.' });
    }
    if (preflight.largestAreaHa > 50000) {
      warnings.push({ tone: 'warning', text: 'At least one AOI covers ' + formatHectares(preflight.largestAreaHa) + '. Very large areas may produce lower-resolution output.' });
    }
    if (preflight.maxSpreadKm > 100) {
      warnings.push({ tone: 'warning', text: 'AOI spread is ' + formatDistance(preflight.maxSpreadKm) + '. Widely spread areas may need batching in a future release.' });
    } else if (preflight.maxSpreadKm > 25) {
      warnings.push({ tone: 'info', text: 'AOI spread is ' + formatDistance(preflight.maxSpreadKm) + '. All areas will be processed in one run.' });
    }
    if (activeProfile.preflightDisclaimer) {
      warnings.push({ tone: 'info', text: activeProfile.preflightDisclaimer });
    }
    if (workspaceRole === 'portfolio' && preflight.aoiCount > 10) {
      warnings.push({ tone: 'info', text: 'Large parcel sets work well with batch analysis. This run still enters your tracked workflow.' });
    }
    if (!warnings.length) {
      warnings.push({ tone: 'info', text: 'No warnings. This will queue as one tracked analysis run.' });
    }
    return warnings;
  }

  // ── Geometry preflight builder ────────────────────────────────

  function buildAnalysisPreflight(text) {
    var trimmed = parseKmlText(text);
    if (!trimmed) return null;

    var parsed = parseKmlGeometry(trimmed);
    if (parsed.error) return { error: parsed.error };
    if (!parsed.polygons || !parsed.polygons.length) {
      return { error: 'No polygon boundaries were detected. Canopex expects polygon AOIs.' };
    }

    var centroids = parsed.polygons.map(function (polygon) { return polygonCentroid(polygon.coords); });
    var groupLat = centroids.reduce(function (sum, coord) { return sum + coord[0]; }, 0) / centroids.length;
    var groupLon = centroids.reduce(function (sum, coord) { return sum + coord[1]; }, 0) / centroids.length;
    var maxSpreadKm = centroids.reduce(function (maxDistance, coord) {
      return Math.max(maxDistance, haversineKm(groupLat, groupLon, coord[0], coord[1]));
    }, 0);
    var totalAreaHa = parsed.polygons.reduce(function (sum, polygon) {
      return sum + polygonAreaHa(polygon.coords);
    }, 0);
    var largestAreaHa = parsed.polygons.reduce(function (maxArea, polygon) {
      return Math.max(maxArea, polygonAreaHa(polygon.coords));
    }, 0);
    var processingMode = determineProcessingMode(parsed.polygons.length, maxSpreadKm);
    var latestBillingStatus = _getLatestBillingStatus ? _getLatestBillingStatus() : null;

    var preflight = {
      featureCount: parsed.featureCount,
      aoiCount: parsed.polygons.length,
      polygons: parsed.polygons,
      maxSpreadKm: maxSpreadKm,
      totalAreaHa: totalAreaHa,
      largestAreaHa: largestAreaHa,
      processingMode: processingMode,
      quotaImpact: latestBillingStatus && latestBillingStatus.runs_remaining != null
        ? '1 of ' + latestBillingStatus.runs_remaining + ' runs'
        : '1 analysis',
      summary: parsed.featureCount + ' features across ' + parsed.polygons.length + ' AOIs covering about ' + formatHectares(totalAreaHa) + '. ' + processingMode + ' processing for this request.'
    };
    preflight.warnings = buildPreflightWarnings(preflight);
    return preflight;
  }

  // ── Preflight map thumbnail ───────────────────────────────────

  function renderPreflightMap(polygons) {
    var wrap = document.getElementById('app-preflight-map-wrap');
    var container = document.getElementById('app-preflight-map');
    if (!wrap || !container) return;

    if (!polygons || !polygons.length) {
      wrap.hidden = true;
      if (preflightMap) { preflightMap.remove(); preflightMap = null; }
      return;
    }

    wrap.hidden = false;

    if (preflightMap) { preflightMap.remove(); preflightMap = null; }

    preflightMap = L.map(container, {
      zoomControl: true,
      attributionControl: true,
      scrollWheelZoom: false,
      dragging: true
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>'
    }).addTo(preflightMap);

    var bounds = L.latLngBounds([]);
    polygons.forEach(function (polygon) {
      var layer = L.polygon(polygon.coords, {
        color: '#5eecc4',
        weight: 2,
        fillColor: '#5eecc4',
        fillOpacity: 0.15
      }).addTo(preflightMap);
      var tip = document.createElement('span');
      tip.textContent = polygon.name;
      layer.bindTooltip(tip, { sticky: true });
      bounds.extend(layer.getBounds());
    });

    preflightMap.fitBounds(bounds, { padding: [24, 24], maxZoom: 15 });
  }

  // ── Preflight warnings list ───────────────────────────────────

  function renderPreflightWarnings(items) {
    var list = document.getElementById('app-preflight-warnings');
    if (!list) return;
    list.replaceChildren();
    items.forEach(function (item) {
      var el = document.createElement('div');
      el.className = 'app-preflight-item';
      el.setAttribute('data-tone', item.tone || 'info');
      el.textContent = item.text;
      list.appendChild(el);
    });
  }

  // ── Cost estimator for EUDR preflight ────────────────────────

  function computeEudrCostEstimate(parcelCount) {
    var activeProfile = _getActiveProfile ? _getActiveProfile() : {};
    var eudrModule = window.CanopexEudr || {};
    if (typeof eudrModule.computeCostEstimate === 'function') {
      return eudrModule.computeCostEstimate(parcelCount, activeProfile);
    }
    if (!activeProfile.enableParcelCostEstimate || !parcelCount) return '—';
    var billing = typeof window.eudrBillingData === 'function' ? window.eudrBillingData() : null;
    if (!billing) return '—';
    if (!billing.subscribed) {
      var remaining = billing.trial_remaining != null ? billing.trial_remaining : 0;
      if (remaining > 0) return parcelCount + ' parcel' + (parcelCount !== 1 ? 's' : '') + ' · ' + remaining + ' free assessment' + (remaining !== 1 ? 's' : '') + ' left';
      return 'Subscribe to continue';
    }
    var used = billing.period_parcels_used || 0;
    var included = billing.included_parcels || 10;
    var remainingIncluded = Math.max(included - used, 0);
    var overageParcels = Math.max(parcelCount - remainingIncluded, 0);
    if (overageParcels === 0) return parcelCount + ' parcel' + (parcelCount !== 1 ? 's' : '') + ' included';
    var rate = overageParcels >= 500 ? 1.80 : overageParcels >= 100 ? 2.50 : 3.00;
    return overageParcels + ' overage × £' + rate.toFixed(2) + ' = £' + (overageParcels * rate).toFixed(2);
  }

  // ── Input tab switching (KML / CSV) ──────────────────────────

  function switchInputTab(tabName) {
    var tabs = document.querySelectorAll('[data-input-tab]');
    tabs.forEach(function (tab) {
      var isActive = tab.getAttribute('data-input-tab') === tabName;
      tab.classList.toggle('active', isActive);
      tab.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
    var kmlPanel = document.getElementById('app-input-panel-kml');
    var csvPanel = document.getElementById('app-input-panel-csv');
    if (kmlPanel) kmlPanel.hidden = tabName !== 'kml';
    if (csvPanel) csvPanel.hidden = tabName !== 'csv';
  }

  // ── CSV → KML conversion ──────────────────────────────────────

  async function convertCSVToKml() {
    var textarea = document.getElementById('app-csv-input');
    var statusEl = document.getElementById('app-csv-status');
    var convertBtn = document.getElementById('app-csv-convert-btn');
    if (!textarea || !statusEl) return;

    var text = textarea.value.trim();
    if (!text) {
      statusEl.hidden = false;
      statusEl.setAttribute('data-tone', 'error');
      statusEl.textContent = 'Paste coordinate data first.';
      return;
    }

    var parsed = parseCSVCoordinates(text);
    if (parsed.errors.length > 0 && parsed.plots.length === 0) {
      statusEl.hidden = false;
      statusEl.setAttribute('data-tone', 'error');
      statusEl.textContent = parsed.errors.join('; ');
      return;
    }
    if (parsed.plots.length === 0) {
      statusEl.hidden = false;
      statusEl.setAttribute('data-tone', 'error');
      statusEl.textContent = 'No valid coordinates found.';
      return;
    }

    if (convertBtn) { convertBtn.disabled = true; convertBtn.textContent = 'Converting…'; }
    statusEl.hidden = false;
    statusEl.setAttribute('data-tone', 'info');
    var warningText = parsed.errors.length > 0 ? ' (' + parsed.errors.length + ' rows skipped)' : '';
    statusEl.textContent = 'Converting ' + parsed.plots.length + ' parcels…' + warningText;

    try {
      if (_getApiReady) await _getApiReady();
      var res = await _apiFetch('/api/convert-coordinates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_name: 'EUDR Parcels', buffer_m: 100, plots: parsed.plots })
      });
      var kmlText = await res.text();

      // Put converted KML into the KML textarea and switch to KML tab
      var kmlTextarea = document.getElementById('app-analysis-kml');
      if (kmlTextarea) {
        kmlTextarea.value = kmlText;
        updateAnalysisPreflight(kmlText);
      }
      switchInputTab('kml');
      statusEl.hidden = true;

      var fileNote = document.getElementById('app-analysis-file-note');
      if (fileNote) fileNote.textContent = 'Generated from ' + parsed.plots.length + ' coordinate' + (parsed.plots.length !== 1 ? 's' : '') + '.';
    } catch (err) {
      statusEl.setAttribute('data-tone', 'error');
      statusEl.textContent = (err.body && err.body.error) || 'Coordinate conversion failed. Check your data and try again.';
    } finally {
      if (convertBtn) { convertBtn.disabled = false; convertBtn.textContent = 'Convert to KML'; }
    }
  }

  // ── Full preflight panel update ───────────────────────────────

  function updateAnalysisPreflight(text) {
    var headlineEl = document.getElementById('app-preflight-headline');
    var modeEl = document.getElementById('app-preflight-mode');
    var summaryEl = document.getElementById('app-preflight-summary');
    var featuresEl = document.getElementById('app-preflight-features');
    var aoisEl = document.getElementById('app-preflight-aois');
    var spreadEl = document.getElementById('app-preflight-spread');
    var quotaEl = document.getElementById('app-preflight-quota');
    var costEl = document.getElementById('app-preflight-cost');
    if (!headlineEl || !modeEl || !summaryEl || !featuresEl || !aoisEl || !spreadEl || !quotaEl) return null;

    var activeProfile = _getActiveProfile ? _getActiveProfile() : {};
    var roleConfig = _getWorkspaceRoleConfig ? _getWorkspaceRoleConfig() : {};
    var roleLabel = roleConfig.label || 'conservation';

    var trimmed = parseKmlText(text);
    if (!trimmed) {
      if (_onPreflightUpdate) _onPreflightUpdate(null);
      headlineEl.textContent = 'Awaiting KML';
      modeEl.textContent = 'No file yet';
      summaryEl.textContent = 'Paste KML to see feature count, area spread, and guidance for the ' + roleLabel + ' view.';
      featuresEl.textContent = '0';
      aoisEl.textContent = '0';
      spreadEl.textContent = '—';
      quotaEl.textContent = '—';
      if (costEl) costEl.textContent = '—';
      renderPreflightWarnings([{ tone: 'info', text: 'Preflight will show warnings here after you paste or upload KML.' }]);
      renderPreflightMap(null);
      var submitBtn = document.getElementById('app-analysis-submit-btn');
      if (submitBtn) submitBtn.textContent = 'Queue Analysis';
      return null;
    }

    var preflight = buildAnalysisPreflight(trimmed);
    if (_onPreflightUpdate) _onPreflightUpdate(preflight);
    if (preflight && preflight.error) {
      headlineEl.textContent = 'KML needs attention';
      modeEl.textContent = 'Check geometry';
      summaryEl.textContent = preflight.error;
      featuresEl.textContent = '—';
      aoisEl.textContent = '—';
      spreadEl.textContent = '—';
      quotaEl.textContent = '—';
      if (costEl) costEl.textContent = '—';
      renderPreflightWarnings([{ tone: 'error', text: preflight.error }]);
      renderPreflightMap(null);
      return preflight;
    }

    headlineEl.textContent = preflight.aoiCount + '-AOI request ready';
    modeEl.textContent = preflight.processingMode;
    summaryEl.textContent = preflight.summary;
    featuresEl.textContent = String(preflight.featureCount);
    aoisEl.textContent = String(preflight.aoiCount);
    spreadEl.textContent = formatDistance(preflight.maxSpreadKm);
    quotaEl.textContent = preflight.quotaImpact;
    if (costEl) costEl.textContent = computeEudrCostEstimate(preflight.aoiCount);
    renderPreflightWarnings(preflight.warnings);
    renderPreflightMap(preflight.polygons);
    var submitBtn = document.getElementById('app-analysis-submit-btn');
    if (submitBtn) submitBtn.textContent = 'Confirm & Queue';
    return preflight;
  }

  // ── File reading ──────────────────────────────────────────────

  function readKmlFile(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function (e) { resolve(String(e.target.result || '')); };
      reader.onerror = function () { reject(new Error('Could not read KML file')); };
      reader.readAsText(file);
    });
  }

  async function readKmzFile(file) {
    var buffer = await file.arrayBuffer();
    var view = new DataView(buffer);
    var offset = 0;

    while (offset < buffer.byteLength - 4) {
      var signature = view.getUint32(offset, true);
      if (signature !== 0x04034b50) break;
      var compressionMethod = view.getUint16(offset + 8, true);
      var compressedSize = view.getUint32(offset + 18, true);
      var fileNameLength = view.getUint16(offset + 26, true);
      var extraLength = view.getUint16(offset + 28, true);
      var fileNameBytes = new Uint8Array(buffer, offset + 30, fileNameLength);
      var fileName = new TextDecoder().decode(fileNameBytes);
      var dataStart = offset + 30 + fileNameLength + extraLength;

      if (fileName.toLowerCase().endsWith('.kml')) {
        var compressed = new Uint8Array(buffer, dataStart, compressedSize);
        if (compressionMethod === 0) {
          return new TextDecoder().decode(compressed);
        }
        if (compressionMethod === 8) {
          var stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
          return await new Response(stream).text();
        }
      }
      offset = dataStart + compressedSize;
    }

    throw new Error('No .kml found inside KMZ archive');
  }

  async function loadAnalysisFile(file) {
    var note = document.getElementById('app-analysis-file-note');
    var textarea = document.getElementById('app-analysis-kml');
    if (!file || !note || !textarea) return;

    try {
      var name = file.name.toLowerCase();
      var content = name.endsWith('.kmz') ? await readKmzFile(file) : await readKmlFile(file);
      textarea.value = content;
      note.textContent = 'Loaded ' + file.name + ' into the analysis form.';
      updateAnalysisPreflight(content);
    } catch (err) {
      note.textContent = err.message || 'Could not read file';
    }
  }

  window.CanopexAnalysisPreflight = {
    init: init,
    updateAnalysisPreflight: updateAnalysisPreflight,
    loadAnalysisFile: loadAnalysisFile,
    switchInputTab: switchInputTab,
    convertCSVToKml: convertCSVToKml,
    buildAnalysisPreflight: buildAnalysisPreflight,
  };
})();
