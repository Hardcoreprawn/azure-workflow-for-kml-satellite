'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');

function loadGeo() {
  const context = vm.createContext({ window: {} });
  vm.runInContext(
    fs.readFileSync(path.join(root, 'website/js/canopex-geo.js'), 'utf8'),
    context,
    { filename: 'canopex-geo.js' }
  );
  return context.window.CanopexGeo;
}

const outer = [
  [36.8, -1.3],
  [36.81, -1.3],
  [36.81, -1.31],
  [36.8, -1.31],
  [36.8, -1.3]
];
const firstHole = [
  [36.802, -1.302],
  [36.804, -1.302],
  [36.804, -1.304],
  [36.802, -1.304],
  [36.802, -1.302]
];
const secondHole = [
  [36.805, -1.305],
  [36.807, -1.305],
  [36.807, -1.307],
  [36.805, -1.307],
  [36.805, -1.305]
];
const secondOuter = [
  [36.82, -1.3],
  [36.83, -1.3],
  [36.83, -1.31],
  [36.82, -1.31],
  [36.82, -1.3]
];

function geometry(parts) {
  return { parts, crs: 'EPSG:4326' };
}

test('converts one canonical polygon to Leaflet outer and multiple inner rings', () => {
  const geo = loadGeo();
  const result = geo.geometryLatLngs(geometry([{ outer, inners: [firstHole, secondHole] }]));

  assert.deepEqual(JSON.parse(JSON.stringify(result)), [
    outer.map(([lon, lat]) => [lat, lon]),
    firstHole.map(([lon, lat]) => [lat, lon]),
    secondHole.map(([lon, lat]) => [lat, lon])
  ]);
});

test('keeps each multipolygon part and its holes nested for Leaflet', () => {
  const geo = loadGeo();
  const result = geo.geometryLatLngs(geometry([
    { outer, inners: [firstHole, secondHole] },
    { outer: secondOuter, inners: [] }
  ]));

  assert.deepEqual(JSON.parse(JSON.stringify(result)), [
    [
      outer.map(([lon, lat]) => [lat, lon]),
      firstHole.map(([lon, lat]) => [lat, lon]),
      secondHole.map(([lon, lat]) => [lat, lon])
    ],
    [secondOuter.map(([lon, lat]) => [lat, lon])]
  ]);
});

test('bounds include all outer and inner rings for every part', () => {
  const geo = loadGeo();
  const bounds = {
    positions: [],
    extend(position) { this.positions.push(position); }
  };

  assert.equal(geo.extendBoundsWithGeometry(bounds, geometry([
    { outer, inners: [firstHole, secondHole] },
    { outer: secondOuter, inners: [] }
  ])), true);
  assert.equal(bounds.positions.length, outer.length + firstHole.length + secondHole.length + secondOuter.length);
  assert.ok(bounds.positions.some(([lat, lon]) => lat === -1.302 && lon === 36.802));
  assert.ok(bounds.positions.some(([lat, lon]) => lat === -1.3 && lon === 36.83));
});

test('returns no Leaflet rings for missing or invalid canonical geometry', () => {
  const geo = loadGeo();
  const validPart = { outer, inners: [] };
  const invalidCases = [
    null,
    {},
    { ...geometry([]), parts: [] },
    { ...geometry([validPart]), crs: 'EPSG:3857' },
    geometry([{ outer: outer.slice(0, -1), inners: [] }]),
    geometry([{ outer: [[0, 0], [1, 0], [0, 0], [0, 0]], inners: [] }]),
    geometry([{ outer: [[0, 0], [1, 0], [1, 1], [0, 0]], inners: [[[0, 0]]] }]),
    geometry([{ outer: [[0, 0], [181, 0], [1, 1], [0, 0]], inners: [] }])
  ];

  for (const value of invalidCases) {
    assert.deepEqual(JSON.parse(JSON.stringify(geo.geometryLatLngs(value))), []);
  }
});

test('invalid geometry does not change Leaflet bounds', () => {
  const geo = loadGeo();
  const bounds = { positions: [], extend(position) { this.positions.push(position); } };

  assert.equal(geo.extendBoundsWithGeometry(bounds, { parts: [], crs: 'EPSG:4326' }), false);
  assert.deepEqual(bounds.positions, []);
});
