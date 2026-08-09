/**
 * app-evidence-display-selection.js
 *
 * Evidence compare view + per-AOI selection helpers.
 */
(function () {
  'use strict';

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

  function destroyCompareMaps(ctx) {
    var state = ctx.state;
    if (state.compareMaps) {
      if (state.compareMaps.before) { state.compareMaps.before.remove(); }
      if (state.compareMaps.after) { state.compareMaps.after.remove(); }
      state.compareMaps = null;
    }
    var before = document.getElementById('app-evidence-compare-map-before');
    var after = document.getElementById('app-evidence-compare-map-after');
    if (before) before.textContent = '';
    if (after) after.textContent = '';
  }

  function buildCompareView(manifest, ctx) {
    var state = ctx.state;
    destroyCompareMaps(ctx);

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
    var _er = ctx.er();
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

    function syncMaps(source, target) {
      source.on('moveend', function () {
        target.setView(source.getCenter(), source.getZoom(), { animate: false });
      });
    }
    syncMaps(beforeMap, afterMap);
    syncMaps(afterMap, beforeMap);

    state.compareMaps = { before: beforeMap, after: afterMap };

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

  function openCompareView(manifest, ctx) {
    var state = ctx.state;
    var mainWrap = document.getElementById('app-evidence-map-wrap');
    var compareWrap = document.getElementById('app-evidence-compare-wrap');
    var frameControls = document.getElementById('app-evidence-frame-controls');
    var frameLabel = document.getElementById('app-map-frame-label');
    var compareBtn = document.getElementById('app-map-btn-compare');
    if (!mainWrap || !compareWrap) return;

    if (state.playInterval) { clearInterval(state.playInterval); state.playInterval = null; }

    mainWrap.hidden = true;
    if (frameControls) frameControls.hidden = true;
    if (frameLabel) frameLabel.textContent = '';
    compareWrap.hidden = false;
    state.compareMode = true;
    if (compareBtn) compareBtn.classList.add('active');

    buildCompareView(manifest, ctx);
  }

  function closeCompareView(ctx) {
    var state = ctx.state;
    var mainWrap = document.getElementById('app-evidence-map-wrap');
    var compareWrap = document.getElementById('app-evidence-compare-wrap');
    var compareBtn = document.getElementById('app-map-btn-compare');
    if (!mainWrap || !compareWrap) return;

    destroyCompareMaps(ctx);
    compareWrap.hidden = true;
    mainWrap.hidden = false;
    state.compareMode = false;
    if (compareBtn) compareBtn.classList.remove('active');

    var frameControls = document.getElementById('app-evidence-frame-controls');
    if (frameControls && state.mapLayers.length) frameControls.hidden = false;
    ctx.showEvidenceFrame(state.frameIndex);
  }

  function toggleCompareView(ctx) {
    var state = ctx.state;
    if (state.compareMode) {
      closeCompareView(ctx);
    } else if (state.manifest) {
      openCompareView(state.manifest, ctx);
    }
  }

  function parcelKeyForIndex(idx, ctx) {
    var _ep = ctx.ep();
    if (typeof _ep.parcelKeyForIndex === 'function') return _ep.parcelKeyForIndex(idx);
    return String(idx);
  }

  function selectAoi(idx, ctx) {
    var state = ctx.state;
    if (!state.manifest || !state.manifest.per_aoi_enrichment) return;
    var perAoi = state.manifest.per_aoi_enrichment;
    if (idx < 0 || idx >= perAoi.length) return;

    state.selectedAoi = idx;
    var aoi = perAoi[idx];

    state.aoiPolygons.forEach(function (poly, i) {
      if (i === idx) {
        poly.setStyle({ color: '#5eecc4', weight: 3, fillOpacity: 0.15 });
      } else {
        poly.setStyle({ color: 'rgba(88,166,255,.3)', weight: 1, fillOpacity: 0.02 });
      }
    });

    if (state.aoiPolygons[idx] && state.map) {
      state.map.fitBounds(state.aoiPolygons[idx].getBounds().pad(0.15));
    }

    var chips = document.querySelectorAll('.app-evidence-aoi-chip');
    chips.forEach(function (chip, i) {
      chip.className = 'app-evidence-aoi-chip' + (i === idx ? ' active' : '');
    });

    var _er = ctx.er();
    if (typeof _er.renderAoiDetail === 'function') _er.renderAoiDetail(aoi);

    state.currentOverrideParcelKey = parcelKeyForIndex(idx, ctx);
    state.currentOverrideAoiData = aoi;

    var _ep = ctx.ep();
    if (typeof _ep.renderParcelNotes === 'function') _ep.renderParcelNotes(parcelKeyForIndex(idx, ctx));
    if (typeof _ep.renderParcelOverride === 'function') _ep.renderParcelOverride(parcelKeyForIndex(idx, ctx), aoi);
  }

  function resetAoiSelection(ctx) {
    var state = ctx.state;
    state.selectedAoi = -1;
    state.currentOverrideParcelKey = null;
    state.currentOverrideAoiData = null;

    state.aoiPolygons.forEach(function (poly) {
      poly.setStyle({ color: 'rgba(88,166,255,.7)', weight: 2, fillOpacity: 0.05 });
    });

    if (state.aoiPolygons.length && state.map) {
      var allBounds = L.latLngBounds([]);
      state.aoiPolygons.forEach(function (poly) { allBounds.extend(poly.getBounds()); });
      if (allBounds.isValid()) state.map.fitBounds(allBounds.pad(0.1));
    }

    var chips = document.querySelectorAll('.app-evidence-aoi-chip');
    chips.forEach(function (chip) { chip.className = 'app-evidence-aoi-chip'; });

    var _er = ctx.er();
    if (typeof _er.clearAoiDetail === 'function') _er.clearAoiDetail();

    var savedEl = document.getElementById('app-evidence-notes-saved');
    var editEl = document.getElementById('app-evidence-notes-edit');
    var addBtn = document.getElementById('app-evidence-notes-add-btn');
    if (savedEl) savedEl.hidden = true;
    if (editEl) editEl.hidden = true;
    if (addBtn) { addBtn.hidden = false; addBtn.textContent = '+ Add note'; }
    var overrideEl = document.getElementById('app-evidence-override');
    if (overrideEl) overrideEl.hidden = true;
  }

  function populateAoiSelector(perAoi, ctx) {
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
      chip.addEventListener('click', function () { selectAoi(idx, ctx); });
      list.appendChild(chip);
    });

    if (resetBtn) {
      resetBtn.addEventListener('click', function () { resetAoiSelection(ctx); });
    }
  }

  window.CanopexEvidenceDisplaySelection = {
    initCompareView: initCompareView,
    toggleCompareView: toggleCompareView,
    destroyCompareMaps: destroyCompareMaps,
    populateAoiSelector: populateAoiSelector,
    selectAoi: selectAoi,
    resetAoiSelection: resetAoiSelection
  };
})();
