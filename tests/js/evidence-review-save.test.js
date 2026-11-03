'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function element() {
  return {
    hidden: true, disabled: false, value: '', checked: false, className: '',
    children: [], text: '', focus() {},
    get textContent() { return this.text + this.children.map(child => child.textContent).join(''); },
    set textContent(value) { this.text = value; this.children = []; },
    appendChild(child) { this.children.push(child); }
  };
}

function harness(apiFetch) {
  const ids = [
    'notes', 'notes-saved', 'notes-text', 'notes-meta', 'notes-edit', 'notes-add-btn',
    'notes-input', 'notes-save-btn', 'notes-error', 'override', 'override-badge',
    'override-btn', 'override-revert-btn', 'override-error',
    'eudr-loading', 'eudr-content', 'eudr-btn'
  ];
  const nodes = new Map(ids.map(id => [`app-evidence-${id}`, element()]));
  for (const id of [
    'app-override-backdrop', 'app-override-reason-input', 'app-override-confirm-btn',
    'app-override-charcount', 'app-override-error', 'app-override-original',
    'app-override-mark-compliant'
  ]) nodes.set(id, element());
  const state = { manifest: { name: 'Parcel A' }, instanceId: 'run-a', selectedAoi: 0 };
  const context = vm.createContext({
    window: {}, console,
    document: { getElementById: id => nodes.get(id) || null, createElement: element }
  });
  for (const file of ['app-evidence-panels.js', 'app-evidence-display-ai.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../website/js', file), 'utf8'), context);
  }
  const panels = context.window.CanopexEvidencePanels;
  panels.init({
    apiFetch, getApiReady: async () => {},
    getManifest: () => state.manifest, getInstanceId: () => state.instanceId
  });
  panels.renderParcelNotes('0');
  panels.showNoteEditor();
  nodes.get('app-evidence-notes-input').value = 'Review evidence before reporting';
  return {
    nodes, state, panels,
    assess: () => context.window.CanopexEvidenceDisplayAi.requestEudrAssessment({
      state, apiFetch, em: () => ({ buildNdviTimeseries: () => [], latLon: () => ({ lat: 1, lon: 2 }) })
    })
  };
}

test('note HTTP and network failures preserve the draft and show a retryable error', async () => {
  for (const response of [
    async () => ({ ok: false, status: 503, json: async () => ({ message: 'Storage unavailable' }) }),
    async () => { throw new Error('Network unavailable'); }
  ]) {
    const { nodes, state, panels } = harness(response);
    await panels.saveParcelNote();
    assert.equal(nodes.get('app-evidence-notes-edit').hidden, false);
    assert.equal(nodes.get('app-evidence-notes-input').value, 'Review evidence before reporting');
    assert.equal(nodes.get('app-evidence-notes-error').hidden, false);
    assert.match(nodes.get('app-evidence-notes-error').textContent, /save|unavailable/i);
    assert.equal(state.manifest.parcel_notes, undefined);
    assert.equal(nodes.get('app-evidence-notes-save-btn').disabled, false);
  }
});

test('failed note saves can be retried successfully', async () => {
  let calls = 0;
  const { nodes, state, panels } = harness(async () => ({ ok: ++calls > 1, status: 503 }));
  await panels.saveParcelNote();
  await panels.saveParcelNote();
  assert.equal(state.manifest.parcel_notes['0'].text, 'Review evidence before reporting');
  assert.equal(nodes.get('app-evidence-notes-error').hidden, true);
  assert.equal(nodes.get('app-evidence-notes-edit').hidden, true);
});

test('a note save finishing after parcel selection updates only its original parcel', async () => {
  let finish;
  const { nodes, state, panels } = harness(() => new Promise(resolve => { finish = resolve; }));
  const saving = panels.saveParcelNote();
  await new Promise(resolve => setImmediate(resolve));
  panels.renderParcelNotes('1');
  panels.showNoteEditor();
  nodes.get('app-evidence-notes-input').value = 'Different parcel draft';
  finish({ ok: true });
  await saving;
  assert.equal(state.manifest.parcel_notes['0'].text, 'Review evidence before reporting');
  assert.equal(state.manifest.parcel_notes['1'], undefined);
  assert.equal(nodes.get('app-evidence-notes-input').value, 'Different parcel draft');
  assert.equal(nodes.get('app-evidence-notes-edit').hidden, false);
});

test('a note save finishing after run navigation never mutates the new run', async () => {
  let finish;
  const { state, panels } = harness(() => new Promise(resolve => { finish = resolve; }));
  const original = state.manifest;
  const saving = panels.saveParcelNote();
  await new Promise(resolve => setImmediate(resolve));
  state.instanceId = 'run-b';
  state.manifest = {};
  finish({ ok: true });
  await saving;
  assert.equal(state.manifest.parcel_notes, undefined);
  assert.equal(original.parcel_notes['0'].text, 'Review evidence before reporting');
});

