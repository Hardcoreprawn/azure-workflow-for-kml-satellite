(function() {
  'use strict';

  var currentAccount = null;
  var _apiBase = '';
  var _clientPrincipal = null;

  function authEnabled() { return true; }

  async function initAuth() {
    try {
      var res = await fetch('/.auth/me');
      if (!res.ok) { updateAuthUI(); updateSampleReportGate(); return; }
      var data = await res.json();
      var principal = data && data.clientPrincipal;
      if (principal && principal.userId) {
        _clientPrincipal = principal;
        currentAccount = {
          userId: principal.userId,
          name: principal.userDetails || principal.userId,
          identityProvider: principal.identityProvider,
          userRoles: principal.userRoles || []
        };
      }
    } catch (err) {
      console.warn('[canopex] SWA auth check failed:', err);
    }
    updateAuthUI();
    updateSampleReportGate();
  }

  function login() {
    window.location.href = '/.auth/login/aad';
  }

  function logout() {
    window.location.href = '/.auth/logout';
  }

  function updateAuthUI() {
    var loginBtn = document.getElementById('auth-login-btn');
    var logoutBtn = document.getElementById('auth-logout-btn');
    var userSpan = document.getElementById('auth-user');
    var dashLink = document.getElementById('auth-dashboard-link');

    if (!authEnabled()) {
      if (loginBtn) loginBtn.style.display = 'none';
      if (logoutBtn) logoutBtn.style.display = 'none';
      if (userSpan) userSpan.style.display = 'none';
      if (dashLink) dashLink.style.display = 'none';
      return;
    }

    if (currentAccount) {
      var name = currentAccount.name || currentAccount.userId || 'User';
      if (userSpan) userSpan.textContent = name;
      if (userSpan) userSpan.style.display = 'inline';
      if (loginBtn) loginBtn.style.display = 'none';
      if (logoutBtn) logoutBtn.style.display = 'inline';
      if (dashLink) dashLink.style.display = 'inline';
    } else {
      if (userSpan) userSpan.style.display = 'none';
      if (loginBtn) loginBtn.style.display = 'inline';
      if (logoutBtn) logoutBtn.style.display = 'none';
      if (dashLink) dashLink.style.display = 'none';
    }
  }

  async function apiFetch(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    if (_clientPrincipal) {
      var jsonStr = JSON.stringify(_clientPrincipal);
      var bytes = new TextEncoder().encode(jsonStr);
      var binStr = Array.from(bytes, function (b) { return String.fromCharCode(b); }).join('');
      opts.headers['X-MS-CLIENT-PRINCIPAL'] = btoa(binStr);
    }
    var url = _apiBase ? _apiBase + path : path;
    var resp = await fetch(url, opts);
    if (!resp.ok) {
      var body = await resp.json().catch(function () { return {}; });
      var msg = body.error || ('API request failed: ' + resp.status + ' ' + resp.statusText);
      var err = new Error(msg);
      err.status = resp.status;
      err.body = body;
      throw err;
    }
    return resp;
  }

  async function discoverApiBase() {
    try {
      var cfgRes = await fetch('/api-config.json');
      if (cfgRes.ok) {
        var cfg = await cfgRes.json();
        if (cfg.apiBase) {
          _apiBase = cfg.apiBase.replace(/\/+$/, '');
        }
      }
    } catch (e) { /* local dev — no api-config.json, use same-origin */ }

    var badge = document.getElementById('status-badge');
    if (!badge) return;

    try {
      var healthUrl = _apiBase ? _apiBase + '/api/health' : '/api/health';
      var res = await fetch(healthUrl);
      if (res.ok) {
        badge.textContent = 'Online';
        badge.className = 'online';
        return;
      }
    } catch (err) {
      console.warn('[canopex] Health check failed:', err);
    }

    badge.textContent = 'Unavailable';
    badge.className = 'offline';
  }

  /* --- Sample Report Map (Planetary Computer S2 visual) --- */
  function initSampleMap() {
    var mapEl = document.getElementById('sample-map');
    if (!mapEl || typeof L === 'undefined') return;

    // São Félix do Xingu, Pará — real PRODES d2021 deforestation polygon
    // from INPE/Terrabrasilis WFS (prodes-amazon-nb:yearly_deforestation_biome).
    // 0.379 km² clearing detected 2021, near Fresco River, state PA.
    // Coordinates sourced from official Brazilian government deforestation
    // monitoring — the same data EUDR regulators reference.
    var parcelCoords = [
      [-6.6624, -51.8461],
      [-6.6620, -51.8461],
      [-6.6618, -51.8461],
      [-6.6591, -51.8449],
      [-6.6613, -51.8394],
      [-6.6618, -51.8394],
      [-6.6618, -51.8400],
      [-6.6620, -51.8400],
      [-6.6628, -51.8400],
      [-6.6628, -51.8394],
      [-6.6634, -51.8394],
      [-6.6634, -51.8389],
      [-6.6639, -51.8389],
      [-6.6639, -51.8383],
      [-6.6644, -51.8383],
      [-6.6644, -51.8386],
      [-6.6647, -51.8386],
      [-6.6647, -51.8389],
      [-6.6653, -51.8389],
      [-6.6653, -51.8391],
      [-6.6655, -51.8391],
      [-6.6655, -51.8394],
      [-6.6658, -51.8394],
      [-6.6658, -51.8389],
      [-6.6661, -51.8389],
      [-6.6661, -51.8383],
      [-6.6662, -51.8383],
      [-6.6665, -51.8389],
      [-6.6671, -51.8387],
      [-6.6671, -51.8389],
      [-6.6674, -51.8389],
      [-6.6674, -51.8391],
      [-6.6673, -51.8391],
      [-6.6672, -51.8392],
      [-6.6671, -51.8415],
      [-6.6670, -51.8416],
      [-6.6664, -51.8417],
      [-6.6662, -51.8419],
      [-6.6660, -51.8419],
      [-6.6660, -51.8421],
      [-6.6654, -51.8425],
      [-6.6635, -51.8419],
      [-6.6624, -51.8461]
    ];
    var center = [-6.6647, -51.8404];

    var map = L.map(mapEl, {
      scrollWheelZoom: false,
      zoomControl: true,
      attributionControl: true
    }).setView(center, 14);

    // Register a PC mosaic for recent low-cloud S2 visual imagery
    var bbox = [-51.85, -6.68, -51.83, -6.65];
    var registerBody = {
      collections: ['sentinel-2-l2a'],
      'filter-lang': 'cql2-json',
      filter: {
        op: 'and',
        args: [
          { op: 's_intersects', args: [
            { property: 'geometry' },
            { type: 'Polygon', coordinates: [[
              [bbox[0], bbox[1]], [bbox[2], bbox[1]],
              [bbox[2], bbox[3]], [bbox[0], bbox[3]],
              [bbox[0], bbox[1]]
            ]]}
          ]},
          { op: '<=', args: [{ property: 'eo:cloud_cover' }, 10] },
          { op: '>=', args: [{ property: 'datetime' }, '2025-01-01T00:00:00Z'] }
        ]
      }
    };

    // Esri fallback base layer
    var esriLayer = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { attribution: 'Tiles &copy; Esri', maxZoom: 18 }
    );
    esriLayer.addTo(map);

    // Try to overlay PC Sentinel-2 visual tiles
    fetch('https://planetarycomputer.microsoft.com/api/data/v1/mosaic/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(registerBody)
    }).then(function(res) {
      if (!res.ok) return;
      return res.json();
    }).then(function(data) {
      if (!data || !data.searchid) return;
      var tileUrl = 'https://planetarycomputer.microsoft.com/api/data/v1/mosaic/tiles/' +
        encodeURIComponent(data.searchid) + '/WebMercatorQuad/{z}/{x}/{y}@2x' +
        '?collection=sentinel-2-l2a&assets=visual';
      var pcLayer = L.tileLayer(tileUrl, {
        tileSize: 512,
        zoomOffset: -1,
        maxNativeZoom: 14,
        maxZoom: 18,
        attribution: 'Sentinel-2 &copy; ESA / Copernicus via Planetary Computer'
      });
      map.removeLayer(esriLayer);
      pcLayer.addTo(map);
    }).catch(function() { /* keep Esri fallback */ });

    L.polygon(parcelCoords, {
      color: '#5eecc4',
      weight: 2,
      fillColor: '#5eecc4',
      fillOpacity: 0.15
    }).addTo(map);

    // Fix Leaflet tile rendering after container becomes visible
    setTimeout(function() { map.invalidateSize(); }, 200);
  }

  /* --- Sample Report PDF Gate --- */
  function updateSampleReportGate() {
    var btn = document.getElementById('btn-download-sample');
    var note = document.getElementById('sample-gated-note');
    if (!btn) return;

    if (currentAccount) {
      btn.textContent = 'Download Full PDF Report';
      if (note) note.style.display = 'none';
      btn.onclick = function() {
        // Placeholder — actual PDF export wired in Stage 2F (#605)
        alert('PDF report download coming soon. The assessment data shown above is representative of the full evidence package.');
      };
    } else {
      btn.textContent = 'Sign In to Download PDF';
      if (note) {
        note.textContent = 'Sign in to download the full PDF evidence report.';
        note.style.display = 'block';
      }
      btn.onclick = function() { login(); };
    }
  }

  /* --- Subscribe Button --- */
  function initSubscribe() {
    var btn = document.getElementById('btn-subscribe');
    if (!btn) return;

    btn.addEventListener('click', async function() {
      if (!currentAccount && authEnabled()) { login(); return; }
      try {
        var res = await apiFetch('/api/billing/checkout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tier: 'eudr_pro' })
        });
        var data = await res.json();
        if (data.checkout_url) { window.location.href = data.checkout_url; }
      } catch (e) {
        console.error('Checkout error:', e);
        alert((e && e.message) || 'Could not connect to billing. Please try again later.');
      }
    });
  }

  /* --- FAQ toggle --- */
  function initFAQ() {
    var faqList = document.getElementById('faq-list');
    if (!faqList) return;

    faqList.addEventListener('click', function(e) {
      var item = e.target.closest('.faq-item');
      if (item) item.classList.toggle('open');
    });
  }

  /* --- Auth event listeners --- */
  document.addEventListener('DOMContentLoaded', function() {
    var loginBtn = document.getElementById('auth-login-btn');
    var logoutBtn = document.getElementById('auth-logout-btn');

    if (loginBtn) loginBtn.addEventListener('click', login);
    if (logoutBtn) logoutBtn.addEventListener('click', logout);

    initFAQ();
    initSampleMap();
    initSubscribe();
  });

  /* Handle billing return query params */
  document.addEventListener('DOMContentLoaded', function() {
    var params = new URLSearchParams(window.location.search);
    if (params.get('billing') === 'success') {
      setTimeout(function() { alert('Welcome to EUDR Pro! Your subscription is now active.'); }, 500);
      history.replaceState(null, '', window.location.pathname);
    } else if (params.get('billing') === 'cancel') {
      history.replaceState(null, '', window.location.pathname);
    }
  });

  /* Initialization */
  initAuth();
  discoverApiBase();
})();
