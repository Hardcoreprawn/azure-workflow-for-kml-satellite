# Security Assessment: canopex.hrdcrprwn.com

## CRITICAL / HIGH

**1. API Backend Completely Down (500 on all `/api/*` routes)**
Every API endpoint returns `500 Internal Server Error` with body `"Backend call failure"` and **zero security headers** (no CSP, no HSTS, no X-Frame-Options). The Azure Container Apps backend is unreachable from the SWA proxy. This means:

- No user can actually use the product
- If/when it comes back up, **API responses won't inherit the SWA's security headers** — you need to ensure the Function App itself also sets security headers on responses.

**2. Overly Broad CSP Wildcards Leak Attack Surface**
Your `connect-src` allows:

- `https://*.azurecontainerapps.io` — any Container App on the entire Azure platform, not just yours
- `https://*.blob.core.windows.net` — any Azure Storage account globally

An attacker who controls *any* Azure Container App or Blob Storage account can exfiltrate data from your frontend via XSS or a compromised dependency. **Pin these to your specific hostnames.**

**3. Unauthenticated API Endpoints**
Per your README's "Endpoint Access Contract", these endpoints are public/anonymous:

- `POST /api/eudr-assessment`
- `POST /api/convert-coordinates`
- `POST /api/export`
- `POST /api/create-checkout-session`
- `POST /api/stripe-webhook`
- `GET /api/orchestrator/{instance_id}`

The orchestrator endpoint is particularly concerning — if instance IDs are enumerable or low-entropy, any visitor can query pipeline results for any tenant. Verify that IDs are cryptographically random UUIDs.

**4. Old Domain May Be Vulnerable to Takeover**
Your GitHub repo's "About" section still links to `treesight.jablab.dev` (pre-rebrand domain). If that DNS record still points to an Azure SWA or any service you've since deprovisioned, an attacker can claim it and serve malicious content under your old brand. **Verify or decommission the old DNS entry.**

---

## MEDIUM

**5. Missing `robots.txt`, `sitemap.xml`, and `security.txt`**
All three return `200 OK` with the SPA's `index.html` (22,961 bytes of HTML). This is because SWA's fallback routing catches all unknown paths:

- Search engines receive no crawling guidance
- Security researchers have no `/.well-known/security.txt` contact channel (ironic given you have a `SECURITY.md` in the repo)
- Add these as actual static files in your `website/` directory, or configure navigation fallback exclusions in `staticwebapp.config.json`

**6. Excessive Information Disclosure via Public GitHub Repo**
Your repo exposes:

- Full API route table with auth/anon annotations
- Infrastructure naming conventions (`evgs-kml-upload`, `evgt-<baseName>`, container naming like `acme-input`)
- Deployment workflow secrets pipeline (OIDC, Event Grid system keys)
- Operations runbook with recovery procedures
- Durable Task hub name: `TreeSightHub`
- Architecture diagrams showing every component

While the repo is intentionally open-source (Apache 2.0), the **operations runbook and endpoint access contract** give attackers a detailed map. Consider moving operational docs to a private wiki.

**7. CSP Allows `'unsafe-inline'` for Styles**

```text
style-src 'self' 'unsafe-inline' https://unpkg.com
```

This enables CSS injection attacks. If you can refactor to use nonces or hashes for inline styles, remove `'unsafe-inline'`.

**8. Contact/Early Access Form — No Visible Anti-Abuse**
The "Request Early Access" form submits to what appears to be a backend endpoint with no CAPTCHA, rate limiting, or honeypot visible in the HTML. This can be abused for:

- Spam flooding your email/database
- Phishing (submitting victim emails to appear as if they opted in)

---

## LOW / INFORMATIONAL

**9. Deprecated `X-XSS-Protection` Header**

```text
X-XSS-Protection: 1; mode=block
```

This header is [deprecated and removed from modern browsers](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-XSS-Protection). In some edge cases it can introduce vulnerabilities. Remove it — your CSP provides the real protection.

**10. SPA Catch-All Returns 200 for Everything**
Requests to `/.env`, `/.git/config`, `/wp-admin/`, `/admin/` all return `200 OK` with HTML (no actual sensitive data leaks). However:

- Security scanners may report false positives
- The 200 status makes it harder to distinguish real pages from non-existent ones
- Consider configuring SWA to return 404 for common probe paths

**11. No `X-Robots-Tag` Header**
Combined with the missing `robots.txt`, crawlers can freely index all pages including `/app/`, docs, and error states.

**12. Short Cache TTL**

```text
Cache-Control: public, must-revalidate, max-age=30
```

30 seconds is very aggressive revalidation for a static site. Not a security issue per se, but it increases origin load.

---

### What's Done Well

- **HSTS** enabled with `includeSubDomains` and a 1-year max-age
- **X-Frame-Options: DENY** prevents clickjacking
- **X-Content-Type-Options: nosniff** prevents MIME sniffing
- **Referrer-Policy: strict-origin-when-cross-origin** — good default
- **Permissions-Policy** disables camera, microphone, geolocation
- **No server version header leaked** — Azure SWA doesn't expose `Server:` or `X-Powered-By:`
- **detect-secrets baseline is clean** (empty `results: {}`)
- **Strong CI security tooling** — Semgrep, Trivy, CodeQL, pip-audit, detect-secrets
- **Valet tokens** for demo artifact access (replay-limited, short-lived)
- **No cookies** for tracking/analytics
- **SWA built-in auth** avoids the complexity of self-managed OAuth

---

### Recommended Priority Actions

| Priority | Action |
|---|---|
| **P0** | Fix the API backend — all `/api/*` returning 500 |
| **P0** | Narrow CSP wildcards to your actual hostnames |
| **P1** | Verify `treesight.jablab.dev` DNS is decommissioned or redirects |
| **P1** | Verify orchestrator instance IDs are high-entropy UUIDs |
| **P1** | Add real `robots.txt`, `security.txt`, and `sitemap.xml` static files |
| **P2** | Add rate limiting / CAPTCHA to the contact form |
| **P2** | Remove `'unsafe-inline'` from `style-src` |
| **P2** | Remove deprecated `X-XSS-Protection` header |
| **P3** | Consider making operational docs private |
