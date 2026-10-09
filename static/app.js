/* ── app.js ─────────────────────────────────────────────────────────────────
   UGC Ad Maker v3.1 — Dual Engine & Director Edition Logic
   ─────────────────────────────────────────────────────────────────────────── */

// ─── Product mode toggle ──────────────────────────────────────────────────────
const physicalBtn      = document.getElementById('btn-physical');
const softwareBtn      = document.getElementById('btn-software');
const productModeInput = document.getElementById('product_mode');
const physicalFields   = document.getElementById('physical-fields');
const softwareFields   = document.getElementById('software-fields');

function setMode(mode) {
  productModeInput.value = mode;
  if (mode === 'physical') {
    physicalBtn.classList.add('active');
    softwareBtn.classList.remove('active');
    physicalFields.style.display = '';
    softwareFields.style.display = 'none';
  } else {
    softwareBtn.classList.add('active');
    physicalBtn.classList.remove('active');
    physicalFields.style.display = 'none';
    softwareFields.style.display = '';
  }
}
physicalBtn.addEventListener('click', () => setMode('physical'));
softwareBtn.addEventListener('click', () => setMode('software'));

// ─── Video Engine Selection ───────────────────────────────────────────────────
const cardWavespeed     = document.getElementById('card-engine-wavespeed');
const cardOpenrouter    = document.getElementById('card-engine-openrouter');
const videoBackendInput = document.getElementById('video_backend');
const openrouterModelContainer = document.getElementById('openrouter-model-container');

cardWavespeed.addEventListener('click', () => {
  cardWavespeed.classList.add('active');
  cardOpenrouter.classList.remove('active');
  videoBackendInput.value = 'wavespeed';
  openrouterModelContainer.style.display = 'none';
});

cardOpenrouter.addEventListener('click', () => {
  cardOpenrouter.classList.add('active');
  cardWavespeed.classList.remove('active');
  videoBackendInput.value = 'openrouter';
  openrouterModelContainer.style.display = '';
});

// ─── Avatar upload ────────────────────────────────────────────────────────────
const avatarInput       = document.getElementById('avatar-file');
const avatarPreview     = document.getElementById('avatar-preview');
const avatarPreviewImg  = document.getElementById('avatar-preview-img');
const avatarPreviewName = document.getElementById('avatar-preview-name');
const avatarPreviewSize = document.getElementById('avatar-preview-size');
const avatarRemove      = document.getElementById('avatar-remove');
const avatarUrlHidden   = document.getElementById('avatar_url');
let avatarUploading = false;

avatarInput.addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file || avatarUploading) return;

  const localUrl = URL.createObjectURL(file);
  avatarPreviewImg.src  = localUrl;
  avatarPreviewName.textContent = file.name;
  avatarPreviewSize.textContent = formatBytes(file.size) + ' — uploading…';
  avatarPreview.classList.add('visible');
  avatarUploading = true;

  try {
    const form = new FormData();
    form.append('file', file);
    const resp = await fetch('/upload/avatar', { method: 'POST', body: form });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    avatarUrlHidden.value = data.url;
    avatarPreviewSize.textContent = formatBytes(file.size) + ' ✅ ready';
  } catch (err) {
    avatarPreviewSize.textContent = '❌ Upload failed — ' + err.message;
    avatarUrlHidden.value = '';
  } finally {
    avatarUploading = false;
  }
});

avatarRemove.addEventListener('click', () => {
  avatarInput.value = '';
  avatarUrlHidden.value = '';
  avatarPreview.classList.remove('visible');
  avatarPreviewImg.src = '';
});

// ─── Product image file upload ────────────────────────────────────────────────
const productFileInput   = document.getElementById('product_image_file');
const productPreview     = document.getElementById('product-preview');
const productPreviewImg  = document.getElementById('product-preview-img');
const productPreviewName = document.getElementById('product-preview-name');
const productPreviewSize = document.getElementById('product-preview-size');
const productRemove      = document.getElementById('product-remove');

