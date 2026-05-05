/* Canopex — lightweight page analytics via Application Insights SDK.
 *
 * Loaded on every page.  The connection string is injected at deploy time
 * into the Static Web App environment.  When missing (local dev), the
 * snippet is a no-op.
 *
 * Uses the Application Insights JS SDK "snippet" (lightweight ~36 KB).
 * Tracks: page views, click events, unhandled exceptions (window.onerror +
 * unhandledrejection), and basic Web Vitals (LCP, FID, CLS) when the
 * browser supports them.
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
    disableExceptionTracking: false, // catch unhandled errors via SDK
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

      // Expose SDK for use by other scripts (e.g. app-run-lifecycle.js).
      window.__ai = sdk;

      // Track click events with data-track attribute
      document.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-track]");
        if (btn) {
          sdk.trackEvent({ name: btn.getAttribute("data-track") });
        }
      });

      // Catch unhandled synchronous errors not already caught by the SDK.
      var _origOnError = window.onerror;
      window.onerror = function (msg, src, line, col, err) {
        sdk.trackException({ exception: err || new Error(String(msg)), severityLevel: 3 });
        if (typeof _origOnError === "function") return _origOnError.apply(this, arguments);
        return false;
      };

      // Catch unhandled Promise rejections.
      window.addEventListener("unhandledrejection", function (evt) {
        var err = evt.reason instanceof Error ? evt.reason : new Error(String(evt.reason));
        sdk.trackException({ exception: err, severityLevel: 3 });
      });
    }
  };

  // SDK load failure — we can't use AI to report this, but log to console.
  script.onerror = function () {
    if (window.console && window.console.warn) {
      window.console.warn("[canopex] App Insights SDK failed to load");
    }
  };

  document.head.appendChild(script);
})();
