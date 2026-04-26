/**
 * app-bindings.js
 *
 * All DOM event listener registrations for the Canopex app.
 * Extracted from app-shell.js to reduce shell size and group
 * all click/input/change wiring in one place.
 *
 * Exposes window.CanopexBindings = { init }
 */
(function () {
  'use strict';

  // ── Injected deps ────────────────────────────────────────────
  var _deps = {};

  function init(deps) {
    _deps = deps || {};
    _registerAll();
  }

  // ── Helper ────────────────────────────────────────────────────

  function bindClick(id, handler) {
    var coreDom = window.CanopexCoreDom || {};
    if (typeof coreDom.bindClick === 'function') {
      coreDom.bindClick(id, handler);
      return;
    }
    var el = document.getElementById(id);
    if (el) el.addEventListener('click', handler);
  }

  // ── All registrations ─────────────────────────────────────────

  function _registerAll() {
    var d = _deps;

    // Workspace role / preference chooser cards
    document.querySelectorAll('[data-role-choice]').forEach(function (button) {
      button.addEventListener('click', function () {
        if (d.setWorkspaceRole) d.setWorkspaceRole(button.getAttribute('data-role-choice'));
      });
    });

    document.querySelectorAll('[data-preference-choice]').forEach(function (button) {
      button.addEventListener('click', function () {
        if (d.setWorkspacePreference) d.setWorkspacePreference(button.getAttribute('data-preference-choice'));
      });
    });

    // Auth
    bindClick('auth-login-btn', function () { if (d.login) d.login(); });
    bindClick('auth-logout-btn', function () { if (d.logout) d.logout(); });
    bindClick('app-sign-in-btn', function () { if (d.login) d.login(); });
    bindClick('app-analysis-sign-in-btn', function () { if (d.login) d.login(); });

    // Billing / account
    bindClick('app-manage-billing-btn', function () { if (d.manageBilling) d.manageBilling(); });
    bindClick('app-apply-tier-emulation-btn', function () { if (d.saveTierEmulation) d.saveTierEmulation(); });

    // Guided workflow
    bindClick('app-guided-primary-btn', function () {
      var target = this.getAttribute('data-target');
      if (d.revealWorkflowTarget && d.currentPreferenceConfig) {
        d.revealWorkflowTarget(target || d.currentPreferenceConfig().primaryTarget);
      }
    });
    bindClick('app-guided-secondary-btn', function () {
      var target = this.getAttribute('data-target');
      if (d.revealWorkflowTarget && d.currentPreferenceConfig) {
        d.revealWorkflowTarget(target || d.currentPreferenceConfig().secondaryTarget);
      }
    });

    // Analysis submit
    bindClick('app-analysis-submit-btn', function () { if (d.queueAnalysis) d.queueAnalysis(); });

    // Run-link copy-to-clipboard
    bindClick('app-run-link', function (event) {
      var el = document.getElementById('app-run-link');
      var href = el && el.href;
      if (!href) return;
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') {
        return; // Let normal navigation proceed
      }
      var fullUrl = new URL(href, window.location.origin).href;
      event.preventDefault();
      try {
        navigator.clipboard.writeText(fullUrl).then(function () {
          if (el._copyTimer) clearTimeout(el._copyTimer);
          var prev = el.textContent;
          el.textContent = 'Link copied!';
          el._copyTimer = setTimeout(function () {
            if (el.textContent === 'Link copied!') el.textContent = prev;
            el._copyTimer = null;
          }, 1500);
        }).catch(function () {
          window.location.href = href;
        });
      } catch (_) {
        window.location.href = href;
      }
    });

    // Run export format buttons (data-export-format)
    document.querySelectorAll('[data-export-format]').forEach(function (button) {
      button.addEventListener('click', function (event) {
        event.stopPropagation();
        if (d.downloadRunExport) d.downloadRunExport(button.getAttribute('data-export-format'));
      });
    });

    // KML text input
    var kmlInput = document.getElementById('app-analysis-kml');
    if (kmlInput) {
      kmlInput.addEventListener('input', function () {
        if (d.updateAnalysisPreflight) d.updateAnalysisPreflight(this.value);
      });
    }

    // File upload
    var fileInput = document.getElementById('app-analysis-file');
    if (fileInput) {
      fileInput.addEventListener('change', function () {
        if (this.files && this.files[0] && d.loadAnalysisFile) d.loadAnalysisFile(this.files[0]);
      });
    }

    // Input tab switching (KML / CSV)
    document.querySelectorAll('[data-input-tab]').forEach(function (tab) {
      tab.addEventListener('click', function () {
        if (d.switchInputTab) d.switchInputTab(this.getAttribute('data-input-tab'));
      });
    });
    bindClick('app-csv-convert-btn', function () { if (d.convertCSVToKml) d.convertCSVToKml(); });

    // Evidence surface controls
    bindClick('app-map-play-btn', function () { if (d.toggleEvidencePlay) d.toggleEvidencePlay(); });
    var frameSlider = document.getElementById('app-map-frame-slider');
    if (frameSlider) {
      frameSlider.addEventListener('input', function () {
        if (d.showEvidenceFrame) d.showEvidenceFrame(parseInt(this.value, 10));
      });
    }
    bindClick('app-map-btn-rgb', function () { if (d.setEvidenceLayerMode) d.setEvidenceLayerMode('rgb'); });
    bindClick('app-map-btn-ndvi', function () { if (d.setEvidenceLayerMode) d.setEvidenceLayerMode('ndvi'); });
    bindClick('app-evidence-ai-btn', function () { if (d.requestAiAnalysis) d.requestAiAnalysis(); });
    bindClick('app-evidence-eudr-btn', function () { if (d.requestEudrAssessment) d.requestEudrAssessment(); });

    // Parcel notes (#669)
    bindClick('app-evidence-notes-add-btn', function () { if (d.showNoteEditor) d.showNoteEditor(); });
    bindClick('app-evidence-notes-cancel-btn', function () { if (d.hideNoteEditor) d.hideNoteEditor(); });
    bindClick('app-evidence-notes-save-btn', function () { if (d.saveParcelNote) d.saveParcelNote(); });

    // Override determination controls (#672)
    bindClick('app-evidence-override-btn', function () {
      if (d.getOverrideContext && d.openOverrideModal) {
        var ctx = d.getOverrideContext();
        d.openOverrideModal(ctx.parcelKey, ctx.aoiData);
      }
    });
    bindClick('app-evidence-override-revert-btn', function () { if (d.revertOverride) d.revertOverride(); });
    bindClick('app-override-confirm-btn', function () { if (d.confirmOverride) d.confirmOverride(); });
    bindClick('app-override-cancel-btn', function () { if (d.closeOverrideModal) d.closeOverrideModal(); });
    var overrideBackdrop = document.getElementById('app-override-backdrop');
    if (overrideBackdrop) {
      overrideBackdrop.addEventListener('click', function (e) {
        if (e.target === this && d.closeOverrideModal) d.closeOverrideModal();
      });
    }
    var overrideReasonInput = document.getElementById('app-override-reason-input');
    if (overrideReasonInput) {
      overrideReasonInput.addEventListener('input', function () {
        if (d.onOverrideReasonInput) d.onOverrideReasonInput();
      });
    }

    // Portfolio summary export (#674)
    bindClick('app-summary-export-btn', function () {
      if (!d.apiFetch) return;
      var btn = document.getElementById('app-summary-export-btn');
      if (btn) { btn.disabled = true; btn.textContent = 'Downloading\u2026'; }
      d.apiFetch('/api/eudr/summary-export')
        .then(function (res) {
          if (!res.ok) throw new Error('Export failed (' + res.status + ')');
          return res.blob();
        })
        .then(function (blob) {
          var url = URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url;
          a.download = 'eudr_summary_export.csv';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        })
        .catch(function (err) {
          console.warn('EUDR summary export error:', err);
          var note = document.getElementById('app-summary-export-note');
          if (note) note.textContent = 'Export failed \u2014 try again';
        })
        .finally(function () {
          if (btn) { btn.disabled = false; btn.textContent = 'Export all runs (CSV)'; }
        });
    });

    // Expanded map viewer controls
    bindClick('app-map-expand-btn', function () { if (d.expandEvidenceMap) d.expandEvidenceMap(); });
    bindClick('app-map-collapse-btn', function () { if (d.collapseEvidenceMap) d.collapseEvidenceMap(); });
    bindClick('app-map-btn-compare', function () { if (d.toggleCompareView) d.toggleCompareView(); }); // #671
    var expandedBackdrop = document.getElementById('app-map-expanded-backdrop');
    if (expandedBackdrop) {
      expandedBackdrop.addEventListener('click', function (e) {
        if (e.target === this && d.collapseEvidenceMap) d.collapseEvidenceMap();
      });
    }
    bindClick('app-map-expanded-play-btn', function () { if (d.toggleEvidencePlay) d.toggleEvidencePlay(); });
    var expandedSlider = document.getElementById('app-map-expanded-slider');
    if (expandedSlider) {
      expandedSlider.addEventListener('input', function () {
        if (d.showEvidenceFrame) d.showEvidenceFrame(parseInt(this.value, 10));
      });
    }
    bindClick('app-map-expanded-btn-rgb', function () { if (d.setEvidenceLayerMode) d.setEvidenceLayerMode('rgb'); });
    bindClick('app-map-expanded-btn-ndvi', function () { if (d.setEvidenceLayerMode) d.setEvidenceLayerMode('ndvi'); });
  }

  // ── Public API ────────────────────────────────────────────────

  window.CanopexBindings = {
    init: init,
  };
})();