productFileInput.addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  productPreviewImg.src = URL.createObjectURL(file);
  productPreviewName.textContent = file.name;
  productPreviewSize.textContent = formatBytes(file.size);
  productPreview.classList.add('visible');
});

productRemove.addEventListener('click', () => {
  productFileInput.value = '';
  productPreview.classList.remove('visible');
  productPreviewImg.src = '';
});

// ─── Audio file upload ────────────────────────────────────────────────────────
const audioFileInput   = document.getElementById('reference_audio_file');
const audioPreview     = document.getElementById('audio-preview');
const audioPreviewName = document.getElementById('audio-preview-name');
const audioPreviewSize = document.getElementById('audio-preview-size');
const audioRemove      = document.getElementById('audio-remove');

audioFileInput.addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  audioPreviewName.textContent = file.name;
  audioPreviewSize.textContent = formatBytes(file.size);
  audioPreview.classList.add('visible');
});

audioRemove.addEventListener('click', () => {
  audioFileInput.value = '';
  audioPreview.classList.remove('visible');
});

// ─── Drag-and-drop for upload zones ──────────────────────────────────────────
document.querySelectorAll('.upload-zone').forEach(zone => {
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('drag-over');
    const input = zone.querySelector('input[type="file"]');
    if (input && e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event('change'));
    }
  });
});

// ─── Result Tabs ─────────────────────────────────────────────────────────────
document.querySelectorAll('.result-tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.result-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.result-tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    const targetId = btn.getAttribute('data-tab');
    const content = document.getElementById(targetId);
    if (content) content.classList.add('active');
  });
});

// ─── Form submission & SSE progress ──────────────────────────────────────────
const form          = document.getElementById('ugc-form');
const generateBtn   = document.getElementById('btn-generate');
const progressPanel = document.getElementById('progress-panel');
const resultPanel   = document.getElementById('result-panel');
const stepsList     = document.getElementById('steps-list');
const progressFill  = document.getElementById('progress-fill');
const progressPct   = document.getElementById('progress-pct');

let currentJobId = null;
let eventSource  = null;

form.addEventListener('submit', async (e) => {
  e.preventDefault();

  if (avatarUploading) {
    alert('Please wait for avatar photo upload to complete.');
    return;
  }

  const benefitVal = (document.getElementById('product_benefit')?.value || '').trim();
  const customScriptVal = (document.getElementById('custom_script')?.value || '').trim();

  if (!benefitVal && !customScriptVal) {
    alert('Please provide either the Key Benefit/Hook or paste your Custom Script.');
    return;
  }

  // Reset UI
  progressPanel.classList.add('visible');
  resultPanel.classList.remove('visible');
  stepsList.innerHTML = '';
  progressFill.style.width = '0%';
  progressPct.textContent  = '0%';
  generateBtn.disabled = true;
  generateBtn.innerHTML = '<div class="spinner"></div> Directing &amp; Generating…';

  const terminalConsole = document.getElementById('terminal-console');
  if (terminalConsole) {
    terminalConsole.innerHTML = '';
    appendTerminalLog(null, 'info', '🚀 UGC Ad generation request dispatched to server...');
  }

  if (eventSource) { eventSource.close(); eventSource = null; }

  const formData = new FormData(form);

  try {
    const resp = await fetch('/generate', { method: 'POST', body: formData });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Server error');
    }
    const { job_id } = await resp.json();
    currentJobId = job_id;
    try { localStorage.setItem('ugc_last_job_id', job_id); } catch(e) {}
    appendTerminalLog(null, 'info', `Job ID registered: ${job_id}`);
    listenToProgress(job_id);
  } catch (err) {
    addStep('❌', err.message, 'error');
    appendTerminalLog(null, 'error', `Submission error: ${err.message}`);
    generateBtn.disabled = false;
    generateBtn.innerHTML = '🎬 Generate Complete UGC Ad';
  }
});

