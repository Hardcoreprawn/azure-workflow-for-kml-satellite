(function() {
  'use strict';

  let currentAccount = null;

  function authEnabled() { return true; }

  async function initAuth() {
    try {
      const res = await fetch('/.auth/me');
      if (!res.ok) { updateAuthUI(); return; }
      const data = await res.json();
      const principal = data && data.clientPrincipal;
      if (principal && principal.userId) {
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
    if (window.canopexBilling && window.canopexBilling.loadStatus) {
      window.canopexBilling.loadStatus();
    }
  }

  function login() {
    window.location.href = '/.auth/login/aad';
  }

  function logout() {
    window.location.href = '/.auth/logout';
  }

  function updateAuthUI() {
    const loginBtn = document.getElementById('auth-login-btn');
    const logoutBtn = document.getElementById('auth-logout-btn');
    const userSpan = document.getElementById('auth-user');
    const dashLink = document.getElementById('auth-dashboard-link');

    if (!authEnabled()) {
      if (loginBtn) loginBtn.style.display = 'none';
      if (logoutBtn) logoutBtn.style.display = 'none';
      if (userSpan) userSpan.style.display = 'none';
      if (dashLink) dashLink.style.display = 'none';
      return;
    }

    if (currentAccount) {
      const name = currentAccount.name || currentAccount.userId || 'User';
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
    const resp = await fetch(path, opts);
    if (!resp.ok) {
      const body = await resp.json().catch(function () { return {}; });
      const msg = body.error || ('API request failed: ' + resp.status + ' ' + resp.statusText);
      const err = new Error(msg);
      err.status = resp.status;
      err.body = body;
      throw err;
    }
    return resp;
  }

  async function discoverApiBase() {
    const badge = document.getElementById('status-badge');
    if (!badge) return;

    try {
      const res = await fetch('/api/health');
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
    console.warn('Backend not reachable — SWA managed API health check failed');
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

        if (status) {
          status.textContent = 'Thanks! We\'ll be in touch.';
          status.style.color = 'var(--c-green)';
        }
      } catch (err) {
        if (status) {
          status.textContent = (err && err.message) || 'Submission failed. Please try again.';
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
  const _originalCardState = {};
  document.addEventListener('DOMContentLoaded', function() {
    const cards = document.querySelectorAll('.pricing-card[data-tier]');
    cards.forEach(function(card) {
      const tier = card.getAttribute('data-tier');
      const priceEl = card.querySelector('.tier-price');
      const cta = card.querySelector('.pricing-cta');
      _originalCardState[tier] = {
        priceNode: priceEl ? priceEl.cloneNode(true) : null,
        ctaText: cta ? cta.textContent : '',
        ctaHref: cta ? cta.getAttribute('href') : null,
        ctaOnclick: cta ? cta.getAttribute('onclick') : null
      };
    });
  });

  function applyGatedPricing(gated, priceLabels) {
    const cards = document.querySelectorAll('.pricing-card[data-tier]');
    const subtitle = document.getElementById('pricing-subtitle');

    cards.forEach(function(card) {
      const tier = card.getAttribute('data-tier');
      const priceEl = card.querySelector('.tier-price');
      if (!priceEl) return;

      if (gated && priceLabels && priceLabels[tier]) {
        priceEl.textContent = priceLabels[tier];
      } else {
        // Restore original price DOM from captured clone (avoids innerHTML)
        const orig = _originalCardState[tier];
        if (orig && orig.priceNode) {
          const restored = orig.priceNode.cloneNode(true);
          priceEl.parentNode.replaceChild(restored, priceEl);
        }
      }
    });

    // Swap "Get Pro" checkout button with "Express Interest" when gated
    const proBtn = document.getElementById('btn-upgrade-pro');
    if (proBtn && gated) {
      proBtn.textContent = 'Express Interest';
      proBtn.onclick = function() { window.canopexBilling.expressInterest(); };
    } else if (proBtn && !gated) {
      proBtn.textContent = 'Get Pro';
      proBtn.disabled = false;
      proBtn.style.opacity = '';
      proBtn.onclick = function() { window.canopexBilling.checkout(); };
    }

    // Update subtitle
    if (subtitle && gated) {
      subtitle.textContent = 'Start free, express interest to unlock paid tiers. All plans include Sentinel-2 and NAIP satellite imagery, weather correlation, and NDVI change detection.';
    }

    // Swap paid tier CTAs to "Express Interest" when gated, restore when ungated
    cards.forEach(function(card) {
      const tier = card.getAttribute('data-tier');
      if (tier === 'free' || tier === 'enterprise') return;
      const cta = card.querySelector('.pricing-cta');
      if (!cta || cta.id === 'btn-upgrade-pro') return;

      if (gated) {
        cta.textContent = 'Express Interest';
        cta.href = '#early-access';
      } else {
        const orig = _originalCardState[tier];
        if (orig) {
          cta.textContent = orig.ctaText;
          if (orig.ctaHref) cta.href = orig.ctaHref;
        }
      }
    });
  }

  window.canopexBilling = {
    checkout: async function() {
      if (!currentAccount && authEnabled()) { login(); return; }
      try {
        const res = await apiFetch('/api/billing/checkout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tier: 'pro' })
        });
        const data = await res.json();
        if (data.checkout_url) { window.location.href = data.checkout_url; }
      } catch(e) {
        console.error('Checkout error:', e);
        alert((e && e.message) || 'Could not connect to billing. Please try again later.');
      }
    },

    portal: async function() {
      if (!currentAccount && authEnabled()) { login(); return; }
      try {
        const res = await apiFetch('/api/billing/portal', { method: 'POST' });
        const data = await res.json();
        if (data.portal_url) { window.location.href = data.portal_url; }
      } catch(e) {
        console.error('Portal error:', e);
        alert((e && e.message) || 'Could not connect to billing. Please try again later.');
      }
    },

    expressInterest: function() {
      // Scroll to the early-access / contact form section
      const section = document.getElementById('early-access');
      if (section) {
        section.scrollIntoView({ behavior: 'smooth' });
        const emailInput = document.getElementById('ea-email');
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
            manageLink.onclick = function(e) { e.preventDefault(); window.canopexBilling.portal(); };
          }
        } else if (!data.billing_gated && data.status === 'past_due' && proBtn) {
          proBtn.textContent = 'Payment Issue — Update';
          proBtn.onclick = function() { window.canopexBilling.portal(); };
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
