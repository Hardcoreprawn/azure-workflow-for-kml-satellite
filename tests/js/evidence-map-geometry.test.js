'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');

function renderGeometry(manifest) {
  const polygonInputs = [];
  const map = {
    setView() { return this; },
    fitBounds() {},
    invalidateSize() {},
    remove() {}
  };
  const bounds = {
    extend() { return this; },
    isValid() { return true; },
    pad() { return this; }
  };
  const elements = new Map([
    ['app-evidence-map', {}],
    ['app-evidence-map-overlay', { hidden: false }],
    ['app-evidence-frame-controls', { hidden: true }]
  ]);
  const context = vm.createContext({
    window: {},
    document: {
      getElementById: id => elements.get(id) || null,
      createElement: () => ({ textContent: '' })
    },
    L: {
      map: () => map,
      tileLayer: () => ({ addTo() {} }),
      latLngBounds: () => bounds,
      polygon: latLngs => {
        polygonInputs.push(latLngs);
        return {
          addTo() { return this; },
          bindTooltip() {},
          on() {},
          getBounds: () => bounds
        };
      }
    },
    setTimeout: () => 0
  });
  vm.runInContext(
    fs.readFileSync(path.join(root, 'website/js/app-evidence-display-map.js'), 'utf8'),
    context,
    { filename: 'app-evidence-display-map.js' }
  );
  context.window.CanopexEvidenceDisplayMap.initEvidenceMap(manifest, {
    state: {},
    em: () => ({})
  });
  return polygonInputs;
}

function compareBounds(manifest) {
  const bounds = {
    points: [],
    extend(point) { this.points.push(point); return this; },
    isValid() { return this.points.length > 0; },
    pad() { return this; }
  };
  const map = {
    setView() { return this; },
    on() {},
    fitBounds() {},
    invalidateSize() {},
    remove() {}
  };
  const elements = new Map([
    ['app-evidence-map-wrap', { hidden: false }],
    ['app-evidence-compare-wrap', { hidden: true }],
    ['app-evidence-compare-map-before', {}],
    ['app-evidence-compare-map-after', {}]
  ]);
  const context = vm.createContext({
    window: {},
    document: { getElementById: id => elements.get(id) || null },
    L: {
      map: () => map,
      tileLayer: () => ({ addTo() {} }),
      latLngBounds: () => bounds
    },
    setTimeout: () => 0
  });
  vm.runInContext(
    fs.readFileSync(path.join(root, 'website/js/app-evidence-display-selection.js'), 'utf8'),
    context,
    { filename: 'app-evidence-display-selection.js' }
  );
  context.window.CanopexEvidenceDisplaySelection.toggleCompareView({
    state: { manifest },
    er: () => ({ pcTileUrl: () => '' })
  });
  return JSON.parse(JSON.stringify(bounds.points));
}

test('renders stored polygon interior rings as Leaflet holes', () => {
  const outer = [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.3]];
  const hole = [[36.802, -1.302], [36.804, -1.302], [36.803, -1.304], [36.802, -1.302]];
  const [rendered] = renderGeometry({
    center: [-1.3, 36.8],
    per_aoi_enrichment: [{ geometry: { type: 'Polygon', coordinates: [outer, hole] } }]
  });

  assert.deepEqual(JSON.parse(JSON.stringify(rendered)), [
    outer.map(([lon, lat]) => [lat, lon]),
    hole.map(([lon, lat]) => [lat, lon])
  ]);
});

test('renders legacy coords when stored geometry is absent', () => {
  const coords = [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.3]];
  const [rendered] = renderGeometry({ center: [-1.3, 36.8], coords });

  assert.deepEqual(JSON.parse(JSON.stringify(rendered)), [coords.map(([lon, lat]) => [lat, lon])]);
});

test('uses top-level coords when a legacy per-AOI entry has no geometry', () => {
  const coords = [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.3]];
  const [rendered] = renderGeometry({
    center: [-1.3, 36.8],
    coords,
    per_aoi_enrichment: [{ name: 'Legacy parcel' }]
  });

  assert.deepEqual(JSON.parse(JSON.stringify(rendered)), [coords.map(([lon, lat]) => [lat, lon])]);
});

test('renders canonical rings for each parcel on a multi-AOI map', () => {
  const outer = [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.3]];
  const hole = [[36.802, -1.302], [36.804, -1.302], [36.803, -1.304], [36.802, -1.302]];
  const other = [[36.82, -1.3], [36.83, -1.3], [36.83, -1.31], [36.82, -1.3]];
  const rendered = renderGeometry({
    center: [-1.3, 36.8],
    per_aoi_enrichment: [
      { geometry: { type: 'Polygon', coordinates: [outer, hole] } },
      { geometry: { type: 'Polygon', coordinates: [other] } }
    ]
  });

  assert.equal(rendered.length, 2);
  assert.deepEqual(JSON.parse(JSON.stringify(rendered[0])), [
    outer.map(([lon, lat]) => [lat, lon]),
    hole.map(([lon, lat]) => [lat, lon])
  ]);
  assert.deepEqual(JSON.parse(JSON.stringify(rendered[1])), [other.map(([lon, lat]) => [lat, lon])]);
});

test('compare bounds use canonical geometry and legacy coords fallback', () => {
  const outer = [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.3]];
  const staleCoords = [[0, 0], [1, 0], [1, 1], [0, 0]];
  const legacyCoords = [[37.8, -2.3], [37.81, -2.3], [37.81, -2.31], [37.8, -2.3]];

  const points = compareBounds({
    center: [-1.3, 36.8],
    search_ids: ['before', 'after'],
    per_aoi_enrichment: [
      { geometry: { type: 'Polygon', coordinates: [outer] }, coords: staleCoords },
      { coords: legacyCoords }
    ]
  });

  assert.deepEqual(points, [
    [-1.3, 36.8], [-1.3, 36.81], [-1.31, 36.81], [-1.3, 36.8],
    [-2.3, 37.8], [-2.3, 37.81], [-2.31, 37.81], [-2.3, 37.8]
  ]);
});
