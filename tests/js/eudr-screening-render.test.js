'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');

function loadRenderer() {
  const elements = new Map();
  function element() {
    return {
      hidden: true,
      children: [],
      text: '',
      get textContent() {
        return this.text + this.children.map(child => child.textContent).join('');
      },
      set textContent(value) {
        this.text = value;
        this.children = [];
      },
      className: '',
      appendChild(child) {
        this.children = this.children || [];
        this.children.push(child);
      }
    };
  }

  for (const id of [
    'app-evidence-aoi-detail',
    'app-evidence-aoi-detail-name',
    'app-evidence-aoi-detail-grid',
    'app-evidence-aoi-determination',
    'app-evidence-flags',
    'app-evidence-ndvi-grid',
    'app-evidence-change-block',
    'app-evidence-change-list'
  ]) {
    elements.set(id, element());
  }

  const context = vm.createContext({
    window: {},
    document: {
      getElementById: id => elements.get(id) || null,
      createElement: () => element()
    },
    CanopexHelpers: { setStatGrid(target, rows) { target.rows = rows; } }
  });
  vm.runInContext(
    fs.readFileSync(path.join(root, 'website/js/app-evidence-map.js'), 'utf8'),
    context,
    { filename: 'app-evidence-map.js' }
  );
  vm.runInContext(
    fs.readFileSync(path.join(root, 'website/js/canopex-evidence-render.js'), 'utf8'),
    context,
    { filename: 'canopex-evidence-render.js' }
  );
  return {
    render: context.window.CanopexEvidenceRender.renderAoiDetail,
    renderChange: context.window.CanopexEvidenceRender.renderEvidenceChangeDetection,
    renderNdvi: context.window.CanopexEvidenceRender.renderEvidenceNdvi,
    elements
  };
}

test('missing or zero-comparison change evidence is visible and never stable or positive', () => {
  for (const change_detection of [undefined, {}, { summary: {} }, {
    summary: { comparisons: 0, trajectory: 'Stable' }
  }, { summary: 'Stable' }]) {
    const renderer = loadRenderer();
    renderer.renderChange({ change_detection });
    const list = renderer.elements.get('app-evidence-change-list');
    assert.equal(renderer.elements.get('app-evidence-change-block').hidden, false);
    assert.match(list.textContent, /unavailable|insufficient/i);
    assert.doesNotMatch(list.textContent, /Stable|net loss|net gain/);
    assert.ok(list.children.every(child => !child.className.includes('positive')));
  }
});

test('change summary tones reflect observed trajectories and do not persist on rerender', () => {
  const renderer = loadRenderer();
  for (const [trajectory, tone] of [
    ['Declining', 'negative'], ['Stable', ''], ['Improving', 'positive'], [undefined, '']
  ]) {
    renderer.renderChange({ change_detection: { summary: { comparisons: 2, trajectory } } });
    const list = renderer.elements.get('app-evidence-change-list');
    assert.equal(list.children.length, 1);
    assert.match(list.textContent, new RegExp(trajectory || 'Unavailable', 'i'));
    assert.equal(list.children[0].className, 'app-evidence-change-item' + (tone ? ' ' + tone : ''));
  }
});

test('absent determination stays visible as insufficient evidence and clears previous flags', () => {
  const renderer = loadRenderer();
  renderer.render({ determination: { screening_outcome: 'signal_detected', flags: ['Loss detected'] } });
  renderer.render({});
  const determination = renderer.elements.get('app-evidence-aoi-determination');
  assert.equal(determination.hidden, false);
  assert.match(determination.textContent, /Insufficient evidence for screening/);
  assert.equal(renderer.elements.get('app-evidence-flags').hidden, true);
  assert.equal(renderer.elements.get('app-evidence-flags').textContent, '');
});

test('nested EUDR determination renders its screening outcome and preserves flags', () => {
  const renderer = loadRenderer();
  renderer.render({ eudr: { determination: {
    screening_outcome: 'insufficient_evidence', confidence: 'low',
    flags: ['No usable NDVI observations', 'WDPA lookup unavailable']
  } } });
  const determination = renderer.elements.get('app-evidence-aoi-determination');
  assert.equal(determination.hidden, false);
  assert.match(determination.textContent, /Insufficient evidence for screening \(low confidence\)/);
  const flags = renderer.elements.get('app-evidence-flags');
  assert.equal(flags.hidden, false);
  assert.match(flags.textContent, /No usable NDVI observations/);
  assert.match(flags.textContent, /WDPA lookup unavailable/);
});

test('NDVI and parcel trends do not infer stability or improvement without comparisons', () => {
  for (const summary of [undefined, {}, { comparisons: 0, trajectory: 'Stable' }, { comparisons: 2 }]) {
    const renderer = loadRenderer();
    const manifest = {
      ndvi_stats: [0.4, 0.5, 0.6, 0.7].map(mean => ({ mean })),
      change_detection: { summary }
    };
    renderer.renderNdvi(manifest);
    renderer.render(manifest);
    const trajectory = renderer.elements.get('app-evidence-ndvi-grid').rows.find(row => row[0] === 'Trajectory');
    const trend = renderer.elements.get('app-evidence-aoi-detail-grid').rows.find(row => row[0] === 'Trend');
    assert.equal(trajectory[1], 'Unavailable');
    assert.equal(trajectory[2], '');
    assert.equal(trend[1], 'Unavailable');
    assert.equal(trend[2], '');
  }
});

test('renders no-signal current-schema outcome without a legal conclusion', () => {
  const renderer = loadRenderer();
  renderer.render({
    name: 'North parcel',
    determination: {
      screening_outcome: 'no_signal_detected',
      confidence: 'high',
      flags: [],
      operator_conclusion: null
    }
  });
  const determination = renderer.elements.get('app-evidence-aoi-determination');
  assert.match(determination.textContent, /No deforestation signal detected/);
  assert.doesNotMatch(determination.textContent, /Deforestation-free|Risk detected/);
  assert.equal(determination.className, 'app-evidence-aoi-determination screening-no-signal');
});

test('renders signal and insufficient-evidence outcomes distinctly', () => {
  for (const [outcome, expected, className] of [
    ['signal_detected', 'Deforestation signal detected', 'screening-signal'],
    ['insufficient_evidence', 'Insufficient evidence for screening', 'screening-insufficient'],
    ['error', 'Screening unavailable', 'screening-error']
  ]) {
    const renderer = loadRenderer();
    renderer.render({ determination: { screening_outcome: outcome, flags: [] } });
    const determination = renderer.elements.get('app-evidence-aoi-determination');
    assert.match(determination.textContent, new RegExp(expected));
    assert.equal(determination.className, `app-evidence-aoi-determination ${className}`);
  }
});

test('treats missing and unknown outcomes as insufficient evidence', () => {
  for (const determination of [{ flags: [] }, { screening_outcome: 'unexpected', flags: [] }]) {
    const renderer = loadRenderer();
    renderer.render({ determination });
    const element = renderer.elements.get('app-evidence-aoi-determination');
    assert.match(element.textContent, /Insufficient evidence for screening/);
    assert.equal(element.className, 'app-evidence-aoi-determination screening-insufficient');
  }
});

test('keeps a human operator conclusion separate from machine screening', () => {
  const renderer = loadRenderer();
  renderer.render({
    determination: {
      screening_outcome: 'signal_detected',
      flags: [],
      operator_conclusion: 'Requires field inspection'
    }
  });
  const text = renderer.elements.get('app-evidence-aoi-determination').textContent;
  assert.match(text, /Deforestation signal detected/);
  assert.match(text, /Operator conclusion: Requires field inspection/);
});
