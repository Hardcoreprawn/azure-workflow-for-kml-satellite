/**
 * app-evidence-display-ai.js
 *
 * AI analysis + EUDR assessment helpers for app-evidence-display.
 */
(function () {
  'use strict';

  function createCallout(type, message) {
    var helper = (window.CanopexHelpers || {}).createCallout;
    if (typeof helper === 'function') {
      return helper(type, message);
    }
    var d = document.createElement('div');
    d.className = 'callout callout-' + type;
    d.textContent = message;
    return d;
  }

  async function loadSavedAnalysis(instanceId, ctx) {
    var state = ctx.state;
    var aiBlock = document.getElementById('app-evidence-ai-block');
    var content = document.getElementById('app-evidence-ai-content');
    if (!aiBlock || !content) return;

    try {
      await (ctx.getApiReady ? ctx.getApiReady() : Promise.resolve());
      var res = await ctx.apiFetch('/api/timelapse-analysis-load/' + encodeURIComponent(instanceId));
      state.analysis = await res.json();
      var _er = ctx.er();
      if (state.analysis && (state.analysis.observations || state.analysis.summary)) {
        aiBlock.hidden = false;
        if (typeof _er.renderEvidenceAnalysis === 'function') _er.renderEvidenceAnalysis(state.analysis);
      }
    } catch (e) {
      if (e && e.status && e.status !== 404) {
        console.warn('Failed to load saved analysis:', e.message || e);
      }
    }
  }

  async function requestAiAnalysis(ctx) {
    var state = ctx.state;
    var loading = document.getElementById('app-evidence-ai-loading');
    var content = document.getElementById('app-evidence-ai-content');
    var btn = document.getElementById('app-evidence-ai-btn');
    if (!loading || !content || !state.manifest) return;

    var originalLabel = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Analyzing…'; }
    loading.hidden = false;
    content.textContent = '';

    try {
      await (ctx.getApiReady ? ctx.getApiReady() : Promise.resolve());

      var ndviTimeseries = (state.manifest.ndvi_stats || []).map(function (f, i) {
        if (!f) return null;
        var fp = (state.manifest.frame_plan || [])[i] || {};
        return { date: f.datetime || fp.label, mean: f.mean, min: f.min, max: f.max, year: fp.year, season: fp.season };
      }).filter(Boolean);

      var wm = state.manifest.weather_monthly;
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

      var center = state.manifest.center || state.manifest.coords;
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

      var res = await ctx.apiFetch('/api/timelapse-analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      state.analysis = await res.json();
      var _er = ctx.er();
      if (typeof _er.renderEvidenceAnalysis === 'function') _er.renderEvidenceAnalysis(state.analysis);

      ctx.apiFetch('/api/timelapse-analysis-save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instance_id: state.instanceId, analysis: state.analysis })
      }).catch(function () {
        var saveWarn = document.getElementById('app-evidence-ai-content');
        if (saveWarn) saveWarn.appendChild(createCallout('warning', 'Analysis displayed but could not be saved. It will be lost on reload.'));
      });
    } catch (err) {
      content.textContent = '';
      content.appendChild(createCallout('error', (err && err.message) || 'Could not run AI analysis.'));
    } finally {
      loading.hidden = true;
      if (btn) { btn.disabled = false; btn.textContent = originalLabel; }
    }
  }

  function activeEvidenceContext(state) {
    if (!state.manifest) return null;
    var perAoi = state.manifest.per_aoi_enrichment || [];
    if (state.selectedAoi >= 0 && state.selectedAoi < perAoi.length) {
      return perAoi[state.selectedAoi];
    }
    return state.manifest;
  }

  function buildEvidenceNdviTimeseries(source, em) {
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

  function evidenceLatLon(source, em) {
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

  async function requestEudrAssessment(ctx) {
    var state = ctx.state;
    var loading = document.getElementById('app-evidence-eudr-loading');
    var content = document.getElementById('app-evidence-eudr-content');
    var btn = document.getElementById('app-evidence-eudr-btn');
    if (!loading || !content || !state.manifest) return;

    if (btn) btn.disabled = true;
    loading.hidden = false;
    content.textContent = '';

    try {
      await (ctx.getApiReady ? ctx.getApiReady() : Promise.resolve());

      var source = activeEvidenceContext(state);
      var ndviTimeseries = buildEvidenceNdviTimeseries(source, ctx.em);
      var latLon = evidenceLatLon(source, ctx.em);

      var body = {
        context: {
          aoi_name: source && source.name ? source.name : 'Analysis area',
          latitude: latLon.lat,
          longitude: latLon.lon,
          ndvi_timeseries: ndviTimeseries,
          reference_date: '2020-12-31'
        }
      };

      var res = await ctx.apiFetch('/api/eudr-assessment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      var result = await res.json();
      var cls = (result.compliant || result.deforestation_free) ? 'compliant' : 'non-compliant';
      var label = cls === 'compliant' ? '✓ No deforestation detected since Dec 2020' : '⚠ Potential deforestation detected';
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
      content.appendChild(createCallout('error', (err && err.message) || 'Could not run EUDR assessment.'));
    } finally {
      loading.hidden = true;
      if (btn) btn.disabled = false;
    }
  }

  window.CanopexEvidenceDisplayAi = {
    loadSavedAnalysis: loadSavedAnalysis,
    requestAiAnalysis: requestAiAnalysis,
    requestEudrAssessment: requestEudrAssessment
  };
})();