function listenToProgress(jobId) {
  eventSource = new EventSource(`/status/${jobId}`);

  eventSource.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    const { step, message, progress, time, video_url, script, raw_script, display_script,
            audio_url, ugc_image_url, segments, clip_urls, analysis, error } = data;

    if (progress != null) {
      progressFill.style.width = progress + '%';
      progressPct.textContent  = progress + '%';
    }

    if (message) {
      appendTerminalLog(time, step, message);
    }

    if (step === 'done' || step === 'completed') {
      addStep('✅', message, 'active');
      appendTerminalLog(time, 'done', '🎉 Pipeline completed! Loading video player...');
      eventSource.close();
      generateBtn.disabled = false;
      generateBtn.innerHTML = '🎬 Generate Another Ad';

      // Always fetch full authoritative result to ensure video_url & metadata are fully populated
      fetch(`/result/${jobId}`)
        .then(r => r.json())
        .then(fullResult => {
          showResult(fullResult);
        })
        .catch(err => {
          console.error('Failed fetching /result', err);
          showResult(data);
        });
    } else if (step === 'error' || step === 'failed') {
      addStep('❌', message || error, 'error');
      appendTerminalLog(time, 'error', `Pipeline failed: ${message || error}`);
      eventSource.close();
      generateBtn.disabled = false;
      generateBtn.innerHTML = '🎬 Generate Complete UGC Ad';
    } else {
      document.querySelectorAll('.step-item').forEach(el => el.classList.remove('active'));
      addStep(stepIcon(step), message, 'active');
    }
  };

  eventSource.onerror = () => {
    if (eventSource.readyState === EventSource.CLOSED) return;
    addStep('❌', 'Connection lost — check server logs.', 'error');
    appendTerminalLog(null, 'error', 'SSE connection disconnected.');
    eventSource.close();
    generateBtn.disabled = false;
    generateBtn.innerHTML = '🎬 Generate Complete UGC Ad';
  };
}

function appendTerminalLog(time, step, message) {
  const terminalConsole = document.getElementById('terminal-console');
  if (!terminalConsole || !message) return;

  const row = document.createElement('div');
  const badgeCls = (step || 'info').toLowerCase();
  row.className = `terminal-row ${badgeCls}`;

  const now = new Date();
  const displayTime = time || now.toTimeString().split(' ')[0];
  const stepLabel = (step || 'INFO').toUpperCase();

  row.innerHTML = `
    <span class="term-time">${escapeHtml(displayTime)}</span>
    <span class="term-badge ${escapeHtml(badgeCls)}">${escapeHtml(stepLabel)}</span>
    <span class="term-text">${escapeHtml(message)}</span>
  `;

  terminalConsole.appendChild(row);
  terminalConsole.scrollTop = terminalConsole.scrollHeight;
}

// Terminal toolbar actions: Copy & Clear
document.getElementById('btn-copy-logs')?.addEventListener('click', () => {
  const terminalConsole = document.getElementById('terminal-console');
  if (!terminalConsole) return;
  const text = Array.from(terminalConsole.querySelectorAll('.terminal-row'))
    .map(r => r.innerText.replace(/\s+/g, ' ').trim())
    .join('\n');
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.getElementById('btn-copy-logs');
    const oldText = btn.innerHTML;
    btn.innerHTML = '✅ Copied!';
    setTimeout(() => { btn.innerHTML = oldText; }, 2000);
  });
});

document.getElementById('btn-clear-logs')?.addEventListener('click', () => {
  const terminalConsole = document.getElementById('terminal-console');
  if (terminalConsole) {
    terminalConsole.innerHTML = `
      <div class="terminal-row sys">
        <span class="term-time">${new Date().toTimeString().split(' ')[0]}</span>
        <span class="term-badge info">CLEARED</span>
        <span class="term-text">Console cleared. Continuing log stream...</span>
      </div>`;
  }
});

