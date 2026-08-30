// The server injects <meta name="csrf-token"> into every page it serves and
// requires the token on state-changing requests. Wrap fetch once so every
// mutating call carries it; the browser adds the same-origin Origin header
// on its own. When the page is opened directly from disk (no server, no meta)
// the token is empty and the wrapper is a no-op.
const CSRF_TOKEN = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
(function () {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    init = init || {};
    const method = (init.method || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD' && CSRF_TOKEN) {
      const headers = new Headers(init.headers || {});
      if (!headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', CSRF_TOKEN);
      init.headers = headers;
    }
    return nativeFetch(input, init);
  };
})();

// ---- Visible, non-blocking UI: toast + modal (no browser dialogs) -------

function toast(message, isError) {
  const el = document.getElementById('efl-toast');
  if (!el) return;
  el.textContent = message;
  el.classList.toggle('error', !!isError);
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 3500);
}

// Promise-based replacement for the blocking browser dialogs, built from DOM
// nodes with listeners (no inline handlers), so it works under a strict CSP.
function modal({ title, message, input, value, confirmLabel, danger }) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'efl-modal-overlay';
    const box = document.createElement('div');
    box.className = 'efl-modal';
    const h = document.createElement('h3');
    h.textContent = title || '';
    const p = document.createElement('p');
    p.textContent = message || '';
    box.appendChild(h);
    box.appendChild(p);
    let field = null;
    if (input) {
      field = document.createElement('input');
      field.type = 'text';
      field.value = value || '';
      field.className = 'efl-modal-input';
      box.appendChild(field);
    }
    const row = document.createElement('div');
    row.className = 'efl-modal-actions';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'btn-ghost';
    cancel.textContent = 'Cancel';
    const ok = document.createElement('button');
    ok.type = 'button';
    ok.className = danger ? 'btn-danger' : 'btn-primary';
    ok.textContent = confirmLabel || 'OK';
    row.appendChild(cancel);
    row.appendChild(ok);
    box.appendChild(row);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    if (field) field.focus();

    const close = (result) => { overlay.remove(); resolve(result); };
    cancel.addEventListener('click', () => close(input ? null : false));
    ok.addEventListener('click', () => close(input ? (field.value || '') : true));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(input ? null : false); });
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') close(input ? null : false);
      if (e.key === 'Enter' && input) close(field.value || '');
    });
  });
}

function modalConfirm(message, { danger, confirmLabel } = {}) {
  return modal({ title: 'Confirm', message, danger, confirmLabel: confirmLabel || 'OK' });
}

function modalPrompt(message, value) {
  return modal({ title: 'Enter a value', message, input: true, value, confirmLabel: 'OK' });
}

// Dual-handle range selector for trimming a sound. Resolves {start, end} in ms,
// or null if cancelled. Two overlaid range inputs share one track (the classic
// two-thumb slider); neither handle can cross the other, and a minimum window is
// always kept so the trim can never be empty.
function modalTrim(sound, durationMs) {
  return new Promise((resolve) => {
    const STEP = 10;
    const GAP = STEP;                    // smallest window the handles allow
    const max = Math.max(durationMs, GAP);
    let lo = 0, hi = max;

    const overlay = document.createElement('div');
    overlay.className = 'efl-modal-overlay';
    const box = document.createElement('div');
    box.className = 'efl-modal';
    const h = document.createElement('h3');
    h.textContent = `Trim ${sound}`;
    const p = document.createElement('p');
    p.textContent = 'Drag the handles to choose the part to keep. A new file is written; the original is left untouched.';
    box.append(h, p);

    const widget = document.createElement('div');
    widget.className = 'efl-range';
    const fill = document.createElement('div');
    fill.className = 'efl-range-fill';
    const loI = document.createElement('input');
    const hiI = document.createElement('input');
    for (const el of [loI, hiI]) { el.type = 'range'; el.min = '0'; el.max = String(max); el.step = String(STEP); }
    loI.value = String(lo); hiI.value = String(hi);
    loI.setAttribute('aria-label', 'Trim start (ms)');
    hiI.setAttribute('aria-label', 'Trim end (ms)');
    widget.append(fill, loI, hiI);

    const readout = document.createElement('div');
    readout.className = 'efl-range-readout';
    box.append(widget, readout);

    const row = document.createElement('div');
    row.className = 'efl-modal-actions';
    const cancel = document.createElement('button');
    cancel.type = 'button'; cancel.className = 'btn-ghost'; cancel.textContent = 'Cancel';
    const ok = document.createElement('button');
    ok.type = 'button'; ok.className = 'btn-primary'; ok.textContent = 'Trim';
    row.append(cancel, ok);
    box.append(row);
    overlay.append(box);
    document.body.appendChild(overlay);

    const pct = (v) => (v / max) * 100;
    const render = () => {
      fill.style.left = pct(lo) + '%';
      fill.style.right = (100 - pct(hi)) + '%';
      readout.innerHTML = `Keep <b>${lo}–${hi} ms</b> · ${hi - lo} ms of ${max} ms`;
    };
    loI.addEventListener('input', () => { lo = Math.min(+loI.value, hi - GAP); loI.value = String(lo); render(); });
    hiI.addEventListener('input', () => { hi = Math.max(+hiI.value, lo + GAP); hiI.value = String(hi); render(); });
    render();

    const close = (result) => { overlay.remove(); resolve(result); };
    cancel.addEventListener('click', () => close(null));
    ok.addEventListener('click', () => close({ start: lo, end: hi }));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(null); });
    box.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(null); });
  });
}

