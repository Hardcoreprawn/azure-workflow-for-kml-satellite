/* Canopex — lightweight page analytics via Application Insights SDK.
 *
 * Loaded on every page.  The connection string is injected at deploy time
 * into the Static Web App environment.  When missing (local dev), the
 * snippet is a no-op.
 *
 * Uses the Application Insights JS SDK "snippet" (lightweight ~36 KB).
 * Tracks: page views, click events, unhandled exceptions, and basic
 * Web Vitals (LCP, FID, CLS) when the browser supports them.
 */
(function () {
  "use strict";

  // Connection string is embedded by the deploy pipeline into a meta tag.
  // <meta name="ai-connection-string" content="InstrumentationKey=...">
  var meta = document.querySelector('meta[name="ai-connection-string"]');
  var connStr = meta ? meta.getAttribute("content") : "";
  if (!connStr) return; // no-op in local dev

  // Minimal Application Insights config — no cookies, no user tracking.
  var cfg = {
    connectionString: connStr,
    disableCookiesUsage: true,       // GDPR-friendly: no cookies
    enableAutoRouteTracking: true,   // SPA hash-change tracking
    disableAjaxTracking: false,      // track API calls
    maxBatchInterval: 15000,         // batch telemetry every 15s
    disableExceptionTracking: false, // catch unhandled errors
  };

  // Load the SDK asynchronously from the CDN
  var sdkUrl = "https://js.monitor.azure.com/scripts/b/ai.3.gbl.min.js";
  var script = document.createElement("script");
  script.src = sdkUrl;
  script.crossOrigin = "anonymous";
  script.onload = function () {
    if (window.Microsoft && window.Microsoft.ApplicationInsights) {
      var sdk = new window.Microsoft.ApplicationInsights.ApplicationInsights({ config: cfg });
      sdk.loadAppInsights();
      sdk.trackPageView();

      // Track demo funnel events
      document.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-track]");
        if (btn) {
          sdk.trackEvent({ name: btn.getAttribute("data-track") });
        }
      });
    }
  };
  document.head.appendChild(script);
})();
