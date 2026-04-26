/**
 * app-evidence-map.js
 *
 * Pure data helpers for the evidence map domain. No DOM, no Leaflet, no fetch.
 *
 * Exposes: window.CanopexEvidenceMap
 *
 * Contract:
 *   pickDefaultLayer(frame)              → 'rgb' | 'ndvi'
 *   pickInitialFrameIndex(frames)        → number
 *   buildNdviTimeseries(source)          → Array<{ date, mean, min, max, year, season }>
 *   latLon(source)                       → { lat: number, lon: number }
 */
(function () {
  'use strict';

  /**
   * Choose the default layer mode for a given evidence frame.
   * Returns 'ndvi' when the frame has an explicit preference, otherwise 'rgb'.
   *
   * @param {object|null} frame
   * @returns {'rgb'|'ndvi'}
   */
  function pickDefaultLayer(frame) {
    if (!frame) return 'rgb';
    if (frame.preferredLayer === 'ndvi' || frame.preferred_layer === 'ndvi') return 'ndvi';
    return 'rgb';
  }

  /**
   * Select the best initial frame index from an array of evidence map layers.
   *
   * Scoring priority (descending):
   *   1. rgbDisplaySuitable — frames where RGB is shown are preferred.
   *   2. displayResolutionM — lower resolution value wins (sharper imagery).
   *   3. recency — latest index wins when tied on resolution.
   *
   * @param {Array} frames - evidence map layer descriptors
   * @returns {number}
   */
  function pickInitialFrameIndex(frames) {
    if (!Array.isArray(frames) || !frames.length) return 0;

    var bestIndex = 0;
    var bestScore = null;

    frames.forEach(function (frame, idx) {
      if (!frame) return;

      var rgbSuitable = frame.rgbDisplaySuitable !== false;
      var resolution = Number(frame.displayResolutionM || 9999);
      var score = {
        rgbSuitable: rgbSuitable ? 1 : 0,
        resolution: Number.isFinite(resolution) ? -resolution : -9999,
        recency: idx
      };

      if (!bestScore) {
        bestScore = score;
        bestIndex = idx;
        return;
      }

      if (score.rgbSuitable > bestScore.rgbSuitable) {
        bestScore = score;
        bestIndex = idx;
        return;
      }

      if (score.rgbSuitable < bestScore.rgbSuitable) return;

      if (score.resolution > bestScore.resolution) {
        bestScore = score;
        bestIndex = idx;
        return;
      }

      if (score.resolution === bestScore.resolution && score.recency > bestScore.recency) {
        bestScore = score;
        bestIndex = idx;
      }
    });

    return bestIndex;
  }

  /**
   * Build a normalised NDVI time-series array from an evidence source object.
   * Works for both the top-level manifest and per-AOI enrichment entries.
   *
   * @param {object|null} source - evidence manifest or per-AOI context
   * @returns {Array<{ date: string, mean: number, min: number, max: number, year, season }>}
   */
  function buildNdviTimeseries(source) {
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

  /**
   * Extract a { lat, lon } coordinate pair from an evidence source.
   * Falls back to { lat: 0, lon: 0 } when the source has no usable center.
   *
   * @param {object|null} source
   * @returns {{ lat: number, lon: number }}
   */
  function latLon(source) {
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

  window.CanopexEvidenceMap = {
    pickDefaultLayer: pickDefaultLayer,
    pickInitialFrameIndex: pickInitialFrameIndex,
    buildNdviTimeseries: buildNdviTimeseries,
    latLon: latLon
  };
})();
