/**
 * app-analysis-preflight.js
 *
 * KML/KMZ file loading, CSV conversion, geometry preflight analysis,
 * and the preflight UI panel update. Extracted from app-shell.js.
 *
 * Exposes window.CanopexAnalysisPreflight = { init, updateAnalysisPreflight,
 *   loadAnalysisFile, switchInputTab, convertCSVToKml,
 *   getPendingKmzBytes, clearPendingKmzBytes }
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
  var _computeEudrCostEstimate = null;

  // Module-local Leaflet map instance for the preflight thumbnail.
  var preflightMap = null;

  // KMZ bytes to upload — set by loadAnalysisFile, cleared on manual text edit.
  var _pendingKmzBytes = null;

  // ── KMZ ZIP builder (no external dependencies) ───────────────

  // CRC-32 table initialised once at module load (IEEE 802.3 polynomial).
  var _crc32Table = (function () {
    var t = new Uint32Array(256);
    for (var i = 0; i < 256; i++) {
      var c = i;
      for (var k = 0; k < 8; k++) {
        c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      }
      t[i] = c >>> 0;
    }
    return t;
  }());

  function _crc32(bytes) {
    var crc = 0xFFFFFFFF;
    for (var i = 0; i < bytes.length; i++) {
      crc = _crc32Table[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    }
    return (crc ^ 0xFFFFFFFF) >>> 0;
  }

  function _u16(view, offset, value) { view.setUint16(offset, value, true); }
  function _u32(view, offset, value) { view.setUint32(offset, value, true); }

  function _buildLocalFileHeader(buf, off, fileName, compSize, rawSize, crc, dosTime, dosDate) {
    var view = new DataView(buf);
    var bytes = new Uint8Array(buf);
    bytes.set([0x50, 0x4B, 0x03, 0x04], off);
    _u16(view, off + 4, 20);        // version needed: 2.0
    _u16(view, off + 6, 0);         // flags
    _u16(view, off + 8, 8);         // method: deflate
    _u16(view, off + 10, dosTime);
    _u16(view, off + 12, dosDate);
    _u32(view, off + 14, crc);
    _u32(view, off + 18, compSize);
    _u32(view, off + 22, rawSize);
    _u16(view, off + 26, fileName.length);
    _u16(view, off + 28, 0);        // extra field length
    bytes.set(fileName, off + 30);
  }

  function _buildCentralDirRecord(buf, off, fileName, compSize, rawSize, crc, dosTime, dosDate, localOffset) {
    var view = new DataView(buf);
    var bytes = new Uint8Array(buf);
    bytes.set([0x50, 0x4B, 0x01, 0x02], off);
    _u16(view, off + 4, 0x031E);    // version made by: Unix 3.0
    _u16(view, off + 6, 20);        // version needed
    _u16(view, off + 8, 0);         // flags
    _u16(view, off + 10, 8);        // method: deflate
    _u16(view, off + 12, dosTime);
    _u16(view, off + 14, dosDate);
    _u32(view, off + 16, crc);
    _u32(view, off + 20, compSize);
    _u32(view, off + 24, rawSize);
    _u16(view, off + 28, fileName.length);
    _u16(view, off + 30, 0);        // extra field length
    _u16(view, off + 32, 0);        // comment length
    _u16(view, off + 34, 0);        // disk start
    _u16(view, off + 36, 0);        // internal attributes
    _u32(view, off + 38, 0);        // external attributes
    _u32(view, off + 42, localOffset);
    bytes.set(fileName, off + 46);
  }

  function _buildEndOfCentralDir(buf, off, cdSize, cdOffset) {
    var view = new DataView(buf);
    var bytes = new Uint8Array(buf);
    bytes.set([0x50, 0x4B, 0x05, 0x06], off);
    _u16(view, off + 4, 0);         // disk number
    _u16(view, off + 6, 0);         // disk with CD start
    _u16(view, off + 8, 1);         // entries on this disk
    _u16(view, off + 10, 1);        // total entries
    _u32(view, off + 12, cdSize);
    _u32(view, off + 16, cdOffset);
    _u16(view, off + 20, 0);        // comment length
  }

  async function buildKmzFromKmlText(kmlText) {
    var kmlBytes = new TextEncoder().encode(kmlText);
    var fileName = new TextEncoder().encode('doc.kml');
    var crc = _crc32(kmlBytes);

    // Deflate-compress the KML bytes (supported in all modern browsers).
    var comprStream = new Blob([kmlBytes]).stream().pipeThrough(new CompressionStream('deflate-raw'));
    var compressedBytes = new Uint8Array(await new Response(comprStream).arrayBuffer());

    var now = new Date();
    var dosDate = (((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate()) >>> 0;
    var dosTime = ((now.getHours() << 11) | (now.getMinutes() << 5) | Math.floor(now.getSeconds() / 2)) >>> 0;

    var lfhSize = 30 + fileName.length;
    var cdrSize = 46 + fileName.length;
    var cdOffset = lfhSize + compressedBytes.length;
    var totalSize = cdOffset + cdrSize + 22;

    var buf = new ArrayBuffer(totalSize);
    _buildLocalFileHeader(buf, 0, fileName, compressedBytes.length, kmlBytes.length, crc, dosTime, dosDate);
    new Uint8Array(buf).set(compressedBytes, lfhSize);
    _buildCentralDirRecord(buf, cdOffset, fileName, compressedBytes.length, kmlBytes.length, crc, dosTime, dosDate, 0);
    _buildEndOfCentralDir(buf, cdOffset + cdrSize, cdrSize, cdOffset);

    return new Uint8Array(buf);
  }

  function getPendingKmzBytes() {
    return _pendingKmzBytes;
  }

  function clearPendingKmzBytes() {
    _pendingKmzBytes = null;
  }

  function init(deps) {
    _apiFetch = deps.apiFetch;
    _getApiReady = deps.getApiReady;
    _getWorkspaceRole = deps.getWorkspaceRole;
    _getActiveProfile = deps.getActiveProfile;
    _getLatestBillingStatus = deps.getLatestBillingStatus;
    _getWorkspaceRoleConfig = deps.getWorkspaceRoleConfig;
    _onPreflightUpdate = deps.onPreflightUpdate;
    _computeEudrCostEstimate = deps.computeEudrCostEstimate;
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
    if (!activeProfile.enableParcelCostEstimate || !parcelCount || !_computeEudrCostEstimate) return null;
    var estimateText = _computeEudrCostEstimate(parcelCount, activeProfile);
    if (!estimateText || estimateText === '—') return null;
    return estimateText;
  }

  function renderPreflightCost(estimateText) {
    var costEl = document.getElementById('app-preflight-cost');
    if (!costEl) return;
    var costWrap = costEl.parentElement;
    if (!estimateText) {
      costEl.textContent = '';
      if (costWrap) costWrap.hidden = true;
      return;
    }
    if (costWrap) costWrap.hidden = false;
    costEl.textContent = estimateText;
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
      renderPreflightCost(null);
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
      renderPreflightCost(null);
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
    renderPreflightCost(computeEudrCostEstimate(preflight.aoiCount));
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
      var content;
      if (name.endsWith('.kmz')) {
        // Keep original bytes for upload; extract KML text only for preflight display.
        var buffer = await file.arrayBuffer();
        _pendingKmzBytes = new Uint8Array(buffer);
        content = await readKmzFile(file);
      } else {
        content = await readKmlFile(file);
        // Compress the KML to KMZ so the pipeline always receives a single format.
        _pendingKmzBytes = await buildKmzFromKmlText(content);
      }
      textarea.value = content;
      note.textContent = 'Loaded ' + file.name + ' into the analysis form.';
      updateAnalysisPreflight(content);
    } catch (err) {
      _pendingKmzBytes = null;
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
    buildKmzFromKmlText: buildKmzFromKmlText,
    getPendingKmzBytes: getPendingKmzBytes,
    clearPendingKmzBytes: clearPendingKmzBytes,
  };
})();
