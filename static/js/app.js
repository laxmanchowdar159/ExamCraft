/* ═══════════════════════════════════════════════════════════════
   ExamCraft — app.js
   Plain vanilla JS. No animation library, no particle system.
   State lives in a few module-level variables; the DOM is the
   only "framework".
   ═══════════════════════════════════════════════════════════════ */

const state = {
  examType: 'state-board',     // 'state-board' | 'competitive'
  boardScope: 'single',        // 'single' | 'all'
  compScope: 'topic',          // 'topic' | 'subject' | 'all'
  marks: 100,
  difficulty: 'Medium',
};

let curriculum = {};
let currentPaper = '';
let currentAnswerKey = '';
let currentMeta = {};
let pdfDirect = null; // { paper: b64|null, withKey: b64|null, ... }

const $ = (id) => document.getElementById(id);

/* ── Toast ─────────────────────────────────────────────────────── */
let toastTimer = null;
function toast(msg) {
  const el = $('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
}

/* ── Exam type / scope segmented controls ─────────────────────── */
function wireSegGroup(containerId, attr, onSelect) {
  const container = $(containerId);
  if (!container) return;
  container.querySelectorAll('.seg-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      onSelect(btn.dataset[attr]);
    });
  });
}

wireSegGroup('examTypeSeg', 'examType', (val) => {
  state.examType = val;
  $('stateField').classList.toggle('is-hidden', val !== 'state-board');
  $('compField').classList.toggle('is-hidden', val !== 'competitive');
  $('boardScopeSeg').classList.toggle('is-hidden', val !== 'state-board');
  $('compScopeSeg').classList.toggle('is-hidden', val !== 'competitive');
  $('chapterLabel').textContent = val === 'competitive' ? 'Topic' : 'Chapter';
  $('subjectLabel').textContent = val === 'competitive' ? 'Subject / Paper' : 'Subject';
  updateSubjects();
  updateFormVisibility();
});

wireSegGroup('boardScopeSeg', 'scope', (val) => {
  state.boardScope = val;
  applySmartMarksDefault();
  updateFormVisibility();
});

wireSegGroup('compScopeSeg', 'compScope', (val) => {
  state.compScope = val;
  applySmartMarksDefault();
  updateFormVisibility();
});

function updateFormVisibility() {
  const { examType, boardScope, compScope } = state;
  const subjectPart = $('subjectPart');
  const subjectField = $('subjectField');
  const chapterField = $('chapterField');

  if (examType === 'state-board') {
    subjectPart.classList.remove('is-hidden');
    subjectField.style.display = '';
    chapterField.style.display = boardScope === 'single' ? '' : 'none';
  } else {
    subjectPart.classList.remove('is-hidden');
    subjectField.style.display = compScope === 'all' ? 'none' : '';
    chapterField.style.display = compScope === 'topic' ? '' : 'none';
  }
}

/* ── Marks chips ───────────────────────────────────────────────── */
$('marksChips').addEventListener('click', (e) => {
  const chip = e.target.closest('.chip[data-marks]');
  if (!chip) return;
  $('marksChips').querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
  chip.classList.add('active');
  $('marksCustom').value = '';
  state.marks = parseInt(chip.dataset.marks, 10);
  $('marksPreview').textContent = state.marks;
});
$('marksCustom').addEventListener('input', (e) => {
  const v = parseInt(e.target.value, 10);
  if (!v) return;
  $('marksChips').querySelectorAll('.chip[data-marks]').forEach(c => c.classList.remove('active'));
  state.marks = Math.max(10, Math.min(200, v));
  $('marksPreview').textContent = state.marks;
});

function applySmartMarksDefault() {
  const isFullScope = (state.examType === 'state-board' && state.boardScope === 'all')
                    || (state.examType === 'competitive' && state.compScope !== 'topic');
  const target = isFullScope ? 100 : 50;
  const chip = $('marksChips').querySelector(`.chip[data-marks="${target}"]`);
  if (chip) {
    $('marksChips').querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    $('marksCustom').value = '';
    state.marks = target;
    $('marksPreview').textContent = target;
  }
}

/* ── Difficulty chips ─────────────────────────────────────────── */
$('diffChips').addEventListener('click', (e) => {
  const chip = e.target.closest('.chip[data-diff]');
  if (!chip) return;
  $('diffChips').querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
  chip.classList.add('active');
  state.difficulty = chip.dataset.diff;
});

/* ── Special instructions toggle ─────────────────────────────────*/
$('moreToggle').addEventListener('click', () => {
  const panel = $('morePanel');
  const open = panel.classList.toggle('open');
  $('moreToggle').textContent = open ? '− Hide special instructions' : '+ Add special instructions for the AI';
});