test('review reversion failures remain visible and do not erase the saved review', async () => {
  const { nodes, state, panels } = harness(async () => ({ ok: false, status: 500 }));
  state.manifest.parcel_reviews = { '0': { override: true, note: 'Saved assessment' } };
  panels.renderParcelOverride('0', { determination: { screening_outcome: 'signal_detected' } });
  await panels.revertOverride();
  assert.equal(state.manifest.parcel_reviews['0'].override, true);
  assert.equal(nodes.get('app-evidence-override-error').hidden, false);
  assert.match(nodes.get('app-evidence-override-error').textContent, /revert|save/i);
  assert.equal(nodes.get('app-evidence-override-revert-btn').disabled, false);
});

test('a lost reversion response reports an unconfirmed outcome rather than unchanged server state', async () => {
  const { nodes, state, panels } = harness(async () => { throw new Error('Response lost after commit'); });
  state.manifest.parcel_reviews = { '0': { override: true, note: 'Previously saved review' } };
  panels.renderParcelOverride('0', {});
  await panels.revertOverride();
  const error = nodes.get('app-evidence-override-error').textContent;
  assert.match(error, /unconfirmed|could not confirm/i);
  assert.match(error, /reload/i);
  assert.doesNotMatch(error, /saved review is unchanged/i);
});

test('a completed note save never closes a reopened editor for the same parcel', async () => {
  let finish;
  const { nodes, state, panels } = harness(() => new Promise(resolve => { finish = resolve; }));
  const saving = panels.saveParcelNote();
  await new Promise(resolve => setImmediate(resolve));
  panels.hideNoteEditor();
  panels.showNoteEditor();
  nodes.get('app-evidence-notes-input').value = 'Review evidence before reporting';
  finish({ ok: true });
  await saving;
  assert.equal(state.manifest.parcel_notes['0'].text, 'Review evidence before reporting');
  assert.equal(nodes.get('app-evidence-notes-edit').hidden, false);
  assert.equal(nodes.get('app-evidence-notes-input').value, 'Review evidence before reporting');
});

test('a completed note save never discards edits made while the same editor is saving', async () => {
  let finish;
  const { nodes, panels } = harness(() => new Promise(resolve => { finish = resolve; }));
  const saving = panels.saveParcelNote();
  await new Promise(resolve => setImmediate(resolve));
  nodes.get('app-evidence-notes-input').value = 'Newer text typed during save';
  finish({ ok: true });
  await saving;
  assert.equal(nodes.get('app-evidence-notes-edit').hidden, false);
  assert.equal(nodes.get('app-evidence-notes-input').value, 'Newer text typed during save');
});

test('a completed review save never closes a reopened modal or discards its draft', async () => {
  let finish;
  const { nodes, state, panels } = harness(() => new Promise(resolve => { finish = resolve; }));
  panels.openOverrideModal('0', {});
  nodes.get('app-override-reason-input').value = 'Original reviewer assessment';
  panels.onOverrideReasonInput();
  const saving = panels.confirmOverride();
  await new Promise(resolve => setImmediate(resolve));
  panels.closeOverrideModal();
  panels.openOverrideModal('0', {});
  nodes.get('app-override-reason-input').value = 'Original reviewer assessment';
  finish({ ok: true });
  await saving;
  assert.equal(state.manifest.parcel_reviews['0'].note, 'Original reviewer assessment');
  assert.equal(nodes.get('app-override-backdrop').hidden, false);
  assert.equal(nodes.get('app-override-reason-input').value, 'Original reviewer assessment');
});

test('returning to the original parcel cannot revive a stale note editor response', async () => {
  let finish;
  const { nodes, panels } = harness(() => new Promise(resolve => { finish = resolve; }));
  const saving = panels.saveParcelNote();
  await new Promise(resolve => setImmediate(resolve));
  panels.renderParcelNotes('1');
  panels.renderParcelNotes('0');
  panels.showNoteEditor();
  nodes.get('app-evidence-notes-input').value = 'Review evidence before reporting';
  finish({ ok: true });
  await saving;
  assert.equal(nodes.get('app-evidence-notes-edit').hidden, false);
  assert.equal(nodes.get('app-evidence-notes-input').value, 'Review evidence before reporting');
});

test('editing a pending review retains the draft and cannot submit overlapping writes', async () => {
  let finish;
  let calls = 0;
  const { nodes, panels } = harness(() => {
    calls++;
    return new Promise(resolve => { finish = resolve; });
  });
  panels.openOverrideModal('0', {});
  nodes.get('app-override-reason-input').value = 'Original reviewer assessment';
  panels.onOverrideReasonInput();
  const saving = panels.confirmOverride();
  await new Promise(resolve => setImmediate(resolve));
  nodes.get('app-override-reason-input').value = 'Edited while saving';
  panels.onOverrideReasonInput();
  await panels.confirmOverride();
  assert.equal(calls, 1);
  finish({ ok: true });
  await saving;
  assert.equal(nodes.get('app-override-backdrop').hidden, false);
  assert.equal(nodes.get('app-override-reason-input').value, 'Edited while saving');
  assert.equal(nodes.get('app-override-confirm-btn').disabled, false);
});

