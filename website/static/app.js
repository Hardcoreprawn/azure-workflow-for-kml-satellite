/**
 * TreeSight Website - App Logic
 * Handles status fetching, form interactions, and demo UX
 */

const API_ENDPOINT = '/api/readiness';
const CONTACT_FORM_ENDPOINT = '/api/contact-form';
const DEPLOYMENT_FALLBACK_ORIGIN = '__FUNCTION_APP_ORIGIN__';
const DEFAULT_FALLBACK_ORIGIN = 'https://func-kmlsat-dev.azurewebsites.net';
const FALLBACK_API_ORIGIN = DEPLOYMENT_FALLBACK_ORIGIN.startsWith('__')
    ? DEFAULT_FALLBACK_ORIGIN
    : DEPLOYMENT_FALLBACK_ORIGIN;
const READINESS_FALLBACK_ENDPOINT = `${FALLBACK_API_ORIGIN}${API_ENDPOINT}`;
const CONTACT_FORM_FALLBACK_ENDPOINT = `${FALLBACK_API_ORIGIN}${CONTACT_FORM_ENDPOINT}`;
const STATUS_CHECK_INTERVAL = 30000; // 30 seconds

/**
 * Fetch pipeline status from /api/readiness
 */
async function fetchJson(endpoint, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set('Accept', 'application/json');

    const response = await fetch(endpoint, {
        ...options,
        headers,
    });
    const contentType = response.headers.get('content-type') || '';

    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }

    if (!contentType.toLowerCase().includes('application/json')) {
        throw new Error(`Expected JSON but received ${contentType || 'unknown content type'}`);
    }

    return response.json();
}

async function fetchPipelineStatus() {
    let lastError = null;

    for (const endpoint of [API_ENDPOINT, READINESS_FALLBACK_ENDPOINT]) {
        try {
            const data = await fetchJson(endpoint);
            const ready = data.status === 'ready';

            return {
                online: ready,
                status: ready ? 'Online' : 'Offline',
                message: data.message || (ready ? 'Pipeline is ready' : 'Pipeline is not ready')
            };
        } catch (error) {
            lastError = error;
        }
    }

    try {
        throw lastError || new Error('Readiness check failed');
    } catch (error) {
        console.warn('Status check failed:', error);
        return {
            online: false,
            status: 'Offline',
            message: 'Unable to reach pipeline'
        };
    }
}

/**
 * Update status badge in hero section
 */
function updateStatusBadge(status) {
    const badge = document.getElementById('status-badge');
    const text = badge.querySelector('.status-text');

    badge.classList.remove('online', 'offline');
    badge.classList.add(status.online ? 'online' : 'offline');
    text.textContent = status.online ? '🟢 Online' : '🔴 Offline';
}

/**
 * Update detailed status in demo section
 */
function updateStatusDetail(status) {
    const detail = document.getElementById('status-detail');
    if (!detail) return;

    detail.classList.remove('online', 'offline');
    detail.classList.add(status.online ? 'online' : 'offline');

    const statusText = status.online
        ? '✅ Pipeline is live and ready to process KML files'
        : '⚠️ Pipeline is currently offline. Check back soon.';

    detail.innerHTML = `<p><strong>${statusText}</strong></p>`;
}

/**
 * Load sample KML for demo
 */
