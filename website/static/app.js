/**
 * TreeSight Website - App Logic
 * Handles status fetching, form interactions, and demo UX
 */

const API_ENDPOINT = '/api/readiness';
const CONTACT_FORM_ENDPOINT = '/api/contact-form';
const DEMO_SUBMIT_ENDPOINT = '/api/demo-submit';
const DEPLOYMENT_FALLBACK_ORIGIN = '__FUNCTION_APP_ORIGIN__';
const DEFAULT_FALLBACK_ORIGIN = 'https://func-kmlsat-dev.azurewebsites.net';
const FALLBACK_API_ORIGIN = DEPLOYMENT_FALLBACK_ORIGIN.startsWith('__')
    ? DEFAULT_FALLBACK_ORIGIN
    : DEPLOYMENT_FALLBACK_ORIGIN;
const READINESS_FALLBACK_ENDPOINT = `${FALLBACK_API_ORIGIN}${API_ENDPOINT}`;
const CONTACT_FORM_FALLBACK_ENDPOINT = `${FALLBACK_API_ORIGIN}${CONTACT_FORM_ENDPOINT}`;
const DEMO_SUBMIT_FALLBACK_ENDPOINT = `${FALLBACK_API_ORIGIN}${DEMO_SUBMIT_ENDPOINT}`;
const STATUS_CHECK_INTERVAL = 30000; // 30 seconds
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const DEMO_AOI_POLYGON = [
    [40.7608, -111.8915],
    [40.7608, -111.8905],
    [40.7598, -111.8905],
    [40.7598, -111.8915],
];

const timelapseState = {
    map: null,
    baseLayer: null,
    aoiLayer: null,
    changeLayer: null,
    frames: [],
    currentIndex: 0,
    timerId: null,
};

function formatFrameDate(date) {
    return new Intl.DateTimeFormat('en-US', {
        year: 'numeric',
        month: 'short',
        day: '2-digit',
    }).format(date);
}

function generateTimelapseFrames(count = 24) {
    const frames = [];
    const now = new Date();

    for (let index = 0; index < count; index += 1) {
        const daysAgo = (count - index) * 5;
        const date = new Date(now);
        date.setDate(now.getDate() - daysAgo);

        const phase = index / 3;
        const vigor = 0.52 + (Math.sin(phase) * 0.19) + (Math.cos(phase / 2) * 0.04);
        const cloud = Math.max(2, Math.min(26, Math.round(11 + (Math.cos(phase) * 9))));
        const offset = 0.00008 * Math.sin(phase * 1.4);
        const widthAdjust = 0.00006 * Math.cos(phase * 0.7);

        const stressPolygon = [
            [40.76055 + offset, -111.8912 + widthAdjust],
            [40.76055 + offset, -111.89095 + widthAdjust],
            [40.76028 + offset, -111.89095 + widthAdjust],
            [40.76028 + offset, -111.8912 + widthAdjust],
        ];

        const recoveryPolygon = [
            [40.76016 - offset, -111.89106 - widthAdjust],
            [40.76016 - offset, -111.89074 - widthAdjust],
            [40.75992 - offset, -111.89074 - widthAdjust],
            [40.75992 - offset, -111.89106 - widthAdjust],
        ];

        frames.push({
            dateLabel: formatFrameDate(date),
            cloudCover: `${cloud}%`,
            vigorIndex: Math.max(0, Math.min(1, vigor)).toFixed(2),
            stressPolygon,
            recoveryPolygon,
        });
    }

    return frames;
}

function stopTimelapsePlayback(playButton) {
    if (timelapseState.timerId !== null) {
        clearInterval(timelapseState.timerId);
        timelapseState.timerId = null;
    }
    if (playButton) {
        playButton.textContent = 'Play Timelapse';
    }
}

function renderTimelapseFrame(frameIndex) {
    const frame = timelapseState.frames[frameIndex];
    if (!frame || !timelapseState.map || typeof L === 'undefined') {
        return;
    }

    const frameLabel = document.getElementById('timelapse-frame-label');
    const cloud = document.getElementById('timelapse-cloud');
    const vigor = document.getElementById('timelapse-vigor');

    if (timelapseState.changeLayer) {
        timelapseState.map.removeLayer(timelapseState.changeLayer);
    }

    timelapseState.changeLayer = L.layerGroup([
        L.polygon(frame.stressPolygon, {
            color: '#ef4444',
            fillColor: '#ef4444',
            fillOpacity: 0.28,
            weight: 1,
        }),
        L.polygon(frame.recoveryPolygon, {
            color: '#22c55e',
            fillColor: '#22c55e',
            fillOpacity: 0.28,
            weight: 1,
        }),
    ]).addTo(timelapseState.map);

    if (frameLabel) {
        frameLabel.textContent = `${frameIndex + 1}/${timelapseState.frames.length} — ${frame.dateLabel}`;
    }
    if (cloud) {
        cloud.textContent = frame.cloudCover;
    }
    if (vigor) {
        vigor.textContent = frame.vigorIndex;
    }
}

