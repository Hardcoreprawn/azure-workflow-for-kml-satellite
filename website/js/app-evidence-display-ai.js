/**
 * app-evidence-display-ai.js
 *
 * AI analysis + EUDR assessment helpers for app-evidence-display.
 */
(function () {
  'use strict';

  function createCallout(type, message) {
    let helper = (window.CanopexHelpers || {}).createCallout;
    if (typeof helper === 'function') {
      return helper(type, message);
    }
    let d = document.createElement('div');
    d.className = 'callout callout-' + type;
    d.textContent = message;
    return d;
  }

  async function loadSavedAnalysis(instanceId, ctx) {
    let state = ctx.state;
    let aiBlock = document.getElementById('app-evidence-ai-block');
    let content = document.getElementById('app-evidence-ai-content');
    if (!aiBlock || !content) return;

    try {
      await (ctx.getApiReady ? ctx.getApiReady() : Promise.resolve());
      let res = await ctx.apiFetch('/api/timelapse-analysis-load/' + encodeURIComponent(instanceId));
      state.analysis = await res.json();
      let _er = ctx.er();
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
    let state = ctx.state;
    let loading = document.getElementById('app-evidence-ai-loading');
    let content = document.getElementById('app-evidence-ai-content');
    let btn = document.getElementById('app-evidence-ai-btn');
    if (!loading || !content || !state.manifest) return;

    let originalLabel = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Analyzing…'; }
    loading.hidden = false;
    content.textContent = '';

    try {
      await (ctx.getApiReady ? ctx.getApiReady() : Promise.resolve());

      const source = activeEvidenceContext(state);
      const ndviTimeseries = buildEvidenceNdviTimeseries(source, ctx.em);
      if (!ndviTimeseries.length) throw new Error('NDVI unavailable for this selection. No usable observations to analyse.');

      let wm = source.weather_monthly;
      let weatherTimeseries = [];
      if (wm && wm.labels && Array.isArray(wm.labels)) {
        weatherTimeseries = wm.labels.map(function (lbl, i) {
          return { month_index: i, label: lbl, temperature: wm.temp ? wm.temp[i] : null, precipitation: wm.precip ? wm.precip[i] : null };
        });
      } else if (Array.isArray(wm)) {
        weatherTimeseries = wm.map(function (m, i) {
          return { month_index: i, temperature: m.temperature, precipitation: m.precipitation };
        });
      }

      const latLon = evidenceLatLon(source, ctx.em);

      let body = {
        context: {
          aoi_name: source.name || 'Analysis area',
          latitude: latLon.lat,
          longitude: latLon.lon,
          frame_count: ndviTimeseries.length,
          date_range_start: ndviTimeseries.length ? ndviTimeseries[0].date : '',
          date_range_end: ndviTimeseries.length ? ndviTimeseries[ndviTimeseries.length - 1].date : '',
          ndvi_timeseries: ndviTimeseries,
          weather_timeseries: weatherTimeseries
        }
      };

      let res = await ctx.apiFetch('/api/timelapse-analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      state.analysis = await res.json();
      let _er = ctx.er();
      if (typeof _er.renderEvidenceAnalysis === 'function') _er.renderEvidenceAnalysis(state.analysis);

      ctx.apiFetch('/api/timelapse-analysis-save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instance_id: state.instanceId, analysis: state.analysis })
      }).catch(function () {
        let saveWarn = document.getElementById('app-evidence-ai-content');
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
    let perAoi = state.manifest.per_aoi_enrichment || [];
    if (perAoi.length === 1) return perAoi[0];
    if (state.selectedAoi >= 0 && state.selectedAoi < perAoi.length) {
      return perAoi[state.selectedAoi];
    }
    return state.manifest;
  }

  function buildEvidenceNdviTimeseries(source, em) {
    return em().buildNdviTimeseries(source);
  }

  function evidenceLatLon(source, em) {
    let _em = em();
    if (typeof _em.latLon === 'function') {
      return _em.latLon(source);
    }
    if (!source) return { lat: 0, lon: 0 };
    let center = source.center;
    return {
      lat: (center && (center.lat || center.latitude)) || 0,
      lon: (center && (center.lon || center.longitude)) || 0
    };
  }

  async function requestEudrAssessment(ctx) {
    let state = ctx.state;
    let loading = document.getElementById('app-evidence-eudr-loading');
    let content = document.getElementById('app-evidence-eudr-content');
    let btn = document.getElementById('app-evidence-eudr-btn');
    if (!loading || !content || !state.manifest) return;

    if (btn) btn.disabled = true;
    loading.hidden = false;
    content.textContent = '';

    try {
      await (ctx.getApiReady ? ctx.getApiReady() : Promise.resolve());

      let source = activeEvidenceContext(state);
      let ndviTimeseries = buildEvidenceNdviTimeseries(source, ctx.em);
      let latLon = evidenceLatLon(source, ctx.em);

      let body = {
        context: {
          aoi_name: source && source.name ? source.name : 'Analysis area',
          latitude: latLon.lat,
          longitude: latLon.lon,
          ndvi_timeseries: ndviTimeseries,
          reference_date: '2020-12-31'
        }
      };

      let res = await ctx.apiFetch('/api/eudr-assessment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      let result = await res.json();
      let outcome = result && result.screening_outcome;
      let cls = 'screening-insufficient';
      let label = 'Insufficient evidence for screening';
      if (outcome === 'no_signal_detected') {
        cls = 'screening-no-signal';
        label = 'No deforestation signal detected';
      } else if (outcome === 'signal_detected') {
        cls = 'screening-signal';
        label = 'Deforestation signal detected';
      } else if (outcome === 'error') {
        cls = 'screening-error';
        label = 'Screening unavailable';
      }
      if (typeof result.confidence === 'string' && result.confidence.trim()) {
        label += ' (' + result.confidence.trim() + ' confidence)';
      }
      content.textContent = '';
      let resultDiv = document.createElement('div');
      resultDiv.className = 'app-evidence-eudr-result ' + cls;
      let strong = document.createElement('strong');
      strong.textContent = label;
      resultDiv.appendChild(strong);
      if (result.summary) {
        let p = document.createElement('p');
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
