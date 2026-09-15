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
      textContent: '',
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
    'app-evidence-flags'
  ]) {
    elements.set(id, element());
  }

  const context = vm.createContext({
    window: {},
    document: {
      getElementById: id => elements.get(id) || null,
      createElement: () => element()
    },
    CanopexHelpers: { setStatGrid: () => {} }
  });
  vm.runInContext(
    fs.readFileSync(path.join(root, 'website/js/canopex-evidence-render.js'), 'utf8'),
    context,
    { filename: 'canopex-evidence-render.js' }
  );
  return { render: context.window.CanopexEvidenceRender.renderAoiDetail, elements };
}

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
