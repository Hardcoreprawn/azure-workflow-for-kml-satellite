/**
 * canopex-geo.js — Pure geo/parsing utilities.
 *
 * Extracted from app-shell.js. No DOM state, no auth, no side effects.
 * Exposes window.CanopexGeo for consumption by app-shell.js.
 */
(function () {
  'use strict';

  function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function parseKmlText(text) {
    if (!text) return '';
    return String(text).trim();
  }

  function parseCoordText(text) {
    var raw = String(text || '').trim().split(/\s+/).filter(Boolean);
    var coords = raw.map(function (chunk) {
      var parts = chunk.split(',');
      return [parseFloat(parts[1]), parseFloat(parts[0])];
    }).filter(function (coord) {
      return !isNaN(coord[0]) && !isNaN(coord[1]);
    });
    if (coords.length < 3) return null;
    if (coords[0][0] !== coords[coords.length - 1][0] || coords[0][1] !== coords[coords.length - 1][1]) {
      coords.push(coords[0].slice());
    }
    return coords;
  }

  function parseKmlGeometry(text) {
    var parser = new DOMParser();
    var doc = parser.parseFromString(text, 'text/xml');
    if (doc.getElementsByTagName('parsererror').length) {
      return { error: 'Could not parse the KML markup. Check that the XML is complete.' };
    }

    var placemarks = doc.getElementsByTagName('Placemark');
    var polygons = [];
    for (var p = 0; p < placemarks.length; p++) {
      var nameEl = placemarks[p].getElementsByTagName('name')[0];
      var polygonName = nameEl ? nameEl.textContent.trim() : 'Polygon ' + (polygons.length + 1);
      // Only extract outer boundary coordinates — inner boundaries (holes)
      // must not be counted as separate polygons (#580).
      var outerEls = placemarks[p].getElementsByTagName('outerBoundaryIs');
      if (outerEls.length) {
        for (var o = 0; o < outerEls.length; o++) {
          var outerCoordEls = outerEls[o].getElementsByTagName('coordinates');
          for (var c = 0; c < outerCoordEls.length; c++) {
            var coords = parseCoordText(outerCoordEls[c].textContent);
            if (coords) polygons.push({ name: polygonName, coords: coords });
          }
        }
      } else {
        var coordEls = placemarks[p].getElementsByTagName('coordinates');
        for (var c = 0; c < coordEls.length; c++) {
          var coords = parseCoordText(coordEls[c].textContent);
          if (coords) polygons.push({ name: polygonName, coords: coords });
        }
      }
    }

    if (!polygons.length) {
      var allCoords = doc.getElementsByTagName('coordinates');
      for (var i = 0; i < allCoords.length; i++) {
        var fallbackCoords = parseCoordText(allCoords[i].textContent);
        if (fallbackCoords) polygons.push({ name: 'Polygon ' + (polygons.length + 1), coords: fallbackCoords });
      }
    }

    return {
      featureCount: placemarks.length || polygons.length,
      polygons: polygons,
    };
  }

  function haversineKm(lat1, lon1, lat2, lon2) {
    var radiusKm = 6371;
    var dLat = (lat2 - lat1) * Math.PI / 180;
    var dLon = (lon2 - lon1) * Math.PI / 180;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
      Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return radiusKm * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  function polygonCentroid(coords) {
    var latTotal = 0;
    var lonTotal = 0;
    var count = coords.length - 1;
    for (var i = 0; i < count; i++) {
      latTotal += coords[i][0];
      lonTotal += coords[i][1];
    }
    return [latTotal / count, lonTotal / count];
  }

  function polygonAreaHa(coords) {
    if (!coords || coords.length < 4) return 0;
    var usable = coords.slice(0, -1);
    var meanLat = usable.reduce(function (sum, coord) { return sum + coord[0]; }, 0) / usable.length;
    var metresPerDegreeLat = 111320;
    var metresPerDegreeLon = Math.cos(meanLat * Math.PI / 180) * metresPerDegreeLat;
    var areaM2 = 0;
    for (var i = 0; i < coords.length - 1; i++) {
      var x1 = coords[i][1] * metresPerDegreeLon;
      var y1 = coords[i][0] * metresPerDegreeLat;
      var x2 = coords[i + 1][1] * metresPerDegreeLon;
      var y2 = coords[i + 1][0] * metresPerDegreeLat;
      areaM2 += (x1 * y2) - (x2 * y1);
    }
    return Math.abs(areaM2) / 2 / 10000;
  }

  function formatDistance(km) {
    if (km == null || isNaN(km)) return '\u2014';
    if (km < 1) return '<1 km';
    return (km >= 10 ? km.toFixed(0) : km.toFixed(1)) + ' km';
  }

  function formatHectares(ha) {
    if (ha == null || isNaN(ha)) return '\u2014';
    if (ha < 1) return ha.toFixed(1) + ' ha';
    return Math.round(ha).toLocaleString() + ' ha';
  }

  function determineProcessingMode(aoiCount, maxSpreadKm) {
    if (aoiCount > 30 || maxSpreadKm > 100) return 'May batch';
    if (aoiCount > 6 || maxSpreadKm > 25) return 'Bulk-ready';
    return 'Single run';
  }

  window.CanopexGeo = {
    escHtml: escHtml,
    parseKmlText: parseKmlText,
    parseCoordText: parseCoordText,
    parseKmlGeometry: parseKmlGeometry,
    haversineKm: haversineKm,
    polygonCentroid: polygonCentroid,
    polygonAreaHa: polygonAreaHa,
    formatDistance: formatDistance,
    formatHectares: formatHectares,
    determineProcessingMode: determineProcessingMode,
  };
})();
