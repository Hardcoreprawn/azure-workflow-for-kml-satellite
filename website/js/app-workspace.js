(function () {
  'use strict';

  const WORKSPACE_ROLES = {
    conservation: {
      label: 'Conservation',
      tag: 'Field evidence',
      title: 'Conservation monitoring',
      summary: 'Built for protected-area coordinators who need rapid, plain-English evidence they can take to rangers, directors, or donors.',
      outcome: 'Evidence packs',
      risk: 'No silent fallback',
      rhythm: 'Monthly watchlist',
      historyCopy: 'Keep the most recent incident visible while you compare new reports against what already ran.',
      runCopy: 'Queue an analysis for a protected area or reported clearing.',
      contentCopy: 'Use this rail to understand what evidence is being assembled and what will be ready for a field or donor brief.',
      runLensTitle: 'Conservation analysis',
      runLensNote: 'Frame this run around vegetation change, weather context, and plain-English proof.',
      readyNote: 'Ready to run a conservation analysis.',
      emptyHistoryNote: 'Your next submission will appear here.',
      activeHistoryContext: 'field evidence',
      completedHistoryOutcome: 'shareable evidence brief',
      activePath: 'Tracking evidence build',
      completedPath: 'Review results',
      runLabel: 'Start analysis',
      reviewLabel: 'Review latest incident',
      deliverableLabel: 'Open evidence rail',
      emptyContent: {
        imageryTitle: 'Waiting for a run',
        imageryNote: 'Before/after imagery and NDVI layers will appear here as the evidence stack forms.',
        enrichmentTitle: 'Context pending',
        enrichmentNote: 'Weather and narrative context will follow once the imagery pipeline is stable.',
        exportsTitle: 'Evidence pack next',
        exportsNote: 'Saved maps, narrative, and donor-ready exports will land here once run detail is wired.'
      },
      completedContent: {
        exportsTitle: 'Evidence pack next',
        exportsNote: 'Maps, narrative, and a field-ready evidence pack will be available after results load.'
      }
    },
    eudr: {
      label: 'EUDR',
      tag: 'Audit trail',
      title: 'EUDR due diligence',
      summary: 'Support compliance teams that need post-2020 evidence, clear audit language, and no ambiguity about what the product actually processed.',
      outcome: 'Due diligence dossier',
      risk: 'Audit-ready trust',
      rhythm: 'Quarterly refresh cadence',
      historyCopy: 'Keep the most recent assessment visible while you decide whether another supplier plot needs review.',
      runCopy: 'Queue a due diligence run with explicit product-path status.',
      contentCopy: 'Use this rail to understand what audit evidence is forming before it becomes a saved due diligence dossier.',
      runLensTitle: 'EUDR compliance check',
      runLensNote: 'Keep baseline integrity, plain-English findings, and product-path reliability front and center.',
      readyNote: 'Ready to run a due diligence check.',
      emptyHistoryNote: 'Your next submission will appear here.',
      activeHistoryContext: 'audit context',
      completedHistoryOutcome: 'due diligence dossier',
      activePath: 'Tracking audit evidence',
      completedPath: 'Prepare audit dossier',
      runLabel: 'Start due diligence run',
      reviewLabel: 'Review latest assessment',
      deliverableLabel: 'Open dossier rail',
      emptyContent: {
        imageryTitle: 'Awaiting baseline review',
        imageryNote: 'Before/after imagery will anchor the post-2020 evidence trail once you queue a run.',
        enrichmentTitle: 'Assessment pending',
        enrichmentNote: 'Narrative findings and methodology framing follow after imagery is stable.',
        exportsTitle: 'Audit dossier next',
        exportsNote: 'Saved evidence packages with coordinates, methods, and narrative will land here once run detail is wired.'
      },
      completedContent: {
        exportsTitle: 'Audit dossier next',
        exportsNote: 'Coordinates, methods, and exportable due diligence evidence will be available after results load.'
      }
    },
    portfolio: {
      label: 'Portfolio Ops',
      tag: 'Batch triage',
      title: 'Portfolio operations',
      summary: 'Support advisors, insurers, and ops teams who need to scan many parcels quickly, keep batch context visible, and decide what needs follow-up.',
      outcome: 'Batch triage',
      risk: 'Scale without guesswork',
      rhythm: 'Event-driven review',
      historyCopy: 'Keep the most recent batch visible so you can triage new uploads against what already moved.',
      runCopy: 'Queue a batch-style analysis and keep scale warnings visible.',
      contentCopy: 'Use this rail to understand what the current run is building before you reopen it as a parcel-level review.',
      runLensTitle: 'Portfolio triage run',
      runLensNote: 'Bias the workspace toward batch readiness, AOI spread, and which runs need deeper follow-up.',
      readyNote: 'Ready to run a batch analysis.',
      emptyHistoryNote: 'Your next submission will appear here.',
      activeHistoryContext: 'batch context',
      completedHistoryOutcome: 'triage summary',
      activePath: 'Tracking batch progress',
      completedPath: 'Open triage summary',
      runLabel: 'Start batch triage run',
      reviewLabel: 'Review latest batch',
      deliverableLabel: 'Open triage rail',
      emptyContent: {
        imageryTitle: 'Awaiting parcel stack',
        imageryNote: 'Imagery layers will appear here as batch-ready AOIs begin resolving into usable review outputs.',
        enrichmentTitle: 'Triage context pending',
        enrichmentNote: 'Context layers follow once the imagery stack shows where deeper review is needed.',
        exportsTitle: 'Triage summary next',
        exportsNote: 'Saved parcel review packs and export actions will land here once run detail is wired.'
      },
      completedContent: {
        exportsTitle: 'Triage summary next',
        exportsNote: 'Parcel-level review and export actions will be available after results load.'
      }
    }
  };

  const WORKSPACE_PREFERENCES = {
    investigate: {
      label: 'Investigate',
      tag: 'Run-first',
      title: 'Investigate suspicious change',
      summary: 'Stay centered on the live run while you prove what changed, why it changed, and what to do next.',
      deliverable: 'Operator brief',
      stance: 'Prove the change before escalation',
      primaryTarget: 'run',
      secondaryTarget: 'history'
    },
    monitor: {
      label: 'Monitor',
      tag: 'Queue-first',
      title: 'Monitor for movement over time',
      summary: 'Bias the workspace toward what changed recently so recurring reviews and follow-up runs stay efficient.',
      deliverable: 'Monitoring cadence',
      stance: 'Spot movement early and repeat',
      primaryTarget: 'history',
      secondaryTarget: 'run'
    },
    report: {
      label: 'Report',
      tag: 'Deliverable-first',
      title: 'Package findings for action',
      summary: 'Focus on outputs, evidence language, and what to deliver next.',
      deliverable: 'Decision packet',
      stance: 'Translate signal into action',
      primaryTarget: 'content',
      secondaryTarget: 'run'
    }
  };

  let _deps = {};
  let _workspaceRole = 'conservation';
  let _workspacePreference = 'investigate';

  function init(deps) {
    _deps = deps || {};
  }

  function readStoredValue(key) {
    if (_deps.readStoredValue) return _deps.readStoredValue(key);
    return null;
  }

  function storeValue(key, value) {
    if (_deps.storeValue) _deps.storeValue(key, value);
  }

  function currentRoleConfig() {
    return WORKSPACE_ROLES[_workspaceRole] || WORKSPACE_ROLES.conservation;
  }

  function currentPreferenceConfig() {
    return WORKSPACE_PREFERENCES[_workspacePreference] || WORKSPACE_PREFERENCES.investigate;
  }

  function notifyChange() {
    if (_deps.onChange) _deps.onChange();
  }

  function setRole(roleKey, options) {
    if (!WORKSPACE_ROLES[roleKey]) return;
    _workspaceRole = roleKey;
    if (_deps.setCoreState) _deps.setCoreState('workspaceRole', roleKey);
    if (!options || options.persist !== false) {
      storeValue(_deps.roleStorageKey, roleKey);
    }
    notifyChange();
  }

  function setPreference(preferenceKey, options) {
    if (!WORKSPACE_PREFERENCES[preferenceKey]) return;
    _workspacePreference = preferenceKey;
    if (_deps.setCoreState) _deps.setCoreState('workspacePreference', preferenceKey);
    if (!options || options.persist !== false) {
      storeValue(_deps.preferenceStorageKey, preferenceKey);
    }
    notifyChange();
  }

  function bootstrap(activeProfile, lockedWorkspace) {
    const profile = activeProfile || {};
    if (lockedWorkspace) {
      _workspaceRole = profile.defaultRole || 'eudr';
      _workspacePreference = profile.defaultPreference || 'report';
    } else {
      _workspaceRole = readStoredValue(_deps.roleStorageKey) || _workspaceRole;
      _workspacePreference = readStoredValue(_deps.preferenceStorageKey) || _workspacePreference;
    }
    if (_deps.setCoreState) {
      _deps.setCoreState('workspaceRole', _workspaceRole);
      _deps.setCoreState('workspacePreference', _workspacePreference);
    }
    notifyChange();
  }

  function getRole() {
    return _workspaceRole;
  }

  function getPreference() {
    return _workspacePreference;
  }

  window.CanopexWorkspace = {
    init: init,
    bootstrap: bootstrap,
    getRole: getRole,
    getPreference: getPreference,
    currentRoleConfig: currentRoleConfig,
    currentPreferenceConfig: currentPreferenceConfig,
    setRole: setRole,
    setPreference: setPreference,
  };
})();