function loadSampleKML() {
    const sampleKML = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Sample Orchard - Utah</name>
    <Placemark>
      <name>Sample AOI</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              -111.8915,40.7608,0
              -111.8905,40.7608,0
              -111.8905,40.7598,0
              -111.8915,40.7598,0
              -111.8915,40.7608,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>`;

    const textarea = document.getElementById('demo-kml');
    if (textarea) {
        textarea.value = sampleKML;
        textarea.focus();
    }
}

/**
 * Handle interest form submission
 */
async function handleInterestFormSubmit(event) {
    event.preventDefault();

    const form = document.getElementById('interest-form');
    const submitBtn = form.querySelector('button[type="submit"]');
    const messageEl = document.getElementById('form-message');

    const formData = new FormData(form);
    const data = Object.fromEntries(formData);

    // Validate
    if (!data.email || !data.organization || !data.use_case) {
        messageEl.textContent = '❌ Please fill in all required fields.';
        messageEl.style.color = '#ef4444';
        return;
    }

    // Disable button during submission
    submitBtn.disabled = true;
    submitBtn.textContent = 'Sending...';
    messageEl.textContent = '';

    try {
        const payload = {
            email: String(data.email || '').trim(),
            organization: String(data.organization || '').trim(),
            use_case: String(data.use_case || '').trim(),
            aoi_size: String(data.aoi_size || '').trim(),
        };

        let response;
        try {
            response = await fetch(CONTACT_FORM_ENDPOINT, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });
        } catch (relativeError) {
            console.warn('Relative API endpoint failed, trying fallback endpoint:', relativeError);
            response = await fetch(CONTACT_FORM_FALLBACK_ENDPOINT, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });
        }

        if (!response.ok) {
            let errorMessage = 'Something went wrong. Please try again.';
            try {
                const errorPayload = await response.json();
                if (errorPayload && errorPayload.error) {
                    errorMessage = String(errorPayload.error);
                }
            } catch (_ignored) {
                // Keep default message if response body is not JSON.
            }
            throw new Error(errorMessage);
        }

        messageEl.textContent = '✅ Thank you! We\'ll be in touch within 24 hours. Check your email.';
        messageEl.style.color = '#22c55e';

        // Reset form
        setTimeout(() => {
            form.reset();
            messageEl.textContent = '';
            submitBtn.disabled = false;
            submitBtn.textContent = 'Get Early Access';
        }, 3000);

    } catch (error) {
        console.error('Form submission error:', error);
        messageEl.textContent = `❌ ${error.message || 'Something went wrong. Please try again.'}`;
        messageEl.style.color = '#ef4444';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Get Early Access';
    }
}

/**
 * Handle demo form submission
 */
async function handleDemoFormSubmit(event) {
    event.preventDefault();

    const form = document.getElementById('demo-form');
    const submitBtn = form.querySelector('button[type="submit"]');
    const kmlTextarea = document.getElementById('demo-kml');
    const note = document.getElementById('demo-message');

    const kmlContent = kmlTextarea.value.trim();

    if (!kmlContent) {
        if (note) {
            note.textContent = '❌ Please provide KML content or load a sample.';
            note.style.color = '#ef4444';
        }
        return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting...';

    try {
        // In Phase 4, this will POST to the actual pipeline endpoint
        console.log('Demo submit:', kmlContent);

        if (note) {
            note.textContent = '✅ Your KML has been submitted for processing. You\'ll receive results via email.';
            note.style.color = '#22c55e';
        }

        // Show note for 5 seconds
        setTimeout(() => {
            if (note) {
                note.textContent = '';
            }
            submitBtn.disabled = false;
            submitBtn.textContent = 'Submit for Processing';
        }, 5000);

    } catch (error) {
        console.error('Demo submit error:', error);
        if (note) {
            note.textContent = '❌ Submission failed. Please try again.';
            note.style.color = '#ef4444';
        }
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit for Processing';
    }
}

/**
 * Initialize page
 */
function init() {
    // Attach form event listeners
    const interestForm = document.getElementById('interest-form');
    if (interestForm) {
        interestForm.addEventListener('submit', handleInterestFormSubmit);
    }

    const demoForm = document.getElementById('demo-form');
    if (demoForm) {
        demoForm.addEventListener('submit', handleDemoFormSubmit);
    }

    const loadSampleBtn = document.getElementById('load-sample');
    if (loadSampleBtn) {
        loadSampleBtn.addEventListener('click', loadSampleKML);
    }

    // Fetch and display status
    async function updateStatus() {
        const status = await fetchPipelineStatus();
        updateStatusBadge(status);
        updateStatusDetail(status);
    }

    // Initial status check
    updateStatus();

    // Periodic status checks
    setInterval(updateStatus, STATUS_CHECK_INTERVAL);
}

// Run on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