test('review saves finishing after selection never attach a review to another parcel', async () => {
  let finish;
  const { nodes, state, panels } = harness(() => new Promise(resolve => { finish = resolve; }));
  panels.openOverrideModal('0', { determination: { screening_outcome: 'signal_detected' } });
  nodes.get('app-override-reason-input').value = 'Reviewed against supplier evidence';
  panels.onOverrideReasonInput();
  const saving = panels.confirmOverride();
  await new Promise(resolve => setImmediate(resolve));
  panels.openOverrideModal('1', { determination: { screening_outcome: 'signal_detected' } });
  nodes.get('app-override-reason-input').value = 'Other parcel draft';
  finish({ ok: true });
  await saving;
  assert.equal(state.manifest.parcel_reviews['0'].note, 'Reviewed against supplier evidence');
  assert.equal(state.manifest.parcel_reviews['1'], undefined);
  assert.equal(nodes.get('app-override-backdrop').hidden, false);
  assert.equal(nodes.get('app-override-reason-input').value, 'Other parcel draft');
});

test('review save failures after selection never display an error in another parcel modal', async () => {
  let finish;
  const { nodes, panels } = harness(() => new Promise(resolve => { finish = resolve; }));
  panels.openOverrideModal('0', {});
  nodes.get('app-override-reason-input').value = 'Original draft';
  panels.onOverrideReasonInput();
  const saving = panels.confirmOverride();
  await new Promise(resolve => setImmediate(resolve));
  panels.openOverrideModal('1', {});
  finish({ ok: false, status: 500, json: async () => ({ message: 'Failed to save original parcel' }) });
  await saving;
  assert.equal(nodes.get('app-override-error').hidden, true);
});

test('on-demand EUDR screening is explicitly transient rather than a saved assessment', async () => {
  const { nodes, assess } = harness(async () => ({
    ok: true, json: async () => ({ screening_outcome: 'signal_detected', summary: 'Review required' })
  }));
  await assess();
  assert.match(nodes.get('app-evidence-eudr-content').textContent, /not saved|unsaved/i);
  assert.match(nodes.get('app-evidence-eudr-content').textContent, /reload/i);
});

test('failed EUDR HTTP responses never display a successful screening', async () => {
  const { nodes, assess } = harness(async () => ({
    ok: false, status: 503,
    json: async () => ({ screening_outcome: 'no_signal_detected', summary: 'Misleading response' })
  }));
  await assess();
  assert.doesNotMatch(nodes.get('app-evidence-eudr-content').textContent, /No deforestation signal/);
  assert.match(nodes.get('app-evidence-eudr-content').textContent, /could not|unavailable|failed/i);
});

test('on-demand screening finishing after selection never appears on a different parcel', async () => {
  let finish;
  const { nodes, state, assess } = harness(() => new Promise(resolve => { finish = resolve; }));
  const screening = assess();
  await new Promise(resolve => setImmediate(resolve));
  state.selectedAoi = 1;
  nodes.get('app-evidence-eudr-content').textContent = 'Parcel B evidence';
  finish({ ok: true, json: async () => ({ screening_outcome: 'signal_detected', summary: 'Parcel A evidence' }) });
  await screening;
  assert.equal(nodes.get('app-evidence-eudr-content').textContent, 'Parcel B evidence');
});

test('stale screening completion cannot reset a newer request loading state', async () => {
  const responses = [];
  const { nodes, state, assess } = harness(() => new Promise(resolve => { responses.push(resolve); }));
  const original = assess();
  await new Promise(resolve => setImmediate(resolve));
  state.instanceId = 'run-b';
  state.manifest = { name: 'Parcel B' };
  const current = assess();
  await new Promise(resolve => setImmediate(resolve));
  responses[0]({ ok: true, json: async () => ({ screening_outcome: 'signal_detected' }) });
  await original;
  assert.equal(nodes.get('app-evidence-eudr-loading').hidden, false);
  assert.equal(nodes.get('app-evidence-eudr-btn').disabled, true);
  responses[1]({ ok: true, json: async () => ({ screening_outcome: 'no_signal_detected' }) });
  await current;
  assert.equal(nodes.get('app-evidence-eudr-loading').hidden, true);
  assert.equal(nodes.get('app-evidence-eudr-btn').disabled, false);
  assert.match(nodes.get('app-evidence-eudr-content').textContent, /No deforestation signal/);
});

test('review and screening feedback have accessible live regions on both app surfaces', () => {
  for (const surface of ['app', 'eudr']) {
    const html = fs.readFileSync(path.join(__dirname, '../../website', surface, 'index.html'), 'utf8');
    for (const id of ['app-evidence-notes-error', 'app-evidence-override-error', 'app-override-error']) {
      assert.match(html, new RegExp('<[^>]*id="' + id + '"[^>]*role="alert"[^>]*>'));
    }
    assert.match(html, /<[^>]*id="app-evidence-eudr-content"[^>]*aria-live="polite"[^>]*>/);
  }
});