/* ── Curriculum data ──────────────────────────────────────────── */
async function loadCurriculumFor(key) {
  if (curriculum[key]) return curriculum[key];
  try {
    const res = await fetch(`/chapters?class=${encodeURIComponent(key)}`);
    const json = await res.json();
    if (json.success && json.data) {
      curriculum[key] = json.data;
      return json.data;
    }
  } catch { /* offline — leave selects empty, form still submits */ }
  return null;
}

async function updateSubjects() {
  const subjSel = $('subjectSelect');
  const chapSel = $('chapterSelect');
  const cls = $('classSelect').value;
  const compExam = $('competitiveExam').value;

  const lookupKey = (state.examType === 'competitive' && compExam) ? compExam : cls;
  if (!lookupKey) {
    subjSel.innerHTML = '<option value="">Select class first…</option>';
    chapSel.innerHTML = '<option value="">Select subject first…</option>';
    return;
  }

  subjSel.innerHTML = '<option value="">Loading…</option>';
  const data = await loadCurriculumFor(lookupKey);
  subjSel.innerHTML = '<option value="">Select subject…</option>';
  if (data) {
    Object.keys(data).forEach(s => {
      const opt = document.createElement('option');
      opt.value = s; opt.textContent = s;
      subjSel.appendChild(opt);
    });
  }
  updateChapters();
}

function updateChapters() {
  const chapSel = $('chapterSelect');
  const cls = $('classSelect').value;
  const compExam = $('competitiveExam').value;
  const subj = $('subjectSelect').value;
  const lookupKey = (state.examType === 'competitive' && compExam) ? compExam : cls;

  chapSel.innerHTML = '<option value="">Select topic…</option>';
  const data = curriculum[lookupKey];
  if (!subj || !data || !data[subj]) return;
  data[subj].forEach(ch => {
    const opt = document.createElement('option');
    opt.value = ch; opt.textContent = ch;
    chapSel.appendChild(opt);
  });
}

$('classSelect').addEventListener('change', updateSubjects);
$('competitiveExam').addEventListener('change', updateSubjects);
$('subjectSelect').addEventListener('change', updateChapters);

/* ── Loading overlay ──────────────────────────────────────────── */
let loadingTimer = null;
let loadingStart = 0;
const LOADING_STEPS = [
  { at: 0,  step: 1 },
  { at: 1,  step: 2 },
  { at: 20, step: 3 },
  { at: 30, step: 4 },
];
const TYPICAL_SECONDS = 32; // rough sum of the backend's own time budgets

function showLoading(show) {
  const overlay = $('loadingOverlay');
  if (show) {
    overlay.classList.add('show');
    loadingStart = Date.now();
    setLoadingStep(1);
    $('inkBarFill').style.width = '4%';
    loadingTimer = setInterval(tickLoading, 250);
  } else {
    overlay.classList.remove('show');
    clearInterval(loadingTimer);
  }
}

function tickLoading() {
  const elapsedMs = Date.now() - loadingStart;
  const elapsedS = elapsedMs / 1000;
  $('elapsedTime').textContent = formatClock(elapsedS);

  const pct = Math.min(96, (elapsedS / TYPICAL_SECONDS) * 100);
  $('inkBarFill').style.width = pct + '%';

  let step = 1;
  for (const s of LOADING_STEPS) if (elapsedS >= s.at) step = s.step;
  setLoadingStep(step);
}

function setLoadingStep(n) {
  document.querySelectorAll('.loading-step').forEach(el => {
    const s = parseInt(el.dataset.step, 10);
    el.classList.toggle('active', s === n);
    el.classList.toggle('done', s < n);
  });
}