function addStep(icon, message, cls = '') {
  const el = document.createElement('div');
  el.className = 'step-item ' + cls;
  el.innerHTML = `<span class="step-icon">${icon}</span><span class="step-msg">${escapeHtml(message)}</span>`;
  stepsList.appendChild(el);
  el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function stepIcon(step) {
  const icons = {
    analyze:        '🔍',
    script:         '✍️',
    upload_product: '☁️',
    image_gen:      '🖼️',
    tts:            '🗣️',
    upload_audio:   '☁️',
    video:          '🎥',
    video_poll:     '⏳',
    compose:        '🎬',
    done:           '✅',
    error:          '❌',
    queued:         '⏳',
  };
  return icons[step] || '⚙️';
}

function showResult(data) {
  const { job_id, video_url, script, raw_script, display_script, audio_url, ugc_image_url, segments, clip_urls, analysis } = data;
  resultPanel.classList.add('visible');
  resultPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });

  // Video
  const videoEl = document.getElementById('result-video');
  if (video_url) {
    videoEl.src = video_url;
    videoEl.style.display = 'block';
    videoEl.load();
  } else {
    videoEl.style.display = 'none';
  }

  // Script
  const scriptBox = document.getElementById('result-script');
  if (raw_script) {
    scriptBox.innerHTML = formatScript(raw_script);
  } else {
    scriptBox.textContent = script || '';
  }

  // Links
  const jId = job_id || currentJobId;
  const dlBtn = document.getElementById('result-download');
  if (jId) {
    dlBtn.href = `/download/${jId}`;
  } else if (video_url) {
    dlBtn.href = video_url;
  } else {
    dlBtn.href = '#';
  }
  dlBtn.setAttribute('download', 'ugc-ad.mp4');

  const audioLink = document.getElementById('result-audio');
  audioLink.href = audio_url || '#';
  audioLink.style.display = audio_url ? '' : 'none';

  const imgLink = document.getElementById('result-image');
  imgLink.href = ugc_image_url || '#';
  imgLink.style.display = ugc_image_url ? '' : 'none';

  // Segments breakdown in Script Tab
  if (segments && segments.length) {
    const list = document.getElementById('segment-list');
    list.innerHTML = segments.map(s =>
      `<div class="segment-tag">
        <span class="seg-label">${s.label.toUpperCase()}</span>
        <span class="seg-text">${escapeHtml(s.text)}</span>
      </div>`
    ).join('');
  }

  // Populate Director's Plan Tab
  const directorBox = document.getElementById('director-plan-box');
  if (segments && segments.length) {
    directorBox.innerHTML = segments.map((s, idx) => {
      const dir = s.scene_direction || {};
      return `
        <div class="director-scene-card">
          <div class="director-scene-header">
            <span>SCENE ${idx + 1}: ${s.label.toUpperCase()}</span>
            <span style="font-size:11px;color:var(--text3);font-weight:400">Emotion: ${s.emotion}</span>
          </div>
          ${dir.characters ? `<div class="director-field"><strong>🎭 Character:</strong> ${escapeHtml(dir.characters)}</div>` : ''}
          ${dir.scene_background ? `<div class="director-field"><strong>🏠 Background:</strong> ${escapeHtml(dir.scene_background)}</div>` : ''}
          ${dir.camera_movement ? `<div class="director-field"><strong>📱 Camera:</strong> ${escapeHtml(dir.camera_movement)}</div>` : ''}
          ${dir.movement_in_scene ? `<div class="director-field"><strong>📦 Action &amp; Product:</strong> ${escapeHtml(dir.movement_in_scene)}</div>` : ''}
          ${dir.sound_design ? `<div class="director-field"><strong>🎧 Sound Design:</strong> ${escapeHtml(dir.sound_design)}</div>` : ''}
        </div>
      `;
    }).join('');
  } else {
    directorBox.innerHTML = '<p class="hint">Director plan generated.</p>';
  }

  // Populate Brand & Creator Tab
  const brandBox = document.getElementById('brand-analysis-box');
  if (analysis) {
    const profile = analysis.character_profile || {};
    const colors = analysis.color_scheme || [];
    brandBox.innerHTML = `
      <div class="brand-card">
        <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:6px;">
          🏷️ Brand: ${escapeHtml(analysis.brand_name || 'N/A')}
        </div>
        <div style="font-size:12px;color:var(--text2);margin-bottom:6px;">
          <strong>Product Type:</strong> ${escapeHtml(analysis.product_type || 'N/A')}
        </div>
        ${analysis.visual_description ? `
          <div style="font-size:12px;color:var(--text2);margin-bottom:6px;">
            <strong>Visual Description:</strong> ${escapeHtml(analysis.visual_description)}
          </div>
        ` : ''}
        ${analysis.visible_text ? `
          <div style="font-size:12px;color:var(--text2);margin-bottom:6px;">
            <strong>Packaging Text:</strong> ${escapeHtml(analysis.visible_text)}
          </div>
        ` : ''}
        ${colors.length ? `
          <div style="margin-top:10px;">
            <strong style="font-size:12px;color:var(--text);">Identified Color Palette:</strong>
            <div class="color-swatches">
              ${colors.map(c => `
                <div class="color-swatch-item">
                  <span class="color-swatch-dot" style="background:${c.hex || '#ccc'}"></span>
                  <span>${escapeHtml(c.name || c.hex)}</span>
                </div>
              `).join('')}
            </div>
          </div>
        ` : ''}
      </div>

      <div class="brand-card" style="border-color:rgba(124,58,237,0.3);background:rgba(124,58,237,0.05)">
        <div style="font-size:13px;font-weight:700;color:var(--accent3);margin-bottom:6px;">
          🧑💼 Locked Creator Profile Anchor
        </div>
        <div class="director-field"><strong>Description:</strong> ${escapeHtml(profile.description || 'Natural lifestyle creator')}</div>
        <div class="director-field"><strong>Attire:</strong> ${escapeHtml(profile.attire || 'Everyday casual neutral clothing')}</div>
        <div class="director-field"><strong>Environment:</strong> ${escapeHtml(profile.setting || 'Naturally lit room')}</div>
      </div>
    `;
  }

  resultPanel.scrollIntoView({ behavior: 'smooth' });
}

