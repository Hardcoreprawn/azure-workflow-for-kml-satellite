'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(context, name) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../website/js', name), 'utf8'), context);
}

function element() {
  return { hidden: false, textContent: '', classList: { add() {}, remove() {}, toggle() {} } };
}

test('unavailable and nonfinite NDVI never enter evidence or AI timelines', () => {
  const nodes = new Map();
  const grid = element();
  nodes.set('app-evidence-ndvi-grid', grid);
  nodes.set('app-evidence-ndvi-note', element());
  nodes.set('app-evidence-ndvi-canvas', element());
  const context = vm.createContext({
    window: {},
    document: { getElementById: id => nodes.get(id) || null },
    CanopexHelpers: { setStatGrid(target, rows) { target.rows = rows; } }
  });
  load(context, 'app-evidence-map.js');
  load(context, 'canopex-evidence-render.js');
  const unavailable = [
    { available: false, reason: 'cloud_mask_unavailable', mean: 0.8, datetime: '2024-01-01' },
    { reason: 'no_pixels', datetime: '2024-02-01' },
    { mean: NaN }, { mean: Infinity }, { mean: '0.6' }, { mean: true }, null
  ];
  const manifest = { ndvi_stats: unavailable };
  assert.equal(context.window.CanopexEvidenceMap.buildNdviTimeseries(manifest).length, 0);
  context.window.CanopexEvidenceRender.renderEvidenceNdvi(manifest);
  assert.equal(grid.rows[0][1], 'NDVI unavailable');
  assert.match(nodes.get('app-evidence-ndvi-note').textContent, /cloud_mask_unavailable/);
  assert.equal(nodes.get('app-evidence-ndvi-canvas').hidden, true);
  const source = { ndvi_stats: [...unavailable, { mean: 0, datetime: '2024-03-01' }] };
  assert.equal(context.window.CanopexEvidenceMap.buildNdviTimeseries(source).length, 1);
  context.window.CanopexEvidenceRender.renderEvidenceNdvi(source);
  assert.equal(grid.rows[0][1], '0.000');
  assert.equal(grid.rows[2][1], 'Unavailable');
});

function xmlNode(tag, children = [], textContent = '') {
  return {
    tag, textContent,
    getElementsByTagName(name) {
      return children.flatMap(child => [
        ...(child.tag === name ? [child] : []),
        ...child.getElementsByTagName(name)
      ]);
    }
  };
}

function kmlPolygon(outer, holes = []) {
  const boundary = (tag, ring) => xmlNode(tag, [xmlNode('LinearRing', [
    xmlNode('coordinates', [], ring.map(position => position.join(',')).join(' '))
  ])]);
  return xmlNode('Polygon', [boundary('outerBoundaryIs', outer), ...holes.map(h => boundary('innerBoundaryIs', h))]);
}

test('preflight keeps multipart Placemarks as one AOI with holes excluded', () => {
  const outer = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]];
  const hole = [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]];
  const other = [[5, 0], [6, 0], [6, 1], [5, 1], [5, 0]];
  const doc = xmlNode('kml', [
    xmlNode('Placemark', [xmlNode('name', [], 'Multipart'), xmlNode('MultiGeometry', [
      kmlPolygon(outer, [hole]), kmlPolygon(other)
    ])]),
    xmlNode('Placemark', [xmlNode('name', [], 'Single'), kmlPolygon(other)])
  ]);
  const ids = ['headline', 'mode', 'summary', 'features', 'aois', 'spread', 'quota', 'cost'];
  const nodes = new Map(ids.map(id => [`app-preflight-${id}`, element()]));
  const context = vm.createContext({
    window: {}, DOMParser: class { parseFromString() { return doc; } },
    document: { getElementById: id => nodes.get(id) || null }
  });
  load(context, 'canopex-geo.js');
  const geo = context.window.CanopexGeo;
  const result = geo.parseKmlGeometry('fixture');
  assert.equal(result.polygons.length, 2);
  assert.equal(result.polygons[0].geometry.parts.length, 2);
  assert.equal(result.polygons[0].geometry.parts[0].inners.length, 1);
  const area = ring => geo.polygonAreaHa(ring.map(([lon, lat]) => [lat, lon]));
  const expectedArea = area(outer) - area(hole) + area(other);
  assert.ok(Math.abs(geo.geometryAreaHa(result.polygons[0].geometry) - expectedArea) < 0.001);
  assert.equal(geo.geometryLatLngs(result.polygons[0].geometry).length, 2);
  load(context, 'app-analysis-preflight.js');
  const costs = [];
  context.window.CanopexAnalysisPreflight.init({
    getActiveProfile: () => ({ enableParcelCostEstimate: true }),
    computeEudrCostEstimate: count => { costs.push(count); return 'estimate'; }
  });
  const preflight = context.window.CanopexAnalysisPreflight.updateAnalysisPreflight('fixture');
  assert.equal(preflight.aoiCount, 2);
  assert.equal(nodes.get('app-preflight-aois').textContent, '2');
  assert.deepEqual(costs, [2]);
});

