/**
 * app-evidence-panels.js
 *
 * Evidence side-panel helpers: parcel notes (#669) and human-override
 * determination (#672).  No Leaflet, no direct state mutation beyond the
 * manifest object returned by getManifest().
 *
 * Exposes: window.CanopexEvidencePanels
 *
 * Contract:
 *   init(deps)
 *     deps.apiFetch      — authenticated fetch helper
 *     deps.getApiReady   — () → Promise — resolves when API base is known
 *     deps.getManifest   — () → evidenceManifest object (live reference, mutated in-place)
 *     deps.getInstanceId — () → current evidenceInstanceId string | null
 *
 *   parcelKeyForIndex(idx)          → string
 *   renderParcelNotes(parcelKey)    — update notes panel DOM
 *   showNoteEditor()                — reveal the note editor
 *   hideNoteEditor()                — hide the note editor
 *   saveParcelNote()                → Promise<void>
 *   renderParcelOverride(key, aoi)  — update override panel DOM
 *   openOverrideModal(key, aoi)     — show override backdrop
 *   closeOverrideModal()            — hide override backdrop
 *   onOverrideReasonInput()         — validate + update char counter
 *   confirmOverride()               → Promise<void>
 *   revertOverride()                → Promise<void>
 */
(function () {
  'use strict';

  /* ---- deps (set via init) ---- */

  var _apiFetch      = null;
  var _getApiReady   = null;
  var _getManifest   = null;
  var _getInstanceId = null;

  function init(deps) {
    _apiFetch      = deps.apiFetch      || _apiFetch;
    _getApiReady   = deps.getApiReady   || _getApiReady;
    _getManifest   = deps.getManifest   || _getManifest;
    _getInstanceId = deps.getInstanceId || _getInstanceId;
  }

  /* ---- module-level state ---- */

  var currentNoteParcelKey     = null;
  var currentOverrideParcelKey = null;
  var currentOverrideAoiData   = null;

  /* ---- parcel key helper ---- */

  function parcelKeyForIndex(idx) {
    return String(idx);
  }

  /* ---- parcel notes (#669) ---- */

  function renderParcelNotes(parcelKey) {
    currentNoteParcelKey = parcelKey;

    var notesEl = document.getElementById('app-evidence-notes');
    var savedEl = document.getElementById('app-evidence-notes-saved');
    var textEl  = document.getElementById('app-evidence-notes-text');
    var metaEl  = document.getElementById('app-evidence-notes-meta');
    var editEl  = document.getElementById('app-evidence-notes-edit');
    var addBtn  = document.getElementById('app-evidence-notes-add-btn');
    if (!notesEl) return;

    // Reset edit state
    if (editEl) editEl.hidden = true;
    if (addBtn) addBtn.hidden = false;
    var input = document.getElementById('app-evidence-notes-input');
    if (input) input.value = '';

    var manifest = _getManifest ? _getManifest() : null;
    var note = null;
    if (manifest && manifest.parcel_notes) {
      note = manifest.parcel_notes[parcelKey] || null;
    }

    if (note && note.text) {
      if (savedEl) savedEl.hidden = false;
      if (textEl)  textEl.textContent = note.text;
      if (metaEl) {
        var when = note.updated_at ? new Date(note.updated_at).toLocaleDateString() : '';
        metaEl.textContent = when ? 'Note — ' + when : 'Note saved';
      }
      if (addBtn) addBtn.textContent = 'Edit note';
    } else {
      if (savedEl) savedEl.hidden = true;
      if (textEl)  textEl.textContent = '';
      if (metaEl)  metaEl.textContent = '';
      if (addBtn)  addBtn.textContent = '+ Add note';
    }
  }

  function showNoteEditor() {
    var editEl = document.getElementById('app-evidence-notes-edit');
    var addBtn = document.getElementById('app-evidence-notes-add-btn');
    var input  = document.getElementById('app-evidence-notes-input');
    if (!editEl) return;

    var manifest = _getManifest ? _getManifest() : null;
    if (input && manifest && manifest.parcel_notes && currentNoteParcelKey) {
      var existing = manifest.parcel_notes[currentNoteParcelKey];
      input.value = existing ? (existing.text || '') : '';
    }
    if (editEl) editEl.hidden = false;
    if (addBtn) addBtn.hidden = true;
    if (input)  input.focus();
  }

  function hideNoteEditor() {
    var editEl = document.getElementById('app-evidence-notes-edit');
    var addBtn = document.getElementById('app-evidence-notes-add-btn');
    if (editEl) editEl.hidden = true;
    if (addBtn) addBtn.hidden = false;
  }

  async function saveParcelNote() {
    var input = document.getElementById('app-evidence-notes-input');
    var instanceId = _getInstanceId ? _getInstanceId() : null;
    if (!input || !instanceId || currentNoteParcelKey === null) return;

    var noteText = input.value.trim();
    var saveBtn  = document.getElementById('app-evidence-notes-save-btn');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }

    try {
      if (_getApiReady) await _getApiReady();
      var res = await _apiFetch('/api/analysis/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          instance_id: instanceId,
          parcel_key: currentNoteParcelKey,
          note: noteText,
        }),
      });
      if (!res.ok) {
        var err = await res.json().catch(function() { return {}; });
        console.warn('Note save failed:', err);
        return;
      }
      // Mutate the live manifest reference so the note appears immediately.
      var manifest = _getManifest ? _getManifest() : null;
      if (manifest) {
        if (!manifest.parcel_notes) manifest.parcel_notes = {};
        if (noteText) {
          manifest.parcel_notes[currentNoteParcelKey] = {
            text: noteText,
            updated_at: new Date().toISOString(),
          };
        } else {
          delete manifest.parcel_notes[currentNoteParcelKey];
        }
      }
      hideNoteEditor();
      renderParcelNotes(currentNoteParcelKey);
    } catch (e) {
      console.warn('Note save error:', e);
    } finally {
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save note'; }
    }
  }

  /* ---- human override determination (#672) ---- */

  function renderParcelOverride(parcelKey, aoiData) {
    currentOverrideParcelKey = parcelKey;
    currentOverrideAoiData   = aoiData;

    var overrideEl  = document.getElementById('app-evidence-override');
    var badgeEl     = document.getElementById('app-evidence-override-badge');
    var overrideBtn = document.getElementById('app-evidence-override-btn');
    var revertBtn   = document.getElementById('app-evidence-override-revert-btn');
    if (!overrideEl) return;

    var manifest = _getManifest ? _getManifest() : null;
    var override = null;
    if (manifest && manifest.parcel_overrides) {
      override = manifest.parcel_overrides[parcelKey] || null;
    }

    var det           = aoiData && aoiData.determination;
    var isNonCompliant = det && !det.deforestation_free;

    overrideEl.hidden = !(isNonCompliant || override);

    if (override) {
      if (badgeEl) {
        badgeEl.hidden    = false;
        badgeEl.className = 'app-evidence-override-badge';
        badgeEl.textContent = '\u2705 Compliant (overridden)';
      }
      if (overrideBtn) overrideBtn.hidden = true;
      if (revertBtn)   revertBtn.hidden   = false;
    } else {
      if (badgeEl)     badgeEl.hidden     = true;
      if (overrideBtn) overrideBtn.hidden = !isNonCompliant;
      if (revertBtn)   revertBtn.hidden   = true;
    }
  }

  function openOverrideModal(parcelKey, aoiData) {
    var backdrop    = document.getElementById('app-override-backdrop');
    var reasonInput = document.getElementById('app-override-reason-input');
    var confirmBtn  = document.getElementById('app-override-confirm-btn');
    var charCount   = document.getElementById('app-override-charcount');
    var errorEl     = document.getElementById('app-override-error');
    var originalEl  = document.getElementById('app-override-original');
    if (!backdrop) return;

    if (reasonInput) reasonInput.value = '';
    if (confirmBtn)  confirmBtn.disabled = true;
    if (charCount)   charCount.textContent = '0 / 500';
    if (errorEl)     { errorEl.hidden = true; errorEl.textContent = ''; }
    if (originalEl) {
      var det    = aoiData && aoiData.determination;
      var reason = det && det.reason ? det.reason : 'Risk detected';
      originalEl.textContent = 'Algorithmic determination: ' + reason;
    }

    backdrop.hidden = false;
    if (reasonInput) reasonInput.focus();
  }

  function closeOverrideModal() {
    var backdrop = document.getElementById('app-override-backdrop');
    if (backdrop) backdrop.hidden = true;
  }

  function onOverrideReasonInput() {
    var reasonInput = document.getElementById('app-override-reason-input');
    var confirmBtn  = document.getElementById('app-override-confirm-btn');
    var charCount   = document.getElementById('app-override-charcount');
    if (!reasonInput) return;
    var len = reasonInput.value.trim().length;
    if (charCount)  charCount.textContent  = len + ' / 500';
    if (confirmBtn) confirmBtn.disabled    = len < 20;
  }

  async function confirmOverride() {
    var reasonInput = document.getElementById('app-override-reason-input');
    var confirmBtn  = document.getElementById('app-override-confirm-btn');
    var errorEl     = document.getElementById('app-override-error');
    var instanceId  = _getInstanceId ? _getInstanceId() : null;
    if (!reasonInput || !instanceId || currentOverrideParcelKey === null) return;

    var reason = reasonInput.value.trim();
    if (reason.length < 20) return;

    var originalText = confirmBtn ? confirmBtn.textContent : 'Confirm override';
    if (confirmBtn) { confirmBtn.disabled = true; confirmBtn.textContent = 'Saving\u2026'; }
    if (errorEl)    { errorEl.hidden = true; errorEl.textContent = ''; }

    try {
      if (_getApiReady) await _getApiReady();
      var res = await _apiFetch('/api/analysis/override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          instance_id: instanceId,
          parcel_key: currentOverrideParcelKey,
          reason: reason,
          revert: false,
        }),
      });
      if (!res.ok) {
        var err = await res.json().catch(function() { return {}; });
        if (errorEl) {
          errorEl.textContent = (err && err.message) || 'Failed to save override. Try again.';
          errorEl.hidden = false;
        }
        return;
      }
      var manifest = _getManifest ? _getManifest() : null;
      if (manifest) {
        if (!manifest.parcel_overrides) manifest.parcel_overrides = {};
        manifest.parcel_overrides[currentOverrideParcelKey] = {
          reason: reason,
          overridden_at: new Date().toISOString(),
          override_determination: 'compliant',
        };
      }
      closeOverrideModal();
      renderParcelOverride(currentOverrideParcelKey, currentOverrideAoiData);
    } catch (e) {
      if (errorEl) { errorEl.textContent = 'Failed to save override. Try again.'; errorEl.hidden = false; }
      console.warn('Override save error:', e);
    } finally {
      if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.textContent = originalText; }
    }
  }

  async function revertOverride() {
    var instanceId = _getInstanceId ? _getInstanceId() : null;
    if (!instanceId || currentOverrideParcelKey === null) return;

    var revertBtn = document.getElementById('app-evidence-override-revert-btn');
    if (revertBtn) { revertBtn.disabled = true; revertBtn.textContent = 'Reverting\u2026'; }

    try {
      if (_getApiReady) await _getApiReady();
      var res = await _apiFetch('/api/analysis/override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          instance_id: instanceId,
          parcel_key: currentOverrideParcelKey,
          reason: '',
          revert: true,
        }),
      });
      if (res.ok) {
        var manifest = _getManifest ? _getManifest() : null;
        if (manifest && manifest.parcel_overrides) {
          delete manifest.parcel_overrides[currentOverrideParcelKey];
        }
        renderParcelOverride(currentOverrideParcelKey, currentOverrideAoiData);
      }
    } catch (e) {
      console.warn('Override revert error:', e);
    } finally {
      if (revertBtn) { revertBtn.disabled = false; revertBtn.textContent = 'Revert to algorithmic'; }
    }
  }

  window.CanopexEvidencePanels = {
    init: init,
    parcelKeyForIndex: parcelKeyForIndex,
    renderParcelNotes: renderParcelNotes,
    showNoteEditor: showNoteEditor,
    hideNoteEditor: hideNoteEditor,
    saveParcelNote: saveParcelNote,
    renderParcelOverride: renderParcelOverride,
    openOverrideModal: openOverrideModal,
    closeOverrideModal: closeOverrideModal,
    onOverrideReasonInput: onOverrideReasonInput,
    confirmOverride: confirmOverride,
    revertOverride: revertOverride,
  };
})();
