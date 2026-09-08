'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../..');
const HTML = fs.readFileSync(path.join(ROOT, 'website/account/invite/index.html'), 'utf8');
const AUTH = fs.readFileSync(path.join(ROOT, 'website/js/canopex-auth.js'), 'utf8');
const INVITE_SCRIPT = HTML.match(/<script>\s*([\s\S]*?)<\/script>/)[1];

function loadInvite(accounts, initialize = () => Promise.resolve()) {
  const elements = new Map();
  const listeners = new Map();
  const requests = [];
  const errors = [];
  let tokenProvider;
  const document = {
    readyState: 'loading',
    addEventListener: (event, handler) => listeners.set(event, handler),
    getElementById(id) {
      if (!elements.has(id)) {
        elements.set(id, {
          style: {}, textContent: '',
          addEventListener: (event, handler) => listeners.set(`${id}:${event}`, handler),
        });
      }
      return elements.get(id);
    },
  };
  document.getElementById('canopex-ciam-config').textContent = JSON.stringify({
    clientId: 'test-client', authority: 'https://test.ciamlogin.com', apiAudience: 'test-api',
  });
  const token = `header.${Buffer.from(JSON.stringify({ email: 'member@example.test', org_id: 'org-1' })).toString('base64url')}.signature`;
  const window = {
    location: { search: `?token=${token}`, pathname: '/account/invite/', origin: 'https://example.test' },
    msal: {
      PublicClientApplication: class {
        initialize() { return initialize(); }
        handleRedirectPromise() { return Promise.resolve(null); }
        getAllAccounts() { return accounts; }
        acquireTokenSilent() { return Promise.resolve({ accessToken: 'test-access-token' }); }
      },
    },
    CanopexApiClient: {
      createClient: () => ({
        setGetToken: (provider) => { tokenProvider = provider; },
        async fetch(url, options) {
          requests.push({ url, options, token: await tokenProvider() });
          return { status: 200, json: async () => ({ org: { org_id: 'org-1', name: 'Test organization' } }) };
        },
      }),
    },
  };
  const sandbox = vm.createContext({
    window, document, URLSearchParams,
    console: { error: (...args) => errors.push(args), warn: (...args) => errors.push(args), debug: () => {} },
    atob: (value) => Buffer.from(value, 'base64').toString('binary'),
    setTimeout: () => {},
  });
  vm.runInContext(AUTH, sandbox);
  vm.runInContext(INVITE_SCRIPT, sandbox);
  return { document, listeners, requests, errors };
}

test('invite discovers an existing MSAL session before presenting acceptance controls', async () => {
  const page = loadInvite([{ name: 'Existing Member', username: 'member@example.test' }]);
  await page.listeners.get('DOMContentLoaded')();
  assert.equal(page.document.getElementById('auth-user').textContent, 'Existing Member');
  assert.equal(page.document.getElementById('login-btn').style.display, 'none');
  assert.equal(page.document.getElementById('logout-btn').style.display, 'inline-block');
  page.listeners.get('accept-btn:click')();
  await new Promise(setImmediate);
  assert.ok(page.requests.some((request) => request.options.method === 'POST' && request.token === 'test-access-token'));
  assert.equal(page.document.getElementById('success-state').style.display, 'block');
  assert.equal(page.errors.length, 0);
});

test('invite waits for asynchronous MSAL readiness before enabling acceptance', async () => {
  let resolveReady;
  const ready = new Promise((resolve) => { resolveReady = resolve; });
  const page = loadInvite([{ name: 'Existing Member' }], () => ready);
  const initialization = page.listeners.get('DOMContentLoaded')();
  assert.equal(page.listeners.has('accept-btn:click'), false);
  assert.equal(page.requests.length, 0);
  resolveReady();
  await initialization;
  assert.equal(page.document.getElementById('auth-user').textContent, 'Existing Member');
  assert.equal(page.listeners.has('accept-btn:click'), true);
});

test('invite shows sign-in controls when MSAL has no cached account', async () => {
  const page = loadInvite([]);
  await page.listeners.get('DOMContentLoaded')();
  assert.equal(page.document.getElementById('login-btn').style.display, 'inline-block');
  assert.equal(page.document.getElementById('logout-btn').style.display, 'none');
  assert.equal(page.document.getElementById('accept-btn').textContent, 'Sign In to Accept');
  assert.equal(page.requests.length, 0);
  assert.equal(page.errors.length, 0);
});

test('invite surfaces MSAL initialization failure without exposing acceptance', async () => {
  const page = loadInvite([], () => Promise.reject(new Error('MSAL unavailable')));
  await page.listeners.get('DOMContentLoaded')();
  assert.equal(page.document.getElementById('error-state').style.display, 'block');
  assert.match(page.document.getElementById('error-message').textContent, /Unable to initialize sign-in/);
  assert.equal(page.listeners.has('accept-btn:click'), false);
  assert.equal(page.requests.length, 0);
  assert.ok(page.errors.length > 0);
});