test('malformed inner coordinates fail preflight instead of silently dropping a hole vertex', () => {
  const doc = xmlNode('kml', [xmlNode('Placemark', [kmlPolygon(
    [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
    [[[1, 1], ['bad', 1], [2, 2], [1, 2], [1, 1]]]
  )])]);
  const context = vm.createContext({ window: {}, DOMParser: class { parseFromString() { return doc; } } });
  load(context, 'canopex-geo.js');
  assert.match(context.window.CanopexGeo.parseKmlGeometry('fixture').error, /boundary is incomplete/);
});

test('parcel selection switches imagery and comparison without mutating the manifest', () => {
  const nodes = new Map();
  for (const id of ['app-evidence-compare-wrap', 'app-map-btn-compare', 'app-evidence-frame-controls']) {
    nodes.set(id, element());
  }
  const aoi = name => ({
    name, center: { lat: 0, lon: 0 }, geometry: { parts: [], crs: 'EPSG:4326' },
    frame_plan: [{ label: `${name} before` }, { label: `${name} after` }],
    search_ids: [`${name}-1`, `${name}-2`]
  });
  const manifest = { per_aoi_enrichment: [aoi('A'), aoi('B')] };
  const original = JSON.stringify(manifest);
  const calls = [];
  const context = vm.createContext({
    window: { CanopexEvidenceDisplayMap: { loadImagery(source) { calls.push(source); } } },
    document: { getElementById: id => nodes.get(id) || null, querySelectorAll: () => [] }
  });
  load(context, 'app-evidence-map.js');
  load(context, 'app-evidence-display-selection.js');
  const state = { manifest, aoiPolygons: [], selectedAoi: -1 };
  const ctx = { state, er: () => ({}), ep: () => ({}) };
  const selection = context.window.CanopexEvidenceDisplaySelection;
  selection.selectAoi(0, ctx);
  selection.selectAoi(1, ctx);
  assert.equal(calls.length, 2);
  assert.equal(calls[1], manifest.per_aoi_enrichment[1]);
  assert.equal(nodes.get('app-map-btn-compare').hidden, false);
  selection.resetAoiSelection(ctx);
  assert.equal(calls[2], manifest);
  assert.equal(nodes.get('app-map-btn-compare').hidden, true);
  assert.equal(JSON.stringify(manifest), original);
});

test('two-parcel imagery and before/after maps use only the selected parcel', () => {
  const ids = [
    'app-evidence-compare-wrap', 'app-map-btn-compare', 'app-evidence-frame-controls',
    'app-evidence-map-wrap', 'app-evidence-compare-map-before', 'app-evidence-compare-map-after',
    'app-evidence-compare-label-before', 'app-evidence-compare-label-after'
  ];
  const nodes = new Map(ids.map(id => [id, element()]));
  const tileCalls = [];
  const removed = [];
  const map = () => ({
    setView() { return this; }, on() {}, fitBounds() {}, invalidateSize() {}, remove() {},
    removeLayer(layer) { removed.push(layer.url); }
  });
  const context = vm.createContext({
    window: {}, setTimeout: fn => fn(), clearInterval() {},
    document: { getElementById: id => nodes.get(id) || null, querySelectorAll: () => [] },
    L: {
      map,
      tileLayer(url) {
        tileCalls.push(url);
        return { url, addTo() { return this; }, setOpacity() {} };
      },
      latLngBounds: () => ({ isValid: () => false })
    }
  });
  load(context, 'canopex-geo.js');
  load(context, 'app-evidence-map.js');
  load(context, 'app-evidence-display-map.js');
  load(context, 'app-evidence-display-selection.js');
  const parcel = name => ({
    name, center: { lat: 0, lon: 0 },
    frame_plan: [{ label: `${name} before`, collection: 'landsat-c2-l2' }, { label: `${name} after`, collection: 'landsat-c2-l2' }],
    search_ids: [`${name}-1`, `${name}-2`]
  });
  const state = {
    manifest: { per_aoi_enrichment: [parcel('A'), parcel('B'), { name: 'Unavailable' }] },
    map: map(), mapLayers: [], aoiPolygons: [], selectedAoi: -1
  };
  const ctx = {
    state, er: () => ({ pcTileUrl: sid => sid }), ep: () => ({}),
    em: () => context.window.CanopexEvidenceMap,
    showEvidenceFrame: index => context.window.CanopexEvidenceDisplayMap.showEvidenceFrame(index, ctx)
  };
  const selection = context.window.CanopexEvidenceDisplaySelection;
  selection.selectAoi(0, ctx);
  assert.deepEqual(Array.from(state.mapLayers, frame => frame.rgb.url), ['A-1', 'A-2']);
  selection.selectAoi(1, ctx);
  assert.deepEqual(removed, ['A-1', 'A-2']);
  assert.deepEqual(Array.from(state.mapLayers, frame => frame.rgb.url), ['B-1', 'B-2']);
  assert.equal(nodes.get('app-evidence-frame-controls').hidden, false);
  selection.toggleCompareView(ctx);
  assert.equal(nodes.get('app-evidence-compare-label-before').textContent, 'Before \u2014 B before');
  assert.equal(nodes.get('app-evidence-compare-label-after').textContent, 'After \u2014 B after');
  assert.deepEqual(tileCalls.slice(-3).filter(url => !url.startsWith('https:')), ['B-1', 'B-2']);
  selection.selectAoi(2, ctx);
  assert.equal(state.compareMode, false);
  assert.equal(state.mapLayers.length, 0);
  assert.equal(nodes.get('app-map-btn-compare').hidden, true);
  assert.equal(nodes.get('app-evidence-frame-controls').hidden, true);
});

test('canonical single-AOI comparison uses its own frame fields on initialization', () => {
  const nodes = new Map([
    ['app-evidence-compare-wrap', element()], ['app-map-btn-compare', element()],
    ['app-evidence-map-wrap', element()], ['app-evidence-frame-controls', element()],
    ['app-evidence-compare-map-before', element()], ['app-evidence-compare-map-after', element()]
  ]);
  const tiles = [];
  const context = vm.createContext({
    window: {}, setTimeout: fn => fn(),
    document: { getElementById: id => nodes.get(id) || null },
    L: {
      map: () => ({ setView() { return this; }, on() {}, invalidateSize() {} }),
      tileLayer: url => ({ addTo() { tiles.push(url); } }),
      latLngBounds: () => ({ isValid: () => false })
    }
  });
  load(context, 'app-evidence-display-selection.js');
  const manifest = { per_aoi_enrichment: [{
    center: { lat: 0, lon: 0 }, search_ids: ['single-1', 'single-2'],
    frame_plan: [{ label: 'Before' }, { label: 'After' }]
  }] };
  const selection = context.window.CanopexEvidenceDisplaySelection;
  selection.initCompareView(manifest);
  assert.equal(nodes.get('app-map-btn-compare').hidden, false);
  selection.toggleCompareView({ state: { manifest, selectedAoi: -1 }, er: () => ({ pcTileUrl: sid => sid }) });
  assert.ok(tiles.includes('single-1'));
  assert.ok(tiles.includes('single-2'));
});

test('standard AI request sends only usable observations for the active parcel', async () => {
  const nodes = new Map(['loading', 'content', 'btn'].map(id => [`app-evidence-ai-${id}`, element()]));
  const calls = [];
  const context = vm.createContext({
    window: {}, document: { getElementById: id => nodes.get(id) || null }
  });
  load(context, 'app-evidence-map.js');
  load(context, 'app-evidence-display-ai.js');
  const source = {
    name: 'Selected', center: { lat: 0, lon: 0 },
    ndvi_stats: [
      { mean: 0.9, available: false, datetime: '2022-01-01' },
      { mean: Infinity, datetime: '2023-01-01' },
      { mean: 0, datetime: '2024-01-01' }
    ]
  };
  await context.window.CanopexEvidenceDisplayAi.requestAiAnalysis({
    state: { manifest: { per_aoi_enrichment: [source] }, selectedAoi: 0 },
    em: () => context.window.CanopexEvidenceMap, er: () => ({}),
    async apiFetch(url, options) { calls.push({ url, body: JSON.parse(options.body) }); return { json: async () => ({}) }; }
  });
  const request = calls[0].body.context;
  assert.equal(request.frame_count, 1);
  assert.equal(request.aoi_name, 'Selected');
  assert.equal(request.date_range_start, '2024-01-01');
  assert.equal(request.ndvi_timeseries[0].mean, 0);
});

test('per-AOI detail renders unavailable instead of invalid NDVI aggregates', () => {
  const nodes = new Map(['grid', 'detail'].map(id => [
    id === 'grid' ? 'app-evidence-aoi-detail-grid' : 'app-evidence-aoi-detail', element()
  ]));
  const context = vm.createContext({
    window: {}, document: { getElementById: id => nodes.get(id) || null },
    CanopexHelpers: { setStatGrid(target, rows) { target.rows = rows; } }
  });
  load(context, 'app-evidence-map.js');
  load(context, 'canopex-evidence-render.js');
  context.window.CanopexEvidenceRender.renderAoiDetail({
    ndvi_stats: [{ available: false, mean: 0.8 }, { mean: Infinity }],
    change_detection: { summary: { trajectory: 'Stable' } }
  });
  const rows = nodes.get('app-evidence-aoi-detail-grid').rows;
  assert.equal(rows.find(row => row[0] === 'NDVI')[1], 'Unavailable');
  assert.ok(!rows.some(row => row[0] === 'Trend' && row[1] === 'Stable'));
});
