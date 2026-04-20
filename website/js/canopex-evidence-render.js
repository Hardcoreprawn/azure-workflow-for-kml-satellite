/**
 * canopex-evidence-render.js — Pure evidence rendering functions.
 *
 * Extracted from app-shell.js. These functions take data and render
 * to DOM elements. No shell state, no API calls.
 * Depends on: CanopexHelpers (setStatGrid, createCallout).
 * Exposes window.CanopexEvidenceRender.
 */
(function () {
  'use strict';

  var setStatGrid = CanopexHelpers.setStatGrid;
  var createCallout = CanopexHelpers.createCallout;

  /* ---- NDVI evidence ---- */
  function renderEvidenceNdvi(manifest) {
    var grid = document.getElementById('app-evidence-ndvi-grid');
    var note = document.getElementById('app-evidence-ndvi-note');
    var canvas = document.getElementById('app-evidence-ndvi-canvas');
    if (!grid) return;

    var ndvi = (manifest.ndvi_stats || []).filter(function(f) { return f != null; });
    if (!ndvi.length) {
      setStatGrid(grid, [['Status', 'No NDVI data', '']]);
      return;
    }

    var means = ndvi.map(function(f) { return f.mean; }).filter(function(v) { return v != null && !isNaN(v); });
    var overallMean = means.length ? (means.reduce(function(a, b) { return a + b; }, 0) / means.length) : null;
    var overallMin = means.length ? Math.min.apply(null, means) : null;
    var overallMax = means.length ? Math.max.apply(null, means) : null;

    // Trajectory — prefer backend season-aware change detection
    var trajectory = 'Stable';
    var trajectoryTone = '';
    var cdSummary = manifest.change_detection && manifest.change_detection.summary;
    if (cdSummary && cdSummary.trajectory) {
      var t = cdSummary.trajectory;
      if (t === 'Improving') { trajectory = 'Improving \u2191'; trajectoryTone = 'positive'; }
      else if (t === 'Declining') { trajectory = 'Declining \u2193'; trajectoryTone = 'negative'; }
      else { trajectory = 'Stable'; trajectoryTone = ''; }
    } else if (means.length >= 4) {
      var firstHalf = means.slice(0, Math.floor(means.length / 2));
      var secondHalf = means.slice(Math.floor(means.length / 2));
      var avgFirst = firstHalf.reduce(function(a, b) { return a + b; }, 0) / firstHalf.length;
      var avgSecond = secondHalf.reduce(function(a, b) { return a + b; }, 0) / secondHalf.length;
      var delta = avgSecond - avgFirst;
      if (delta > 0.05) { trajectory = 'Improving \u2191'; trajectoryTone = 'positive'; }
      else if (delta < -0.05) { trajectory = 'Declining \u2193'; trajectoryTone = 'negative'; }
    }

    var meanLabel = overallMean != null ? overallMean.toFixed(3) : '\u2014';
    var meanTone = '';
    if (overallMean != null && overallMean > 0.4) meanTone = 'positive';
    else if (overallMean != null && overallMean < 0.2) meanTone = 'negative';
    var rangeLabel = overallMin != null ? overallMin.toFixed(2) + ' \u2013 ' + overallMax.toFixed(2) : '\u2014';

    setStatGrid(grid, [
      ['Mean NDVI', meanLabel, meanTone],
      ['Range', rangeLabel, ''],
      ['Trajectory', trajectory, trajectoryTone]
    ]);

    if (note) note.textContent = means.length + ' frames sampled across the analysis period.';

    // Draw sparkline
    if (canvas && means.length > 1) drawNdviSparkline(canvas, ndvi);
  }

  function drawNdviSparkline(canvas, ndviStats) {
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth;
    var h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    var means = ndviStats.map(function(f) { return f ? f.mean : null; });
    var valid = means.filter(function(v) { return v != null && !isNaN(v); });
    if (valid.length < 2) return;
    var minV = Math.min.apply(null, valid) - 0.05;
    var maxV = Math.max.apply(null, valid) + 0.05;
    var range = maxV - minV || 1;
    var pad = 4;

    // Background
    ctx.fillStyle = 'rgba(13,17,23,.4)';
    ctx.beginPath();
    ctx.roundRect(0, 0, w, h, 8);
    ctx.fill();

    // Line
    ctx.strokeStyle = 'rgba(63,185,80,.8)';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    var drawn = false;
    for (var i = 0; i < means.length; i++) {
      if (means[i] == null || isNaN(means[i])) continue;
      var x = pad + (i / (means.length - 1)) * (w - 2 * pad);
      var y = h - pad - ((means[i] - minV) / range) * (h - 2 * pad);
      if (!drawn) { ctx.moveTo(x, y); drawn = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Drop markers
    ctx.fillStyle = 'rgba(248,81,73,.9)';
    for (var j = 1; j < means.length; j++) {
      if (means[j] == null || means[j - 1] == null) continue;
      var drop = means[j] - means[j - 1];
      if (drop <= -0.1) {
        var dx = pad + (j / (means.length - 1)) * (w - 2 * pad);
        var dy = h - pad - ((means[j] - minV) / range) * (h - 2 * pad);
        ctx.beginPath();
        ctx.arc(dx, dy, 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  /* ---- Weather evidence ---- */
  function renderEvidenceWeather(manifest) {
    var grid = document.getElementById('app-evidence-weather-grid');
    var canvas = document.getElementById('app-evidence-weather-canvas');
    if (!grid) return;

    var monthly = manifest.weather_monthly;
    var daily = manifest.weather_daily;
    if (!monthly && !daily) {
      setStatGrid(grid, [['Status', 'No weather data', '']]);
      return;
    }

    var temps = [];
    var precips = [];
    var source = [];

    // weather_monthly may be { labels, temp, precip } parallel arrays
    if (monthly && monthly.labels && Array.isArray(monthly.labels)) {
      source = monthly.labels.map(function(lbl, i) {
        return {
          label: lbl,
          temperature: (monthly.temp && monthly.temp[i] != null) ? monthly.temp[i] : null,
          precipitation: (monthly.precip && monthly.precip[i] != null) ? monthly.precip[i] : null
        };
      });
    } else if (Array.isArray(monthly)) {
      source = monthly;
    }

    if (!source.length && daily) {
      // aggregate daily to monthly — daily may be { dates, temp, precip }
      var byMonth = {};
      var dates = daily.dates || daily.time || [];
      var dTemps = daily.temp || daily.temperature_2m_mean || [];
      var dPrecip = daily.precip || daily.precipitation_sum || [];
      dates.forEach(function(d, i) {
        var key = d.slice(0, 7);
        if (!byMonth[key]) byMonth[key] = { temps: [], precips: [] };
        if (dTemps[i] != null) byMonth[key].temps.push(dTemps[i]);
        if (dPrecip[i] != null) byMonth[key].precips.push(dPrecip[i]);
      });
      source = Object.keys(byMonth).sort().map(function(key) {
        var m = byMonth[key];
        return {
          label: key,
          temperature: m.temps.length ? m.temps.reduce(function(a, b) { return a + b; }, 0) / m.temps.length : null,
          precipitation: m.precips.length ? m.precips.reduce(function(a, b) { return a + b; }, 0) : null
        };
      });
    }

    source.forEach(function(m) {
      if (m.temperature != null) temps.push(m.temperature);
      if (m.precipitation != null) precips.push(m.precipitation);
    });

    var avgTemp = temps.length ? (temps.reduce(function(a, b) { return a + b; }, 0) / temps.length) : null;
    var totalPrecip = precips.reduce(function(a, b) { return a + b; }, 0);

    setStatGrid(grid, [
      ['Avg temp', avgTemp != null ? avgTemp.toFixed(1) + '\u00B0C' : '\u2014', ''],
      ['Total precip', totalPrecip ? Math.round(totalPrecip) + ' mm' : '\u2014', ''],
      ['Months', source.length + ' months', '']
    ]);

    if (canvas && source.length > 1) drawWeatherSparkline(canvas, source);
  }

  function drawWeatherSparkline(canvas, monthly) {
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth;
    var h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    var pad = 4;

    ctx.fillStyle = 'rgba(13,17,23,.4)';
    ctx.beginPath();
    ctx.roundRect(0, 0, w, h, 8);
    ctx.fill();

    var temps = monthly.map(function(m) { return m.temperature; });
    var precips = monthly.map(function(m) { return m.precipitation; });
    var validTemps = temps.filter(function(v) { return v != null; });
    var validPrecips = precips.filter(function(v) { return v != null; });
    var maxPrecip = validPrecips.length ? Math.max.apply(null, validPrecips) : 1;
    var minT = validTemps.length ? Math.min.apply(null, validTemps) - 2 : 0;
    var maxT = validTemps.length ? Math.max.apply(null, validTemps) + 2 : 30;

    // Precipitation bars
    var barW = Math.max(2, (w - 2 * pad) / monthly.length - 1);
    ctx.fillStyle = 'rgba(88,166,255,.35)';
    for (var i = 0; i < precips.length; i++) {
      if (precips[i] == null) continue;
      var bx = pad + (i / monthly.length) * (w - 2 * pad);
      var bh = (precips[i] / (maxPrecip || 1)) * (h - 2 * pad) * 0.8;
      ctx.fillRect(bx, h - pad - bh, barW, bh);
    }

    // Temperature line
    ctx.strokeStyle = 'rgba(210,153,34,.9)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    var drawn = false;
    for (var j = 0; j < temps.length; j++) {
      if (temps[j] == null) continue;
      var tx = pad + ((j + 0.5) / monthly.length) * (w - 2 * pad);
      var ty = h - pad - ((temps[j] - minT) / (maxT - minT)) * (h - 2 * pad);
      if (!drawn) { ctx.moveTo(tx, ty); drawn = true; } else ctx.lineTo(tx, ty);
    }
    ctx.stroke();
  }

  /* ---- Change detection ---- */
  function renderEvidenceChangeDetection(manifest) {
    var block = document.getElementById('app-evidence-change-block');
    var list = document.getElementById('app-evidence-change-list');
    if (!block || !list) return;

    var cd = manifest.change_detection;
    if (!cd || (!cd.season_changes && !cd.significant_changes && !cd.events && !cd.summary)) {
      block.hidden = true;
      return;
    }

    block.hidden = false;
    var items = cd.season_changes || cd.significant_changes || cd.events || [];

    // Summary may be an object { comparisons, total_loss_ha, total_gain_ha, avg_mean_delta, trajectory }
    if (cd.summary) {
      var s = cd.summary;
      var summaryText = typeof s === 'string' ? s :
        (s.trajectory || 'Stable') + ' \u2014 ' + (s.comparisons || 0) + ' comparisons, ' +
        'net loss ' + (s.total_loss_ha ? s.total_loss_ha.toFixed(0) + ' ha' : '\u2014') +
        ', net gain ' + (s.total_gain_ha ? s.total_gain_ha.toFixed(0) + ' ha' : '\u2014');
      var summaryDiv = document.createElement('div');
      summaryDiv.className = 'app-evidence-change-item positive';
      summaryDiv.textContent = summaryText;
      list.appendChild(summaryDiv);
    }

    // Show notable season changes (loss_pct > 20% or gain_pct > 20%)
    var notable = items.filter(function(item) {
      return typeof item === 'object' && (item.loss_pct > 20 || item.gain_pct > 20);
    });
    if (!notable.length && items.length > 3) notable = items.slice(0, 5);
    else if (!notable.length) notable = items;

    notable.forEach(function(item) {
      var text;
      if (typeof item === 'string') {
        text = item;
      } else if (item.label) {
        var parts = [item.label];
        if (item.mean_delta != null) parts.push('\u0394 ' + (item.mean_delta > 0 ? '+' : '') + item.mean_delta.toFixed(3));
        if (item.loss_pct != null) parts.push('loss ' + item.loss_pct + '%');
        if (item.gain_pct != null) parts.push('gain ' + item.gain_pct + '%');
        text = parts.join(' \u2014 ');
      } else {
        text = item.description || item.text || JSON.stringify(item);
      }
      var cls = 'app-evidence-change-item';
      if (typeof item === 'object' && (item.gain_pct > item.loss_pct || item.mean_delta > 0.02)) cls += ' positive';
      var el = document.createElement('div');
      el.className = cls;
      el.textContent = text;
      list.appendChild(el);
    });
  }

  /* ---- AI analysis rendering ---- */
  function renderEvidenceAnalysis(analysis) {
    var content = document.getElementById('app-evidence-ai-content');
    if (!content) return;
    content.textContent = '';

    if (analysis.summary) {
      var summaryEl = document.createElement('div');
      summaryEl.className = 'app-evidence-summary';
      summaryEl.textContent = analysis.summary;
      content.appendChild(summaryEl);
    }

    (analysis.observations || []).forEach(function(obs) {
      var card = document.createElement('div');
      card.className = 'app-evidence-obs';

      var header = document.createElement('div');
      header.className = 'app-evidence-obs-header';

      var cat = document.createElement('span');
      cat.className = 'app-evidence-obs-category';
      cat.textContent = (obs.category || 'observation').replace(/_/g, ' ');

      var sev = document.createElement('span');
      sev.className = 'app-evidence-obs-severity severity-' + (obs.severity || 'normal');
      sev.textContent = obs.severity || 'normal';

      header.appendChild(cat);
      header.appendChild(sev);
      card.appendChild(header);

      if (obs.description) {
        var desc = document.createElement('p');
        desc.textContent = obs.description;
        card.appendChild(desc);
      }
      if (obs.recommendation) {
        var rec = document.createElement('p');
        rec.className = 'obs-recommendation';
        rec.textContent = '\uD83D\uDCA1 ' + obs.recommendation;
        card.appendChild(rec);
      }

      content.appendChild(card);
    });
  }

  /* ---- Planetary Computer tile URLs ---- */
  function pcTileUrl(searchId, collection, asset) {
    asset = asset || 'visual';
    return 'https://planetarycomputer.microsoft.com/api/data/v1/mosaic/tiles/' +
      encodeURIComponent(searchId) + '/WebMercatorQuad/{z}/{x}/{y}@2x?' +
      'collection=' + encodeURIComponent(collection) + '&assets=' + encodeURIComponent(asset);
  }

  function pcNdviTileUrl(searchId) {
    return 'https://planetarycomputer.microsoft.com/api/data/v1/mosaic/tiles/' +
      encodeURIComponent(searchId) + '/WebMercatorQuad/{z}/{x}/{y}@2x?' +
      'collection=sentinel-2-l2a&expression=(B08-B04)/(B08%2BB04)&rescale=-0.2,0.8&colormap_name=rdylgn';
  }

  /* ---- Per-AOI detail rendering ---- */
  function renderAoiDetail(aoiData) {
    var nameEl = document.getElementById('app-evidence-aoi-detail-name');
    var grid = document.getElementById('app-evidence-aoi-detail-grid');
    var detEl = document.getElementById('app-evidence-aoi-determination');
    var detail = document.getElementById('app-evidence-aoi-detail');
    if (!detail || !grid) return;

    detail.hidden = false;
    if (nameEl) nameEl.textContent = aoiData.name || 'Unnamed parcel';

    var stats = [];

    // Area
    if (aoiData.area_ha != null) {
      stats.push(['Area', aoiData.area_ha.toFixed(1) + ' ha', '']);
    }

    // NDVI from per-AOI enrichment
    var ndvi = (aoiData.ndvi_stats || []).filter(function(f) { return f != null; });
    var means = ndvi.map(function(f) { return f.mean; }).filter(function(v) { return v != null && !isNaN(v); });
    if (means.length) {
      var avg = means.reduce(function(a, b) { return a + b; }, 0) / means.length;
      var tone = avg > 0.4 ? 'positive' : avg < 0.2 ? 'negative' : '';
      stats.push(['NDVI', avg.toFixed(3), tone]);
    }

    // Weather from per-AOI enrichment
    var wd = aoiData.weather_daily;
    if (wd && wd.temp) {
      var temps = wd.temp.filter(function(t) { return t != null; });
      if (temps.length) {
        var avgT = temps.reduce(function(a, b) { return a + b; }, 0) / temps.length;
        stats.push(['Temp', avgT.toFixed(1) + '\u00B0C', '']);
      }
    }

    // Change detection
    var cd = aoiData.change_detection;
    if (cd && cd.summary) {
      var traj = cd.summary.trajectory || 'Stable';
      var trajTone = traj === 'Improving' ? 'positive' : traj === 'Declining' ? 'negative' : '';
      stats.push(['Trend', traj, trajTone]);
    }

    setStatGrid(grid, stats);

    // EUDR determination
    if (detEl) {
      var det = aoiData.determination;
      if (det) {
        detEl.hidden = false;
        detEl.className = 'app-evidence-aoi-determination ' +
          (det.deforestation_free ? 'compliant' : 'non-compliant');
        detEl.textContent = det.deforestation_free
          ? '\u2705 Deforestation-free (' + (det.confidence || 'medium') + ' confidence)'
          : '\u26A0\uFE0F Risk detected — ' + (det.reason || 'see full report');
        renderFlagCards(det.flags || []);
      } else {
        detEl.hidden = true;
        renderFlagCards([]);
      }
    }
  }

  // ── Flag severity classification and rendering ─────────────
  var FLAG_RULES = [
    { pattern: /vegetation loss/i, severity: 'high', source: 'Change detection', action: 'Compare RGB imagery in the timeline to verify the loss area.' },
    { pattern: /NDVI trajectory is declining/i, severity: 'high', source: 'NDVI analysis', action: 'Check the weather panel for drought correlation before concluding deforestation.' },
    { pattern: /Mean NDVI delta/i, severity: 'moderate', source: 'NDVI analysis', action: 'Review the NDVI time series for seasonal patterns vs permanent loss.' },
    { pattern: /WDPA protected area/i, severity: 'info', source: 'WDPA overlay', action: 'Verify the parcel boundary does not overlap a protected area buffer zone.' },
    { pattern: /IO LULC.*land-cover change/i, severity: 'moderate', source: 'IO Annual LULC', action: 'Review the IO LULC transition data for the specific land-cover class change.' },
    { pattern: /IO LULC.*tree cover.*declining/i, severity: 'high', source: 'IO Annual LULC', action: 'Cross-reference with WorldCover baseline to confirm tree cover loss timeline.' },
    { pattern: /ALOS.*forest/i, severity: 'moderate', source: 'ALOS FNF', action: 'Compare ALOS forest/non-forest classification with Sentinel-2 imagery.' }
  ];

  function classifyFlag(flagText) {
    for (var i = 0; i < FLAG_RULES.length; i++) {
      var rule = FLAG_RULES[i];
      if (rule.pattern.test(flagText)) {
        return { text: flagText, severity: rule.severity, source: rule.source, action: rule.action };
      }
    }
    return { text: flagText, severity: 'info', source: 'Assessment', action: '' };
  }

  function renderFlagCards(flags) {
    var container = document.getElementById('app-evidence-flags');
    if (!container) return;
    container.textContent = '';

    if (!flags || !flags.length) {
      container.hidden = true;
      return;
    }
    container.hidden = false;

    var classified = flags.map(classifyFlag);
    var highCount = classified.filter(function(f) { return f.severity === 'high'; }).length;
    var modCount = classified.filter(function(f) { return f.severity === 'moderate'; }).length;
    var infoCount = classified.filter(function(f) { return f.severity === 'info'; }).length;

    // Summary banner
    var banner = document.createElement('div');
    var bannerStateClass = 'info-only';
    if (highCount > 0) {
      bannerStateClass = 'has-high';
    } else if (modCount > 0) {
      bannerStateClass = 'moderate-only';
    }
    banner.className = 'app-flag-banner ' + bannerStateClass;
    var parts = [];
    if (highCount > 0) parts.push(highCount + ' high concern');
    if (modCount > 0) parts.push(modCount + ' moderate');
    if (infoCount > 0) parts.push(infoCount + ' informational');
    banner.textContent = flags.length + ' flag' + (flags.length !== 1 ? 's' : '') + ' raised \u2014 ' + parts.join(', ');
    container.appendChild(banner);

    // Individual flag cards
    classified.forEach(function(flag) {
      var card = document.createElement('div');
      card.className = 'app-flag-card';

      var header = document.createElement('div');
      header.className = 'flag-header';

      var badge = document.createElement('span');
      badge.className = 'app-flag-badge ' + flag.severity;
      var badgeLabel = 'Info';
      if (flag.severity === 'high') {
        badgeLabel = 'High';
      } else if (flag.severity === 'moderate') {
        badgeLabel = 'Moderate';
      }
      badge.textContent = badgeLabel;
      header.appendChild(badge);

      var text = document.createElement('span');
      text.textContent = flag.text;
      header.appendChild(text);

      card.appendChild(header);

      if (flag.source) {
        var source = document.createElement('div');
        source.className = 'flag-source';
        source.textContent = 'Source: ' + flag.source;
        card.appendChild(source);
      }

      if (flag.action) {
        var action = document.createElement('div');
        action.className = 'flag-action';
        action.textContent = '\uD83D\uDCA1 ' + flag.action;
        card.appendChild(action);
      }

      container.appendChild(card);
    });
  }

  function clearAoiDetail() {
    var detail = document.getElementById('app-evidence-aoi-detail');
    var grid = document.getElementById('app-evidence-aoi-detail-grid');
    var detEl = document.getElementById('app-evidence-aoi-determination');
    var flagsEl = document.getElementById('app-evidence-flags');
    if (detail) detail.hidden = true;
    if (grid) grid.textContent = '';
    if (detEl) { detEl.hidden = true; detEl.textContent = ''; }
    if (flagsEl) { flagsEl.hidden = true; flagsEl.textContent = ''; }
  }

  /* ---- Resources consumed evidence card (#666) ---- */
  function renderResourceUsage(manifest) {
    var block = document.getElementById('app-evidence-resources-block');
    var grid = document.getElementById('app-evidence-resources-grid');
    var note = document.getElementById('app-evidence-resources-note');
    if (!block || !grid) return;

    var usage = manifest.resource_usage;
    if (!usage) return;

    block.hidden = false;
    var items = [];
    var sources = usage.data_sources_queried || [];
    if (sources.length) items.push(['Data sources', String(sources.length), '']);

    var apiTotal = 0;
    var calls = usage.api_calls || {};
    for (var svc in calls) { if (calls.hasOwnProperty(svc)) apiTotal += calls[svc]; }
    if (apiTotal) items.push(['API calls', String(apiTotal), '']);

    if (usage.sentinel2_scenes_registered) items.push(['Sentinel-2 scenes', String(usage.sentinel2_scenes_registered), '']);
    if (usage.landsat_scenes_sampled) items.push(['Landsat scenes', String(usage.landsat_scenes_sampled), '']);
    if (usage.ndvi_computations) items.push(['NDVI computations', String(usage.ndvi_computations), '']);
    if (usage.mosaic_registrations) items.push(['Mosaic registrations', String(usage.mosaic_registrations), '']);
    if (usage.change_detection_comparisons) items.push(['Change comparisons', String(usage.change_detection_comparisons), '']);
    if (usage.per_aoi_enrichments) items.push(['Per-parcel enrichments', String(usage.per_aoi_enrichments), '']);

    if (!items.length) return;
    setStatGrid(grid, items);

    // Cost note — only for logged-in users with cost visibility
    var costPence = manifest.estimated_cost_pence;
    if (note && typeof costPence === 'number' && costPence > 0) {
      note.textContent = 'Est. platform cost: \u00A3' + (costPence / 100).toFixed(2);
    }
  }

  window.CanopexEvidenceRender = {
    renderEvidenceNdvi: renderEvidenceNdvi,
    drawNdviSparkline: drawNdviSparkline,
    renderEvidenceWeather: renderEvidenceWeather,
    drawWeatherSparkline: drawWeatherSparkline,
    renderEvidenceChangeDetection: renderEvidenceChangeDetection,
    renderEvidenceAnalysis: renderEvidenceAnalysis,
    pcTileUrl: pcTileUrl,
    pcNdviTileUrl: pcNdviTileUrl,
    renderAoiDetail: renderAoiDetail,
    clearAoiDetail: clearAoiDetail,
    renderResourceUsage: renderResourceUsage,
  };
})();
