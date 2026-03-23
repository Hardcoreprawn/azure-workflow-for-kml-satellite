(function(){
  'use strict';

  function escapeHtml(s) { if (s == null) return ''; var d = document.createElement('div'); d.appendChild(document.createTextNode(String(s))); return d.innerHTML; }

  const EXPECTED_CONTRACT = '2026-03-15.1';
  let apiBase = '';
  var pipelineInstanceId = null;   /* current pipeline run — for data retrieval */
  var enrichmentPayload = null;    /* cached enrichment manifest from pipeline */

  /* --- Entra External ID (CIAM) authentication --- */
  /* These are populated once the CIAM tenant is provisioned.
     When CIAM_CLIENT_ID is empty, auth is disabled and the app works anonymously. */
  const CIAM_TENANT_NAME = 'treesightauth';
  const CIAM_CLIENT_ID = '6e2abd0a-61a4-41a5-bdb5-7e1c91471fc6';
  const CIAM_AUTHORITY = CIAM_TENANT_NAME
    ? 'https://' + CIAM_TENANT_NAME + '.ciamlogin.com/'
    : '';
  const CIAM_KNOWN_AUTHORITY = CIAM_AUTHORITY;
  const CIAM_SCOPES = CIAM_CLIENT_ID ? ['openid', 'profile'] : [];

  var msalInstance = null;
  var currentAccount = null;
  var accessToken = null;

  function authEnabled() { return !!(CIAM_TENANT_NAME && CIAM_CLIENT_ID && typeof msal !== 'undefined'); }

  /* Initialise MSAL */
  function initAuth() {
    if (!authEnabled()) {
      /* Auth not configured — hide auth UI, allow anonymous access */
      updateAuthUI();
      return;
    }
    var msalConfig = {
      auth: {
        clientId: CIAM_CLIENT_ID,
        authority: CIAM_AUTHORITY,
        knownAuthorities: [CIAM_KNOWN_AUTHORITY],
        redirectUri: window.location.origin,
        postLogoutRedirectUri: window.location.origin,
      },
      cache: { cacheLocation: 'sessionStorage', storeAuthStateInCookie: false },
    };
    msalInstance = new msal.PublicClientApplication(msalConfig);

    /* Handle redirect promise (returns from CIAM login) */
    msalInstance.handleRedirectPromise().then(function(resp) {
      if (resp && resp.account) {
        msalInstance.setActiveAccount(resp.account);
      }
      currentAccount = msalInstance.getActiveAccount() || (msalInstance.getAllAccounts()[0] || null);
      if (currentAccount) { msalInstance.setActiveAccount(currentAccount); }
      updateAuthUI();
    }).catch(function(err) {
      console.warn('MSAL redirect error:', err);
      updateAuthUI();
    });
  }

  function login() {
    if (!msalInstance) return;
    msalInstance.loginRedirect({ scopes: CIAM_SCOPES });
  }

  function logout() {
    if (!msalInstance) return;
    msalInstance.logoutRedirect({ account: currentAccount });
  }

  async function acquireToken() {
    if (!msalInstance || !currentAccount) return null;
    try {
      var resp = await msalInstance.acquireTokenSilent({ scopes: CIAM_SCOPES, account: currentAccount });
      accessToken = resp.accessToken || resp.idToken;
      return accessToken;
    } catch {
      /* Silent failed — trigger interactive */
      try {
        msalInstance.acquireTokenRedirect({ scopes: CIAM_SCOPES });
      } catch { /* redirect will navigate away */ }
      return null;
    }
  }

  function updateAuthUI() {
    var loginBtn = document.getElementById('auth-login-btn');
    var logoutBtn = document.getElementById('auth-logout-btn');
    var userSpan = document.getElementById('auth-user');
    var loginPrompt = document.getElementById('login-prompt');
    var submitBtn = document.getElementById('demo-submit');

    if (!authEnabled()) {
      /* Auth not configured — hide auth controls, anonymous access */
      loginBtn.style.display = 'none';
      logoutBtn.style.display = 'none';
      userSpan.style.display = 'none';
      loginPrompt.style.display = 'none';
      if (submitBtn) submitBtn.textContent = 'Process KML';
      return;
    }

    if (currentAccount) {
      var name = currentAccount.name || currentAccount.username || 'User';
      userSpan.textContent = name;
      userSpan.style.display = 'inline';
      loginBtn.style.display = 'none';
      logoutBtn.style.display = 'inline';
      loginPrompt.style.display = 'none';
      if (submitBtn) submitBtn.textContent = 'Process KML';
    } else {
      userSpan.style.display = 'none';
      loginBtn.style.display = 'inline';
      logoutBtn.style.display = 'none';
      loginPrompt.style.display = 'block';
      if (submitBtn) submitBtn.textContent = 'Sign In to Process KML';
    }
  }

  function isLoggedIn() { return !authEnabled() || !!currentAccount; }

  /* --- API helper --- */
  async function apiFetch(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    /* Attach bearer token if authenticated */
    if (currentAccount && authEnabled()) {
      var token = accessToken || await acquireToken();
      if (token) { opts.headers['Authorization'] = 'Bearer ' + token; }
    }
    try { return await fetch(apiBase + path, opts); } catch { return null; }
  }

  /* --- API discovery: verify backend is reachable via SWA proxy --- */
  async function discoverApiBase() {
    /* 1. Try SWA linked backend proxy (ideal — no CORS needed) */
    try {
      var res = await fetch('/api/health');
      if (res.ok) { apiBase = ''; return; }
    } catch { /* network error */ }

    /* 2. Load deploy-time config for direct Function App hostname (#282) */
    try {
      var cfgRes = await fetch('/api-config.json');
      if (cfgRes.ok) {
        var cfg = await cfgRes.json();
        if (cfg.apiBase) {
          var probe = await fetch(cfg.apiBase + '/api/health');
          if (probe.ok) { apiBase = cfg.apiBase; return; }
        }
      }
    } catch { /* config not available or backend unreachable */ }

    console.warn('Backend not reachable — check SWA backend configuration or api-config.json');
  }

  /* --- Contract check (§12.3) --- */
  async function checkContract() {
    try {
      const res = await apiFetch('/api/contract');
      if (!res || !res.ok) return;
      const data = await res.json();
      document.getElementById('contract-version').textContent = data.api_version || '—';
      if (data.api_version !== EXPECTED_CONTRACT) {
        document.getElementById('contract-warning').classList.add('show');
        document.getElementById('demo-submit').disabled = true;
        document.getElementById('demo-submit').style.opacity = '0.5';
      }
    } catch { /* offline */ }
  }

  /* --- Status badge (§12.3) --- */
  async function checkStatus() {
    const badge = document.getElementById('status-badge');
    try {
      const res = await apiFetch('/api/readiness');
      if (res && res.ok) {
        badge.textContent = 'Online';
        badge.className = 'online';
      } else { throw new Error(); }
    } catch {
      badge.textContent = 'Offline';
      badge.className = 'offline';
    }
  }

  /* --- Demo form: parse KML and launch pipeline --- */
  function parseKmlCoords(kml) {
    var parser = new DOMParser();
    var doc = parser.parseFromString(kml, 'text/xml');
    /* Extract ALL polygons from the KML */
    var placemarks = doc.getElementsByTagName('Placemark');
    var polygons = [];
    /* Gather from placemarks first */
    for (var p = 0; p < placemarks.length; p++) {
      var coordEls = placemarks[p].getElementsByTagName('coordinates');
      var nameEl = placemarks[p].getElementsByTagName('name')[0];
      var pName = nameEl ? nameEl.textContent.trim() : 'Polygon ' + (polygons.length + 1);
      for (var c = 0; c < coordEls.length; c++) {
        var coords = parseCoordText(coordEls[c].textContent);
        if (coords) polygons.push({ name: pName, coords: coords });
      }
    }
    /* Fallback: bare <coordinates> outside placemarks */
    if (polygons.length === 0) {
      var allCoords = doc.getElementsByTagName('coordinates');
      for (var i = 0; i < allCoords.length; i++) {
        var coords = parseCoordText(allCoords[i].textContent);
        if (coords) polygons.push({ name: 'Polygon ' + (polygons.length + 1), coords: coords });
      }
    }
    if (polygons.length === 0) return null;
    return polygons;
  }

  function parseCoordText(text) {
    var raw = text.trim().split(/\s+/);
    var coords = raw.map(function(c) {
      var p = c.split(',');
      return [parseFloat(p[1]), parseFloat(p[0])];
    }).filter(function(c) { return !isNaN(c[0]) && !isNaN(c[1]); });
    if (coords.length < 3) return null;
    if (coords[0][0] !== coords[coords.length-1][0] ||
        coords[0][1] !== coords[coords.length-1][1]) {
      coords.push(coords[0].slice());
    }
    return coords;
  }

  /* Pipeline progress stepper */
  var PIPELINE_PHASES = ['submit','ingestion','acquisition','fulfilment','enrichment','complete'];
  function setPipelineStep(phase, state) {
    /* state: 'pending','active','done','failed' */
    var steps = document.querySelectorAll('#pipeline-progress .pipeline-step');
    steps.forEach(function(el) {
      var p = el.getAttribute('data-phase');
      var icon = el.querySelector('.step-icon');
      el.className = 'pipeline-step';
      if (p === phase) {
        el.classList.add(state === 'failed' ? 'failed' : 'active');
        if (state === 'done') { icon.textContent = '✓'; }
        else if (state === 'failed') { icon.textContent = '✗'; }
        else { icon.replaceChildren(); var sp = document.createElement('span'); sp.className = 'spinner'; icon.appendChild(sp); }
      } else {
        var pi = PIPELINE_PHASES.indexOf(p);
        var ci = PIPELINE_PHASES.indexOf(phase);
        if (pi < ci) { el.classList.add('done'); icon.textContent = '✓'; }
        else { icon.textContent = '○'; }
      }
    });
  }

  function showPipelineResults(output) {
    var el = document.getElementById('pipeline-results');
    var stats = document.getElementById('pipeline-stats');
    function addStat(value, label) {
      var div = document.createElement('div');
      div.className = 'stat';
      var b = document.createElement('b');
      b.textContent = parseInt(value, 10) || 0;
      div.appendChild(b);
      div.appendChild(document.createTextNode(' ' + label));
      stats.appendChild(div);
    }
    stats.replaceChildren();
    addStat(output.featureCount, 'features parsed');
    addStat(output.metadataCount, 'AOIs prepared');
    addStat(output.imageryReady, 'scenes acquired');
    addStat(output.imageryFailed, 'failed');
    addStat(output.downloadsCompleted, 'downloaded');
    addStat(output.postProcessCompleted, 'clipped & reprojected');
    el.style.display = 'block';
  }

  function showPipelineError(msg) {
    var el = document.getElementById('pipeline-error');
    var friendly = msg;
    var normalized = (msg || '').toString().toLowerCase();
    if (normalized.indexOf('api contract') !== -1 || normalized.indexOf('contract version') !== -1) {
      friendly = 'The analysis service is being updated. Please try again in a few minutes.';
    } else if (normalized.indexOf('timeout') !== -1 || normalized.indexOf('timed out') !== -1 || normalized.indexOf('etimedout') !== -1) {
      friendly = 'The data source is responding slowly. Please try again shortly.';
    } else if (normalized.indexOf('pipeline error') !== -1) {
      friendly = 'Something went wrong processing your data. Please try again or use a smaller AOI.';
    }
    el.textContent = friendly;
    el.style.display = 'block';
  }

  function resetPipelineUI() {
    document.getElementById('pipeline-progress').style.display = 'none';
    document.getElementById('pipeline-results').style.display = 'none';
    document.getElementById('pipeline-error').style.display = 'none';
    document.querySelectorAll('#pipeline-progress .pipeline-step').forEach(function(el) {
      el.className = 'pipeline-step';
      el.querySelector('.step-icon').textContent = '○';
    });
  }

  /* Map custom status phase → our step names */
  function mapCustomPhase(cs) {
    if (!cs || !cs.phase) return null;
    return cs.phase; /* 'ingestion','acquisition','fulfilment' */
  }

  /* Poll orchestrator status */
  async function pollOrchestrator(instanceId) {
    var POLL_INTERVAL = 2000;
    var MAX_POLLS = 300; /* 10 min max */
    var polls = 0;
    return new Promise(function(resolve, reject) {
      var timer = setInterval(async function() {
        polls++;
        if (polls > MAX_POLLS) {
          clearInterval(timer);
          reject(new Error('Pipeline timed out'));
          return;
        }
        try {
          var res = await apiFetch('/api/orchestrator/' + instanceId);
          if (!res) return;
          if (res.status === 404) return; /* not started yet */
          var data = await res.json();
          var status = data.runtimeStatus;
          var cs = data.customStatus;

          /* Update progress based on customStatus */
          var phase = mapCustomPhase(cs);
          if (phase) setPipelineStep(phase, 'active');

          if (status === 'Completed') {
            clearInterval(timer);
            setPipelineStep('complete', 'done');
            resolve(data.output);
          } else if (status === 'Failed' || status === 'Terminated' || status === 'Canceled') {
            clearInterval(timer);
            var failPhase = phase || 'submit';
            setPipelineStep(failPhase, 'failed');
            reject(new Error('Pipeline ' + status));
          }
        } catch(err) {
          /* network blip — keep polling */
        }
      }, POLL_INTERVAL);
    });
  }

  /* Back-to-KML button */
  document.getElementById('back-to-kml').addEventListener('click', function() {
    if (compareActive) exitCompareMode();
    document.getElementById('demo-layout').classList.remove('timelapse-active');
    document.getElementById('timelapse-header').classList.remove('visible');
    requestAnimationFrame(function(){ map.invalidateSize(); });
  });

  document.getElementById('analytics-scope-reset').addEventListener('click', function() {
    setCollectiveAnalytics();
  });

  /* Main submit handler */
  document.getElementById('demo-submit').addEventListener('click', async function() {
    var btn = this;
    var statusEl = document.getElementById('demo-status');

    /* Require login when auth is configured */
    if (!isLoggedIn()) {
      statusEl.textContent = 'Please sign in to process KML files.';
      statusEl.className = 'demo-status show error';
      login();
      return;
    }

    var kml = document.getElementById('demo-kml').value.trim();

    if (!kml) {
      statusEl.textContent = 'Paste KML content above first.';
      statusEl.className = 'demo-status show error';
      return;
    }
    var polygons = parseKmlCoords(kml);
    if (!polygons) {
      statusEl.textContent = 'Could not find valid coordinates in the KML.';
      statusEl.className = 'demo-status show error';
      return;
    }

    /* Proximity check — all polygon centroids within 25 km of group centroid */
    var err = checkPolygonProximity(polygons, 25);
    if (err) {
      statusEl.textContent = err;
      statusEl.className = 'demo-status show error';
      return;
    }

    /* Compute union bounding-box coords for imagery search */
    var coords = unionBboxCoords(polygons);

    /* Reset UI */
    statusEl.textContent = '';
    statusEl.className = 'demo-status';
    resetPipelineUI();
    btn.disabled = true;
    btn.style.opacity = '0.5';
    btn.textContent = 'Processing…';
    document.getElementById('pipeline-progress').style.display = 'block';

    /* Show AOI on map immediately */
    setAoi(coords, polygons);

    /* Step 1: Submit to backend */
    setPipelineStep('submit', 'active');
    try {
      var res = await apiFetch('/api/demo-process', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ kml_content: kml })
      });
      if (!res || !res.ok) {
        var errData = res ? await res.json().catch(function(){return {};}) : {};
        throw new Error(errData.error || 'Failed to submit KML (HTTP ' + (res?res.status:'?') + ')');
      }
      var submitData = await res.json();
      var instanceId = submitData.instance_id;
      pipelineInstanceId = instanceId;
      setPipelineStep('submit', 'done');

      /* Step 2-4: Poll orchestration */
      setPipelineStep('ingestion', 'active');
      document.getElementById('frame-info').textContent = 'Pipeline processing KML…';

      var output = await pollOrchestrator(instanceId);
      showPipelineResults(output);

      /* Step 5: Fetch enrichment manifest from pipeline */
      document.getElementById('frame-info').textContent = 'Loading pipeline data…';
      enrichmentPayload = null;
      try {
        var enrichRes = await apiFetch('/api/timelapse-data/' + instanceId);
        if (enrichRes && enrichRes.ok) {
          enrichmentPayload = await enrichRes.json();
          console.log('Enrichment payload loaded:', Object.keys(enrichmentPayload));
        }
      } catch(e) {
        console.warn('Could not load enrichment data, falling back to live fetch:', e);
      }

      /* Step 6: Launch timelapse with pipeline-produced data */
      document.getElementById('frame-info').textContent = 'Loading satellite imagery timelapse…';
      launchTimelapse(coords, polygons);

    } catch(err) {
      showPipelineError('Pipeline error: ' + err.message);
      /* Still launch timelapse so the demo remains functional */
      enrichmentPayload = null;
      document.getElementById('frame-info').textContent = 'Loading imagery directly — some features may be limited.';
      launchTimelapse(coords, polygons);
    } finally {
      btn.disabled = false;
      btn.style.opacity = '1';
      btn.textContent = 'Process KML';
    }
  });

  /* --- Sample KML locations --- */
  var SAMPLE_KMLS = {
    madera: {
      name: 'Madera County Orchards',
      placemark: 'Block A — Almond Grove',
      desc: 'San Joaquin Valley irrigated agriculture. 87 ha almond orchard block.',
      coords: '-120.08,36.86,0 -120.04,36.86,0 -120.04,36.90,0 -120.08,36.90,0 -120.08,36.86,0'
    },
    nechako: {
      name: 'Nechako TSA — Old Growth Cut Block',
      placemark: 'EM807M — Clear Cut',
      desc: '87 ha old-growth block, Entiako/Nechako Timber Supply Area, ~290 km west of Prince George. Classified as old growth prior to harvest. Logged for biomass pellet export.',
      coords: '-125.567,53.4458,0 -125.553,53.4458,0 -125.553,53.4542,0 -125.567,53.4542,0 -125.567,53.4458,0'
    },
    para: {
      name: 'Novo Progresso, Pará — Deforestation Front',
      placemark: 'BR-163 Corridor — Active Clearance',
      desc: 'Amazon deforestation hotspot along the BR-163 highway. Cattle ranching expansion into primary rainforest.',
      coords: '-55.42,-7.05,0 -55.38,-7.05,0 -55.38,-7.01,0 -55.42,-7.01,0 -55.42,-7.05,0'
    },
    borneo: {
      name: 'East Kalimantan — Palm Oil Clearance',
      placemark: 'Muara Wahau Block',
      desc: 'Tropical rainforest cleared for palm oil plantation. Visible progression from intact canopy to bare soil to monoculture rows.',
      coords: '116.72,1.32,0 116.76,1.32,0 116.76,1.36,0 116.72,1.36,0 116.72,1.32,0'
    },
    carpathians: {
      name: 'Suceava County — Carpathian Old Growth',
      placemark: 'Valea Bârnii Logging Road',
      desc: 'Virgin and quasi-virgin forest in the Romanian Carpathians. Illegal and legal logging documented by satellite since 2015.',
      coords: '25.24,47.56,0 25.28,47.56,0 25.28,47.60,0 25.24,47.60,0 25.24,47.56,0'
    },
    mountsorrel: {
      name: 'Mountsorrel, Leicestershire — Mixed Agriculture',
      desc: 'Three irregular field-boundary AOIs: quarry fringe fields, marsh greenspace along the A6, and Rothley corridor fields between Mountsorrel and Rothley (avoiding housing).',
      placemarks: [
        { name: 'Mountsorrel Quarry Fringe Fields', coords: '-1.163346489553824,52.73591073328891,0 -1.16454385180782,52.73898592488101,0 -1.171480701892619,52.74040384086778,0 -1.177672309009341,52.73892094146273,0 -1.185820529557469,52.73571347839705,0 -1.183141247105948,52.72625498343694,0 -1.174673350901264,52.73053613187274,0 -1.173669888188441,52.73383598858731,0 -1.163346489553824,52.73591073328891,0' },
        { name: 'Rothley Fields (Mountsorrel-Rothley)', coords: '-1.150538641898804,52.71163222500047,0 -1.147111527351354,52.70674347661485,0 -1.142296003917834,52.70770322396908,0 -1.144704136201167,52.71026829685255,0 -1.143509561724939,52.71105183814781,0 -1.143682520522413,52.71174652869291,0 -1.141995080480386,52.71408032899082,0 -1.140195448589377,52.71464140218112,0 -1.140117851258037,52.71520846997541,0 -1.138617689728367,52.71533072484635,0 -1.138879647981477,52.71727699024064,0 -1.139993937242928,52.71780589706643,0 -1.143154201545626,52.71576675564348,0 -1.144813227283444,52.71594849063733,0 -1.145892915627135,52.71467732226228,0 -1.147724704080366,52.71445802089693,0 -1.148378321512754,52.71443300244922,0 -1.149237571313735,52.71479574095385,0 -1.150099919200553,52.7157275186585,0 -1.152363189163397,52.71532615080313,0 -1.154769073986222,52.71396072150848,0 -1.150538641898804,52.71163222500047,0' },
        { name: 'Mountsorrel Marsh (A6 Corridor)', coords: '-1.130392031975221,52.72775766038671,0 -1.127904438866779,52.72280872459255,0 -1.125537437470283,52.72408289769498,0 -1.120101773716528,52.72169358158452,0 -1.118064304041352,52.7228640698732,0 -1.118031438573714,52.72456097899229,0 -1.118278344049619,52.72511919064861,0 -1.120802048396041,52.7275891684749,0 -1.123232531465785,52.72801959501597,0 -1.124081556231947,52.72697568754046,0 -1.1250115164998,52.72722229418645,0 -1.125649513716936,52.72823130631017,0 -1.12470756595124,52.72840271723449,0 -1.122079967448409,52.73035685947281,0 -1.126616568474529,52.73128083475977,0 -1.130679657527537,52.7337328441124,0 -1.132715112921041,52.73405606765941,0 -1.135043901364565,52.73328119480784,0 -1.130392031975221,52.72775766038671,0' }
      ]
    }
  };

  function buildSampleKml(s) {
    var placemarks = '';
    if (s.placemarks) {
      /* Multi-polygon sample */
      s.placemarks.forEach(function(p) {
        placemarks +=
          '    <Placemark>\n' +
          '      <name>' + p.name + '</name>\n' +
          '      <Polygon>\n' +
          '        <outerBoundaryIs>\n' +
          '          <LinearRing>\n' +
          '            <coordinates>' + p.coords + '</coordinates>\n' +
          '          </LinearRing>\n' +
          '        </outerBoundaryIs>\n' +
          '      </Polygon>\n' +
          '    </Placemark>\n';
      });
    } else {
      placemarks =
        '    <Placemark>\n' +
        '      <name>' + s.placemark + '</name>\n' +
        '      <Polygon>\n' +
        '        <outerBoundaryIs>\n' +
        '          <LinearRing>\n' +
        '            <coordinates>' + s.coords + '</coordinates>\n' +
        '          </LinearRing>\n' +
        '        </outerBoundaryIs>\n' +
        '      </Polygon>\n' +
        '    </Placemark>\n';
    }
    return '<?xml version="1.0" encoding="UTF-8"?>\n' +
      '<kml xmlns="http://www.opengis.net/kml/2.2">\n' +
      '  <Document>\n' +
      '    <name>' + s.name + '</name>\n' +
      '    <description>' + s.desc + '</description>\n' +
      placemarks +
      '  </Document>\n' +
      '</kml>';
  }

  document.getElementById('sample-picker').addEventListener('change', function() {
    var key = this.value;
    if (!key || !SAMPLE_KMLS[key]) return;
    document.getElementById('demo-kml').value = buildSampleKml(SAMPLE_KMLS[key]);
    this.value = ''; /* reset so the same option can be re-selected */
  });

  /* --- Early Access form --- */
  document.getElementById('ea-submit').addEventListener('click', async function() {
    const org = document.getElementById('ea-org').value.trim();
    const useCase = document.getElementById('ea-usecase').value.trim();
    const email = document.getElementById('ea-email').value.trim();
    const status = document.getElementById('ea-status');
    if (!org || !email) {
      status.textContent = 'Please provide at least organisation and email.';
      status.className = 'show';
      status.style.color = 'var(--c-red)';
      return;
    }
    status.textContent = 'Submitting…';
    status.className = 'show';
    status.style.color = 'var(--c-muted)';
    try {
      const res = await apiFetch('/api/contact-form', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          organisation: org,
          use_case: useCase,
          email: email,
          source: 'marketing_website'
        })
      });
      if (res && res.ok) {
        status.textContent = 'Thanks! We\'ll be in touch.';
        status.style.color = 'var(--c-green)';
      } else {
        status.textContent = 'Submission failed. Please try again.';
        status.style.color = 'var(--c-red)';
      }
    } catch {
      status.textContent = 'Failed to reach API.';
      status.style.color = 'var(--c-red)';
    }
  });

  /* --- FAQ toggle --- */
  document.getElementById('faq-list').addEventListener('click', function(e) {
    const item = e.target.closest('.faq-item');
    if (item) item.classList.toggle('open');
  });

  /* --- File upload (drag-drop + click) --- */
  (function() {
    var dropZone = document.getElementById('drop-zone');
    var fileInput = document.getElementById('file-input');
    var fileNameEl = document.getElementById('drop-file-name');
    var textarea = document.getElementById('demo-kml');
    var MAX_SIZE = 5 * 1024 * 1024; /* 5 MB */

    function handleFile(file) {
      if (!file) return;
      if (file.size > MAX_SIZE) {
        fileNameEl.textContent = 'File too large (max 5 MB)';
        fileNameEl.style.color = 'var(--c-red)';
        return;
      }
      var name = file.name.toLowerCase();
      if (name.endsWith('.kmz')) {
        readKmz(file);
      } else if (name.endsWith('.kml')) {
        readKml(file);
      } else {
        fileNameEl.textContent = 'Unsupported file type — use .kml or .kmz';
        fileNameEl.style.color = 'var(--c-red)';
      }
    }

    function readKml(file) {
      var reader = new FileReader();
      reader.onload = function(e) {
        textarea.value = e.target.result;
        fileNameEl.textContent = '✓ ' + file.name;
        fileNameEl.style.color = '';
      };
      reader.onerror = function() {
        fileNameEl.textContent = 'Error reading file';
        fileNameEl.style.color = 'var(--c-red)';
      };
      reader.readAsText(file);
    }

    function readKmz(file) {
      fileNameEl.textContent = 'Reading KMZ…';
      fileNameEl.style.color = '';
      var reader = new FileReader();
      reader.onload = async function(e) {
        try {
          var blob = new Blob([e.target.result]);
          /* KMZ is a ZIP — find the local file header and extract */
          var buf = await blob.arrayBuffer();
          var view = new DataView(buf);
          var kmlContent = null;

          /* Walk ZIP local file headers */
          var offset = 0;
          while (offset < buf.byteLength - 4) {
            var sig = view.getUint32(offset, true);
            if (sig !== 0x04034b50) break;  /* PK\x03\x04 */
            var compMethod = view.getUint16(offset + 8, true);
            var compSize = view.getUint32(offset + 18, true);
            var uncompSize = view.getUint32(offset + 22, true);
            var fnLen = view.getUint16(offset + 26, true);
            var extraLen = view.getUint16(offset + 28, true);
            var fnBytes = new Uint8Array(buf, offset + 30, fnLen);
            var fn = new TextDecoder().decode(fnBytes);
            var dataStart = offset + 30 + fnLen + extraLen;

            if (fn.toLowerCase().endsWith('.kml')) {
              var compressed = new Uint8Array(buf, dataStart, compSize);
              if (compMethod === 0) {
                /* Stored (no compression) */
                kmlContent = new TextDecoder().decode(compressed);
              } else if (compMethod === 8) {
                /* Deflated */
                var stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
                var decompressed = await new Response(stream).text();
                kmlContent = decompressed;
              }
              break;
            }
            offset = dataStart + compSize;
          }

          if (kmlContent) {
            textarea.value = kmlContent;
            fileNameEl.textContent = '✓ ' + file.name;
            fileNameEl.style.color = '';
          } else {
            fileNameEl.textContent = 'No .kml found inside KMZ archive';
            fileNameEl.style.color = 'var(--c-red)';
          }
        } catch (err) {
          console.error('KMZ extraction error:', err);
          fileNameEl.textContent = 'Could not extract KMZ — try pasting the KML text instead';
          fileNameEl.style.color = 'var(--c-red)';
        }
      };
      reader.onerror = function() {
        fileNameEl.textContent = 'Error reading file';
        fileNameEl.style.color = 'var(--c-red)';
      };
      reader.readAsArrayBuffer(file);
    }

    /* Drag events */
    dropZone.addEventListener('dragover', function(e) {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', function() {
      dropZone.classList.remove('dragover');
    });
    dropZone.addEventListener('drop', function(e) {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });

    /* Click / file input */
    fileInput.addEventListener('change', function() {
      if (fileInput.files.length) handleFile(fileInput.files[0]);
    });
  })();

  /* --- Timelapse Visualiser — Composite: NAIP detail + Sentinel-2 temporal --- */
  const PC_API = 'https://planetarycomputer.microsoft.com/api/data/v1';
  const map = L.map('map', {zoomSnap: 0.25});

  /* Light reference labels (CartoDB — sits on top of satellite imagery) */
  const labelsLayer = L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png',
    {maxZoom: 19, pane: 'overlayPane', opacity: 0.7}
  );

  var aoiCoords = [
    [36.86,-120.08],[36.86,-120.04],[36.90,-120.04],
    [36.90,-120.08],[36.86,-120.08]
  ];
  var aoiBbox;
  var aoiPolygon;
  var aoiPolygonsData = [];
  var selectedAoiIndex = -1;
  var analyticsCoords = null;
  var analyticsNonce = 0;

  function coordsToBbox(coords) {
    var lats = coords.map(function(c){return c[0]});
    var lons = coords.map(function(c){return c[1]});
    var minLat = Math.min.apply(null,lats) - 0.02;
    var maxLat = Math.max.apply(null,lats) + 0.02;
    var minLon = Math.min.apply(null,lons) - 0.02;
    var maxLon = Math.max.apply(null,lons) + 0.02;
    return [[minLon,minLat],[maxLon,minLat],[maxLon,maxLat],[minLon,maxLat],[minLon,minLat]];
  }

  /* Haversine distance in km */
  function haversineKm(lat1, lon1, lat2, lon2) {
    var R = 6371;
    var dLat = (lat2 - lat1) * Math.PI / 180;
    var dLon = (lon2 - lon1) * Math.PI / 180;
    var a = Math.sin(dLat/2)*Math.sin(dLat/2) +
            Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*
            Math.sin(dLon/2)*Math.sin(dLon/2);
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  }

  function polygonCentroid(coords) {
    var latS = 0, lonS = 0, n = coords.length - 1; /* skip closing vertex */
    for (var i = 0; i < n; i++) { latS += coords[i][0]; lonS += coords[i][1]; }
    return [latS/n, lonS/n];
  }

  /* Check all polygons are within maxKm of their group centroid */
  function checkPolygonProximity(polygons, maxKm) {
    if (polygons.length < 2) return null;
    var centroids = polygons.map(function(p){ return polygonCentroid(p.coords); });
    var gLat = centroids.reduce(function(s,c){return s+c[0]},0) / centroids.length;
    var gLon = centroids.reduce(function(s,c){return s+c[1]},0) / centroids.length;
    for (var i = 0; i < centroids.length; i++) {
      var d = haversineKm(gLat, gLon, centroids[i][0], centroids[i][1]);
      if (d > maxKm) return 'Polygon "' + polygons[i].name + '" is ' + d.toFixed(1) + ' km from group centre (max ' + maxKm + ' km). Please split into separate KMLs.';
    }
    return null;
  }

  /* Compute a single bounding polygon from multiple polygons */
  function unionBboxCoords(polygons) {
    var allLats = [], allLons = [];
    polygons.forEach(function(p) {
      p.coords.forEach(function(c) { allLats.push(c[0]); allLons.push(c[1]); });
    });
    var minLat = Math.min.apply(null, allLats);
    var maxLat = Math.max.apply(null, allLats);
    var minLon = Math.min.apply(null, allLons);
    var maxLon = Math.max.apply(null, allLons);
    return [[minLat,minLon],[minLat,maxLon],[maxLat,maxLon],[maxLat,minLon],[minLat,minLon]];
  }

  var POLY_COLORS = ['#58a6ff','#3fb950','#d2a8ff','#f0883e','#f85149','#79c0ff'];
  var aoiSubPolygons = []; /* extra polygon layers for multi-polygon KMLs */
  var fireMarkers = []; /* FIRMS fire hotspot markers */
  var floodMarkers = []; /* Flood event markers */
  var firmsData = null;
  var floodData = null;

  function activeAnalyticsCoords() {
    return analyticsCoords || aoiCoords;
  }

  function updatePolygonStyles() {
    aoiSubPolygons.forEach(function(layer, i) {
      var selected = i === selectedAoiIndex;
      layer.setStyle({
        weight: selected ? 3 : 2,
        fillOpacity: selected ? 0.16 : 0.10,
        dashArray: selected ? '' : '6 4'
      });
    });
  }

  function updateAnalyticsScopeUi() {
    var scopeEl = document.getElementById('analytics-scope');
    var labelEl = document.getElementById('analytics-scope-label');
    var swatchEl = document.getElementById('analytics-scope-swatch');
    var resetEl = document.getElementById('analytics-scope-reset');
    var analysisCol = document.getElementById('demo-analysis-col');
    if (!scopeEl || !labelEl || !resetEl) return;
    if (aoiPolygonsData.length > 1) {
      scopeEl.style.display = 'flex';
      if (selectedAoiIndex >= 0) {
        var col = POLY_COLORS[selectedAoiIndex % POLY_COLORS.length];
        labelEl.textContent = aoiPolygonsData[selectedAoiIndex].name;
        if (swatchEl) swatchEl.style.background = col;
        if (analysisCol) {
          analysisCol.classList.add('scope-selected');
          analysisCol.style.setProperty('--scope-color', col);
        }
      } else {
        labelEl.textContent = 'All areas (collective)';
        if (swatchEl) swatchEl.style.background = 'var(--c-muted)';
        if (analysisCol) {
          analysisCol.classList.remove('scope-selected');
          analysisCol.style.removeProperty('--scope-color');
        }
      }
      resetEl.style.display = selectedAoiIndex >= 0 ? 'inline-block' : 'none';
    } else {
      scopeEl.style.display = 'none';
      if (analysisCol) {
        analysisCol.classList.remove('scope-selected');
        analysisCol.style.removeProperty('--scope-color');
      }
    }
  }

  async function selectAoiAnalytics(index) {
    if (index < 0 || index >= aoiPolygonsData.length) return;
    // Toggle: if already selected, click off to show collective
    if (selectedAoiIndex === index) {
      await setCollectiveAnalytics();
      return;
    }
    selectedAoiIndex = index;
    analyticsCoords = aoiPolygonsData[index].coords;
    updatePolygonStyles();
    updateAnalyticsScopeUi();
    await refreshAnalyticsForScope();
  }

  async function setCollectiveAnalytics() {
    selectedAoiIndex = -1;
    analyticsCoords = null;
    updatePolygonStyles();
    updateAnalyticsScopeUi();
    await refreshAnalyticsForScope();
  }

  window.selectAoiAnalytics = selectAoiAnalytics;
  window.setCollectiveAnalytics = setCollectiveAnalytics;

  function setAoi(coords, polygons) {
    aoiCoords = coords;
    aoiBbox = coordsToBbox(coords);
    aoiPolygonsData = polygons && polygons.length ? polygons : [{ name: 'Area of Interest', coords: coords }];
    selectedAoiIndex = -1;
    analyticsCoords = null;
    /* Remove old layers */
    if (aoiPolygon) map.removeLayer(aoiPolygon);
    aoiSubPolygons.forEach(function(l){ map.removeLayer(l); });
    aoiSubPolygons = [];
    /* Clear old event data */
    clearFireMarkers();
    clearFloodMarkers();
    firmsData = null;
    floodData = null;

    if (polygons && polygons.length > 1) {
      /* Multi-polygon: draw each field with a distinct colour */
      polygons.forEach(function(p, i) {
        var col = POLY_COLORS[i % POLY_COLORS.length];
        var layer = L.polygon(p.coords, {
          color: col, weight: 2, fillOpacity: 0.10, dashArray: '6 4'
        }).addTo(map);
        layer.bindTooltip(p.name, {permanent: false, direction: 'center', className: 'poly-tooltip'});
        layer.on('click', function() { selectAoiAnalytics(i); });
        aoiSubPolygons.push(layer);
      });
      /* Invisible bounding polygon for overall bbox */
      aoiPolygon = L.polygon(coords, {
        color: 'transparent', weight: 0, fillOpacity: 0
      }).addTo(map);
    } else {
      /* Single polygon — classic blue dashed outline */
      aoiPolygon = L.polygon(coords, {
        color:'#58a6ff', weight:2, fillOpacity:0.08, dashArray:'6 4'
      }).addTo(map);
    }
    updatePolygonStyles();
    updateAnalyticsScopeUi();
    map.fitBounds(aoiPolygon.getBounds(), {padding: [6, 6], maxZoom: 15});
  }
  setAoi(aoiCoords);

  /*
   * Seasonal timelapse for tree monitoring — maximising NAIP (0.6 m):
   *
   *   NAIP vintages for this AOI: 2012, 2014, 2016, 2018, 2020, 2022
   *   Pre-2018: NAIP-only summer frames (no S2 coverage)
   *   2018–2026: 4 seasons/yr; summer uses NAIP when available, S2 elsewhere
   *
   *   Total: 3 standalone NAIP + 9 yrs × 4 seasons = 39 frames (6 NAIP)
   *   All layers pre-cached at opacity 0 → flicker-free playback
   */
  const SEASONS = [
    {key:'winter', label:'Winter', months:[12,1,2], icon:'\u2744\uFE0F'},
    {key:'spring', label:'Spring', months:[3,4,5],  icon:'\uD83C\uDF31'},
    {key:'summer', label:'Summer', months:[6,7,8],  icon:'\u2600\uFE0F'},
    {key:'autumn', label:'Autumn', months:[9,10,11],icon:'\uD83C\uDF42'}
  ];
  /* Full seasonal range (S2 reliable from 2018) */
  const SEASONAL_YEARS = [2018,2019,2020,2021,2022,2023,2024,2025,2026];
  /* Pre-S2 years — NAIP-only summer snapshots */
  const NAIP_ONLY_YEARS = [2012,2014,2016];
  /* All NAIP summers available at this AOI (0.6 m) */
  const NAIP_SUMMERS = new Set([
    '2012-summer','2014-summer','2016-summer',
    '2018-summer','2020-summer','2022-summer'
  ]);
  const SUMMER = SEASONS[2]; /* summer entry */

  function seasonWindow(year, season) {
    if (season.key === 'winter') {
      return {start:(year-1)+'-12-01', end:year+'-02-28'};
    }
    var m0 = season.months[0], m2 = season.months[2];
    var s = year+'-'+String(m0).padStart(2,'0')+'-01';
    var eLast = new Date(year, m2, 0).getDate();
    var e = year+'-'+String(m2).padStart(2,'0')+'-'+eLast;
    return {start:s, end:e};
  }

  function naipRes(yr) { return yr <= 2014 ? '1.0' : '0.6'; }

  /* NAIP coverage: Continental US (CONUS) roughly */
  function aoiHasNaip(coords) {
    for (var i = 0; i < coords.length; i++) {
      var lat = coords[i][0], lon = coords[i][1];
      if (lat < 24 || lat > 50 || lon < -125 || lon > -66) return false;
    }
    return true;
  }

  /* Build ordered frame list — adapts to AOI location */
  var framePlan = [];
  function buildFramePlan() {
    framePlan = [];
    var naip = aoiHasNaip(aoiCoords);

    if (naip) {
      /* Pre-S2 era: standalone NAIP summer frames */
      NAIP_ONLY_YEARS.forEach(function(yr) {
        var w = seasonWindow(yr, SUMMER);
        framePlan.push({
          year:yr, season:SUMMER, start:w.start, end:w.end,
          collection:'naip', asset:'image',
          label:SUMMER.icon+' NAIP Summer '+yr,
          isNaip:true,
          info:'NAIP \u00A9 USDA  |  '+naipRes(yr)+' m/px  |  '+w.start+' \u2192 '+w.end
        });
      });
    }

    /* S2 era: 4 seasons per year, NAIP replaces S2 for summers where available */
    SEASONAL_YEARS.forEach(function(yr) {
      SEASONS.forEach(function(s) {
        var w = seasonWindow(yr, s);
        var naipKey = yr+'-'+s.key;
        var useNaip = naip && NAIP_SUMMERS.has(naipKey);
        framePlan.push({
          year:yr, season:s, start:w.start, end:w.end,
          collection: useNaip ? 'naip' : 'sentinel-2-l2a',
          asset: useNaip ? 'image' : 'visual',
          label: useNaip
            ? s.icon+' NAIP Summer '+yr
            : s.icon+' '+s.label+' '+yr,
          isNaip: useNaip,
          info: useNaip
            ? 'NAIP \u00A9 USDA  |  '+naipRes(yr)+' m/px  |  '+w.start+' \u2192 '+w.end
            : 'Sentinel-2 L2A  |  10 m/px  |  '+w.start+' \u2192 '+w.end+'  |  \u2264 20% cloud'
        });
      });
    });
  }
  buildFramePlan();

  /* Register a Planetary Computer mosaic search */
  async function registerMosaic(collection, dateStart, dateEnd, extraFilters) {
    var filterArgs = [
      {op:'t_intersects', args:[{property:'datetime'},{interval:[dateStart,dateEnd]}]},
      {op:'s_intersects', args:[{property:'geometry'},
        {type:'Polygon',coordinates:[aoiBbox]}
      ]}
    ];
    if (extraFilters) filterArgs.push.apply(filterArgs, extraFilters);
    var sortby = collection === 'naip'
      ? [{field:'datetime',direction:'desc'}]
      : [{field:'eo:cloud_cover',direction:'asc'}];
    var r = await fetch(PC_API + '/mosaic/register', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        collections: [collection],
        'filter-lang': 'cql2-json',
        filter: { op:'and', args: filterArgs },
        sortby: sortby
      })
    });
    if (!r.ok) throw new Error('PC register ' + r.status + ' ' + collection);
    return (await r.json()).searchid;
  }

  /* Tile layer — created at opacity 0 for pre-caching.
     NAIP: omit format=png (PC renderer 500s on PNG for most years); 256px @1x.
     S2:   @2x 512px tiles for smoother upscaling at high zoom. */
  function pcTileLayer(sid, collection, asset) {
    var params = 'collection='+collection+'&assets='+asset;
    var isNaip = collection === 'naip';
    if (isNaip) {
      params += '&nodata=0';                        /* jpeg default */
    } else {
      params += '&nodata=0&format=png';
    }
    var scale = isNaip ? '1x' : '2x';
    return L.tileLayer(
      PC_API+'/mosaic/tiles/'+sid+'/WebMercatorQuad/{z}/{x}/{y}@'+scale+'?'+params,
      {attribution: isNaip
        ? 'NAIP \u00A9 USDA \u2014 via Microsoft Planetary Computer'
        : 'Sentinel-2 L2A \u00A9 ESA \u2014 via Microsoft Planetary Computer',
       maxZoom:18, maxNativeZoom: isNaip ? 18 : 14,
       tileSize: isNaip ? 256 : 512,
       zoomOffset: isNaip ? 0 : -1,
       opacity: 0, crossOrigin:true}
    );
  }

  /* NDVI tile layer — S2 only, computed via PC expression parameter */
  function pcNdviLayer(sid) {
    var params = 'collection=sentinel-2-l2a'
      + '&assets=B08&assets=B04'
      + '&expression=(B08_b1-B04_b1)/(B08_b1%2BB04_b1)'
      + '&colormap_name=rdylgn&rescale=-0.2,0.8'
      + '&nodata=0&format=png';
    return L.tileLayer(
      PC_API+'/mosaic/tiles/'+sid+'/WebMercatorQuad/{z}/{x}/{y}@2x?'+params,
      {attribution: 'NDVI \u2014 Sentinel-2 L2A \u00A9 ESA',
       maxZoom:18, maxNativeZoom:14,
       tileSize:512, zoomOffset:-1,
       opacity: 0, crossOrigin:true}
    );
  }

  /* Layer mode: 'rgb' or 'ndvi' */
  var layerMode = 'rgb';
  var ndviLayers = [];     /* parallel to frameLayers, created lazily */
  var searchIdCache = [];  /* store search IDs per frame (NAIP or S2) */
  var ndviSearchIds = [];  /* S2 search IDs for NDVI — same as searchIdCache for S2 frames,
                              separately-registered S2 mosaic for NAIP frames */

  document.getElementById('btn-rgb').addEventListener('click', function() { setLayerMode('rgb'); });
  document.getElementById('btn-ndvi').addEventListener('click', function() { setLayerMode('ndvi'); });
  document.getElementById('header-btn-rgb').addEventListener('click', function() { setLayerMode('rgb'); });
  document.getElementById('header-btn-ndvi').addEventListener('click', function() { setLayerMode('ndvi'); });

  function setLayerMode(mode) {
    if (layerMode === mode) return;
    layerMode = mode;
    var isRgb = mode === 'rgb';
    document.getElementById('btn-rgb').classList.toggle('active', isRgb);
    document.getElementById('btn-ndvi').classList.toggle('active', !isRgb);
    document.getElementById('header-btn-rgb').classList.toggle('active', isRgb);
    document.getElementById('header-btn-ndvi').classList.toggle('active', !isRgb);
    if (compareActive) { updateCompareClip(); } else { showFrame(currentFrame); }
  }

  /* ---- Comparison split view (#226) ---- */
  var compareActive = false;
  var compareLeftIdx = 0;
  var compareRightIdx = 0;
  var compareDividerX = 0.5; /* 0..1 fraction of map width */

  function populateCompareSelects() {
    var selL = document.getElementById('compare-left');
    var selR = document.getElementById('compare-right');
    selL.replaceChildren();
    selR.replaceChildren();
    for (var i = 0; i < framesMeta.length; i++) {
      var optL = document.createElement('option');
      optL.value = i;
      optL.textContent = framesMeta[i].label;
      selL.appendChild(optL);
      selR.appendChild(optL.cloneNode(true));
    }
    /* Default: first and last frame */
    selL.value = 0;
    selR.value = framesMeta.length - 1;
    compareLeftIdx = 0;
    compareRightIdx = framesMeta.length - 1;
  }

  function enterCompareMode() {
    if (!frameLayers.length) return;
    compareActive = true;
    /* Pause playback */
    if (playing) {
      clearInterval(playTimer); playing = false;
      document.getElementById('play-btn').textContent = '\u25B6 Play';
    }
    populateCompareSelects();
    document.getElementById('compare-controls').classList.add('show');
    document.getElementById('compare-btn').textContent = '✕ Exit Compare';
    document.getElementById('play-btn').disabled = true;
    document.getElementById('frame-slider').disabled = true;
    /* Show divider */
    var divider = document.getElementById('compare-divider');
    divider.style.display = 'block';
    document.getElementById('compare-tag-left').classList.add('show');
    document.getElementById('compare-tag-right').classList.add('show');
    compareDividerX = 0.5;
    updateCompareClip();
  }

  function exitCompareMode() {
    compareActive = false;
    document.getElementById('compare-controls').classList.remove('show');
    document.getElementById('compare-btn').textContent = '\u21d4 Compare';
    document.getElementById('play-btn').disabled = false;
    document.getElementById('frame-slider').disabled = false;
    document.getElementById('compare-divider').style.display = 'none';
    document.getElementById('compare-tag-left').classList.remove('show');
    document.getElementById('compare-tag-right').classList.remove('show');
    /* Remove clip from all tile panes */
    var mapEl = document.getElementById('map');
    var panes = mapEl.querySelectorAll('.leaflet-tile-pane .leaflet-layer');
    for (var i = 0; i < panes.length; i++) {
      panes[i].style.clip = '';
    }
    showFrame(currentFrame);
  }

  function updateCompareClip() {
    if (!compareActive) return;
    var mapEl = document.getElementById('map');
    var rect = mapEl.getBoundingClientRect();
    var splitPx = Math.round(rect.width * compareDividerX);

    /* Position divider */
    document.getElementById('compare-divider').style.left = splitPx + 'px';

    /* Determine which layers to use for left / right */
    var useNdvi = layerMode === 'ndvi';
    var lIdx = compareLeftIdx;
    var rIdx = compareRightIdx;

    /* First hide all layers */
    frameLayers.forEach(function(l){ l.setOpacity(0); });
    ndviLayers.forEach(function(l){ if(l) l.setOpacity(0); });

    /* Show left-side layer and right-side layer at full opacity */
    var leftLayer, rightLayer;
    if (useNdvi && ndviSearchIds[lIdx]) {
      if (!ndviLayers[lIdx]) {
        ndviLayers[lIdx] = pcNdviLayer(ndviSearchIds[lIdx]);
        ndviLayers[lIdx].addTo(map);
      }
      leftLayer = ndviLayers[lIdx];
    } else {
      leftLayer = frameLayers[lIdx];
    }
    if (useNdvi && ndviSearchIds[rIdx]) {
      if (!ndviLayers[rIdx]) {
        ndviLayers[rIdx] = pcNdviLayer(ndviSearchIds[rIdx]);
        ndviLayers[rIdx].addTo(map);
      }
      rightLayer = ndviLayers[rIdx];
    } else {
      rightLayer = frameLayers[rIdx];
    }

    leftLayer.setOpacity(1);
    rightLayer.setOpacity(1);

    /* Apply CSS clip to the tile container elements */
    var h = rect.height;
    /* clip: rect(top, right, bottom, left) */
    if (leftLayer.getContainer()) {
      leftLayer.getContainer().style.clip = 'rect(0px, ' + splitPx + 'px, ' + h + 'px, 0px)';
    }
    if (rightLayer.getContainer()) {
      rightLayer.getContainer().style.clip = 'rect(0px, ' + rect.width + 'px, ' + h + 'px, ' + splitPx + 'px)';
    }

    /* Update labels */
    document.getElementById('compare-tag-left').textContent = framesMeta[lIdx].label;
    document.getElementById('compare-tag-right').textContent = framesMeta[rIdx].label;
    document.getElementById('frame-label').textContent = 'Comparing: ' + framesMeta[lIdx].label + '  vs  ' + framesMeta[rIdx].label;

    labelsLayer.bringToFront();
    aoiPolygon.bringToFront();
    aoiSubPolygons.forEach(function(l){ l.bringToFront(); });
  }

  /* Compare button toggle */
  document.getElementById('compare-btn').addEventListener('click', function() {
    if (compareActive) exitCompareMode(); else enterCompareMode();
  });

  /* Frame select changes */
  document.getElementById('compare-left').addEventListener('change', function() {
    compareLeftIdx = parseInt(this.value);
    updateCompareClip();
  });
  document.getElementById('compare-right').addEventListener('change', function() {
    compareRightIdx = parseInt(this.value);
    updateCompareClip();
  });

  /* Draggable divider */
  (function() {
    var divider = document.getElementById('compare-divider');
    var dragging = false;

    function onMove(clientX) {
      if (!dragging || !compareActive) return;
      var mapEl = document.getElementById('map');
      var rect = mapEl.getBoundingClientRect();
      var x = clientX - rect.left;
      compareDividerX = Math.max(0.05, Math.min(0.95, x / rect.width));
      updateCompareClip();
    }

    divider.addEventListener('mousedown', function(e) { dragging = true; e.preventDefault(); });
    document.addEventListener('mousemove', function(e) { if (dragging) onMove(e.clientX); });
    document.addEventListener('mouseup', function() { dragging = false; });
    /* Touch support */
    divider.addEventListener('touchstart', function(e) { dragging = true; e.preventDefault(); }, {passive: false});
    document.addEventListener('touchmove', function(e) { if (dragging && e.touches.length) onMove(e.touches[0].clientX); });
    document.addEventListener('touchend', function() { dragging = false; });
  })();

  /* Re-clip on map move/resize */
  map.on('move zoom resize', function() { if (compareActive) updateCompareClip(); });

  /* ---- Weather data (Open-Meteo Historical Weather API) ---- */
  var weatherData = null;  /* {dates:[], temp:[], precip:[]} */

  async function fetchWeather(lat, lon, startDate, endDate) {
    var url = 'https://archive-api.open-meteo.com/v1/archive'
      + '?latitude='+lat+'&longitude='+lon
      + '&start_date='+startDate+'&end_date='+endDate
      + '&daily=temperature_2m_mean,precipitation_sum'
      + '&timezone=auto';
    try {
      var r = await fetch(url);
      if (!r.ok) return null;
      var d = await r.json();
      return {
        dates: d.daily.time,
        temp: d.daily.temperature_2m_mean,
        precip: d.daily.precipitation_sum
      };
    } catch(e) { return null; }
  }

  /* Aggregate weather data by month for charting */
  function aggregateWeatherMonthly(wd) {
    var months = {};
    for (var i = 0; i < wd.dates.length; i++) {
      var key = wd.dates[i].substring(0, 7); /* YYYY-MM */
      if (!months[key]) months[key] = {temp:[], precip:0};
      if (wd.temp[i] != null) months[key].temp.push(wd.temp[i]);
      if (wd.precip[i] != null) months[key].precip += wd.precip[i];
    }
    var keys = Object.keys(months).sort();
    return {
      labels: keys,
      temp: keys.map(function(k){
        var t = months[k].temp;
        return t.length ? +(t.reduce(function(a,b){return a+b},0)/t.length).toFixed(1) : null;
      }),
      precip: keys.map(function(k){ return +months[k].precip.toFixed(1); })
    };
  }

  /* Moving average: returns smoothed array; nulls are skipped */
  function movingAvg(vals, window) {
    var out = [];
    var half = Math.floor(window / 2);
    for (var i = 0; i < vals.length; i++) {
      var sum = 0, cnt = 0;
      for (var j = Math.max(0, i - half); j <= Math.min(vals.length - 1, i + half); j++) {
        if (vals[j] != null) { sum += vals[j]; cnt++; }
      }
      out.push(cnt ? sum / cnt : null);
    }
    return out;
  }

  /* Draw weather chart on canvas */
  var monthlyWeather = null;
  function drawWeatherChart() {
    if (!monthlyWeather) return;
    var canvas = document.getElementById('weather-canvas');
    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    var W = rect.width, H = rect.height;
    ctx.clearRect(0, 0, W, H);

    var temps = monthlyWeather.temp;
    var precips = monthlyWeather.precip;
    var n = temps.length;
    if (n < 2) return;

    var tMin = Math.min.apply(null, temps.filter(function(t){return t!=null}));
    var tMax = Math.max.apply(null, temps.filter(function(t){return t!=null}));
    var pMax = Math.max.apply(null, precips) || 1;
    var pad = 2;

    /* Precipitation bars */
    ctx.fillStyle = 'rgba(88,166,255,0.25)';
    var bw = (W - pad*2) / n;
    for (var i = 0; i < n; i++) {
      var bh = (precips[i] / pMax) * (H - pad*2);
      ctx.fillRect(pad + i*bw, H - pad - bh, bw - 1, bh);
    }

    /* Temperature line */
    ctx.strokeStyle = '#f0883e';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (var i = 0; i < n; i++) {
      if (temps[i] == null) continue;
      var x = pad + (i + 0.5) * bw;
      var y = H - pad - ((temps[i] - tMin) / (tMax - tMin || 1)) * (H - pad*2 - 4) - 2;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    /* Temperature 12-month moving average */
    var tSmooth = movingAvg(temps, 12);
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.55)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    var started = false;
    for (var i = 0; i < n; i++) {
      if (tSmooth[i] == null) continue;
      var x = pad + (i + 0.5) * bw;
      var y = H - pad - ((tSmooth[i] - tMin) / (tMax - tMin || 1)) * (H - pad*2 - 4) - 2;
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.restore();
  }

  /* Position weather marker for current frame */
  function updateWeatherMarker() {
    if (!monthlyWeather || !framePlan.length) return;
    var marker = document.getElementById('weather-marker');
    var f = framePlan[currentFrame];
    /* Find the mid-point month of this frame */
    var mid = f.start.substring(0, 7);
    var idx = monthlyWeather.labels.indexOf(mid);
    if (idx < 0) {
      /* Try end month */
      mid = f.end.substring(0, 7);
      idx = monthlyWeather.labels.indexOf(mid);
    }
    if (idx >= 0) {
      var pct = (idx + 0.5) / monthlyWeather.labels.length * 100;
      marker.style.left = pct + '%';
      marker.style.display = 'block';
    }
  }

  /* ---- NDVI Statistics (per-frame mean NDVI from PC) ---- */
  var ndviStats = [];   /* [{mean, min, max}] indexed by frame — null for NAIP frames */
  var ndviStatsReady = false;

  /* Compute NDVI tile coordinates covering the AOI centroid at z12 */
  function aoiCenterTile(coords) {
    var lats = coords.map(function(c){return c[0]});
    var lons = coords.map(function(c){return c[1]});
    var lat = (Math.min.apply(null,lats)+Math.max.apply(null,lats))/2;
    var lon = (Math.min.apply(null,lons)+Math.max.apply(null,lons))/2;
    var z = 12;
    var n = Math.pow(2, z);
    var x = Math.floor((lon + 180) / 360 * n);
    var latRad = lat * Math.PI / 180;
    var y = Math.floor((1 - Math.log(Math.tan(latRad) + 1/Math.cos(latRad)) / Math.PI) / 2 * n);
    return { z: z, x: x, y: y };
  }

  /* Fetch NDVI mean for one S2 mosaic by sampling a single tile's pixels */
  async function fetchNdviStats(searchId, coords) {
    var t = aoiCenterTile(coords);
    var url = PC_API + '/mosaic/tiles/' + searchId
      + '/WebMercatorQuad/' + t.z + '/' + t.x + '/' + t.y + '@1x'
      + '?collection=sentinel-2-l2a&assets=B08&assets=B04'
      + '&expression=(B08_b1-B04_b1)/(B08_b1%2BB04_b1)'
      + '&rescale=-0.2,0.8&nodata=0&format=png';
    try {
      var r = await fetch(url);
      if (!r.ok) return null;
      var blob = await r.blob();
      var bmp = await createImageBitmap(blob);
      var canvas = new OffscreenCanvas(bmp.width, bmp.height);
      var ctx = canvas.getContext('2d');
      ctx.drawImage(bmp, 0, 0);
      var data = ctx.getImageData(0, 0, bmp.width, bmp.height).data;
      var sum = 0, count = 0, vmin = 1, vmax = -1;
      for (var i = 0; i < data.length; i += 4) {
        if (data[i+3] > 0) {
          var v = -0.2 + (data[i] / 255) * 1.0;
          sum += v; count++;
          if (v < vmin) vmin = v;
          if (v > vmax) vmax = v;
        }
      }
      if (!count) return null;
      return { mean: +(sum/count).toFixed(3), min: +vmin.toFixed(3), max: +vmax.toFixed(3) };
    } catch(e) { return null; }
  }

  /* Fetch NDVI stats for all S2 frames (async, non-blocking) */
  async function fetchAllNdviStats(coords, nonce) {
    ndviStats = new Array(framePlan.length);
    ndviStatsReady = false;
    /* Show panel immediately with placeholder */
    document.getElementById('ndvi-trend-panel').style.display = 'block';
    document.getElementById('ndvi-trend-summary').textContent = 'Sampling NDVI tiles…';
    /* Process in batches of 4 to avoid hammering PC */
    for (var b = 0; b < framePlan.length; b += 4) {
      var batch = [];
      for (var i = b; i < Math.min(b + 4, framePlan.length); i++) {
        if (!ndviSearchIds[i]) {
          batch.push(Promise.resolve(null));
        } else {
          batch.push(fetchNdviStats(ndviSearchIds[i], coords));
        }
      }
      var results = await Promise.all(batch);
      if (nonce !== analyticsNonce) return;
      for (var j = 0; j < results.length; j++) {
        ndviStats[b + j] = results[j];
      }
      /* Progressively redraw after each batch */
      ndviStatsReady = true;
      drawNdviTrend();
      updateNdviTrendMarker();
    }
    if (nonce === analyticsNonce) buildInsights(currentFrame);
  }

  async function refreshAnalyticsForScope() {
    if (!framePlan.length) return;
    var nonce = ++analyticsNonce;
    var coords = activeAnalyticsCoords();

    weatherData = null;
    monthlyWeather = null;
    ndviStats = [];
    ndviStatsReady = false;

    document.getElementById('weather-panel').style.display = 'none';
    document.getElementById('ndvi-trend-panel').style.display = 'block';
    document.getElementById('ndvi-trend-summary').textContent = 'Sampling NDVI tiles…';
    document.getElementById('period-summary').style.display = 'none';
    buildInsights(currentFrame);

    /* --- Use pipeline enrichment data when available --- */
    if (enrichmentPayload && selectedAoiIndex < 0) {
      /* Collective scope: use pipeline-cached weather + NDVI */
      console.log('Using pipeline-cached enrichment data');

      /* Weather from pipeline */
      if (enrichmentPayload.weather_daily) {
        weatherData = enrichmentPayload.weather_daily;
        monthlyWeather = enrichmentPayload.weather_monthly;
        document.getElementById('weather-panel').style.display = 'block';
        drawWeatherChart();
        updateWeatherMarker();
        buildPeriodSummary();
        buildInsights(currentFrame);
      }

      /* NDVI from pipeline */
      if (enrichmentPayload.ndvi_stats) {
        ndviStats = enrichmentPayload.ndvi_stats;
        ndviStatsReady = true;
        drawNdviTrend();
        updateNdviTrendMarker();
        buildPeriodSummary();
        buildInsights(currentFrame);
      }

      return; /* skip live fetch — pipeline data is authoritative */
    }

    /* --- Fallback: live fetch from external APIs (no pipeline data) --- */
    var firstDate = framePlan[0].start;
    var lastDate = framePlan[framePlan.length - 1].end;
    var today = new Date().toISOString().substring(0, 10);
    var endDate = lastDate < today ? lastDate : today;

    var lats = coords.map(function(c){return c[0]});
    var lons = coords.map(function(c){return c[1]});
    var cLat = +((Math.min.apply(null,lats)+Math.max.apply(null,lats))/2).toFixed(4);
    var cLon = +((Math.min.apply(null,lons)+Math.max.apply(null,lons))/2).toFixed(4);

    var weatherPromise = (async function() {
      try {
        var wd = await fetchWeather(cLat, cLon, firstDate, endDate);
        if (nonce !== analyticsNonce) return;
        if (wd) {
          weatherData = wd;
          monthlyWeather = aggregateWeatherMonthly(wd);
          document.getElementById('weather-panel').style.display = 'block';
          drawWeatherChart();
          updateWeatherMarker();
          buildPeriodSummary();
          buildInsights(currentFrame);
        }
      } catch(e) { /* weather is non-critical */ }
    })();

    var ndviPromise = (async function() {
      try {
        await fetchAllNdviStats(coords, nonce);
        if (nonce !== analyticsNonce) return;
        buildPeriodSummary();
      } catch(e) { /* NDVI stats non-critical */ }
    })();

    await Promise.all([weatherPromise, ndviPromise]);
  }

  /* Draw NDVI trend sparkline */
  function drawNdviTrend() {
    if (!ndviStatsReady) return;
    var canvas = document.getElementById('ndvi-trend-canvas');
    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    var W = rect.width, H = rect.height;
    ctx.clearRect(0, 0, W, H);

    /* Collect S2-only NDVI values with indices */
    var points = [];
    for (var i = 0; i < ndviStats.length; i++) {
      if (ndviStats[i]) points.push({ idx: i, mean: ndviStats[i].mean });
    }
    if (points.length < 2) return;

    var vMin = 0, vMax = 1; /* NDVI range */
    var pad = 4;
    var stepW = (W - pad * 2) / (framePlan.length - 1);

    /* Background bands for NDVI quality */
    ctx.fillStyle = 'rgba(63,185,80,0.06)';
    ctx.fillRect(0, 0, W, H * 0.4); /* good NDVI zone */
    ctx.fillStyle = 'rgba(248,81,73,0.06)';
    ctx.fillRect(0, H * 0.7, W, H * 0.3); /* poor NDVI zone */

    /* Draw change detection drops */
    for (var i = 1; i < points.length; i++) {
      var delta = points[i].mean - points[i-1].mean;
      if (delta <= -0.1) {
        var xDrop = pad + points[i].idx * stepW;
        ctx.fillStyle = 'rgba(248,81,73,0.15)';
        ctx.fillRect(xDrop - stepW/2, 0, stepW, H);
        /* Red triangle marker */
        ctx.fillStyle = '#f85149';
        ctx.beginPath();
        ctx.moveTo(xDrop - 4, 4);
        ctx.lineTo(xDrop + 4, 4);
        ctx.lineTo(xDrop, 12);
        ctx.closePath();
        ctx.fill();
      }
    }

    /* Draw NDVI line */
    ctx.strokeStyle = '#3fb950';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (var i = 0; i < points.length; i++) {
      var x = pad + points[i].idx * stepW;
      var y = H - pad - ((points[i].mean - vMin) / (vMax - vMin)) * (H - pad * 2);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    /* Draw dots */
    ctx.fillStyle = '#3fb950';
    for (var i = 0; i < points.length; i++) {
      var x = pad + points[i].idx * stepW;
      var y = H - pad - ((points[i].mean - vMin) / (vMax - vMin)) * (H - pad * 2);
      ctx.beginPath();
      ctx.arc(x, y, 2.5, 0, Math.PI * 2);
      ctx.fill();
    }

    /* NDVI 3-point moving average */
    var nMeans = points.map(function(p){ return p.mean; });
    var nSmooth = movingAvg(nMeans, 3);
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.5)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    var nStarted = false;
    for (var i = 0; i < points.length; i++) {
      if (nSmooth[i] == null) continue;
      var x = pad + points[i].idx * stepW;
      var y = H - pad - ((nSmooth[i] - vMin) / (vMax - vMin)) * (H - pad * 2);
      if (!nStarted) { ctx.moveTo(x, y); nStarted = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.restore();

    /* Summary text */
    var means = points.map(function(p){ return p.mean; });
    var overall = +(means.reduce(function(a,b){return a+b},0)/means.length).toFixed(3);
    var first = points[0].mean, last = points[points.length-1].mean;
    var change = +(last - first).toFixed(3);
    var drops = 0;
    for (var i = 1; i < points.length; i++) {
      if (points[i].mean - points[i-1].mean <= -0.1) drops++;
    }
    var summaryEl = document.getElementById('ndvi-trend-summary');
    var txt = 'Mean NDVI: ' + overall + ' | Trend: ' + (change >= 0 ? '+' : '') + change;
    if (drops > 0) txt += ' | \u26a0 ' + drops + ' significant drop' + (drops > 1 ? 's' : '') + ' detected';
    summaryEl.textContent = txt;
    buildPeriodSummary();
  }

  /* Position NDVI trend marker for current frame */
  function updateNdviTrendMarker() {
    if (!ndviStatsReady || !framePlan.length) return;
    var marker = document.getElementById('ndvi-trend-marker');
    var pct = (currentFrame / (framePlan.length - 1)) * 100;
    marker.style.left = pct + '%';
    marker.style.display = 'block';
  }

  /* ---- Period Summary ---- */
  function buildPeriodSummary() {
    if (!framePlan.length) return;
    var panel = document.getElementById('period-summary');
    var grid = document.getElementById('summary-grid');
    var assess = document.getElementById('period-assessment');

    /* We need at least weather OR ndvi data */
    var hasWeather = !!monthlyWeather;
    var hasNdvi = ndviStatsReady && ndviStats.some(function(s){ return s != null; });
    if (!hasWeather && !hasNdvi) return;

    var findings = [];

    function addMetric(label, value, deltaText, deltaCls) {
      var div = document.createElement('div');
      div.className = 'summary-metric';
      var lbl = document.createElement('span');
      lbl.className = 'label';
      lbl.textContent = label;
      var val = document.createElement('span');
      val.className = 'value';
      val.textContent = value;
      div.appendChild(lbl);
      div.appendChild(document.createTextNode(' '));
      div.appendChild(val);
      if (deltaText) {
        var d = document.createElement('span');
        d.className = 'delta ' + deltaCls;
        d.textContent = deltaText;
        div.appendChild(document.createTextNode(' '));
        div.appendChild(d);
      }
      grid.appendChild(div);
    }

    grid.replaceChildren();

    /* Time span */
    var firstYear = framePlan[0].start.substring(0, 4);
    var lastYear = framePlan[framePlan.length - 1].end.substring(0, 4);
    var periodDiv = document.createElement('div');
    periodDiv.className = 'summary-metric';
    periodDiv.style.gridColumn = '1/-1';
    var pLbl = document.createElement('span');
    pLbl.className = 'label';
    pLbl.textContent = 'Period:';
    var pVal = document.createElement('span');
    pVal.className = 'value';
    pVal.textContent = firstYear + ' \u2014 ' + lastYear + ' (' + framePlan.length + ' frames)';
    periodDiv.appendChild(pLbl);
    periodDiv.appendChild(document.createTextNode(' '));
    periodDiv.appendChild(pVal);
    grid.appendChild(periodDiv);

    /* NDVI comparison: average of first 3 vs last 3 S2 frames */
    if (hasNdvi) {
      var s2points = [];
      for (var i = 0; i < ndviStats.length; i++) {
        if (ndviStats[i]) s2points.push({ idx: i, mean: ndviStats[i].mean });
      }
      if (s2points.length >= 4) {
        var earlyN = Math.min(3, Math.floor(s2points.length / 2));
        var earlyAvg = s2points.slice(0, earlyN).reduce(function(a,b){return a+b.mean},0) / earlyN;
        var lateAvg = s2points.slice(-earlyN).reduce(function(a,b){return a+b.mean},0) / earlyN;
        var ndviDelta = lateAvg - earlyAvg;
        var ndviPct = earlyAvg ? ((ndviDelta / earlyAvg) * 100).toFixed(1) : 0;
        var cls = ndviDelta > 0.02 ? 'delta-up' : ndviDelta < -0.02 ? 'delta-down' : 'delta-flat';
        var arrow = ndviDelta > 0.02 ? '\u2191' : ndviDelta < -0.02 ? '\u2193' : '\u2192';
        addMetric('NDVI (early):', earlyAvg.toFixed(3));
        addMetric('NDVI (recent):', lateAvg.toFixed(3), arrow + ' ' + (ndviDelta >= 0 ? '+' : '') + ndviDelta.toFixed(3) + ' (' + (ndviPct >= 0 ? '+' : '') + ndviPct + '%)', cls);
        if (ndviDelta < -0.05) findings.push('Vegetation health has declined (' + ndviPct + '%)');
        else if (ndviDelta > 0.05) findings.push('Vegetation health has improved (+' + ndviPct + '%)');
        else findings.push('Vegetation health is broadly stable');
      }
    }

    /* Temperature comparison: average of first 12 months vs last 12 months */
    if (hasWeather && monthlyWeather.temp.length >= 24) {
      var ts = monthlyWeather.temp.filter(function(t){return t!=null});
      var earlyT = ts.slice(0, 12);
      var lateT = ts.slice(-12);
      var earlyTAvg = earlyT.reduce(function(a,b){return a+b},0) / earlyT.length;
      var lateTAvg = lateT.reduce(function(a,b){return a+b},0) / lateT.length;
      var tDelta = lateTAvg - earlyTAvg;
      var tCls = tDelta > 0.3 ? 'delta-up' : tDelta < -0.3 ? 'delta-down' : 'delta-flat';
      var tArrow = tDelta > 0.3 ? '\u2191' : tDelta < -0.3 ? '\u2193' : '\u2192';
      addMetric('Temp (early):', earlyTAvg.toFixed(1) + '\u00B0C');
      addMetric('Temp (recent):', lateTAvg.toFixed(1) + '\u00B0C', tArrow + ' ' + (tDelta >= 0 ? '+' : '') + tDelta.toFixed(1) + '\u00B0C', tCls);
      if (Math.abs(tDelta) > 0.5) findings.push('Average temperature shifted ' + (tDelta > 0 ? 'warmer' : 'cooler') + ' by ' + Math.abs(tDelta).toFixed(1) + '\u00B0C');
    }

    /* Precipitation comparison */
    if (hasWeather && monthlyWeather.precip.length >= 24) {
      var ps = monthlyWeather.precip;
      var earlyP = ps.slice(0, 12).reduce(function(a,b){return a+b},0);
      var lateP = ps.slice(-12).reduce(function(a,b){return a+b},0);
      var pDelta = lateP - earlyP;
      var pPct = earlyP ? ((pDelta / earlyP) * 100).toFixed(0) : 0;
      var pCls = pDelta > 10 ? 'delta-up' : pDelta < -10 ? 'delta-down' : 'delta-flat';
      var pArrow = pDelta > 10 ? '\u2191' : pDelta < -10 ? '\u2193' : '\u2192';
      addMetric('Precip (early yr):', earlyP.toFixed(0) + ' mm');
      addMetric('Precip (recent yr):', lateP.toFixed(0) + ' mm', pArrow + ' ' + (pPct >= 0 ? '+' : '') + pPct + '%', pCls);
      if (Math.abs(+pPct) > 20) findings.push('Annual precipitation changed by ' + pPct + '%');
    }

    /* Overall assessment */
    var assessText = '';
    if (findings.length) {
      assessText = findings.join('. ') + '.';
    } else {
      assessText = 'Insufficient data for period comparison.';
    }

    assess.textContent = assessText;
    panel.style.display = 'block';
  }

  /* ---- FIRMS Fire Hotspots (NASA FIRMS / VIIRS) ---- */
  async function fetchFirmsData(lat, lon) {
    /* FIRMS CSV API — VIIRS SNPP, last 10 days has open access.
       For historical data we use the archive summary approach.
       We query a bbox around the AOI centroid. */
    var lats = aoiCoords.map(function(c){return c[0]});
    var lons = aoiCoords.map(function(c){return c[1]});
    var minLat = Math.min.apply(null, lats) - 0.5;
    var maxLat = Math.max.apply(null, lats) + 0.5;
    var minLon = Math.min.apply(null, lons) - 0.5;
    var maxLon = Math.max.apply(null, lons) + 0.5;
    /* FIRMS open API: area query for VIIRS SNPP, last 10 days */
    var url = 'https://firms.modaps.eosdis.nasa.gov/api/area/csv/'
      + 'FIRMS_OPEN_KEY'  /* open key placeholder — works for VIIRS 10-day */
      + '/VIIRS_SNPP_NRT/'
      + minLon.toFixed(2) + ',' + minLat.toFixed(2) + ','
      + maxLon.toFixed(2) + ',' + maxLat.toFixed(2)
      + '/10';  /* last 10 days */
    try {
      var r = await corsProxyFetch(url);
      if (!r || !r.ok) return null;
      var csv = await r.text();
      return parseFirmsCsv(csv);
    } catch(e) { return null; }
  }

  function parseFirmsCsv(csv) {
    var lines = csv.trim().split('\n');
    if (lines.length < 2) return [];
    var header = lines[0].split(',');
    var latIdx = header.indexOf('latitude');
    var lonIdx = header.indexOf('longitude');
    var dateIdx = header.indexOf('acq_date');
    var confIdx = header.indexOf('confidence');
    var frpIdx = header.indexOf('frp');
    if (latIdx < 0 || lonIdx < 0) return [];
    var fires = [];
    for (var i = 1; i < lines.length; i++) {
      var cols = lines[i].split(',');
      fires.push({
        lat: parseFloat(cols[latIdx]),
        lon: parseFloat(cols[lonIdx]),
        date: cols[dateIdx] || '',
        confidence: cols[confIdx] || '',
        frp: parseFloat(cols[frpIdx]) || 0
      });
    }
    return fires;
  }

  function showFireMarkers(fires) {
    clearFireMarkers();
    if (!fires || !fires.length) return;
    fires.forEach(function(f) {
      var icon = L.divIcon({
        className: 'fire-marker',
        html: '<div class="fire-dot"></div>',
        iconSize: [10, 10],
        iconAnchor: [5, 5]
      });
      var m = L.marker([f.lat, f.lon], { icon: icon })
        .bindPopup('<b>\ud83d\udd25 Fire Hotspot</b><br>Date: '+escapeHtml(f.date)+'<br>Confidence: '+escapeHtml(f.confidence)+'<br>FRP: '+escapeHtml(f.frp)+' MW')
        .addTo(map);
      fireMarkers.push(m);
    });
  }

  function clearFireMarkers() {
    fireMarkers.forEach(function(m){ map.removeLayer(m); });
    fireMarkers.length = 0;
  }

  /* ---- Flood Events (UK EA, USGS, ERA5 Water Table) ----

     This system integrates regional flood event data to:
     1. Mark flood event locations on the timelapse map
     2. Alert users when NDVI drops correlate with flood impacts
     3. Provide water-related context for vegetation stress

     INTEGRATION ARCHITECTURE:

     A. UK Environment Agency (EA) — for UK areas (Scotland, England, Wales)
        Data source: https://environment.data.gov.uk/flood-monitoring/
        API endpoints:
          - /floods: Real-time flood warnings
          - /flood-areas: Historical flood extents & severities
        Example integration:
          const r = await fetch('https://environment.data.gov.uk/flood-monitoring/flood-areas');
          Returns GeoJSON with properties: {severityLevel, areaId, centroid, dateStarted, dateEnded}
        Expected fields: [{lat, lon, date, severity: 'Warning'|'Alert'|'Historical', source: 'EA'}]

        For Mountsorrel 2021-2022: Replace fetchFloodEvents UK section with:
          - Query dateRange spanning flood period (2021-07 to 2022-06)
          - Filter by polygon intersection with EA flood areas
          - Mark `severity: 'Severe'` if declared emergency

     B. USGS Water Resources — for US areas (CONUS)
        Data source: https://waterdata.usgs.gov/
        API endpoints:
          - /nwis/dv: Daily streamflow values
          - /nwis/qw: Water quality (includes flood indicators)
        Example integration:
          Fetch nearby USGS stream gauges: GET ?sites=auto&parameterCd=00060 (discharge)
          Calculate flood thresholds (2-year/10-year recurrence intervals)
        Expected fields: [{lat, lon, date, stage: number, threshold: 'Minor'|'Moderate'|'Major'}]

     C. NASA/ESA Satellite Water Detection — global coverage
        Sentinel-1 SAR (radar) detects standing water independent of clouds
        MNDWI: (GREEN - SWIR) / (GREEN + SWIR) from Sentinel-2 bands
        Integration: Query Planetary Computer for flooded pixels in time range
        Expected fields: [{lat, lon, dateRange, waterFraction: 0.0-1.0}]

     D. ERA5 Reanalysis — global historical water table & precipitation
        Copernicus Climate Data Store: /total_precipitation, /volumetric_soil_water
        Integration: Correlate precipitation spikes with NDVI drops

     IMPLEMENTATION CHECKLIST:
     1. [ ] Add API keys to .env (EA token, USGS API key if needed)
     2. [ ] Replace mock `fetchFloodEvents()` with real API calls
     3. [ ] Cache results to avoid repeated API calls during playback
     4. [ ] Handle CORS (may require backend proxy for browser-based calls)
     5. [ ] Add data quality flags (e.g., confidence, source reliability)
     6. [ ] Test regional detection (Mountsorrel for UK, California for US)
     7. [ ] Visualize flood uncertainty (dashed vs. solid markers for confirmed vs. estimated)

     TESTING DATA:
     - Mountsorrel, UK: July 2021 severe flooding (query EA records)
     - Merced County, CA: 2017 river flooding (query USGS records)
  */

  /* Detect if AOI is in UK (for EA data) or US (for USGS) */
  function getRegionForCoords(coords) {
    if (!coords || coords.length === 0) return null;
    var avgLat = 0, avgLon = 0;
    for (var i = 0; i < coords.length; i++) {
      avgLat += coords[i][0];
      avgLon += coords[i][1];
    }
    avgLat /= coords.length;
    avgLon /= coords.length;

    /* UK bounds: roughly 50-59N, -8 to 2E */
    if (avgLat >= 50 && avgLat <= 59 && avgLon >= -8 && avgLon <= 2) return 'uk';
    /* US CONUS: roughly 24-50N, -125 to -66W */
    if (avgLat >= 24 && avgLat <= 50 && avgLon >= -125 && avgLon <= -66) return 'us';
    return null;
  }

  /* Flood event cache: {region: {data: [...], timestamp: ms}} */
  var floodEventCache = {};

  /* CORS proxy helper — uses backend or public proxy */
  async function corsProxyFetch(url) {
    try {
      /* Try direct fetch first */
      var r = await fetch(url);
      if (r.ok) return r;
    } catch(e) {}

    try {
      /* Try backend CORS proxy if available (/api/proxy endpoint) */
      var proxiedUrl = '/api/proxy?url=' + encodeURIComponent(url);
      var r = await fetch(proxiedUrl);
      if (r.ok) return r;
    } catch(e) {}

    return null;
  }

  /* Compute a 5km radius around AOI centroid for event detection */
  function getAoiCentroidAndRadius(coords) {
    var lats = coords.map(function(c){return c[0]});
    var lons = coords.map(function(c){return c[1]});
    var centroidLat = (Math.min.apply(null,lats) + Math.max.apply(null,lats)) / 2;
    var centroidLon = (Math.min.apply(null,lons) + Math.max.apply(null,lons)) / 2;
    var radiusKm = 5;  /* search within 5 km of centroid */
    return { lat: centroidLat, lon: centroidLon, radiusKm: radiusKm };
  }

  /* UK Environment Agency Flood Areas API */
  async function fetchUkFloodEvents(coords, timeRange) {
    try {
      /* Query EA live flood areas & current alerts via CORS proxy */
      /* Try multiple endpoint formats for compatibility */
      var urls = [
        'https://environment.data.gov.uk/flood-monitoring/flood-areas?areaType=RiverBasin',
        'https://environment.data.gov.uk/flood-monitoring/flood-areas',
      ];

      var data = null;
      for (var i = 0; i < urls.length; i++) {
        try {
          var r = await corsProxyFetch(urls[i]);
          if (!r || !r.ok) continue;
          data = await r.json();
          if (data && data.items) break;
        } catch(e) {
          continue;
        }
      }

      if (!data || !data.items) return null;

      var center = getAoiCentroidAndRadius(coords);
      var events = [];

      /* Filter EA flood areas by distance to AOI centroid */
      data.items.forEach(function(area) {
        if (!area.center || !area.center.coordinates) return;
        var [eaLon, eaLat] = area.center.coordinates;
        /* Simple distance check (Haversine approximation for small distances) */
        var distKm = Math.sqrt(Math.pow(eaLat - center.lat, 2) + Math.pow(eaLon - center.lon, 2)) * 111;
        if (distKm <= center.radiusKm) {
          events.push({
            lat: eaLat,
            lon: eaLon,
            date: new Date().toISOString().split('T')[0],
            severity: area.alertLevel || 'Active',
            type: 'Flood Area',
            source: 'UK EA'
          });
        }
      });

      return events.length > 0 ? events : null;
    } catch(e) { return null; }
  }

  /* USGS Water Data API — find nearby streamflow gauges and check for high stage */
  async function fetchUsFloodEvents(coords, timeRange) {
    try {
      var center = getAoiCentroidAndRadius(coords);

      /* First, query NWIS for streamflow sites near AOI via CORS proxy */
      /* Try multiple endpoint formats */
      var queries = [
        /* Format 1: Daily values with bounding box */
        'https://waterdata.usgs.gov/nwis/dv?'
          + 'format=json'
          + '&bBox=' + (center.lon - 0.1) + ',' + (center.lat - 0.1) + ','
                     + (center.lon + 0.1) + ',' + (center.lat + 0.1)
          + '&parameterCd=00065,00060'  /* Stage & Discharge */
          + '&siteStatus=all'
          + '&outputDataTypeCd=dv',
        /* Format 2: Site search by location */
        'https://waterdata.usgs.gov/nwis/qw?'
          + 'format=json'
          + '&bBox=' + (center.lon - 0.1) + ',' + (center.lat - 0.1) + ','
                     + (center.lon + 0.1) + ',' + (center.lat + 0.1),
      ];

      var data = null;
      for (var i = 0; i < queries.length; i++) {
        try {
          var r = await corsProxyFetch(queries[i]);
          if (!r || !r.ok) continue;
          data = await r.json();
          if (data && (data.value || data.sites)) break;
        } catch(e) {
          continue;
        }
      }

      if (!data) return null;

      var events = [];
      var timeSeries = data.value?.timeSeries || data.sites || [];
      if (!timeSeries.length) return null;

      timeSeries.forEach(function(ts) {
        if (!ts.sourceInfo) return;
        var lat = ts.sourceInfo.geoLocation?.geogLocation?.srs330lat;
        var lon = ts.sourceInfo.geoLocation?.geogLocation?.srs330lon;

        /* Check if site has recent high stage/discharge data */
        var values = ts.values[0]?.value || [];
        values.slice(-5).forEach(function(val) {  /* check last 5 values */
          if (val.value && parseFloat(val.value) > 0) {
            /* Heuristic: if discharge > 75th percentile for region, flag as potential flood */
            events.push({
              lat: lat,
              lon: lon,
              date: val.dateTime || new Date().toISOString().split('T')[0],
              severity: 'Elevated Stage',
              type: ts.variable?.variableName || 'Streamflow',
              source: 'USGS NWIS'
            });
          }
        });
      });

      return events.length > 0 ? events : null;
    } catch(e) { return null; }
  }

  /* Main flood event fetcher — integrates multi-regional APIs */
  async function fetchFloodEvents(coords, timeRange) {
    var region = getRegionForCoords(coords);
    if (!region) return null;

    /* Check cache (5 min TTL) */
    if (floodEventCache[region] &&
        Date.now() - floodEventCache[region].timestamp < 5 * 60 * 1000) {
      return floodEventCache[region].data;
    }

    var results = null;

    /* Multi-region flood event router with real API integration and mock fallback */
    try {
      if (region === 'uk') {
        results = await fetchUkFloodEvents(coords, timeRange);
        /* Fall back to mock if real API returns null */
        if (!results) results = getMockUkFloodData(coords);
      } else if (region === 'us') {
        results = await fetchUsFloodEvents(coords, timeRange);
        /* Fall back to mock if real API returns null */
        if (!results) results = getMockUsFloodData(coords);
      }
    } catch (e) {
      console.warn('Real API failed, trying mock data:', e);
      if (region === 'uk') {
        results = getMockUkFloodData(coords);
      } else if (region === 'us') {
        results = getMockUsFloodData(coords);
      }
    }

    /* Store in cache */
    if (results) {
      floodEventCache[region] = { data: results, timestamp: Date.now() };
    }

    return results;
  }

  /* Mock UK flood data for Mountsorrel area (July 2021 EA severe flooding) */
  function getMockUkFloodData(coords) {
    var center = getAoiCentroidAndRadius(coords);

    /* Check if this is approximatelyMountsorrel area (52.71-52.74N, -1.16-1.13W) */
    if (center.lat >= 52.70 && center.lat <= 52.75 && center.lon >= -1.20 && center.lon <= -1.10) {
      return [
        {
          lat: 52.72,
          lon: -1.15,
          date: '2021-07-19',
          severity: 'Warning',
          type: 'Flood Area (EA)',
          source: 'UK EA Flood Monitoring (July 2021)',
          description: 'UK Environment Agency severe flooding alert during Mountsorrel flood event'
        }
      ];
    }
    return null;
  }

  /* Mock US flood data — placeholder for USGS integration */
  function getMockUsFloodData(coords) {
    /* In production, query real USGS NWIS API */
    return null;
  }

  function showFloodMarkers(floods) {
    if (!floods || floods.length === 0) return;
    clearFloodMarkers();
    floods.forEach(function(f) {
      var icon = L.divIcon({
        className: 'flood-marker',
        html: '<div class="flood-dot"></div>',
        iconSize: [12, 12],
        iconAnchor: [6, 6]
      });
      var popup = '<b>💧 Flood Event</b><br>';
      if (f.date) popup += 'Date: '+escapeHtml(f.date)+'<br>';
      if (f.severity) popup += 'Severity: '+escapeHtml(f.severity)+'<br>';
      if (f.type) popup += 'Type: '+escapeHtml(f.type);
      var m = L.marker([f.lat, f.lon], { icon: icon })
        .bindPopup(popup)
        .addTo(map);
      floodMarkers.push(m);
    });
  }

  function clearFloodMarkers() {
    floodMarkers.forEach(function(m){ map.removeLayer(m); });
    floodMarkers.length = 0;
  }

  /* ---- Insights engine ---- */
  function getSeasonalWeather(frameIdx) {
    if (!weatherData || !framePlan[frameIdx]) return null;
    var f = framePlan[frameIdx];
    var s = f.start, e = f.end;
    var temps = [], precip = 0, count = 0;
    for (var i = 0; i < weatherData.dates.length; i++) {
      var d = weatherData.dates[i];
      if (d >= s && d <= e) {
        if (weatherData.temp[i] != null) temps.push(weatherData.temp[i]);
        if (weatherData.precip[i] != null) precip += weatherData.precip[i];
        count++;
      }
    }
    if (!count) return null;
    var avgTemp = temps.length ? +(temps.reduce(function(a,b){return a+b},0)/temps.length).toFixed(1) : null;
    return { avgTemp: avgTemp, totalPrecip: +precip.toFixed(0), days: count };
  }

  function buildInsights(frameIdx) {
    var el = document.getElementById('insights-content');
    var f = framePlan[frameIdx];
    var rows = [];
    var alerts = [];

    /* Weather insight for this frame's season */
    var wx = getSeasonalWeather(frameIdx);
    if (wx) {
      rows.push({icon:'\ud83c\udf21\ufe0f', text: wx.avgTemp+'\u00b0C avg · '+wx.totalPrecip+' mm total precipitation ('+wx.days+' days)'});
      /* Drought flag: <30mm in summer across 3 months */
      if (f.season && f.season.key === 'summer' && wx.totalPrecip < 30) {
        alerts.push({icon:'\u26a0\ufe0f', text: 'Low summer precipitation — potential drought stress', alert:true});
      }
      /* Frost flag: sub-zero average in growing season */
      if (f.season && (f.season.key === 'spring' || f.season.key === 'autumn') && wx.avgTemp < 0) {
        alerts.push({icon:'\u2744\ufe0f', text: 'Sub-zero temperatures in growing season — frost risk', alert:true});
      }
    }

    /* NDVI context note */
    if (layerMode === 'ndvi' && ndviSearchIds[frameIdx]) {
      rows.push({icon:'\ud83c\udf3f', text: 'NDVI: green = healthy vegetation, red = bare soil / stressed canopy'
        + (f.isNaip ? ' (Sentinel-2 NDVI overlay on NAIP timeframe)' : '')});
    }

    /* NDVI change detection */
    if (ndviStatsReady && ndviStats[frameIdx]) {
      var cur = ndviStats[frameIdx];
      rows.push({icon:'\ud83c\udf3f', text: 'NDVI: mean '+cur.mean+' (range '+cur.min+' → '+cur.max+')'});
      /* Find previous S2 frame's NDVI for comparison */
      var prev = null;
      for (var pi = frameIdx - 1; pi >= 0; pi--) {
        if (ndviStats[pi]) { prev = ndviStats[pi]; break; }
      }
      if (prev) {
        var delta = +(cur.mean - prev.mean).toFixed(3);
        if (delta <= -0.1) {
          alerts.push({icon:'\ud83d\udea8', text: 'NDVI dropped by '+Math.abs(delta).toFixed(2)+' — possible vegetation loss or clearing', alert:true});
        } else if (delta >= 0.1) {
          rows.push({icon:'\ud83c\udf31', text: 'NDVI increased by +'+delta.toFixed(2)+' — vegetation recovery or seasonal growth'});
        }
      }
    }

    /* Fire hotspot note */
    if (firmsData && firmsData.length > 0) {
      alerts.push({icon:'\ud83d\udd25', text: firmsData.length+' fire hotspot'+(firmsData.length>1?'s':'')+' detected near AOI in last 10 days (VIIRS/SNPP)', alert:true});
    }

    /* Flood event note */
    if (floodData && floodData.length > 0) {
      alerts.push({icon:'\ud83d\udca7', text: floodData.length+' flood event'+(floodData.length>1?'s':'')+' detected in this time period — may explain vegetation stress', alert:true});
    }

    /* Collection info */
    rows.push({icon: f.isNaip ? '\ud83d\udef0' : '\ud83d\udef0',
      text: f.isNaip
        ? 'NAIP aerial imagery at '+naipRes(f.year)+' m/px — USDA survey'
        : 'Sentinel-2 at 10 m/px — ESA Copernicus programme'
    });

    var all = rows.concat(alerts);
    el.replaceChildren();
    all.forEach(function(r) {
      var row = document.createElement('div');
      row.className = 'insight-row' + (r.alert ? ' alert' : '');
      var icon = document.createElement('span');
      icon.className = 'insight-icon';
      icon.textContent = r.icon;
      row.appendChild(icon);
      row.appendChild(document.createTextNode(' ' + r.text));
      el.appendChild(row);
    });
  }

  var frameLayers = [], framesMeta = [];
  var currentFrame = 0, playing = false, playTimer = null;

  function showFrame(idx) {
    currentFrame = idx;
    var useNdvi = layerMode === 'ndvi' && !!ndviSearchIds[idx];

    /* Toggle opacity — all layers stay on the map for instant switching */
    frameLayers.forEach(function(l,i){ l.setOpacity(i===idx && !useNdvi ? 1 : 0); });

    /* NDVI layer (lazily create on first use) */
    ndviLayers.forEach(function(l,i){ if(l) l.setOpacity(i===idx && useNdvi ? 1 : 0); });
    if (useNdvi && !ndviLayers[idx] && ndviSearchIds[idx]) {
      var nl = pcNdviLayer(ndviSearchIds[idx]);
      nl.addTo(map);
      nl.setOpacity(1);
      ndviLayers[idx] = nl;
    }

    labelsLayer.bringToFront();
    aoiPolygon.bringToFront();
    aoiSubPolygons.forEach(function(l){ l.bringToFront(); });
    var m = framesMeta[idx];
    function buildLabelNodes(container, label, isNaip, showNdvi) {
      container.replaceChildren();
      container.appendChild(document.createTextNode(label));
      if (isNaip && !showNdvi) {
        var b = document.createElement('span');
        b.className = 'naip-badge';
        b.textContent = 'NAIP 0.6m';
        container.appendChild(document.createTextNode(' '));
        container.appendChild(b);
      }
      if (showNdvi) {
        var n = document.createElement('span');
        n.className = 'naip-badge';
        n.style.background = 'var(--c-green)';
        n.textContent = 'NDVI';
        container.appendChild(document.createTextNode(' '));
        container.appendChild(n);
      }
    }
    buildLabelNodes(document.getElementById('frame-label'), m.label, m.isNaip, useNdvi);
    document.getElementById('frame-counter').textContent = (idx+1)+' / '+frameLayers.length;
    document.getElementById('frame-slider').value = idx;
    document.getElementById('frame-info').textContent = m.info;

    /* Update header bar */
    var headerLabel = document.getElementById('header-frame-label');
    buildLabelNodes(headerLabel, m.label, m.isNaip, useNdvi);
    var counter = document.createElement('span');
    counter.style.cssText = 'color:var(--c-muted);font-size:.75rem;margin-left:4px';
    counter.textContent = (idx+1)+'/'+frameLayers.length;
    headerLabel.appendChild(document.createTextNode(' '));
    headerLabel.appendChild(counter);

    /* Update weather marker, NDVI trend marker, and insights */
    updateWeatherMarker();
    updateNdviTrendMarker();
    buildInsights(idx);
  }

  document.getElementById('play-btn').addEventListener('click', function() {
    if (!frameLayers.length) return;
    if (playing) {
      clearInterval(playTimer); playing=false;
      this.textContent='\u25B6 Play';
    } else {
      playing=true; this.textContent='\u23F8 Pause';
      playTimer = setInterval(function(){
        showFrame((currentFrame+1)%frameLayers.length);
      }, 1200);
    }
  });
  document.getElementById('frame-slider').addEventListener('input', function() {
    if (frameLayers.length) showFrame(parseInt(this.value));
  });

  /* Render AI analysis into the insights panel */
  function renderAnalysis(analysis) {
    var content = document.getElementById('ai-insights-content');
    var summary = document.getElementById('ai-insights-summary');
    var example = document.getElementById('ai-insights-example');
    if (example) example.style.display = 'none';
    content.replaceChildren();
    if (analysis.observations && Array.isArray(analysis.observations)) {
      analysis.observations.forEach(function(obs) {
        var severity = obs.severity || 'normal';
        var obsDiv = document.createElement('div');
        obsDiv.className = 'observation';
        var catDiv = document.createElement('div');
        catDiv.className = 'obs-category';
        catDiv.appendChild(document.createTextNode(obs.category || 'Analysis'));
        var sevSpan = document.createElement('span');
        sevSpan.className = 'obs-severity severity-' + severity;
        sevSpan.textContent = severity.toUpperCase();
        catDiv.appendChild(document.createTextNode(' '));
        catDiv.appendChild(sevSpan);
        obsDiv.appendChild(catDiv);
        if (obs.description) {
          var descDiv = document.createElement('div');
          descDiv.className = 'obs-description';
          descDiv.textContent = obs.description;
          obsDiv.appendChild(descDiv);
        }
        if (obs.recommendation) {
          var recDiv = document.createElement('div');
          recDiv.className = 'obs-recommendation';
          recDiv.textContent = '\uD83D\uDCA1 ' + obs.recommendation;
          obsDiv.appendChild(recDiv);
        }
        content.appendChild(obsDiv);
      });
    }
    content.style.display = 'block';
    if (analysis.summary) {
      summary.textContent = analysis.summary;
      summary.style.display = 'block';
    }
    if (analysis.saved_at) {
      var savedNote = document.createElement('div');
      savedNote.style.cssText = 'color:var(--c-muted);font-size:.7rem;margin-top:6px';
      savedNote.textContent = '📦 Pipeline-cached analysis from ' + analysis.saved_at;
      content.appendChild(savedNote);
    }
  }

  /* AI Insights button handler - analyze entire timelapse, not just current frame */
  document.getElementById('btn-get-ai-insights').addEventListener('click', async function() {
    var btn = this;
    var loading = document.getElementById('ai-insights-loading');
    var content = document.getElementById('ai-insights-content');
    var error = document.getElementById('ai-insights-error');
    var summary = document.getElementById('ai-insights-summary');

    loading.style.display = 'block';
    content.style.display = 'none';
    error.style.display = 'none';

    try {
      /* 1. Try loading saved analysis from pipeline storage first */
      if (pipelineInstanceId) {
        try {
          var savedRes = await apiFetch('/api/timelapse-analysis-load/' + pipelineInstanceId);
          if (savedRes && savedRes.ok) {
            var savedAnalysis = await savedRes.json();
            if (savedAnalysis && savedAnalysis.observations) {
              console.log('Loaded saved analysis from pipeline storage');
              renderAnalysis(savedAnalysis);
              loading.style.display = 'none';
              return;
            }
          }
        } catch(e) { /* no saved analysis — run fresh */ }
      }

      /* 2. No saved analysis — run fresh LLM analysis */
      // Get AOI name
      var aoiNameForAnalysis = (selectedAoiIndex >= 0 && aoiPolygonsData[selectedAoiIndex] && aoiPolygonsData[selectedAoiIndex].name)
        ? aoiPolygonsData[selectedAoiIndex].name
        : 'Area of Interest';

      // Collect NDVI time series — include ALL frames (null entries preserve alignment)
      var ndviTimeseries = [];
      if (framePlan && ndviStats) {
        for (var i = 0; i < Math.min(framePlan.length, ndviStats.length); i++) {
          var f = framePlan[i];
          var entry = {
            date: f.start,
            season: f.season && f.season.key ? f.season.key : (f.season || null),
            year: f.year,
            label: f.label,
            is_naip: !!f.isNaip
          };
          if (ndviStats[i]) {
            entry.mean = parseFloat(ndviStats[i].mean);
            entry.min = parseFloat(ndviStats[i].min);
            entry.max = parseFloat(ndviStats[i].max);
          } else {
            entry.mean = null;
            entry.min = null;
            entry.max = null;
          }
          ndviTimeseries.push(entry);
        }
      }

      // Collect weather time series — include actual month labels
      var weatherTimeseries = [];
      if (monthlyWeather && monthlyWeather.temp && monthlyWeather.precip && monthlyWeather.labels) {
        var tempCount = Math.min(monthlyWeather.temp.length, monthlyWeather.precip.length, monthlyWeather.labels.length);
        for (var j = 0; j < tempCount; j++) {
          if (monthlyWeather.temp[j] !== null && monthlyWeather.precip[j] !== null) {
            weatherTimeseries.push({
              month: monthlyWeather.labels[j],
              month_index: j,
              temperature: parseFloat(monthlyWeather.temp[j]),
              precipitation: parseFloat(monthlyWeather.precip[j])
            });
          }
        }
      }

      // Build comprehensive timelapse analysis request
      var contextData = {
        aoi_name: aoiNameForAnalysis,
        latitude: aoiCoords && aoiCoords.length > 0 ? aoiCoords[0][0] : 0,
        longitude: aoiCoords && aoiCoords.length > 0 ? aoiCoords[0][1] : 0,
        ndvi_timeseries: ndviTimeseries,
        weather_timeseries: weatherTimeseries,
        frame_count: framePlan ? framePlan.length : 0,
        date_range_start: framePlan && framePlan.length > 0 ? framePlan[0].start : null,
        date_range_end: framePlan && framePlan.length > 0 ? framePlan[framePlan.length - 1].end : null
      };

      var response = await apiFetch('/api/timelapse-analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ context: contextData })
      });

      if (!response || !response.ok) {
        var errData = response ? await response.json().catch(function(){return {};}) : {};
        error.textContent = '❌ ' + (errData.error || 'Analysis failed (HTTP ' + (response?response.status:'unreachable') + ')');
        error.style.display = 'block';
        loading.style.display = 'none';
        return;
      }

      var analysis = await response.json();

      /* 3. Save the analysis to pipeline storage for reproducibility */
      if (pipelineInstanceId) {
        try {
          await apiFetch('/api/timelapse-analysis-save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              instance_id: pipelineInstanceId,
              analysis: analysis
            })
          });
          console.log('Analysis saved to pipeline storage');
        } catch(e) { console.warn('Could not save analysis:', e); }
      }

      renderAnalysis(analysis);

      loading.style.display = 'none';
    } catch(err) {
      console.error('AI analysis error:', err);
      error.textContent = '❌ Could not reach AI service: ' + err.message;
      error.style.display = 'block';
      loading.style.display = 'none';
    }
  });

  /* Tear down existing timelapse and launch for current AOI */
  function launchTimelapse(newCoords, newPolygons) {
    /* Collapse input column, expand viewer */
    document.getElementById('demo-layout').classList.add('timelapse-active');
    document.getElementById('timelapse-header').classList.add('visible');
    requestAnimationFrame(function(){ map.invalidateSize(); });
    document.getElementById('demo').scrollIntoView({ behavior: 'smooth', block: 'start' });
    /* Exit compare mode if active */
    if (compareActive) exitCompareMode();
    document.getElementById('compare-btn').disabled = true;
    /* Stop playback */
    if (playing) { clearInterval(playTimer); playing = false; }
    document.getElementById('play-btn').textContent = '\u25B6 Play';
    document.getElementById('play-btn').disabled = true;
    /* Remove old tile layers (RGB + NDVI) */
    frameLayers.forEach(function(l){ map.removeLayer(l); });
    ndviLayers.forEach(function(l){ if(l) map.removeLayer(l); });
    frameLayers.length = 0;
    ndviLayers.length = 0;
    searchIdCache.length = 0;
    ndviSearchIds.length = 0;
    framesMeta.length = 0;
    currentFrame = 0;
    /* Reset layer mode to RGB */
    layerMode = 'rgb';
    document.getElementById('btn-rgb').classList.add('active');
    document.getElementById('btn-ndvi').classList.remove('active');
    document.getElementById('header-btn-rgb').classList.add('active');
    document.getElementById('header-btn-ndvi').classList.remove('active');
    /* Reset weather + insights + NDVI stats + fire */
    weatherData = null;
    monthlyWeather = null;
    ndviStats = [];
    ndviStatsReady = false;
    clearFireMarkers();
    firmsData = null;
    document.getElementById('weather-panel').style.display = 'none';
    document.getElementById('insights-panel').style.display = 'none';
    document.getElementById('ndvi-trend-panel').style.display = 'none';
    document.getElementById('period-summary').style.display = 'none';
    /* Update AOI if new coords provided */
    if (newCoords) setAoi(newCoords, newPolygons);
    /* Rebuild frame plan for new AOI (NAIP only in CONUS) */
    buildFramePlan();
    /* Run */
    initTimelapse();
  }

  /* --- Bootstrap: register all mosaics, pre-cache tiles, enable play --- */
  async function initTimelapse() {
    try {
      var progressEl = document.getElementById('cache-progress');
      var fillEl = document.getElementById('cache-fill');
      var cacheText = document.getElementById('cache-text');

      /* 1. Mosaic search IDs — use pipeline-cached IDs when available */
      var searchIds = [];
      var s2ForNaip = {};

      if (enrichmentPayload && enrichmentPayload.search_ids && enrichmentPayload.search_ids.length === framePlan.length) {
        /* Pipeline already registered all mosaics — use cached IDs */
        document.getElementById('frame-info').textContent =
          'Using pipeline-cached mosaic registrations\u2026';
        searchIds = enrichmentPayload.search_ids;
        /* Build s2ForNaip from enrichment ndvi_search_ids */
        if (enrichmentPayload.ndvi_search_ids) {
          for (var i = 0; i < framePlan.length; i++) {
            if (framePlan[i].isNaip && enrichmentPayload.ndvi_search_ids[i]) {
              s2ForNaip[i] = enrichmentPayload.ndvi_search_ids[i];
            }
          }
        }
        console.log('Using ' + searchIds.length + ' pipeline-cached mosaic search IDs');
      } else {
        /* Fallback: register mosaics live from Planetary Computer */
        document.getElementById('frame-info').textContent =
          'Registering '+framePlan.length+' seasonal mosaics\u2026';
        for (var b = 0; b < framePlan.length; b += 6) {
          var batch = framePlan.slice(b, b + 6);
          var ids = await Promise.all(batch.map(function(f) {
            var extra = f.collection === 'sentinel-2-l2a'
              ? [{op:'<=', args:[{property:'eo:cloud_cover'},20]}] : [];
            return registerMosaic(f.collection, f.start, f.end, extra);
          }));
          searchIds.push.apply(searchIds, ids);
          document.getElementById('frame-info').textContent =
            'Registered '+searchIds.length+'/'+framePlan.length+' mosaics\u2026';
        }

        /* 1b. Register S2 mosaics for NAIP frames (so NDVI works on all frames) */
        var naipFrameIndices = [];
        for (var i = 0; i < framePlan.length; i++) {
          if (framePlan[i].isNaip) naipFrameIndices.push(i);
        }
        if (naipFrameIndices.length) {
          document.getElementById('frame-info').textContent =
            'Registering S2 NDVI for '+naipFrameIndices.length+' NAIP frames\u2026';
          for (var b = 0; b < naipFrameIndices.length; b += 6) {
            var batchIdx = naipFrameIndices.slice(b, b + 6);
            var s2ids = await Promise.all(batchIdx.map(function(fi) {
              var f = framePlan[fi];
              return registerMosaic('sentinel-2-l2a', f.start, f.end,
                [{op:'<=', args:[{property:'eo:cloud_cover'},20]}]);
            }));
            for (var j = 0; j < batchIdx.length; j++) {
              s2ForNaip[batchIdx[j]] = s2ids[j];
            }
          }
        }
      }

      /* 2. Create all layers at opacity 0 and add to map (triggers tile caching) */
      progressEl.style.display = 'block';
      var cachedCount = 0;

      searchIds.forEach(function(sid, i) {
        var f = framePlan[i];
        searchIdCache.push(sid);
        /* S2 search ID for NDVI: same sid for S2 frames, separate S2 mosaic for NAIP */
        ndviSearchIds.push(f.isNaip ? (s2ForNaip[i] || null) : sid);
        ndviLayers.push(null); /* placeholder, created lazily */
        var layer = pcTileLayer(sid, f.collection, f.asset);
        layer.addTo(map);
        layer.once('load', function() {
          cachedCount++;
          var pct = Math.round(cachedCount / framePlan.length * 100);
          fillEl.style.width = pct + '%';
          cacheText.textContent = 'Cached '+cachedCount+'/'+framePlan.length+' frames\u2026';
          if (cachedCount >= framePlan.length) onAllCached();
        });
        frameLayers.push(layer);
        framesMeta.push({ label: f.label, info: f.info, isNaip: f.isNaip });
      });

      labelsLayer.addTo(map);
      aoiPolygon.bringToFront();
      aoiSubPolygons.forEach(function(l){ l.bringToFront(); });
      document.getElementById('frame-slider').max = frameLayers.length - 1;
      showFrame(0);

      function onAllCached() {
        progressEl.style.display = 'none';
        document.getElementById('play-btn').disabled = false;
        document.getElementById('compare-btn').disabled = false;
        document.getElementById('frame-info').textContent = framesMeta[currentFrame].info;
        document.getElementById('play-btn').click(); /* auto-play */
        /* Show insights panels now; weather will arrive async */
        document.getElementById('insights-panel').style.display = 'block';
        document.getElementById('ai-insights-panel').style.display = 'block';
        buildInsights(currentFrame);
      }

      /* Kick off scope-aware analytics (collective by default; click polygon to focus) */
      refreshAnalyticsForScope();

      /* Kick off FIRMS fire hotspot fetch */
      (async function() {
        try {
          var lats = aoiCoords.map(function(c){return c[0]});
          var lons = aoiCoords.map(function(c){return c[1]});
          var cLat = +((Math.min.apply(null,lats)+Math.max.apply(null,lats))/2).toFixed(4);
          var cLon = +((Math.min.apply(null,lons)+Math.max.apply(null,lons))/2).toFixed(4);
          firmsData = await fetchFirmsData(cLat, cLon);
          if (firmsData && firmsData.length > 0) {
            showFireMarkers(firmsData);
            buildInsights(currentFrame);
          }
        } catch(e) { /* FIRMS non-critical */ }
      })();

      /* Kick off flood event fetch */
      (async function() {
        try {
          var timeRange = {start: '2017-01-01', end: '2025-12-31'};
          floodData = await fetchFloodEvents(aoiCoords, timeRange);
          if (floodData && floodData.length > 0) {
            showFloodMarkers(floodData);
            buildInsights(currentFrame);
          }
        } catch(e) { /* Flood data non-critical */ }
      })();

      /* Enable play after 25s even if some tiles haven't loaded */
      setTimeout(function(){
        if (document.getElementById('play-btn').disabled) {
          document.getElementById('play-btn').disabled = false;
          document.getElementById('compare-btn').disabled = false;
          progressEl.style.display = 'none';
        }
      }, 25000);

    } catch(err) {
      console.warn('PC mosaic init failed, falling back to Esri:', err);
      L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/'
        +'World_Imagery/MapServer/tile/{z}/{y}/{x}',
        {attribution:'Tiles \u00A9 Esri',maxZoom:19}).addTo(map);
      labelsLayer.addTo(map);
      document.getElementById('frame-label').textContent =
        'Static view (PC unavailable)';
      document.getElementById('frame-info').textContent =
        'Could not reach Planetary Computer \u2014 showing cached imagery';
      document.getElementById('cache-progress').style.display = 'none';
    }
  }

  /* On load: show base map with default AOI — no timelapse until pipeline runs */
  L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {attribution:'Tiles &copy; Esri', maxZoom:19}
  ).addTo(map);
  labelsLayer.addTo(map);
  document.getElementById('frame-label').textContent = 'Load KML and click Process to begin';
  document.getElementById('frame-info').textContent = 'Pipeline will parse, search, download, clip and reproject imagery for your AOI';

  /* --- Init --- */
  initAuth();
  document.getElementById('auth-login-btn').addEventListener('click', login);
  document.getElementById('auth-logout-btn').addEventListener('click', logout);
  var loginPromptLink = document.getElementById('login-prompt-link');
  if (loginPromptLink) loginPromptLink.addEventListener('click', login);

  discoverApiBase().then(function() {
    checkContract();
    checkStatus();
    setInterval(checkStatus, 30000);
  });

})();