function formatClock(totalSeconds) {
  const m = Math.floor(totalSeconds / 60);
  const s = Math.floor(totalSeconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

/* ── Generate ─────────────────────────────────────────────────── */
$('generateBtn').addEventListener('click', generatePaper);

function buildPayload() {
  const cls = $('classSelect').value;
  const subject = $('subjectSelect').value;
  const chapter = $('chapterSelect').value;
  const suggestions = $('suggestions').value || '';

  const payload = {
    class: cls, subject, marks: String(state.marks), difficulty: state.difficulty,
    suggestions, examType: state.examType,
  };

  if (state.examType === 'state-board') {
    payload.state = $('stateSelect').value || '';
    if (!payload.state) return { error: 'Please choose a state board.' };
    if (!cls) return { error: 'Please select a class.' };
    if (!subject) return { error: 'Please select a subject.' };
    if (state.boardScope === 'single') {
      if (!chapter) return { error: 'Please select a chapter.' };
      payload.chapter = chapter;
    } else {
      payload.chapter = '';
      payload.all_chapters = true;
    }
    payload.scope = state.boardScope;
  } else {
    payload.competitiveExam = $('competitiveExam').value || '';
    if (!payload.competitiveExam) return { error: 'Please choose a competitive exam.' };
    if (!cls) return { error: 'Please select a class.' };
    if (state.compScope === 'topic') {
      if (!subject) return { error: 'Please select a subject.' };
      if (!chapter) return { error: 'Please select a topic.' };
      payload.chapter = chapter;
    } else if (state.compScope === 'subject') {
      if (!subject) return { error: 'Please select a subject.' };
      payload.chapter = '';
    } else {
      payload.chapter = '';
      payload.all_chapters = true;
    }
    payload.scope = state.compScope;
  }
  return { payload };
}

async function generatePaper() {
  const { payload, error } = buildPayload();
  if (error) { toast(error); return; }

  const btn = $('generateBtn');
  btn.disabled = true;
  $('generateBtnLabel').textContent = 'Generating…';
  showLoading(true);

  try {
    const res = await fetch('/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = await res.json();
    showLoading(false);

    if (!result.success) {
      toast(result.error || 'Generation failed — please try again.');
      return;
    }

    currentPaper = result.paper || '';
    currentAnswerKey = result.answer_key || '';
    const boardText = result.board || payload.state || payload.competitiveExam || '';
    currentMeta = {
      board: boardText,
      subject: payload.subject || result.subject || '',
      chapter: payload.chapter || result.chapter || 'Full Syllabus',
      marks: payload.marks,
      difficulty: state.difficulty,
      class: payload.class || '',
    };
    pdfDirect = {
      paper: result.pdf_b64 || null,
      withKey: result.pdf_key_b64 || null,
      board: boardText, subject: currentMeta.subject, chapter: currentMeta.chapter,
    };

    addToHistory(currentMeta, currentPaper, currentAnswerKey);
    renderResult();

    if (pdfDirect.paper) {
      downloadBase64(pdfDirect.paper, safeFilename(pdfDirect, false));
      toast('Paper generated and downloaded ✓');
    } else if (result.pdf_error) {
      toast('Paper generated, but the PDF failed to render — use Download to retry.');
    }
  } catch (err) {
    showLoading(false);
    toast('Server error: ' + err.message);
  } finally {
    btn.disabled = false;
    $('generateBtnLabel').textContent = 'Generate paper';
  }
}

/* ── Result panel ─────────────────────────────────────────────── */
function renderResult() {
  $('resultEmpty').style.display = 'none';
  $('resultFilled').style.display = '';
  // restart the stamp animation
  const stamp = $('resultStamp');
  stamp.style.animation = 'none';
  void stamp.offsetWidth;
  stamp.style.animation = '';

  $('resultTitle').textContent = `${currentMeta.subject || 'Paper'} — ${currentMeta.marks} marks`;
  $('resultSub').textContent = [currentMeta.board, currentMeta.chapter !== 'Full Syllabus' ? currentMeta.chapter : 'Full syllabus', currentMeta.difficulty].filter(Boolean).join(' · ');

  $('downloadKeyBtn').disabled = !currentAnswerKey;
  setPreviewTab('paper');
}

function setPreviewTab(tab) {
  document.querySelectorAll('.preview-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  $('previewBody').textContent = tab === 'key' ? (currentAnswerKey || 'No answer key available.') : (currentPaper || '');
}
document.querySelectorAll('.preview-tab').forEach(t => t.addEventListener('click', () => setPreviewTab(t.dataset.tab)));

/* ── Downloads ────────────────────────────────────────────────── */
function downloadBase64(b64, filename) {
  try {
    const bin = atob(b64);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([buf], { type: 'application/pdf' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: filename });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    return true;
  } catch (e) {
    toast('Download error: ' + e.message);
    return false;
  }
}

function safeFilename(d, withKey) {
  const base = [d.board, d.subject, (d.chapter && d.chapter !== 'Full Syllabus') ? d.chapter : null]
    .filter(Boolean).join('_').replace(/\s+/g, '_').replace(/[\/\\:*?"<>|]/g, '-') || 'ExamPaper';
  return base + (withKey ? '_with_key' : '') + '.pdf';
}

async function downloadViaServer(withKey) {
  if (!currentPaper.trim()) { toast('Generate a paper first.'); return; }
  toast('Rendering PDF…');
  try {
    const res = await fetch('/download-pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        paper: currentPaper, answer_key: currentAnswerKey || '',
        subject: currentMeta.subject,
        chapter: currentMeta.chapter !== 'Full Syllabus' ? currentMeta.chapter : '',
        board: currentMeta.board, includeKey: !!withKey, marks: currentMeta.marks,
      }),
    });
    if (!res.ok) {
      let msg = `Server error ${res.status}`;
      try { msg = (await res.json()).error || msg; } catch {}
      toast('PDF error: ' + msg);
      return;
    }
    const blob = await res.blob();
    if (!blob.size) { toast('PDF was empty — try regenerating.'); return; }
    const url = URL.createObjectURL(blob);
    Object.assign(document.createElement('a'), {
      href: url, download: safeFilename(currentMeta, withKey),
    }).click();
    URL.revokeObjectURL(url);
    toast('PDF downloaded ✓');
  } catch (err) {
    toast('Download failed: ' + err.message);
  }
}

$('downloadPaperBtn').addEventListener('click', () => {
  if (pdfDirect && pdfDirect.paper) { downloadBase64(pdfDirect.paper, safeFilename(pdfDirect, false)); toast('Paper downloaded ✓'); return; }
  downloadViaServer(false);
});
$('downloadKeyBtn').addEventListener('click', () => {
  if (pdfDirect && pdfDirect.withKey) { downloadBase64(pdfDirect.withKey, safeFilename(pdfDirect, true)); toast('Answer key PDF downloaded ✓'); return; }
  downloadViaServer(true);
});
$('copyBtn').addEventListener('click', () => {
  if (!currentPaper) { toast('Nothing to copy.'); return; }
  navigator.clipboard.writeText(currentPaper).then(() => toast('Copied ✓')).catch(() => toast('Copy failed.'));
});

/* ── History (localStorage) ──────────────────────────────────── */
const HISTORY_KEY = 'ec_history_v1';
const HISTORY_MAX = 10;
const pKey = id => 'ec_p_' + id;
const kKey = id => 'ec_k_' + id;

function loadHistory() {
  try {
    const meta = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    return meta.map(m => ({ ...m, paper: localStorage.getItem(pKey(m.id)) || '', key: localStorage.getItem(kKey(m.id)) || '' }));
  } catch { return []; }
}

function addToHistory(meta, paper, key) {
  let list = [];
  try { list = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); } catch {}
  const id = 'p' + Date.now();
  list.unshift({ id, ...meta, ts: Date.now() });
  const removed = list.splice(HISTORY_MAX);
  removed.forEach(r => { localStorage.removeItem(pKey(r.id)); localStorage.removeItem(kKey(r.id)); });
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(list));
    localStorage.setItem(pKey(id), paper || '');
    localStorage.setItem(kKey(id), key || '');
  } catch { /* storage full — history is best-effort */ }
  bumpLifetime();
  renderHistory();
}

