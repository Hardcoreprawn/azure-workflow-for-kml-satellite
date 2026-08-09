/**
 * app-evidence-display-map.js
 *
 * Evidence map + frame controls for app-evidence-display.
 */
(function () {
  'use strict';

  function pickEvidenceDefaultLayer(frame, emObj) {
    if (typeof emObj.pickDefaultLayer === 'function') {
      return emObj.pickDefaultLayer(frame);
    }
    if (!frame) return 'rgb';
    if (frame.preferredLayer === 'ndvi' || frame.preferred_layer === 'ndvi') return 'ndvi';
    return 'rgb';
  }

  function pickInitialEvidenceFrameIndex(frames, emObj) {
    if (typeof emObj.pickInitialFrameIndex === 'function') {
      return emObj.pickInitialFrameIndex(frames);
    }
    if (!Array.isArray(frames) || !frames.length) return 0;
    return 0;
  }

  function syncEvidenceLayerButtons(state, frame) {
    let rgbBtn = document.getElementById('app-map-btn-rgb');
    let ndviBtn = document.getElementById('app-map-btn-ndvi');
    let expandedRgbBtn = document.getElementById('app-map-expanded-btn-rgb');
    let expandedNdviBtn = document.getElementById('app-map-expanded-btn-ndvi');
    let rgbDisabled = !!(frame && frame.rgbDisplaySuitable === false);
    let warning = frame && frame.rgbDisplayWarning ? frame.rgbDisplayWarning : '';

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

  function updateLayerButtonLabels(frame) {
    let btnRgb = document.getElementById('app-map-btn-rgb');
    let btnNdvi = document.getElementById('app-map-btn-ndvi');
    let expRgb = document.getElementById('app-map-expanded-btn-rgb');
    let expNdvi = document.getElementById('app-map-expanded-btn-ndvi');
    if (!frame) return;
    let info = frame.collectionLabel
      ? (frame.collectionLabel + (frame.resLabel || ''))
      : '';
    [btnRgb, expRgb].forEach(function (btn) {
      if (!btn) return;
      let base = info ? 'True-colour RGB — ' + info : 'True-colour RGB';
      if (!btn.disabled) btn.title = base;
      btn.setAttribute('aria-label', info ? 'RGB (' + info + ')' : 'RGB');
    });
    [btnNdvi, expNdvi].forEach(function (btn) {
      if (!btn) return;
      btn.title = info ? 'Vegetation index (NDVI) — ' + info : 'Vegetation index (NDVI)';
      btn.setAttribute('aria-label', info ? 'NDVI (' + info + ')' : 'NDVI');
    });
  }

  function syncLayerModeButtons(state) {
    let isRgb = state.layerMode === 'rgb';
    ['app-map-btn-rgb', 'app-map-expanded-btn-rgb'].forEach(function (id) {
      let btn = document.getElementById(id);
      if (btn) btn.classList.toggle('active', isRgb);
    });
    ['app-map-btn-ndvi', 'app-map-expanded-btn-ndvi'].forEach(function (id) {
      let btn = document.getElementById(id);
      if (btn) btn.classList.toggle('active', !isRgb);
    });
  }

  function showEvidenceFrame(idx, ctx) {
    let state = ctx.state;
    if (idx < 0 || idx >= state.mapLayers.length) return;
    state.frameIndex = idx;
    let activeFrame = state.mapLayers[idx];

    if (state.layerMode === 'ndvi' && !activeFrame.ndvi) {
      state.layerMode = 'rgb';
    }
    if (activeFrame.rgbDisplaySuitable === false && activeFrame.ndvi) {
      state.layerMode = 'ndvi';
    }
    syncLayerModeButtons(state);

    state.mapLayers.forEach(function (frame, i) {
      let showRgb = (i === idx && state.layerMode === 'rgb');
      let showNdvi = (i === idx && state.layerMode === 'ndvi');
      if (frame.rgb) frame.rgb.setOpacity(showRgb ? 1 : 0);
      if (frame.ndvi) frame.ndvi.setOpacity(showNdvi ? 1 : 0);
    });

    let slider = document.getElementById('app-map-frame-slider');
    let counter = document.getElementById('app-map-frame-counter');
    let label = document.getElementById('app-map-frame-label');
    if (slider) slider.value = idx;
    if (counter) counter.textContent = (idx + 1) + '/' + state.mapLayers.length;
    if (label) {
      label.textContent = activeFrame.label + ' — ' + activeFrame.info +
        (activeFrame.rgbDisplayWarning ? ' — ' + activeFrame.rgbDisplayWarning : '');
    }
    syncEvidenceLayerButtons(state, activeFrame);
    updateLayerButtonLabels(activeFrame);

    if (state.mapExpanded) syncExpandedControls(ctx);
  }

  function setEvidenceLayerMode(mode, ctx) {
    let state = ctx.state;
    if (mode !== 'rgb' && mode !== 'ndvi') return;
    state.layerMode = mode;
    syncLayerModeButtons(state);
    showEvidenceFrame(state.frameIndex, ctx);
  }

  function syncExpandedControls(ctx) {
    let state = ctx.state;
    let slider = document.getElementById('app-map-expanded-slider');
    let counter = document.getElementById('app-map-expanded-counter');
    let label = document.getElementById('app-map-expanded-label');
    let rgbBtn = document.getElementById('app-map-expanded-btn-rgb');
    let ndviBtn = document.getElementById('app-map-expanded-btn-ndvi');

    if (slider && state.mapLayers.length) {
      slider.max = state.mapLayers.length - 1;
      slider.value = state.frameIndex;
    }
    if (counter) counter.textContent = (state.frameIndex + 1) + '/' + state.mapLayers.length;
    if (label && state.mapLayers[state.frameIndex]) {
      let expandedFrame = state.mapLayers[state.frameIndex];
      label.textContent = expandedFrame.label + ' — ' + expandedFrame.info +
        (expandedFrame.rgbDisplayWarning ? ' — ' + expandedFrame.rgbDisplayWarning : '');
    }
    syncEvidenceLayerButtons(state, state.mapLayers[state.frameIndex]);
    if (rgbBtn) rgbBtn.classList.toggle('active', state.layerMode === 'rgb');
    if (ndviBtn) ndviBtn.classList.toggle('active', state.layerMode === 'ndvi');
  }

  function buildEvidenceFrames(framePlan, searchIds, ndviSearchIds, ctx) {
    let state = ctx.state;
    state.mapLayers = [];
    let slider = document.getElementById('app-map-frame-slider');
    if (slider) { slider.max = framePlan.length - 1; slider.value = 0; }

    let _er = ctx.er();
    let _pcTileUrl = typeof _er.pcTileUrl === 'function' ? _er.pcTileUrl : function () { return ''; };
    let _pcNdviTileUrl = typeof _er.pcNdviTileUrl === 'function' ? _er.pcNdviTileUrl : function () { return ''; };

    framePlan.forEach(function (frame, idx) {
      let sid = searchIds[idx];
      let ndviSid = ndviSearchIds[idx] || sid;
      let collection = frame.display_collection || frame.collection || 'sentinel-2-l2a';
      let asset = frame.asset || (collection.indexOf('naip') >= 0 ? 'image' : 'visual');

      let rgbLayer = null;
      let ndviLayer = null;
      if (sid) {
        rgbLayer = L.tileLayer(_pcTileUrl(sid, collection, asset), { maxZoom: 18, opacity: 0 });
        rgbLayer.addTo(state.map);
      }
      if (ndviSid && collection.indexOf('sentinel') >= 0) {
        ndviLayer = L.tileLayer(_pcNdviTileUrl(ndviSid), { maxZoom: 18, opacity: 0 });
        ndviLayer.addTo(state.map);
      }

      let collectionLabel = collection.indexOf('naip') >= 0 ? 'NAIP'
        : collection.indexOf('sentinel') >= 0 ? 'Sentinel-2'
          : collection.indexOf('landsat') >= 0 ? 'Landsat'
            : collection;
      let resolutionM = (frame.provenance && frame.provenance.resolution_m)
        || frame.display_resolution_m
        || null;
      let resLabel = resolutionM ? (' · ' + resolutionM + 'm') : '';

      state.mapLayers.push({
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

    const emObj = ctx.em();
    state.frameIndex = pickInitialEvidenceFrameIndex(state.mapLayers, emObj);
    state.layerMode = pickEvidenceDefaultLayer(state.mapLayers[state.frameIndex], emObj);
    syncLayerModeButtons(state);
    showEvidenceFrame(state.frameIndex, ctx);
  }

  function initEvidenceMap(manifest, ctx) {
    let state = ctx.state;
    let container = document.getElementById('app-evidence-map');
    let overlay = document.getElementById('app-evidence-map-overlay');
    let controls = document.getElementById('app-evidence-frame-controls');
    if (!container) return;

    if (state.map) { state.map.remove(); state.map = null; }
    state.mapLayers = [];
    state.frameIndex = 0;
    if (state.playInterval) { clearInterval(state.playInterval); state.playInterval = null; }

    let center = manifest.center || manifest.coords;
    if (!center) {
      if (overlay) overlay.textContent = 'No location data available.';
      return;
    }

    let lat = Array.isArray(center) ? center[0] : center.lat || center.latitude;
    let lon = Array.isArray(center) ? center[1] : center.lon || center.longitude;
    if (!lat || !lon) {
      if (overlay) overlay.textContent = 'Invalid coordinates in manifest.';
      return;
    }

    state.map = L.map(container, { zoomControl: true, attributionControl: false }).setView([lat, lon], 13);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 18
    }).addTo(state.map);

    state.aoiPolygons = [];
    let perAoi = manifest.per_aoi_enrichment || [];
    if (perAoi.length > 1) {
      try {
        let allBounds = L.latLngBounds([]);
        perAoi.forEach(function (aoi, idx) {
          if (!aoi.coords || !aoi.coords.length) return;
          let ll = aoi.coords.map(function (c) { return [c[1], c[0]]; });
          let poly = L.polygon(ll, {
            color: 'rgba(88,166,255,.7)',
            weight: 2,
            fillOpacity: 0.05
          }).addTo(state.map);
          let tip = document.createElement('span');
          tip.textContent = aoi.name || ('Parcel ' + (idx + 1));
          poly.bindTooltip(tip, { sticky: true });
          poly.on('click', function () { ctx.selectAoi(idx); });
          state.aoiPolygons.push(poly);
          allBounds.extend(poly.getBounds());
        });
        if (allBounds.isValid()) state.map.fitBounds(allBounds.pad(0.1));
      } catch (e) { /* skip polygon */ }
    } else if (manifest.coords && Array.isArray(manifest.coords)) {
      try {
        let rings = [];
        let ringStart = 0;
        for (let ci = ringStart + 3; ci < manifest.coords.length; ci++) {
          if (Math.abs(manifest.coords[ci][0] - manifest.coords[ringStart][0]) < 1e-5 &&
            Math.abs(manifest.coords[ci][1] - manifest.coords[ringStart][1]) < 1e-5) {
            rings.push(manifest.coords.slice(ringStart, ci + 1));
            ringStart = ci + 1;
            ci = ringStart + 2;
          }
        }
        if (ringStart < manifest.coords.length) rings.push(manifest.coords.slice(ringStart));
        if (!rings.length) rings.push(manifest.coords);

        let singleBounds = L.latLngBounds([]);
        rings.forEach(function (ring) {
          let ll = ring.map(function (c) { return [c[1], c[0]]; });
          L.polygon(ll, { color: 'rgba(88,166,255,.7)', weight: 2, fillOpacity: 0.05 }).addTo(state.map);
          singleBounds.extend(L.polygon(ll).getBounds());
        });
        state.map.fitBounds(singleBounds.pad(0.1));
      } catch (e) { /* skip polygon */ }
    }

    if (overlay) overlay.hidden = true;

    let searchIds = manifest.search_ids || [];
    let ndviSearchIds = manifest.ndvi_search_ids || [];
    let framePlan = manifest.frame_plan || [];

    if (searchIds.length && framePlan.length) {
      buildEvidenceFrames(framePlan, searchIds, ndviSearchIds, ctx);
      if (controls) controls.hidden = false;
    } else if (controls) {
      controls.hidden = true;
    }

    setTimeout(function () { if (state.map) state.map.invalidateSize(); }, 200);
  }

  function toggleEvidencePlay(ctx) {
    let state = ctx.state;
    let btn = document.getElementById('app-map-play-btn');
    let expBtn = document.getElementById('app-map-expanded-play-btn');
    if (state.playInterval) {
      clearInterval(state.playInterval);
      state.playInterval = null;
      if (btn) btn.textContent = '▶ Play';
      if (expBtn) expBtn.textContent = '▶ Play';
      return;
    }
    if (btn) btn.textContent = '⏸ Pause';
    if (expBtn) expBtn.textContent = '⏸ Pause';
    state.playInterval = setInterval(function () {
      let next = (state.frameIndex + 1) % state.mapLayers.length;
      showEvidenceFrame(next, ctx);
    }, 1500);
  }

  function stopEvidencePlay(ctx) {
    let state = ctx.state;
    if (state.playInterval) {
      clearInterval(state.playInterval);
      state.playInterval = null;
    }
  }

  window.CanopexEvidenceDisplayMap = {
    syncExpandedControls: syncExpandedControls,
    setLayerMode: setEvidenceLayerMode,
    initEvidenceMap: initEvidenceMap,
    showEvidenceFrame: showEvidenceFrame,
    toggleEvidencePlay: toggleEvidencePlay,
    stopEvidencePlay: stopEvidencePlay
  };
})();