function initDemoTimelapse() {
    const mapElement = document.getElementById('timelapse-map');
    const slider = document.getElementById('timelapse-slider');
    const playButton = document.getElementById('timelapse-play');
    const nextButton = document.getElementById('timelapse-next');

    if (!mapElement || !slider || !playButton || !nextButton) {
        return;
    }

    if (typeof L === 'undefined') {
        mapElement.innerHTML = '<p style="padding: 1rem;">Unable to load map renderer. Please refresh to retry.</p>';
        return;
    }

    timelapseState.frames = generateTimelapseFrames(24);
    slider.max = String(timelapseState.frames.length - 1);
    slider.value = '0';

    timelapseState.map = L.map(mapElement, {
        zoomControl: true,
        attributionControl: true,
    }).setView([40.7603, -111.8910], 17);

    timelapseState.baseLayer = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        {
            attribution: 'Tiles © Esri',
            maxZoom: 19,
        }
    ).addTo(timelapseState.map);

    timelapseState.aoiLayer = L.polygon(DEMO_AOI_POLYGON, {
        color: '#0f766e',
        fillColor: '#14b8a6',
        fillOpacity: 0.08,
        weight: 2,
        dashArray: '6 4',
    }).addTo(timelapseState.map);

    timelapseState.map.fitBounds(timelapseState.aoiLayer.getBounds(), {
        padding: [30, 30],
    });

    renderTimelapseFrame(0);

    slider.addEventListener('input', (event) => {
        const target = event.target;
        const value = Number(target && target.value ? target.value : 0);
        timelapseState.currentIndex = value;
        renderTimelapseFrame(timelapseState.currentIndex);
        stopTimelapsePlayback(playButton);
    });

    nextButton.addEventListener('click', () => {
        const nextIndex = (timelapseState.currentIndex + 1) % timelapseState.frames.length;
        timelapseState.currentIndex = nextIndex;
        slider.value = String(nextIndex);
        renderTimelapseFrame(nextIndex);
    });

    playButton.addEventListener('click', () => {
        if (timelapseState.timerId !== null) {
            stopTimelapsePlayback(playButton);
            return;
        }

        playButton.textContent = 'Pause Timelapse';
        timelapseState.timerId = setInterval(() => {
            const nextIndex = (timelapseState.currentIndex + 1) % timelapseState.frames.length;
            timelapseState.currentIndex = nextIndex;
            slider.value = String(nextIndex);
            renderTimelapseFrame(nextIndex);
        }, 1400);
    });
}

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
        form.reset();

    } catch (error) {
        console.error('Form submission error:', error);
        messageEl.textContent = `❌ ${error.message || 'Something went wrong. Please try again.'}`;
        messageEl.style.color = '#ef4444';
    } finally {
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
    const demoEmailInput = document.getElementById('demo-email');
    const kmlTextarea = document.getElementById('demo-kml');
    const note = document.getElementById('demo-message');
    const demoEmail = String(demoEmailInput && demoEmailInput.value ? demoEmailInput.value : '')
        .trim()
        .toLowerCase();

    const kmlContent = kmlTextarea.value.trim();

    if (!demoEmail) {
        if (note) {
            note.textContent = '❌ Please provide an email so we can send your results.';
            note.style.color = '#ef4444';
        }
        return;
    }

    if (!EMAIL_PATTERN.test(demoEmail)) {
        if (note) {
            note.textContent = '❌ Please enter a valid email address.';
            note.style.color = '#ef4444';
        }
        return;
    }

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
        const payload = {
            email: demoEmail,
            kml: kmlContent,
        };

        let response;
        try {
            response = await fetch(DEMO_SUBMIT_ENDPOINT, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });
        } catch (relativeError) {
            console.warn('Relative demo endpoint failed, trying fallback endpoint:', relativeError);
            response = await fetch(DEMO_SUBMIT_FALLBACK_ENDPOINT, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });
        }

        if (!response.ok) {
            let errorMessage = 'Submission failed. Please try again.';
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

        const result = await response.json();
        const submissionId = result && result.submission_id ? String(result.submission_id) : '';

        if (note) {
            note.textContent = submissionId
                ? `✅ Submitted. We will email your results link when processing completes. Tracking ID: ${submissionId}`
                : '✅ Submitted. We will email your results link when processing completes.';
            note.style.color = '#22c55e';
        }

    } catch (error) {
        console.error('Demo submit error:', error);
        if (note) {
            note.textContent = '❌ Submission failed. Please try again.';
            note.style.color = '#ef4444';
        }
    } finally {
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
    initDemoTimelapse();

    // Periodic status checks
    setInterval(updateStatus, STATUS_CHECK_INTERVAL);
}

// Run on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
