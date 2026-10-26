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
    const raw = String(text || '').trim().split(/\s+/).filter(Boolean);
    const coords = raw.map(function (chunk) {
      const parts = chunk.split(',');
      if (parts.length < 2 || !parts[0].trim() || !parts[1].trim()) return [NaN, NaN];
      return [Number(parts[1]), Number(parts[0])];
    });
    if (coords.some(function (coord) {
      return !Number.isFinite(coord[0]) || !Number.isFinite(coord[1]) ||
        coord[0] < -90 || coord[0] > 90 || coord[1] < -180 || coord[1] > 180;
    })) return null;
    if (coords.length < 3) return null;
    if (coords[0][0] !== coords[coords.length - 1][0] || coords[0][1] !== coords[coords.length - 1][1]) {
      coords.push(coords[0].slice());
    }
    return coords;
  }

  function parseKmlGeometry(text) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(text, 'text/xml');
    if (doc.getElementsByTagName('parsererror').length) {
      return { error: 'Could not parse the KML markup. Check that the XML is complete.' };
    }

    const placemarks = Array.from(doc.getElementsByTagName('Placemark'));
    const polygons = [];
    for (const placemark of placemarks) {
      const parts = Array.from(placemark.getElementsByTagName('Polygon')).map(parsePolygonPart);
      if (parts.some(function (part) { return part === null; })) {
        return { error: 'A polygon boundary is incomplete. Check the outer and inner rings.' };
      }
      if (!parts.length) continue;
      const geometry = { parts: parts, crs: 'EPSG:4326' };
      if (!geometryLatLngs(geometry).length) {
        return { error: 'A polygon contains an invalid ring. Check its coordinates.' };
      }
      const nameEl = placemark.getElementsByTagName('name')[0];
      polygons.push({
        name: nameEl ? nameEl.textContent.trim() : 'Polygon ' + (polygons.length + 1),
        geometry: geometry
      });
    }

    return {
      featureCount: placemarks.length || polygons.length,
      polygons: polygons,
    };
  }

  function parseBoundary(boundary) {
    const coordinate = boundary && boundary.getElementsByTagName('coordinates')[0];
    const coords = coordinate && parseCoordText(coordinate.textContent);
    return coords ? coords.map(function (point) { return [point[1], point[0]]; }) : null;
  }

  function parsePolygonPart(polygon) {
    const outer = parseBoundary(polygon.getElementsByTagName('outerBoundaryIs')[0]);
    const inners = Array.from(polygon.getElementsByTagName('innerBoundaryIs')).map(parseBoundary);
    if (!outer || inners.some(function (ring) { return ring === null; })) return null;
    return { outer: outer, inners: inners };
  }

  function geometryAreaHa(geometry) {
    return geometry.parts.reduce(function (total, part) {
      const ringArea = function (ring) {
        return polygonAreaHa(ring.map(function (position) { return [position[1], position[0]]; }));
      };
      return total + ringArea(part.outer) - part.inners.reduce(function (sum, ring) { return sum + ringArea(ring); }, 0);
    }, 0);
  }

  function geometryCentroid(geometry) {
    const points = geometry.parts.flatMap(function (part) { return part.outer.slice(0, -1); });
    const lon = points.reduce(function (sum, point) { return sum + point[0]; }, 0) / points.length;
    const lat = points.reduce(function (sum, point) { return sum + point[1]; }, 0) / points.length;
    return [lat, lon];
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

  function geometryLatLngs(geometry) {
    if (!geometry || geometry.crs !== 'EPSG:4326' ||
        !Array.isArray(geometry.parts) || !geometry.parts.length) return [];

    var polygons = [];
    for (var partIndex = 0; partIndex < geometry.parts.length; partIndex++) {
      var part = geometry.parts[partIndex];
      if (!part || !Array.isArray(part.outer) || !Array.isArray(part.inners)) return [];

      var rings = [part.outer].concat(part.inners);
      var latLngRings = [];
      for (var ringIndex = 0; ringIndex < rings.length; ringIndex++) {
        var ring = rings[ringIndex];
        if (!Array.isArray(ring) || ring.length < 4) return [];
        if (!samePosition(ring[0], ring[ring.length - 1])) return [];

        var latLngRing = [];
        var uniquePositions = new Set();
        for (var positionIndex = 0; positionIndex < ring.length; positionIndex++) {
          var position = ring[positionIndex];
          if (!Array.isArray(position) || position.length !== 2 ||
              !Number.isFinite(position[0]) || !Number.isFinite(position[1]) ||
              position[0] < -180 || position[0] > 180 ||
              position[1] < -90 || position[1] > 90) return [];
          if (positionIndex < ring.length - 1) {
            uniquePositions.add(position[0] + ',' + position[1]);
          }
          latLngRing.push([position[1], position[0]]);
        }
        if (uniquePositions.size < 3) return [];
        latLngRings.push(latLngRing);
      }
      polygons.push(latLngRings);
    }

    return polygons.length === 1 ? polygons[0] : polygons;
  }

  function samePosition(first, second) {
    return Array.isArray(first) && Array.isArray(second) &&
      first.length === 2 && second.length === 2 &&
      first[0] === second[0] && first[1] === second[1];
  }

  function extendBoundsWithGeometry(bounds, geometry) {
    if (!bounds || typeof bounds.extend !== 'function') return false;

    var latLngs = geometryLatLngs(geometry);
    if (!latLngs.length) return false;

    var polygons = geometry.parts.length === 1 ? [latLngs] : latLngs;
    var rings = [];
    polygons.forEach(function (polygon) {
      polygon.forEach(function (ring) { rings.push(ring); });
    });
    rings.forEach(function (ring) {
      ring.forEach(function (position) { bounds.extend(position); });
    });
    return true;
  }

  function determineProcessingMode(aoiCount, maxSpreadKm) {
    if (aoiCount > 30 || maxSpreadKm > 100) return 'May batch';
    if (aoiCount > 6 || maxSpreadKm > 25) return 'Bulk-ready';
    return 'Single run';
  }

  /**
   * Parse name/lat/lon rows from CSV text.
   * Accepts an optional header row detected by the presence of "name" and "lat"/"lon".
   *
   * @param {string} text - raw CSV text from user input
   * @returns {{ plots: Array<{ name: string, lat: number, lon: number }>, errors: string[] }}
   */
  function parseCSVCoordinates(text) {
    var lines = text.trim().split(/\r?\n/).filter(Boolean);
    if (lines.length === 0) return { plots: [], errors: ['No data entered'] };

    var plots = [];
    var errors = [];
    var startIdx = 0;

    // Detect header row
    var firstLine = lines[0].toLowerCase().replace(/\s/g, '');
    if (firstLine.indexOf('name') >= 0 && (firstLine.indexOf('lat') >= 0 || firstLine.indexOf('lon') >= 0)) {
      startIdx = 1;
    }

    for (var i = startIdx; i < lines.length; i++) {
      var parts = lines[i].split(',').map(function(s) { return s.trim(); });
      if (parts.length < 3) {
        errors.push('Row ' + (i + 1) + ': expected name, lat, lon — got ' + parts.length + ' columns');
        continue;
      }
      var name = parts[0] || 'Parcel ' + (plots.length + 1);
      var lat = parseFloat(parts[1]);
      var lon = parseFloat(parts[2]);
      if (isNaN(lat) || isNaN(lon)) {
        errors.push('Row ' + (i + 1) + ': invalid coordinates (' + parts[1] + ', ' + parts[2] + ')');
        continue;
      }
      if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        errors.push('Row ' + (i + 1) + ': coordinates out of range (lat: ' + lat + ', lon: ' + lon + ')');
        continue;
      }
      plots.push({ name: name, lat: lat, lon: lon });
    }
    return { plots: plots, errors: errors };
  }

  window.CanopexGeo = {
    escHtml: escHtml,
    parseKmlText: parseKmlText,
    parseCoordText: parseCoordText,
    parseKmlGeometry: parseKmlGeometry,
    haversineKm: haversineKm,
    polygonCentroid: polygonCentroid,
    polygonAreaHa: polygonAreaHa,
    geometryAreaHa: geometryAreaHa,
    geometryCentroid: geometryCentroid,
    geometryLatLngs: geometryLatLngs,
    extendBoundsWithGeometry: extendBoundsWithGeometry,
    formatDistance: formatDistance,
    formatHectares: formatHectares,
    determineProcessingMode: determineProcessingMode,
    parseCSVCoordinates: parseCSVCoordinates,
  };
})();