function formatScript(raw) {
  const labelMap = { HOOK: 'Hook', BODY: 'Body', CTA: 'Call to Action' };
  let html = '';
  const lines = raw.split('\n');
  for (const line of lines) {
    const s = line.trim();
    const m = s.match(/^\[(HOOK|BODY|CTA)\]$/i);
    if (m) {
      const label = labelMap[m[1].toUpperCase()] || m[1];
      html += `<div class="script-segment-label">${label}</div>`;
    } else if (s.startsWith('[SCENE_')) {
      // Scene markers are displayed in the Director tab instead
      continue;
    } else if (s && !s.startsWith('Characters:') && !s.startsWith('Scene Background:') &&
               !s.startsWith('Camera Movement:') && !s.startsWith('Movement in Scene:') &&
               !s.startsWith('Sound Design:')) {
      html += `<p class="script-segment-text">${escapeHtml(s)}</p>`;
    }
  }
  return html;
}

// ─── Utilities ────────────────────────────────────────────────────────────────
function formatBytes(b) {
  if (b < 1024) return b + ' B';
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
  return (b / (1024 * 1024)).toFixed(1) + ' MB';
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ─── Auto-Restore Recent Completed Ad on Page Load ────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  const urlParams = new URLSearchParams(window.location.search);
  const qJobId = urlParams.get('job_id') || localStorage.getItem('ugc_last_job_id');
  if (qJobId) {
    fetch(`/result/${qJobId}`)
      .then(r => {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then(data => {
        if (data.status === 'completed' && data.video_url) {
          currentJobId = qJobId;
          showResult(data);
        }
      })
      .catch(() => {});
  }
});
