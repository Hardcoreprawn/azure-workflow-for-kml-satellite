/**
 * TreeSight Website - App Logic
 * Handles status fetching, form interactions, and demo UX
 */

const API_ENDPOINT = '/api/readiness';
const STATUS_CHECK_INTERVAL = 30000; // 30 seconds

/**
 * Fetch pipeline status from /api/readiness
 */
async function fetchPipelineStatus() {
    try {
        const response = await fetch(API_ENDPOINT);
        if (response.ok) {
            const data = await response.json();
            return {
                online: true,
                status: 'Online',
                message: data.message || 'Pipeline is ready'
            };
        } else {
            return {
                online: false,
                status: 'Offline',
                message: 'Pipeline is not responding'
            };
        }
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
    text.textContent = `🟢 ${status.status}` || (status.online ? '🟢 Online' : '🔴 Offline');
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
        // In #154, this will POST to /api/contact-form
        // For now, just acknowledge
        console.log('Interest form data:', data);

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
        messageEl.textContent = '❌ Something went wrong. Please try again.';
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
    const note = form.querySelector('.form-note');

    const kmlContent = kmlTextarea.value.trim();

    if (!kmlContent) {
        note.textContent = '❌ Please provide KML content or load a sample.';
        note.style.color = '#ef4444';
        return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting...';

    try {
        // In Phase 4, this will POST to the actual pipeline endpoint
        console.log('Demo submit:', kmlContent);

        note.textContent = '✅ Your KML has been submitted for processing. You\'ll receive results via email.';
        note.style.color = '#22c55e';

        // Show note for 5 seconds
        setTimeout(() => {
            note.textContent = '';
            submitBtn.disabled = false;
            submitBtn.textContent = 'Submit for Processing';
        }, 5000);

    } catch (error) {
        console.error('Demo submit error:', error);
        note.textContent = '❌ Submission failed. Please try again.';
        note.style.color = '#ef4444';
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