function setSpeed(imgId, slug, filename, factor) {
  const img = document.getElementById(imgId);
  const base = img.dataset.baseSrc;
  const url = factor === '1'
    ? base
    : `/speed/${encodeURIComponent(slug)}/${encodeURIComponent(filename)}?factor=${encodeURIComponent(factor)}`;
  img.src = '';
  img.onload = null;
  img.src = url;
}

function playWithSound(imgId, audioId) {
  const audio = document.getElementById(audioId);
  const player = PLAYERS.get(imgId);
  if (player) {
    // Frame package: restart the stepper at frame 0 and start the audio in
    // the same tick, so the pairing is judged from a known origin.
    player.restart();
    audio.currentTime = 0;
    audio.play();
    return;
  }
  const img = document.getElementById(imgId);
  const src = img.src;
  img.src = '';
  audio.currentTime = 0;
  img.onload = () => audio.play();
  img.src = src;
}

async function uploadFiles(slug, fileList) {
  const files = Array.from(fileList);
  if (!files.length) return;
  for (const file of files) {
    const res = await fetch(`/upload/${encodeURIComponent(slug)}/${encodeURIComponent(file.name)}`, {
      method: 'PUT',
      body: file,
    });
    if (!res.ok) {
      toast(`Upload failed for ${file.name}: ${await res.text()}`, true);
      return;
    }
  }
  location.href = `actor-${encodeURIComponent(slug)}.html`;
}

function uploadNewActor() {
  const slug = document.getElementById('new-actor-slug').value.trim();
  const files = document.getElementById('new-actor-files').files;
  if (!slug) {
    toast('Enter an actor slug first.', true);
    return;
  }
  uploadFiles(slug, files);
}

async function linkSound(slug, animation, selectId) {
  const select = document.getElementById(selectId);
  const sound = select.value;
  if (!sound) return;
  const res = await fetch('/link', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({slug, animation, sound}),
  });
  if (!res.ok) {
    toast(`Link failed: ${await res.text()}`, true);
    return;
  }
  location.reload();
}

