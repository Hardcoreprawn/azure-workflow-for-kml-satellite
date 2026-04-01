(function() {
  'use strict';

  const CIAM_TENANT_NAME = 'treesightauth';
  const CIAM_CLIENT_ID = '6e2abd0a-61a4-41a5-bdb5-7e1c91471fc6';
  const CIAM_AUTHORITY = CIAM_TENANT_NAME
    ? 'https://' + CIAM_TENANT_NAME + '.ciamlogin.com/'
    : '';
  const CIAM_KNOWN_AUTHORITY = CIAM_AUTHORITY;
  const CIAM_SCOPES = CIAM_CLIENT_ID ? ['openid', 'profile'] : [];

  let msalInstance = null;
  let currentAccount = null;
  let accessToken = null;
  let apiBase = '';

  function authEnabled() { return !!(CIAM_TENANT_NAME && CIAM_CLIENT_ID && typeof msal !== 'undefined'); }

  function initAuth() {
    if (!authEnabled()) {
      updateAuthUI();
      return;
    }

    const msalConfig = {
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

    msalInstance.handleRedirectPromise().then(function(resp) {
      if (resp && resp.account) {
        msalInstance.setActiveAccount(resp.account);
      }
      currentAccount = msalInstance.getActiveAccount() || (msalInstance.getAllAccounts()[0] || null);
      if (currentAccount) { msalInstance.setActiveAccount(currentAccount); }
      updateAuthUI();
      // Load billing status after auth — ungates pricing for allowed users
      if (window.treesightBilling && window.treesightBilling.loadStatus) {
        window.treesightBilling.loadStatus();
      }
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
      const resp = await msalInstance.acquireTokenSilent({ scopes: CIAM_SCOPES, account: currentAccount });
      accessToken = resp.accessToken || resp.idToken;
      return accessToken;
    } catch {
      try { msalInstance.acquireTokenRedirect({ scopes: CIAM_SCOPES }); } catch { }
      return null;
    }
  }

  function updateAuthUI() {
    const loginBtn = document.getElementById('auth-login-btn');
    const logoutBtn = document.getElementById('auth-logout-btn');
    const userSpan = document.getElementById('auth-user');

    if (!authEnabled()) {
      if (loginBtn) loginBtn.style.display = 'none';
      if (logoutBtn) logoutBtn.style.display = 'none';
      if (userSpan) userSpan.style.display = 'none';
      return;
    }

    if (currentAccount) {
      const name = currentAccount.name || currentAccount.username || 'User';
      if (userSpan) userSpan.textContent = name;
      if (userSpan) userSpan.style.display = 'inline';
      if (loginBtn) loginBtn.style.display = 'none';
      if (logoutBtn) logoutBtn.style.display = 'inline';
    } else {
      if (userSpan) userSpan.style.display = 'none';
      if (loginBtn) loginBtn.style.display = 'inline';
      if (logoutBtn) logoutBtn.style.display = 'none';
    }
  }

  async function apiFetch(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    if (currentAccount && authEnabled()) {
      const token = accessToken || await acquireToken();
      if (token) { opts.headers['Authorization'] = 'Bearer ' + token; }
    }
    try { return await fetch(apiBase + path, opts); } catch { return null; }
  }

  async function discoverApiBase() {
    const badge = document.getElementById('status-badge');
    if (!badge) return;

    try {
      const cfgRes = await fetch('/api-config.json');
      if (cfgRes.ok) {
        const cfg = await cfgRes.json();
        if (cfg.apiBase && cfg.apiBase !== 'http://localhost:7071') {
          apiBase = cfg.apiBase;
          if (cfg.lastVerified) {
            badge.textContent = 'Verified';
            badge.className = 'verified';
            badge.title = 'Deploy-time verified: ' + cfg.lastVerified;
          } else {
            badge.textContent = 'Verified';
            badge.className = 'verified';
          }
          fetch(cfg.apiBase + '/api/health').then(function(r) {
            if (r.ok && badge) { badge.textContent = 'Online'; badge.className = 'online'; badge.title = ''; }
          }).catch(function() { });
          return;
        }

        if (cfg.apiBase) {
          try {
            const probe = await fetch(cfg.apiBase + '/api/health');
            if (probe.ok) {
              apiBase = cfg.apiBase;
              if (badge) { badge.textContent = 'Online'; badge.className = 'online'; }
              return;
            }
          } catch { }
        }
      }
    } catch { }

    try {
      const res = await fetch('/api/health');
      if (res.ok) {
        apiBase = '';
        if (badge) { badge.textContent = 'Online'; badge.className = 'online'; }
        return;
      }
    } catch { }

    if (badge) {
      badge.textContent = 'Unavailable';
      badge.className = 'offline';
    }
    console.warn('Backend not reachable — check SWA backend configuration or api-config.json');
  }

  /* --- Early Access form --- */
  function initEarlyAccessForm() {
    const submitBtn = document.getElementById('ea-submit');
    if (!submitBtn) return;

    submitBtn.addEventListener('click', async function() {
      const org = document.getElementById('ea-org').value.trim();
      const useCase = document.getElementById('ea-usecase').value.trim();
      const email = document.getElementById('ea-email').value.trim();
      const status = document.getElementById('ea-status');

      if (!org || !email) {
        if (status) {
          status.textContent = 'Please provide at least organisation and email.';
          status.className = 'show';
          status.style.color = 'var(--c-red)';
        }
        return;
      }

      if (status) {
        status.textContent = 'Submitting…';
        status.className = 'show';
        status.style.color = 'var(--c-muted)';
      }

      try {
        const res = await apiFetch('/api/contact-form', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            organisation: org,
            use_case: useCase,
            email: email,
            source: 'marketing_website'
          })
        });

        if (res && res.ok) {
          if (status) {
            status.textContent = 'Thanks! We\'ll be in touch.';
            status.style.color = 'var(--c-green)';
          }
        } else {
          if (status) {
            status.textContent = 'Submission failed. Please try again.';
            status.style.color = 'var(--c-red)';
          }
        }
      } catch {
        if (status) {
          status.textContent = 'Failed to reach API.';
          status.style.color = 'var(--c-red)';
        }
      }
    });
  }

  /* --- FAQ toggle --- */
  function initFAQ() {
    const faqList = document.getElementById('faq-list');
    if (!faqList) return;

    faqList.addEventListener('click', function(e) {
      const item = e.target.closest('.faq-item');
      if (item) item.classList.toggle('open');
    });
  }

  /* --- Billing integration --- */
  /* --- Apply gated pricing (hide real prices when billing is restricted) --- */

  // Capture original pricing card state at init for safe restoration
  var _originalCardState = {};
  document.addEventListener('DOMContentLoaded', function() {
    var cards = document.querySelectorAll('.pricing-card[data-tier]');
    cards.forEach(function(card) {
      var tier = card.getAttribute('data-tier');
      var priceEl = card.querySelector('.tier-price');
      var cta = card.querySelector('.pricing-cta');
      _originalCardState[tier] = {
        priceNode: priceEl ? priceEl.cloneNode(true) : null,
        ctaText: cta ? cta.textContent : '',
        ctaHref: cta ? cta.getAttribute('href') : null,
        ctaOnclick: cta ? cta.getAttribute('onclick') : null
      };
    });
  });

  function applyGatedPricing(gated, priceLabels) {
    var cards = document.querySelectorAll('.pricing-card[data-tier]');
    var subtitle = document.getElementById('pricing-subtitle');

    cards.forEach(function(card) {
      var tier = card.getAttribute('data-tier');
      var priceEl = card.querySelector('.tier-price');
      if (!priceEl) return;

      if (gated && priceLabels && priceLabels[tier]) {
        priceEl.textContent = priceLabels[tier];
      } else {
        // Restore original price DOM from captured clone (avoids innerHTML)
        var orig = _originalCardState[tier];
        if (orig && orig.priceNode) {
          var restored = orig.priceNode.cloneNode(true);
          priceEl.parentNode.replaceChild(restored, priceEl);
        }
      }
    });

    // Swap "Get Pro" checkout button with "Express Interest" when gated
    var proBtn = document.getElementById('btn-upgrade-pro');
    if (proBtn && gated) {
      proBtn.textContent = 'Express Interest';
      proBtn.onclick = function() { window.treesightBilling.expressInterest(); };
    } else if (proBtn && !gated) {
      proBtn.textContent = 'Get Pro';
      proBtn.disabled = false;
      proBtn.style.opacity = '';
      proBtn.onclick = function() { window.treesightBilling.checkout(); };
    }

    // Update subtitle
    if (subtitle && gated) {
      subtitle.textContent = 'Start free, express interest to unlock paid tiers. All plans include Sentinel-2 and NAIP satellite imagery, weather correlation, and NDVI change detection.';
    }

    // Swap paid tier CTAs to "Express Interest" when gated, restore when ungated
    cards.forEach(function(card) {
      var tier = card.getAttribute('data-tier');
      if (tier === 'free' || tier === 'enterprise') return;
      var cta = card.querySelector('.pricing-cta');
      if (!cta || cta.id === 'btn-upgrade-pro') return;

      if (gated) {
        cta.textContent = 'Express Interest';
        cta.href = '#early-access';
      } else {
        var orig = _originalCardState[tier];
        if (orig) {
          cta.textContent = orig.ctaText;
          if (orig.ctaHref) cta.href = orig.ctaHref;
        }
      }
    });
  }

  window.treesightBilling = {
    checkout: async function() {
      if (!currentAccount && authEnabled()) { login(); return; }
      try {
        const res = await apiFetch('/api/billing/checkout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tier: 'pro' })
        });
        if (!res || !res.ok) {
          const err = res ? await res.json().catch(function(){return {};}) : {};
          alert(err.error || 'Could not connect to billing. Please try again.');
          return;
        }
        const data = await res.json();
        if (data.checkout_url) { window.location.href = data.checkout_url; }
      } catch(e) {
        console.error('Checkout error:', e);
        alert('Could not connect to billing. Please try again later.');
      }
    },

    portal: async function() {
      if (!currentAccount && authEnabled()) { login(); return; }
      try {
        const res = await apiFetch('/api/billing/portal', { method: 'POST' });
        if (!res || !res.ok) {
          const err = res ? await res.json().catch(function(){return {};}) : {};
          alert(err.error || 'Could not open billing portal. Please try again.');
          return;
        }
        const data = await res.json();
        if (data.portal_url) { window.location.href = data.portal_url; }
      } catch(e) {
        console.error('Portal error:', e);
        alert('Could not connect to billing. Please try again later.');
      }
    },

    expressInterest: function() {
      // Scroll to the early-access / contact form section
      var section = document.getElementById('early-access');
      if (section) {
        section.scrollIntoView({ behavior: 'smooth' });
        var emailInput = document.getElementById('ea-email');
        if (emailInput) setTimeout(function() { emailInput.focus(); }, 400);
      }
    },

    loadStatus: async function() {
      if (!currentAccount || !authEnabled()) {
        // Not signed in — show gated pricing by default
        applyGatedPricing(true, { free: 'Free', starter: '$', pro: '$$', team: '$$$', enterprise: 'Price on Enquiry' });
        return;
      }
      try {
        const res = await apiFetch('/api/billing/status');
        if (!res || !res.ok) return;
        const data = await res.json();

        // Apply gated pricing if billing is restricted for this user
        if (data.billing_gated) {
          applyGatedPricing(true, data.price_labels || {});
        } else {
          applyGatedPricing(false, null);
        }

        const proBtn = document.getElementById('btn-upgrade-pro');
        const manageLink = document.getElementById('manage-billing-link');

        if (!data.billing_gated && data.tier === 'pro' && data.status === 'active') {
          if (proBtn) { proBtn.textContent = 'Current Plan'; proBtn.disabled = true; proBtn.style.opacity = '0.6'; }
          if (manageLink) {
            manageLink.style.display = 'inline';
            manageLink.onclick = function(e) { e.preventDefault(); window.treesightBilling.portal(); };
          }
        } else if (!data.billing_gated && data.status === 'past_due' && proBtn) {
          proBtn.textContent = 'Payment Issue — Update';
          proBtn.onclick = function() { window.treesightBilling.portal(); };
        }
      } catch(e) {
        console.debug('Billing status check skipped:', e);
      }
    }
  };

  /* --- Auth event listeners --- */
  document.addEventListener('DOMContentLoaded', function() {
    const loginBtn = document.getElementById('auth-login-btn');
    const logoutBtn = document.getElementById('auth-logout-btn');

    if (loginBtn) loginBtn.addEventListener('click', login);
    if (logoutBtn) logoutBtn.addEventListener('click', logout);

    initEarlyAccessForm();
    initFAQ();

    // Apply gated pricing on load (will be overwritten by loadStatus if signed in)
    applyGatedPricing(true, { free: 'Free', starter: '$', pro: '$$', team: '$$$', enterprise: 'Price on Enquiry' });
  });

  /* Handle billing return query params */
  document.addEventListener('DOMContentLoaded', function() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('billing') === 'success') {
      setTimeout(function() { alert('Welcome to Pro! Your subscription is now active.'); }, 500);
      history.replaceState(null, '', window.location.pathname);
    } else if (params.get('billing') === 'cancel') {
      history.replaceState(null, '', window.location.pathname);
    }
  });

  /* Initialization */
  initAuth();
  discoverApiBase();
})();
