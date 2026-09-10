'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');

function loadModal({ getToken = async () => 'test-access-token', status = 200 } = {}) {
  const requests = [];
  const alerts = [];
  const errors = [];
  const handlers = {};
  const button = {
    disabled: false,
    textContent: 'Subscribe Now',
    addEventListener: (event, handler) => { handlers[event] = handler; }
  };
  const window = {
    location: { pathname: '/eudr/', hostname: 'localhost', search: '', href: '/eudr/' },
    CanopexAuth: { getToken }
  };
  const context = vm.createContext({
    window,
    document: {
      getElementById: id => id === 'eudr-subscribe-btn' ? button : null,
      addEventListener: (event, handler) => {
        if (event === 'DOMContentLoaded') handler();
      }
    },
    localStorage: { getItem: () => null, setItem: () => {} },
    console: { error: (...args) => errors.push(args), warn: (...args) => errors.push(args) },
    alert: message => alerts.push(message),
    URL,
    AbortController,
    setTimeout,
    clearTimeout,
    fetch: async (url, options) => {
      if (url === '/api-config.json') return { ok: true, json: async () => ({}) };
      if (url === '/api/health' || url === '/api/internal-health') return { ok: true };
      assert.equal(url, '/api/eudr/subscribe');
      requests.push({ url, options });
      return {
        ok: status === 200,
        status,
        json: async () => status === 200
          ? { checkout_url: 'https://checkout.stripe.test/session' }
          : { error: 'Owner permission required' }
      };
    }
  });
  for (const filename of ['canopex-api-client.js', 'app-eudr-subscribe-modal.js']) {
    vm.runInContext(fs.readFileSync(path.join(root, 'website/js', filename), 'utf8'), context, { filename });
  }
  return { requests, alerts, errors, button, window, subscribe: () => handlers.click() };
}

test('signed-in checkout sends bearer token through the real API client', async () => {
  const modal = loadModal();
  await modal.subscribe();
  assert.equal(modal.requests.length, 1);
  const request = modal.requests[0].options;
  assert.equal(request.method, 'POST');
  assert.equal(request.headers.Authorization, 'Bearer test-access-token');
  assert.equal(request.headers['Content-Type'], 'application/json');
  assert.equal(request.body, '{}');
  assert.equal(modal.window.location.href, 'https://checkout.stripe.test/session');
  assert.deepEqual(modal.alerts, []);
  assert.deepEqual(modal.errors, []);
  assert.equal(modal.button.disabled, false);
});

test('redirecting authentication prevents an unauthenticated checkout POST', async () => {
  const modal = loadModal({ getToken: async () => {
    throw Object.assign(new Error('Redirecting to sign in'), { authRedirectTriggered: true });
  } });
  await modal.subscribe();
  assert.equal(modal.requests.length, 0);
  assert.equal(modal.window.location.href, '/eudr/');
  assert.deepEqual(modal.alerts, ['Redirecting to sign in']);
  assert.equal(modal.button.disabled, false);
  assert.equal(modal.button.textContent, 'Subscribe Now');
});

test('owner rejection is visible and restores the subscribe button', async () => {
  const modal = loadModal({ status: 403 });
  await modal.subscribe();
  assert.equal(modal.requests.length, 1);
  assert.equal(modal.requests[0].options.headers.Authorization, 'Bearer test-access-token');
  assert.deepEqual(modal.alerts, ['Only organisation owners can subscribe.']);
  assert.equal(modal.window.location.href, '/eudr/');
  assert.equal(modal.button.disabled, false);
  assert.equal(modal.button.textContent, 'Subscribe Now');
});