function bumpLifetime() {
  try {
    const n = parseInt(localStorage.getItem('ec_lifetime') || '0', 10) + 1;
    localStorage.setItem('ec_lifetime', String(n));
    $('lifetimeLine').textContent = `${n} paper${n === 1 ? '' : 's'} generated on this device`;
  } catch {}
}

function renderHistory() {
  const list = loadHistory();
  const el = $('historyList');
  if (!list.length) { el.innerHTML = '<div class="history-empty">No papers generated yet on this device.</div>'; return; }
  el.innerHTML = '';
  list.forEach((item, idx) => {
    const row = document.createElement('div');
    row.className = 'history-item';
    row.innerHTML = `
      <div>
        <div class="history-item-title">${escapeHtml(item.subject || 'Paper')} · ${escapeHtml(String(item.marks || ''))}m</div>
        <div class="history-item-sub">${escapeHtml([item.board, item.chapter].filter(Boolean).join(' · '))}</div>
      </div>
      <button type="button" data-idx="${idx}">Load</button>
    `;
    row.querySelector('button').addEventListener('click', (e) => {
      e.stopPropagation();
      currentPaper = item.paper; currentAnswerKey = item.key; currentMeta = item;
      pdfDirect = null;
      renderResult();
    });
    el.appendChild(row);
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

$('clearHistoryBtn').addEventListener('click', () => {
  const list = loadHistory();
  list.forEach(item => { localStorage.removeItem(pKey(item.id)); localStorage.removeItem(kKey(item.id)); });
  localStorage.removeItem(HISTORY_KEY);
  renderHistory();
  toast('History cleared.');
});

/* ── Init ─────────────────────────────────────────────────────── */
(function init() {
  updateFormVisibility();
  renderHistory();
  const n = parseInt(localStorage.getItem('ec_lifetime') || '0', 10);
  $('lifetimeLine').textContent = `${n} paper${n === 1 ? '' : 's'} generated on this device`;
})();