async function deleteAsset(slug, filename) {
  if (!(await modalConfirm(`Delete ${filename}? This can't be undone.`, { danger: true, confirmLabel: 'Delete' }))) return;
  const res = await fetch(`/asset/${encodeURIComponent(slug)}/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    toast(`Delete failed: ${await res.text()}`, true);
    return;
  }
  location.reload();
}

async function renameAsset(slug, filename) {
  const newName = await modalPrompt(`Rename ${filename} to:`, filename);
  if (!newName || newName === filename) return;
  const res = await fetch('/rename', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({slug, filename, new_name: newName}),
  });
  if (!res.ok) {
    toast(`Rename failed: ${await res.text()}`, true);
    return;
  }
  location.reload();
}

async function unlinkSound(slug, animation, sound) {
  const res = await fetch('/unlink', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({slug, animation, sound}),
  });
  if (!res.ok) {
    toast(`Unlink failed: ${await res.text()}`, true);
    return;
  }
  location.reload();
}

async function trimSound(slug, sound, durationMs, linkTo) {
  let start, end;
  if (durationMs) {
    const range = await modalTrim(sound, durationMs);
    if (!range) return;
    start = range.start; end = range.end;
  } else {
    // Unknown duration (rare): fall back to typing an explicit window.
    const answer = await modalPrompt(
      `${sound}: keep which part? Enter start-end in ms (a new file is written; the original is kept):`, '0-1000');
    if (!answer) return;
    const m = answer.trim().match(/^(\d+)\s*-\s*(\d+)$/);
    if (!m) { toast('Enter a range like 120-700', true); return; }
    start = +m[1]; end = +m[2];
  }
  const res = await fetch('/trim', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({slug, sound, start_ms: start, end_ms: end, link_to: linkTo || null}),
  });
  if (!res.ok) {
    let msg = await res.text();
    try { msg = JSON.parse(msg).error; } catch (e) {}
    toast(`Trim failed: ${msg}`, true);
    return;
  }
  location.reload();
}

// ---- Generation panel ---------------------------------------------------

const GEN = { kind: 'animation', estimate: null, slug: null };

function $(id) { return document.getElementById(id); }

function genTab(kind) {
  GEN.kind = kind;
  document.querySelectorAll('.gen-tab').forEach(b => b.classList.toggle('active', b.dataset.kind === kind));
  ['animation', 'sound', 'source'].forEach(k => { $(`gen-form-${k}`).hidden = (k !== kind); });
  genDirty();
}

function genDirty() {
  GEN.estimate = null;
  $('gen-confirm').hidden = true;
  $('gen-cost').textContent = '';
}

function genParams() {
  const form = $(`gen-form-${GEN.kind}`);
  const params = { slug: GEN.slug, kind: GEN.kind };
  new FormData(form).forEach((v, k) => { params[k] = v; });
  return params;
}

function genStatus(text, isError) {
  const el = $('gen-status');
  el.textContent = text;
  el.classList.toggle('error', !!isError);
}

async function genJson(url, body, method) {
  const res = await fetch(url, {
    method: method || 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (e) { data = { error: `HTTP ${res.status}` }; }
  if (!res.ok) throw Object.assign(new Error(data.error || `HTTP ${res.status}`), { status: res.status, data });
  return data;
}

async function genEstimate() {
  genDirty();
  genStatus('');
  const btn = $('gen-estimate');
  btn.disabled = true;
  try {
    const est = await genJson('/estimate', genParams());
    GEN.estimate = est;
    const parts = [est.display];
    if (est.submitted_size) parts.push(`submits ${est.submitted_size[0]}×${est.submitted_size[1]}`);
    parts.push(`writes ${est.output_name}`);
    $('gen-cost').textContent = parts.join(' · ');
    const confirm = $('gen-confirm');
    confirm.textContent = `Confirm & generate (${est.display.split(' · ')[0]})`;
    confirm.hidden = false;
    if (!est.live) genStatus('Offline: a fake provider will answer. Start the server with --allow-spend to use the real API.');
  } catch (err) {
    genStatus(err.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function genConfirm() {
  if (!GEN.estimate) return;
  const confirm = $('gen-confirm');
  confirm.disabled = true;
  const params = genParams();
  params.confirm_amount = GEN.estimate.amount;
  const kind = GEN.kind;
  try {
    if (kind === 'animation') {
      genStatus('Submitting…');
      const job = await genJson('/generate/animation', params);
      await genPoll(job.job_id, job.output_name);
    } else {
      genStatus('Generating…');
      const result = await genJson(`/generate/${kind}`, params);
      genStatus(`Done: ${result.filename}` + (result.reported_charge ? ` · charged ${result.reported_charge}` : ''));
      setTimeout(() => location.reload(), 600);
    }
  } catch (err) {
    genStatus(err.data && err.data.ambiguous
      ? `Ambiguous: ${err.message}`
      : err.message, true);
    confirm.disabled = false;
  }
}

async function genPoll(jobId, outputName) {
  const started = Date.now();
  for (;;) {
    let job;
    try {
      job = await genJson(`/job/${encodeURIComponent(GEN.slug)}/${encodeURIComponent(jobId)}`, undefined, 'GET');
    } catch (err) {
      genStatus(err.message, true);
      return;
    }
    const elapsed = Math.round((Date.now() - started) / 1000);
    if (job.state === 'running' || job.state === 'queued') {
      genStatus(`Animating ${outputName || ''}… ${elapsed}s (SpriteLab jobs usually take 30–90 s; keep this page open)`);
      await new Promise(r => setTimeout(r, 3000));
      continue;
    }
    if (job.state === 'succeeded') {
      genStatus(`Done: ${(job.outputs && job.outputs.gif) || 'sheet only'}`);
      setTimeout(() => location.reload(), 600);
    } else {
      genStatus(`${job.state}: ${job.error || 'no detail'}`, true);
    }
    return;
  }
}

async function genInit() {
  const panel = document.querySelector('.gen-panel');
  if (!panel) return;
  GEN.slug = panel.dataset.slug;
  try {
    const info = await genJson('/providers', undefined, 'GET');
    const badge = $('gen-badge');
    const p = info.providers;
    if (info.allow_spend) {
      badge.textContent = 'LIVE — spending enabled';
      badge.classList.add('live');
    } else {
      badge.textContent = 'offline — fake providers';
    }
    const usable = {
      animation: !info.allow_spend || p.spritelab.live,
      sound: !info.allow_spend || p.elevenlabs.live,
      source: !info.allow_spend || p.spritelab.live || p.openai.live,
    };
    document.querySelectorAll('.gen-tab').forEach(b => {
      b.disabled = !usable[b.dataset.kind];
      if (b.disabled) b.title = 'no API key configured for this provider';
    });
    const jobs = await genJson(`/jobs/${encodeURIComponent(GEN.slug)}`, undefined, 'GET');
    if (jobs.open && jobs.open.length) {
      const job = jobs.open[jobs.open.length - 1];
      panel.open = true;
      genStatus(`Resuming animation job for "${job.action}"…`);
      genPoll(job.job_id, job.action);
    }
  } catch (err) {
    $('gen-badge').textContent = 'server not running';
  }
}

// ---- Frame-package player -------------------------------------------------
// A frame package is an animation stored as ordered PNGs plus manifest.json
// with an exact per-frame delay in ms. The browser's GIF decoder cannot honour
// that (GIF delays are centiseconds), so these cards draw frames onto a canvas
// themselves. Time is accumulated from requestAnimationFrame timestamps and
// frames advance when their delay has elapsed, so long-running playback never
// drifts from the authored total.

const PLAYERS = new Map();   // canvas id -> FramePlayer

class FramePlayer {
  constructor(card) {
    this.card = card;
    this.slug = card.dataset.slug;
    this.name = card.dataset.animation;
    this.canvas = document.getElementById(card.dataset.canvas);
    this.ctx = this.canvas.getContext('2d');
    this.ctx.imageSmoothingEnabled = false;
    this.framesBase = card.dataset.framesBase;
    this.scrub = card.querySelector('[data-action="fp-scrub"]');
    this.readout = card.querySelector('[data-role="frame"]');
    this.toggleBtn = card.querySelector('[data-action="fp-toggle"]');
    this.loopBox = card.querySelector('[data-action="fp-loop"]');
    this.images = [];
    this.delays = [];
    this.loop = false;
    this.idx = 0;
    this.acc = 0;
    this.speed = 1;
    this.playing = false;
    this.last = 0;
    this.raf = 0;
    this.timer = 0;
    this.ready = false;
  }

  async load() {
    const res = await fetch(this.card.dataset.manifest);
    if (!res.ok) throw new Error(`manifest ${res.status}`);
    const manifest = await res.json();
    this.manifest = manifest;
    this.delays = manifest.frames.map(f => f.delay_ms);
    this.loop = !!manifest.loop;
    if (this.loopBox) this.loopBox.checked = this.loop;
    if (manifest.frame_size) {
      this.canvas.width = manifest.frame_size[0];
      this.canvas.height = manifest.frame_size[1];
      this.ctx.imageSmoothingEnabled = false;
    }
    this.images = await Promise.all(manifest.frames.map(f => new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error(`frame ${f.file}`));
      img.src = this.framesBase + encodeURIComponent(f.file);
    })));
    if (this.scrub) this.scrub.max = String(this.images.length - 1);
    this.ready = true;
    this.draw();
    this.play();
  }

  draw() {
    const img = this.images[this.idx];
    if (!img) return;
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.ctx.drawImage(img, 0, 0);
    if (this.scrub) this.scrub.value = String(this.idx);
    if (this.readout) {
      const elapsed = this.delays.slice(0, this.idx).reduce((a, b) => a + b, 0);
      this.readout.textContent = `${this.idx} / ${this.images.length} · ${elapsed} ms`;
    }
  }

  tick(ts) {
    if (!this.playing) return;
    if (this.last) this.acc += (ts - this.last) * this.speed;
    this.last = ts;
    let moved = false;
    while (this.acc >= this.delays[this.idx]) {
      this.acc -= this.delays[this.idx];
      moved = true;
      if (this.idx + 1 >= this.images.length) {
        if (this.loop) { this.idx = 0; }
        else { this.idx = this.images.length - 1; this.pause(); break; }   // hold the last frame
      } else {
        this.idx += 1;
      }
    }
    if (moved) this.draw();
    if (this.playing) this.schedule();
  }

  // requestAnimationFrame stops in a hidden tab; a GIF would keep going, so
  // fall back to a timer there and resume rAF when the page is visible again.
  schedule() {
    clearTimeout(this.timer);
    cancelAnimationFrame(this.raf);
    if (document.visibilityState === 'hidden') {
      this.timer = setTimeout(() => this.tick(performance.now()), Math.max(16, this.delays[this.idx] / this.speed));
    } else {
      this.raf = requestAnimationFrame((t) => this.tick(t));
    }
  }

  play() {
    if (!this.ready || this.playing) return;
    if (!this.loop && this.idx >= this.images.length - 1) { this.idx = 0; this.acc = 0; this.draw(); }
    this.playing = true;
    this.last = 0;
    this.card.classList.add('playing');
    this.schedule();
  }

  pause() {
    this.playing = false;
    this.card.classList.remove('playing');
    cancelAnimationFrame(this.raf);
    clearTimeout(this.timer);
  }

  toggle() { this.playing ? this.pause() : this.play(); }

  restart() { this.pause(); this.idx = 0; this.acc = 0; this.draw(); this.play(); }

  seek(i) {
    this.pause();
    this.idx = Math.max(0, Math.min(this.images.length - 1, i | 0));
    this.acc = 0;
    this.draw();
  }

  step(dir) {
    const n = this.images.length;
    this.seek((this.idx + dir + n) % n);
  }

  setSpeed(factor) { this.speed = Number(factor) || 1; }

  setLoop(on) {
    this.loop = !!on;
    if (this.loop && !this.playing) this.play();
  }

  setDelays(delays) {
    this.delays = delays.slice();
    this.acc = 0;
    this.draw();
    const meta = this.card.querySelector('.fp-meta');
    if (meta) {
      const total = this.delays.reduce((a, b) => a + b, 0);
      meta.textContent = `${this.delays.length} frames · ${total} ms · timing: edited`;
    }
  }
}

function playerFor(el) {
  return PLAYERS.get(el.dataset.canvas);
}

async function initPlayers() {
  for (const card of document.querySelectorAll('[data-player]')) {
    const player = new FramePlayer(card);
    PLAYERS.set(card.dataset.canvas, player);
    player.load().catch(err => {
      card.classList.add('broken');
      toast(`Could not load ${player.name}: ${err.message}`, true);
    });
  }
}

// Per-frame delay editor. Thumbnails are drawn from the already-loaded frame
// images, each with a number input; the total updates live. Saving POSTs the
// whole delay list, which the server validates against the manifest.
function modalTiming(player) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'efl-modal-overlay';
    const box = document.createElement('div');
    box.className = 'efl-modal efl-modal-wide';
    const h = document.createElement('h3');
    h.textContent = `Timing for ${player.name}`;
    const p = document.createElement('p');
    p.textContent = 'How long each frame is shown, in milliseconds. Saved into the package manifest.';
    box.append(h, p);

    const grid = document.createElement('div');
    grid.className = 'fp-timing-grid';
    const inputs = [];
    player.images.forEach((img, i) => {
      const cell = document.createElement('div');
      cell.className = 'fp-timing-cell';
      const thumb = document.createElement('canvas');
      thumb.width = 48; thumb.height = 48; thumb.className = 'pixel-art';
      const tctx = thumb.getContext('2d');
      tctx.imageSmoothingEnabled = false;
      tctx.drawImage(img, 0, 0, 48, 48);
      const label = document.createElement('div');
      label.className = 'fp-timing-index';
      label.textContent = String(i);
      const input = document.createElement('input');
      input.type = 'number'; input.min = '1'; input.max = '60000'; input.step = '1';
      input.value = String(player.delays[i]);
      input.setAttribute('aria-label', `Frame ${i} delay (ms)`);
      inputs.push(input);
      cell.append(thumb, label, input);
      cell.addEventListener('click', (e) => { if (e.target !== input) player.seek(i); });
      grid.appendChild(cell);
    });
    box.appendChild(grid);

    const loopRow = document.createElement('label');
    loopRow.className = 'fp-timing-loop';
    const loopBox = document.createElement('input');
    loopBox.type = 'checkbox'; loopBox.checked = player.loop;
    loopRow.append(loopBox, document.createTextNode(' Loop'));
    const total = document.createElement('div');
    total.className = 'efl-range-readout';
    const values = () => inputs.map(el => Math.max(1, Math.min(60000, Math.round(Number(el.value) || 0))));
    const render = () => { total.innerHTML = `Total <b>${values().reduce((a, b) => a + b, 0)} ms</b>`; };
    grid.addEventListener('input', render);
    render();
    box.append(loopRow, total);

    const row = document.createElement('div');
    row.className = 'efl-modal-actions';
    const cancel = document.createElement('button');
    cancel.type = 'button'; cancel.className = 'btn-ghost'; cancel.textContent = 'Cancel';
    const ok = document.createElement('button');
    ok.type = 'button'; ok.className = 'btn-primary'; ok.textContent = 'Save';
    row.append(cancel, ok);
    box.append(row);
    overlay.append(box);
    document.body.appendChild(overlay);

    const close = (result) => { overlay.remove(); resolve(result); };
    cancel.addEventListener('click', () => close(null));
    ok.addEventListener('click', () => close({ delays: values(), loop: loopBox.checked }));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(null); });
    box.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(null); });
  });
}

async function editTiming(player) {
  if (!player || !player.ready) return;
  const wasPlaying = player.playing;
  player.pause();
  const edit = await modalTiming(player);
  if (!edit) { if (wasPlaying) player.play(); return; }
  const res = await fetch('/timing', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug: player.slug, animation: player.name, delays: edit.delays, loop: edit.loop }),
  });
  if (!res.ok) {
    toast(`Timing not saved: ${await res.text()}`, true);
    if (wasPlaying) player.play();
    return;
  }
  const body = await res.json();
  player.setDelays(edit.delays);
  player.setLoop(edit.loop);
  if (player.loopBox) player.loopBox.checked = edit.loop;
  toast(`Saved timing for ${player.name}: ${body.total_ms} ms total`);
  player.restart();
}

// ---- Event delegation ---------------------------------------------------
// No inline handlers anywhere: every interactive element carries a data-action
// (plus data-* payload) and is dispatched from these three delegated listeners,
// so the page needs no inline scripts and runs under a strict CSP.

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  switch (el.dataset.action) {
    case 'delete': deleteAsset(el.dataset.slug, el.dataset.filename); break;
    case 'rename': renameAsset(el.dataset.slug, el.dataset.filename); break;
    case 'play': playWithSound(el.dataset.img, el.dataset.audio); break;
    case 'unlink': unlinkSound(el.dataset.slug, el.dataset.animation, el.dataset.sound); break;
    case 'link': linkSound(el.dataset.slug, el.dataset.animation, el.dataset.select); break;
    case 'trim': trimSound(el.dataset.slug, el.dataset.sound, +el.dataset.duration, el.dataset.linkTo || ''); break;
    case 'gen-tab': genTab(el.dataset.kind); break;
    case 'gen-estimate': genEstimate(); break;
    case 'gen-confirm': genConfirm(); break;
    case 'new-actor': uploadNewActor(); break;
    case 'fp-toggle': playerFor(el)?.toggle(); break;
    case 'fp-step': playerFor(el)?.step(+el.dataset.dir); break;
    case 'fp-edit': editTiming(playerFor(el)); break;
  }
});

document.addEventListener('change', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  if (el.dataset.action === 'speed') setSpeed(el.dataset.img, el.dataset.slug, el.dataset.filename, el.value);
  else if (el.dataset.action === 'upload-files') uploadFiles(el.dataset.slug, el.files);
  else if (el.dataset.action === 'fp-speed') playerFor(el)?.setSpeed(el.value);
  else if (el.dataset.action === 'fp-loop') playerFor(el)?.setLoop(el.checked);
});

document.addEventListener('input', (e) => {
  const el = e.target.closest('[data-action="fp-scrub"]');
  if (el) playerFor(el)?.seek(+el.value);
});

document.addEventListener('input', (e) => { if (e.target.closest('.gen-form')) genDirty(); });
document.addEventListener('submit', (e) => { if (e.target.closest('.gen-form')) e.preventDefault(); });

document.addEventListener('DOMContentLoaded', () => { genInit(); initPlayers(); });
