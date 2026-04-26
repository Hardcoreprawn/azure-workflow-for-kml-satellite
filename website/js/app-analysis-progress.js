/**
 * app-analysis-progress.js
 *
 * Pipeline progress UI: step indicators, enrichment sub-steps,
 * and the analysis story text. Extracted from app-shell.js.
 *
 * Exposes window.CanopexAnalysisProgress = {
 *   init, reset, setVisible, setStep, mapPhase, updateStory
 * }
 */
(function () {
  'use strict';

  var _setAnalysisStatus = null;
  var _getActiveProfile = null;
  var _getAnalysisPhases = null;
  var _getAnalysisPhaseDetails = null;
  var _summarizeRunTiming = null;

  const ENRICHMENT_STEP_LABELS = {
    data_sources_and_imagery: 'Fetching weather, flood/fire context, and registering satellite mosaics in parallel.',
    per_aoi: 'Running per-parcel enrichment across AOIs in parallel.',
    finalizing: 'Merging results and storing the analysis manifest.'
  };

  // Sub-step order for the enrichment phase progress UI.
  // 'data_sources_and_imagery' maps to both data_sources_and_imagery + imagery
  // sub-bullets since the orchestrator runs them in parallel under one status.
  const ENRICHMENT_SUB_ORDER = ['data_sources_and_imagery', 'imagery', 'per_aoi', 'finalizing'];

  function init(deps) {
    _setAnalysisStatus = deps.setAnalysisStatus;
    _getActiveProfile = deps.getActiveProfile;
    _getAnalysisPhases = deps.getAnalysisPhases;
    _getAnalysisPhaseDetails = deps.getAnalysisPhaseDetails;
    _summarizeRunTiming = deps.summarizeRunTiming;
  }

  function analysisPhases() {
    return _getAnalysisPhases ? _getAnalysisPhases() : ['submit', 'ingestion', 'acquisition', 'fulfilment', 'enrichment', 'complete'];
  }

  // ── Sub-step helpers ──────────────────────────────────────────

  function updateEnrichmentSubSteps(enrichmentStep) {
    const container = document.querySelector('#app-analysis-progress .pipeline-step[data-phase="enrichment"] .pipeline-sub-steps');
    if (!container) return;
    container.hidden = false;
    const currentIdx = ENRICHMENT_SUB_ORDER.indexOf(enrichmentStep);
    const subs = container.querySelectorAll('.pipeline-sub-step');
    subs.forEach(function (el) {
      const sub = el.getAttribute('data-sub');
      const icon = el.querySelector('.sub-icon');
      el.className = 'pipeline-sub-step';
      if (!icon) return;
      const subIdx = ENRICHMENT_SUB_ORDER.indexOf(sub);
      if (subIdx < 0) return;

      // data_sources_and_imagery and imagery run in parallel — treat
      // them as the same phase for status purposes.
      const isParallelPair = (sub === 'imagery' && enrichmentStep === 'data_sources_and_imagery')
        || (sub === 'data_sources_and_imagery' && enrichmentStep === 'imagery');

      if (sub === enrichmentStep || isParallelPair) {
        el.classList.add('active');
        icon.replaceChildren();
        const spinner = document.createElement('span');
        spinner.className = 'spinner';
        icon.appendChild(spinner);
      } else if (subIdx < currentIdx) {
        el.classList.add('done');
        icon.textContent = '✓';
      } else {
        icon.textContent = '○';
      }
    });
  }

  function resetEnrichmentSubSteps() {
    const container = document.querySelector('#app-analysis-progress .pipeline-step[data-phase="enrichment"] .pipeline-sub-steps');
    if (!container) return;
    container.hidden = true;
    const subs = container.querySelectorAll('.pipeline-sub-step');
    subs.forEach(function (el) {
      el.className = 'pipeline-sub-step';
      const icon = el.querySelector('.sub-icon');
      if (icon) icon.textContent = '○';
    });
  }

  function completeEnrichmentSubSteps() {
    const container = document.querySelector('#app-analysis-progress .pipeline-step[data-phase="enrichment"] .pipeline-sub-steps');
    if (!container) return;
    container.hidden = false;
    const subs = container.querySelectorAll('.pipeline-sub-step');
    subs.forEach(function (el) {
      el.className = 'pipeline-sub-step done';
      const icon = el.querySelector('.sub-icon');
      if (icon) icon.textContent = '✓';
    });
  }

  // ── Public API ────────────────────────────────────────────────

  function reset() {
    var progress = document.getElementById('app-analysis-progress');
    if (!progress) return;
    progress.hidden = true;
    progress.querySelectorAll('.pipeline-step').forEach(function (el) {
      el.className = 'pipeline-step';
      var icon = el.querySelector('.step-icon');
      if (icon) icon.textContent = '○';
    });
    resetEnrichmentSubSteps();
  }

  function setVisible(visible) {
    var progress = document.getElementById('app-analysis-progress');
    if (!progress) return;
    progress.hidden = !visible;
  }

  function setStep(phase, state) {
    var phases = analysisPhases();
    var steps = document.querySelectorAll('#app-analysis-progress .pipeline-step');
    steps.forEach(function (el) {
      var stepPhase = el.getAttribute('data-phase');
      var icon = el.querySelector('.step-icon');
      el.className = 'pipeline-step';

      if (stepPhase === phase) {
        if (state === 'failed') el.classList.add('failed');
        else if (state === 'done') el.classList.add('done');
        else el.classList.add('active');
        if (!icon) return;
        if (state === 'done') {
          icon.textContent = '✓';
        } else if (state === 'failed') {
          icon.textContent = '✗';
        } else {
          icon.replaceChildren();
          var spinner = document.createElement('span');
          spinner.className = 'spinner';
          icon.appendChild(spinner);
        }
        return;
      }

      if (!icon) return;
      var stepIndex = phases.indexOf(stepPhase);
      var currentIndex = phases.indexOf(phase);
      if (stepIndex > -1 && currentIndex > -1 && stepIndex < currentIndex) {
        el.classList.add('done');
        icon.textContent = '✓';
      } else {
        icon.textContent = '○';
      }
    });
  }

  function mapPhase(customStatus, runtimeStatus) {
    var phases = analysisPhases();
    var appRuns = window.CanopexAppRuns || {};
    if (typeof appRuns.mapPhase === 'function') {
      return appRuns.mapPhase(customStatus, runtimeStatus, phases);
    }
    if (runtimeStatus === 'Completed') return 'complete';
    if (customStatus && customStatus.phase && phases.indexOf(customStatus.phase) > -1) {
      return customStatus.phase;
    }
    return 'submit';
  }

  function updateStory(phase, runtimeStatus, data) {
    var phases = analysisPhases();
    var runtime = runtimeStatus || 'Pending';
    var activeProfile = _getActiveProfile ? _getActiveProfile() : {};
    var defaultPhaseDetails = _getAnalysisPhaseDetails ? _getAnalysisPhaseDetails() : {};
    var phaseDetails = activeProfile.phaseDetails || defaultPhaseDetails;
    var detail = phaseDetails[phase] || 'Working through the analysis pipeline.';
    var timing = _summarizeRunTiming ? _summarizeRunTiming(data) : {};

    if (runtime !== 'Completed' && phase === 'enrichment') {
      var cs = data && data.customStatus;
      var step = cs && cs.step;
      const stepLabel = step && ENRICHMENT_STEP_LABELS[step];
      if (stepLabel) {
        detail = stepLabel;
        if (step === 'per_aoi' && cs.aois) {
          detail += ' (' + cs.aois + ' AOIs)';
        }
      } else {
        detail += ' Enrichment batches weather, flood/fire checks, mosaic registration, NDVI, and change detection in parallel.';
      }
      if (timing.sinceUpdate) {
        detail += ' Last backend update ' + timing.sinceUpdate + ' ago.';
      }
      // Drive the nested sub-step progress indicators.
      if (step) updateEnrichmentSubSteps(step);
    } else if (phase !== 'enrichment') {
      // Past enrichment (complete) — mark all sub-steps done.
      // Before enrichment — keep sub-steps hidden.
      const enrichIdx = phases.indexOf('enrichment');
      const phaseIdx = phases.indexOf(phase);
      if (phaseIdx > enrichIdx) {
        completeEnrichmentSubSteps();
      } else {
        resetEnrichmentSubSteps();
      }
      if (runtime !== 'Completed' && timing.elapsed) {
        detail += ' Elapsed ' + timing.elapsed + '.';
      }
    } else {
      // Completed while on enrichment phase — mark all sub-steps done.
      completeEnrichmentSubSteps();
    }

    if (!_setAnalysisStatus) return;
    if (runtime === 'Completed') {
      _setAnalysisStatus(detail, 'success');
      return;
    }
    if (runtime === 'Failed' || runtime === 'Canceled' || runtime === 'Terminated') {
      _setAnalysisStatus('Analysis stopped during ' + phase + '. ' + detail, 'error');
      return;
    }
    _setAnalysisStatus(detail, 'info');
  }

  window.CanopexAnalysisProgress = {
    init: init,
    reset: reset,
    setVisible: setVisible,
    setStep: setStep,
    mapPhase: mapPhase,
    updateStory: updateStory,
  };
})();
