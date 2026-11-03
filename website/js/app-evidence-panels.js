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

  function screeningOutcomeLabel(determination) {
    var outcome = determination && determination.screening_outcome;
    if (outcome === 'no_signal_detected') return 'No deforestation signal detected';
    if (outcome === 'signal_detected') return 'Deforestation signal detected';
    if (outcome === 'error') return 'Screening unavailable';
    return 'Insufficient evidence for screening';
  }

  /* ---- module-level state ---- */

  var currentNoteParcelKey     = null;
  var currentOverrideParcelKey = null;
  var currentOverrideAoiData   = null;
  let noteEditorGeneration = 0;
  let reviewEditorGeneration = 0;
  let reviewSavePending = false;

  /* ---- review constants (must match backend _MIN_REVIEW_NOTE_LENGTH) ---- */

  var MIN_REVIEW_NOTE_LENGTH = 20;

  /* ---- parcel key helper ---- */

  function parcelKeyForIndex(idx) {
    return String(idx);
  }

  function showPanelError(id, message) {
    const errorEl = document.getElementById(id);
    if (errorEl) {
      errorEl.textContent = message;
      errorEl.hidden = !message;
    }
  }

  function isCurrentReview(manifest, instanceId, parcelKey, currentKey) {
    return _getManifest() === manifest && _getInstanceId() === instanceId && parcelKey === currentKey;
  }

  /* ---- parcel notes (#669) ---- */

  function renderParcelNotes(parcelKey) {
    noteEditorGeneration++;
    currentNoteParcelKey = parcelKey;
    showPanelError('app-evidence-notes-error', '');

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
    noteEditorGeneration++;
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
    noteEditorGeneration++;
    var editEl = document.getElementById('app-evidence-notes-edit');
    var addBtn = document.getElementById('app-evidence-notes-add-btn');
    if (editEl) editEl.hidden = true;
    if (addBtn) addBtn.hidden = false;
  }

  async function saveParcelNote() {
    const input = document.getElementById('app-evidence-notes-input');
    const instanceId = _getInstanceId ? _getInstanceId() : null;
    const manifest = _getManifest ? _getManifest() : null;
    const parcelKey = currentNoteParcelKey;
    const saveBtn = document.getElementById('app-evidence-notes-save-btn');
    if (saveBtn && saveBtn.disabled) return;
    if (!input || !instanceId || !manifest || parcelKey === null) {
      showPanelError('app-evidence-notes-error', 'Cannot save a note without an active parcel. Reopen the analysis and try again.');
      return;
    }
    const noteText = input.value.trim();
    const editorGeneration = noteEditorGeneration;
    showPanelError('app-evidence-notes-error', '');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }

    try {
      if (_getApiReady) await _getApiReady();
      const res = await _apiFetch('/api/analysis/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          instance_id: instanceId,
          parcel_key: parcelKey,
          note: noteText,
        }),
      });
      if (!res.ok) {
        throw new Error('Failed to save note. Your draft is unchanged; try again. (HTTP ' + res.status + ')');
      }
      if (!manifest.parcel_notes) manifest.parcel_notes = {};
      if (noteText) {
        manifest.parcel_notes[parcelKey] = { text: noteText, updated_at: new Date().toISOString() };
      } else {
        delete manifest.parcel_notes[parcelKey];
      }
      if (isCurrentReview(manifest, instanceId, parcelKey, currentNoteParcelKey) &&
          editorGeneration === noteEditorGeneration && input.value.trim() === noteText) {
        hideNoteEditor();
        renderParcelNotes(parcelKey);
      }
    } catch (e) {
      console.warn('Note save error:', e);
      if (isCurrentReview(manifest, instanceId, parcelKey, currentNoteParcelKey) &&
          editorGeneration === noteEditorGeneration) {
        showPanelError('app-evidence-notes-error', 'Failed to save note. Your draft is unchanged; try again.');
      }
    } finally {
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save note'; }
    }
  }

  /* ---- human override determination (#672) + human review (#866) ---- */

  function renderParcelOverride(parcelKey, aoiData) {
    reviewEditorGeneration++;
    currentOverrideParcelKey = parcelKey;
    currentOverrideAoiData   = aoiData;
    showPanelError('app-evidence-override-error', '');

    var overrideEl  = document.getElementById('app-evidence-override');
    var badgeEl     = document.getElementById('app-evidence-override-badge');
    var overrideBtn = document.getElementById('app-evidence-override-btn');
    var revertBtn   = document.getElementById('app-evidence-override-revert-btn');
    if (!overrideEl) return;

    var manifest = _getManifest ? _getManifest() : null;
    var override = null;
    var review   = null;
    if (manifest && manifest.parcel_overrides) {
      override = manifest.parcel_overrides[parcelKey] || null;
    }
    if (manifest && manifest.parcel_reviews) {
      review = manifest.parcel_reviews[parcelKey] || null;
    }

    var det              = aoiData && aoiData.determination;
    var hasScreening     = !!(det && typeof det.screening_outcome === 'string');
    var isSignalDetected = !!(det && det.screening_outcome === 'signal_detected');

    overrideEl.hidden = !(hasScreening || override || review);

    if (review && review.override) {
      // New review-layer override: amber "Reviewed" badge.
      // Both edit and revert controls remain reachable so the reviewer can
      // update or withdraw the assessment.
      if (badgeEl) {
        badgeEl.hidden      = false;
        badgeEl.className   = 'app-evidence-override-badge reviewed';
        badgeEl.textContent = '\u26A0\uFE0F Reviewed \u2014 compliant with explanation';
      }
      if (overrideBtn) {
        overrideBtn.hidden      = false;
        overrideBtn.textContent = 'Edit assessment';
      }
      if (revertBtn) {
        revertBtn.hidden      = false;
        revertBtn.textContent = 'Revert to algorithmic';
      }
    } else if (review) {
      // Review note attached but no override — show badge and allow editing.
      if (badgeEl) {
        badgeEl.hidden      = false;
        badgeEl.className   = 'app-evidence-override-badge reviewed';
        badgeEl.textContent = '\u{1F4DD} Review note attached';
      }
      if (overrideBtn) {
        overrideBtn.hidden      = false;
        overrideBtn.textContent = 'Edit assessment';
      }
      if (revertBtn) {
        revertBtn.hidden      = false;
        revertBtn.textContent = 'Revert to algorithmic';
      }
    } else if (override) {
      // Legacy parcel_overrides badge
      if (badgeEl) {
        badgeEl.hidden      = false;
        badgeEl.className   = 'app-evidence-override-badge';
        badgeEl.textContent = '\u2705 Compliant (overridden)';
      }
      if (overrideBtn) overrideBtn.hidden = true;
      if (revertBtn)   revertBtn.hidden   = false;
    } else {
      if (badgeEl)     badgeEl.hidden     = true;
      if (overrideBtn) {
        overrideBtn.hidden      = !isSignalDetected;
        overrideBtn.textContent = 'Override determination';
      }
      if (revertBtn)   revertBtn.hidden   = true;
    }

    // Show existing review note in the modal original field when reopening
    var reviewNoteEl = document.getElementById('app-evidence-review-note');
    if (reviewNoteEl) {
      var existingNote = review && review.note ? review.note : '';
      reviewNoteEl.textContent = existingNote;
      reviewNoteEl.hidden = !existingNote;
    }
  }

  function openOverrideModal(parcelKey, aoiData) {
    reviewEditorGeneration++;
    currentOverrideParcelKey = parcelKey;
    currentOverrideAoiData = aoiData;
    var backdrop    = document.getElementById('app-override-backdrop');
    var reasonInput = document.getElementById('app-override-reason-input');
    var confirmBtn  = document.getElementById('app-override-confirm-btn');
    var charCount   = document.getElementById('app-override-charcount');
    var errorEl     = document.getElementById('app-override-error');
    var originalEl  = document.getElementById('app-override-original');
    var overrideChk = document.getElementById('app-override-mark-compliant');
    if (!backdrop) return;

    // Pre-fill with existing review note if present
    var manifest = _getManifest ? _getManifest() : null;
    var existingNote = '';
    var existingOverride = false;
    if (manifest && manifest.parcel_reviews && manifest.parcel_reviews[parcelKey]) {
      existingNote = manifest.parcel_reviews[parcelKey].note || '';
      existingOverride = !!manifest.parcel_reviews[parcelKey].override;
    }

    if (reasonInput) reasonInput.value = existingNote;
    if (overrideChk) overrideChk.checked = existingOverride;
    var existingLen = existingNote.length;
    var minRequired = existingOverride ? MIN_REVIEW_NOTE_LENGTH : 1;
    if (charCount)  charCount.textContent  = existingLen + ' / 1000';
    if (confirmBtn) confirmBtn.disabled    = reviewSavePending || existingLen < minRequired;
    if (errorEl)     { errorEl.hidden = true; errorEl.textContent = ''; }
    if (originalEl) {
      var det = aoiData && aoiData.determination;
      originalEl.textContent = 'Algorithmic screening: ' + screeningOutcomeLabel(det);
    }

    backdrop.hidden = false;
    if (reasonInput) reasonInput.focus();
  }

  function closeOverrideModal() {
    reviewEditorGeneration++;
    var backdrop = document.getElementById('app-override-backdrop');
    if (backdrop) backdrop.hidden = true;
  }

  function onOverrideReasonInput() {
    var reasonInput = document.getElementById('app-override-reason-input');
    var confirmBtn  = document.getElementById('app-override-confirm-btn');
    var charCount   = document.getElementById('app-override-charcount');
    var overrideChk = document.getElementById('app-override-mark-compliant');
    if (!reasonInput) return;
    var len = reasonInput.value.trim().length;
    var minRequired = (overrideChk && overrideChk.checked) ? MIN_REVIEW_NOTE_LENGTH : 1;
    if (charCount)  charCount.textContent  = len + ' / 1000';
    if (confirmBtn) confirmBtn.disabled    = reviewSavePending || len < minRequired;
  }

  async function confirmOverride() {
    var reasonInput  = document.getElementById('app-override-reason-input');
    var confirmBtn   = document.getElementById('app-override-confirm-btn');
    var errorEl      = document.getElementById('app-override-error');
    var overrideChk  = document.getElementById('app-override-mark-compliant');
    var instanceId   = _getInstanceId ? _getInstanceId() : null;
    const manifest = _getManifest ? _getManifest() : null;
    const parcelKey = currentOverrideParcelKey;
    const aoiData = currentOverrideAoiData;
    if (reviewSavePending || (confirmBtn && confirmBtn.disabled)) return;
    if (!reasonInput || !instanceId || !manifest || parcelKey === null) {
      showPanelError('app-override-error', 'Cannot save without an active assessment. Reopen the analysis and try again.');
      return;
    }

    var note       = reasonInput.value.trim();
    var doOverride = overrideChk ? overrideChk.checked : false;
    if (!note) return;
    if (doOverride && note.length < MIN_REVIEW_NOTE_LENGTH) {
      if (errorEl) {
        errorEl.textContent = 'Note must be at least ' + MIN_REVIEW_NOTE_LENGTH + ' characters when marking as reviewed.';
        errorEl.hidden = false;
      }
      return;
    }

    var originalText = confirmBtn ? confirmBtn.textContent : 'Save assessment';
    const editorGeneration = reviewEditorGeneration;
    reviewSavePending = true;
    if (confirmBtn) { confirmBtn.disabled = true; confirmBtn.textContent = 'Saving\u2026'; }
    if (errorEl)    { errorEl.hidden = true; errorEl.textContent = ''; }

    try {
      if (_getApiReady) await _getApiReady();
      var url = '/api/analysis/' + instanceId + '/parcel/' + parcelKey + '/review';
      var res = await _apiFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ override: doOverride, note: note }),
      });
      if (!res.ok) {
        throw new Error('Failed to save assessment. Try again. (HTTP ' + res.status + ')');
      }
      // Update the in-memory manifest so UI reflects the change immediately
      if (manifest) {
        if (!manifest.parcel_reviews) manifest.parcel_reviews = {};
        manifest.parcel_reviews[parcelKey] = {
          override:    doOverride,
          note:        note,
          reviewed_at: new Date().toISOString(),
        };
      }
      if (isCurrentReview(manifest, instanceId, parcelKey, currentOverrideParcelKey) &&
          editorGeneration === reviewEditorGeneration && reasonInput.value.trim() === note &&
          (!overrideChk || overrideChk.checked === doOverride)) {
        closeOverrideModal();
        renderParcelOverride(parcelKey, aoiData);
      }
    } catch (e) {
      console.warn('Review save error:', e);
      if (isCurrentReview(manifest, instanceId, parcelKey, currentOverrideParcelKey) &&
          editorGeneration === reviewEditorGeneration) {
        showPanelError('app-override-error', 'Failed to save assessment. Your draft is unchanged; try again.');
      }
    } finally {
      reviewSavePending = false;
      if (confirmBtn) confirmBtn.textContent = originalText;
      onOverrideReasonInput();
    }
  }

  async function revertOverride() {
    const instanceId = _getInstanceId ? _getInstanceId() : null;
    const parcelKey = currentOverrideParcelKey;
    const manifest = _getManifest ? _getManifest() : null;
    const aoiData = currentOverrideAoiData;
    const revertBtn = document.getElementById('app-evidence-override-revert-btn');
    if (revertBtn && revertBtn.disabled) return;
    if (!instanceId || !manifest || parcelKey === null) {
      showPanelError('app-evidence-override-error', 'Cannot revert without an active assessment. Reopen the analysis and try again.');
      return;
    }
    showPanelError('app-evidence-override-error', '');
    if (revertBtn) { revertBtn.disabled = true; revertBtn.textContent = 'Reverting\u2026'; }

    // When an active review exists (review layer, #866), revert via the review
    // endpoint so the audit history is updated.  Only fall back to the legacy
    // parcel_overrides endpoint when there is no active review.
    var hasReview = manifest && manifest.parcel_reviews &&
                    manifest.parcel_reviews[parcelKey];

    try {
      if (_getApiReady) await _getApiReady();
      if (hasReview) {
        var url = '/api/analysis/' + instanceId + '/parcel/' + parcelKey + '/review';
        var res = await _apiFetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'revert' }),
        });
        if (!res.ok) throw new Error('Failed to revert assessment. (HTTP ' + res.status + ')');
        if (manifest.parcel_reviews) {
          delete manifest.parcel_reviews[parcelKey];
        }
      } else {
        var legacyRes = await _apiFetch('/api/analysis/override', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            instance_id: instanceId,
            parcel_key: parcelKey,
            reason: '',
            revert: true,
          }),
        });
        if (!legacyRes.ok) throw new Error('Failed to revert assessment. (HTTP ' + legacyRes.status + ')');
        if (manifest.parcel_overrides) {
          delete manifest.parcel_overrides[parcelKey];
        }
      }
      if (isCurrentReview(manifest, instanceId, parcelKey, currentOverrideParcelKey)) {
        renderParcelOverride(parcelKey, aoiData);
      }
    } catch (e) {
      console.warn('Override revert error:', e);
      if (isCurrentReview(manifest, instanceId, parcelKey, currentOverrideParcelKey)) {
        showPanelError('app-evidence-override-error', 'Reversion outcome is unconfirmed. Reload this analysis to check the saved review before retrying.');
      }
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
