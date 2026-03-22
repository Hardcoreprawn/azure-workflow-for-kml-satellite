# TreeSight Website

Minimal marketing landing page for TreeSight. Deployed to Azure Static Web Apps.

## Structure

```text
website/
├── index.html                 # Main landing page (all-inline CSS/JS)
├── kml-guide.html             # KML creation guide
├── terms.html                 # Terms of service
├── privacy.html               # Privacy policy
└── staticwebapp.config.json   # Azure Static Web Apps configuration
```

## Features

- **Hero section** with value proposition
- **Problem/Solution** sections addressing key pain points
- **Live demo section** with pipeline status badge (fetches from `/api/readiness`)
- **How it works** timeline
- **FAQ** addressing common questions
- **Early access form** (placeholder; wired in #154)
- **Fully responsive** design (mobile, tablet, desktop)
- **Accessibility** semantics included

## Local Development

No build step required. Serve locally with any HTTP server:

```bash
# Python 3
cd website && python -m http.server 8000

# Node.js
cd website && npx http-server

# Or use VS Code Live Server extension
```

Then open `http://localhost:8000` in your browser.

## Deployment to Azure Static Web Apps

### Prerequisites

- Azure subscription
- Azure CLI (`az` command)
- GitHub account with repository access

### Setup

1. **Create Static Web Apps resource** (via Azure Portal or CLI):

   ```bash
   az staticwebapp create \
     --name treesight-website \
     --resource-group <rg-name> \
     --source https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite \
     --branch main \
     --app-location website \
     --output-location "" \
     --api-location "../function_app" \
     --app-build-command "" \
     --api-build-command ""
   ```

2. **GitHub Actions workflow** will be auto-generated. Review and merge the PR.

3. **Configure custom domain** (optional):

   ```bash
   az staticwebapp custom-domain \
     --name treesight-website \
     --domain-name <your-domain.com> \
     --resource-group <rg-name>
   ```

4. **Verify deployment** at `https://treesight-website.azurestaticapps.net`

## API Proxying

The `staticwebapp.config.json` file:

- Routes `/api/*` requests to the backend Azure Functions API
- Rewrites 404s to `index.html` (SPA behavior)
- Sets security headers (CSP, X-Frame-Options, etc.)

### Linking to Backend

The website expects:

- **GET `/api/readiness`** — Returns status of the pipeline (used by status badge)
- **POST `/api/contact-form`** — Form submission handler (implemented in #154)

## Development Checklist (for #153)

- [x] Landing page HTML structure complete
- [x] Responsive CSS styling (mobile, tablet, desktop)
- [x] Status badge fetches from `/api/readiness`
- [x] Demo form with sample KML loader
- [x] Early access form (placeholder, no POST yet)
- [x] Navigation, hero, problem/solution, timeline, FAQ
- [x] Semantic HTML (accessibility-ready)
- [x] Security headers configured in `staticwebapp.config.json`
- [x] No build step required (pure static)

## Next Steps (Subsequent Issues)

- **#154**: Implement `/api/contact-form` handler (Azure Function, store to Azure Storage Table or email)
- **#155**: Deploy website to Azure Static Web Apps (GitHub Actions workflow)
- **#156**: Add E2E smoke tests (POST to form, verify health endpoint)

## Styling Notes

- **Color palette**: Forest green (#1a5f3d, #2d7a4f) + white/light backgrounds
- **Typography**: System fonts (San Francisco, Segoe UI, Roboto)
- **Layout**: CSS Grid + Flexbox, mobile-first responsive design
- **Animations**: Smooth transitions, status spinner, hover effects

## Troubleshooting

**Status badge shows "Offline":**

- Ensure Azure Function `/api/readiness` endpoint is deployed and accessible
- Check CORS configuration on the backend
- Verify network/firewall rules

**Forms don't submit:**

- In development, forms log to console (no backend yet)
- In production (#154), they'll POST to `/api/contact-form`

**Mobile layout broken:**

- Check viewport meta tag in `<head>`
- Test in browser DevTools (F12 → toggle device toolbar)

## Security

- **No secrets** in HTML/CSS/JS — all static content is public
- **CORS**: Configured for local testing; adapt as needed in deployment
- **Headers**: CSP, X-Frame-Options, X-XSS-Protection set in `staticwebapp.config.json`
- **User data**: Contact forms validated client-side before submission

---

**Note:** This is Phase 1 of the roadmap. Website is minimal but complete. Additional marketing features (blog, case studies, advanced analytics) defer to future phases.
