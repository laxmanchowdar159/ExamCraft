// =====================================================================
// ExamCraft — Frontend Controller v4  (bug-fixed)
// =====================================================================

var curriculumData   = {};
var currentPaper     = '';
var currentAnswerKey = '';
var currentMeta      = {};

var compScope  = 'topic';   // 'topic' | 'subject' | 'all'
var boardScope = 'single';  // 'single' | 'all'

// ── Theme System ──────────────────────────────────────────────────────
const APP_THEMES = [
  { name: 'Violet',  accent: '#6d5bff', a2: '#9f8dff', a3: '#c4b8ff', glow: 'rgba(109,91,255,0.4)',  dim: 'rgba(109,91,255,0.12)', orb1:'#4c1d95', orb2:'#1e3a8a', orb3:'#0c4a6e', orb4:'#581c87', orb5:'#1e1b4b' },
  { name: 'Teal',    accent: '#14b8a6', a2: '#2dd4bf', a3: '#5eead4', glow: 'rgba(20,184,166,0.4)',  dim: 'rgba(20,184,166,0.12)',  orb1:'#134e4a', orb2:'#1e3a5f', orb3:'#0c4a3e', orb4:'#164e63', orb5:'#0f2027' },
  { name: 'Crimson', accent: '#e11d48', a2: '#fb7185', a3: '#fda4af', glow: 'rgba(225,29,72,0.4)',   dim: 'rgba(225,29,72,0.12)',   orb1:'#4c0519', orb2:'#3b0764', orb3:'#450a0a', orb4:'#4a044e', orb5:'#1c1917' },
  { name: 'Amber',   accent: '#d97706', a2: '#f59e0b', a3: '#fcd34d', glow: 'rgba(217,119,6,0.4)',   dim: 'rgba(217,119,6,0.12)',   orb1:'#451a03', orb2:'#1c1917', orb3:'#422006', orb4:'#3b1a04', orb5:'#1c0a00' },
  { name: 'Emerald', accent: '#059669', a2: '#10b981', a3: '#6ee7b7', glow: 'rgba(5,150,105,0.4)',   dim: 'rgba(5,150,105,0.12)',   orb1:'#064e3b', orb2:'#1e3a1e', orb3:'#052e16', orb4:'#14532d', orb5:'#022c22' },
  { name: 'Sky',     accent: '#0284c7', a2: '#38bdf8', a3: '#7dd3fc', glow: 'rgba(2,132,199,0.4)',   dim: 'rgba(2,132,199,0.12)',   orb1:'#0c4a6e', orb2:'#1e3a5f', orb3:'#0a3d62', orb4:'#164e63', orb5:'#0f2027' },
];

let appThemeIdx = 0;
let isDark = true;

function applyAppTheme(themeIdx, dark) {
  const t = APP_THEMES[themeIdx];
  const r = document.documentElement;
  r.style.setProperty('--accent',      t.accent);
  r.style.setProperty('--accent-2',    t.a2);
  r.style.setProperty('--accent-3',    t.a3);
  r.style.setProperty('--accent-glow', t.glow);
  r.style.setProperty('--accent-dim',  t.dim);
  if (dark) {
    r.style.setProperty('--orb1', t.orb1);
    r.style.setProperty('--orb2', t.orb2);
    r.style.setProperty('--orb3', t.orb3);
    r.style.setProperty('--orb4', t.orb4);
    r.style.setProperty('--orb5', t.orb5);
  }
  r.setAttribute('data-theme', dark ? 'dark' : 'light');
  const label = document.getElementById('themeLabel');
  if (label) label.textContent = t.name;
  try { localStorage.setItem('themeIdx', themeIdx); localStorage.setItem('themeDark', dark ? '1' : '0'); } catch {}
}

let _autoThemeTimer = null;
function startAppThemeRotation() {
  clearInterval(_autoThemeTimer);
  _autoThemeTimer = setInterval(() => {
    appThemeIdx = (appThemeIdx + 1) % APP_THEMES.length;
    applyAppTheme(appThemeIdx, isDark);
  }, 45000);
}

window.cycleTheme = function() {
  clearInterval(_autoThemeTimer);
  appThemeIdx = (appThemeIdx + 1) % APP_THEMES.length;
  applyAppTheme(appThemeIdx, isDark);
  showToast(`Theme: ${APP_THEMES[appThemeIdx].name}`);
  startAppThemeRotation();
};

window.toggleDark = function() {
  isDark = !isDark;
  applyAppTheme(appThemeIdx, isDark);
};
window.toggleTheme = window.toggleDark;

// ── Competitive exam info ─────────────────────────────────────────────
const COMP_INFO = {
  NTSE: { papers:'MAT (Mental Ability) + SAT (Sci 40Q + Social 40Q + Maths 20Q)', marks:'100 marks each', time:'2 Hours/paper', marking:'Stage 1: +1/0. Stage 2: +1/−⅓.', tip:'Select "MAT" as subject for the Mental Ability paper.' },
  NSO:  { papers:'Logical Reasoning (10Q) + Science (35Q) + Achiever\'s (5Q×3M)', marks:'60 marks', time:'1 Hour', marking:'No negative marking.', tip:'Select class and science chapter. Achiever\'s Section auto-generates as HOT questions.' },
  IMO:  { papers:'Logical Reasoning (10Q) + Maths (25Q) + Everyday Maths (10Q) + Achiever\'s (5Q×3M)', marks:'60 marks', time:'1 Hour', marking:'No negative marking.', tip:'Select class and maths chapter for a focused paper.' },
  IJSO: { papers:'Integrated Science: Physics (27Q) + Chemistry (27Q) + Biology (26Q)', marks:'80Q × +3/−1 = 240 max', time:'2 Hours', marking:'+3 correct, −1 wrong.', tip:'Select class and chapter, or Full Syllabus for a mixed paper.' },
};

// ── History ───────────────────────────────────────────────────────────
const HISTORY_KEY = 'examcraft_history_v2';
const HISTORY_MAX = 8;

function loadHistory() { try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); } catch { return []; } }
function saveHistory(h) { try { localStorage.setItem(HISTORY_KEY, JSON.stringify(h)); } catch {} }

function addToHistory(meta, paper, key) {
  const h = loadHistory();
  h.unshift({ id: Date.now(), timestamp: new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}), date: new Date().toLocaleDateString([],{day:'numeric',month:'short'}), ...meta, paper, answerKey: key });
  if (h.length > HISTORY_MAX) h.length = HISTORY_MAX;
  saveHistory(h); renderHistory();
}

function renderHistory() {
  const list = document.getElementById('historyList');
  if (!list) return;
  const h = loadHistory();
  if (!h.length) {
    list.innerHTML = `<div class="history-empty"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".35"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg><span>No papers yet</span></div>`;
    return;
  }
  list.innerHTML = h.map((e, idx) => `
    <div class="history-item">
      <div class="history-item-top">
        <div class="history-item-name">${e.subject || ''}${e.chapter && e.chapter !== 'Full Syllabus' ? ' · ' + e.chapter : ''}</div>
        <div class="history-item-time">${e.date}<br>${e.timestamp}</div>
      </div>
      <div class="history-item-meta">
        ${e.board ? `<span class="history-tag">${e.board.replace(' State Board','')}</span>` : ''}
        <span class="history-tag">${e.marks || '?'}M</span>
        <span class="history-tag">${e.difficulty || ''}</span>
      </div>
      <div class="history-item-btns">
        <button class="history-dl-btn paper" onclick="downloadFromHistory(${idx}, false)">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Paper PDF
        </button>
        ${e.answerKey ? `<button class="history-dl-btn key" onclick="downloadFromHistory(${idx}, true)">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg> + Key
        </button>` : ''}
      </div>
    </div>`).join('');
}

window.clearHistory = function() { try { localStorage.removeItem(HISTORY_KEY); } catch {} renderHistory(); showToast('History cleared'); };

async function downloadFromHistory(idx, withKey) {
  const e = loadHistory()[idx]; if (!e) return;
  await triggerPDFDownload({ paper: e.paper, answer_key: e.answerKey || '', subject: e.subject, chapter: e.chapter !== 'Full Syllabus' ? e.chapter : '', board: e.board, includeKey: withKey, marks: e.marks }, e.board, e.subject, e.chapter, withKey);
}

// ── Sidebar summary ───────────────────────────────────────────────────
function setSidebarValue(id, val) { const el = document.getElementById(id); if (el) el.textContent = val || '—'; }

function updateSidebar() {
  setSidebarValue('sb-class',   document.getElementById('class')?.value);
  setSidebarValue('sb-subject', document.getElementById('subject')?.value);
  setSidebarValue('sb-marks',   getTotalMarks());
  setSidebarValue('sb-difficulty', getDifficulty());
  setSidebarValue('sb-key', document.getElementById('includeKey')?.checked ? 'Yes' : 'No');

  const examType = document.getElementById('examType')?.value;
  let boardText = '';
  if (examType === 'state-board')      boardText = document.getElementById('stateSelect')?.value || '';
  else if (examType === 'competitive') boardText = document.getElementById('competitiveExam')?.value || '';
  setSidebarValue('sb-board', boardText);

  if (examType === 'state-board') {
    if (boardScope === 'all') { setSidebarValue('sb-scope', 'All Chapters'); setSidebarValue('sb-chapter', '—'); }
    else { setSidebarValue('sb-scope', 'One Chapter'); setSidebarValue('sb-chapter', document.getElementById('chapter')?.value || '—'); }
  } else if (examType === 'competitive') {
    if (compScope === 'all')     { setSidebarValue('sb-scope', 'All Subjects'); setSidebarValue('sb-chapter', '—'); }
    else if (compScope === 'subject') { setSidebarValue('sb-scope', 'Full Subject'); setSidebarValue('sb-chapter', '—'); }
    else { setSidebarValue('sb-scope', 'One Topic'); setSidebarValue('sb-chapter', document.getElementById('chapter')?.value || '—'); }
  } else {
    setSidebarValue('sb-scope', '—');
    setSidebarValue('sb-chapter', '—');
  }
}

// ── Marks helpers ─────────────────────────────────────────────────────
function getTotalMarks() {
  // Read from hidden input (reliable single source of truth)
  return document.getElementById('totalMarks')?.value || '100';
}

// ── Curriculum ────────────────────────────────────────────────────────
async function initCurriculum() {
  try {
    const res  = await fetch('/chapters');
    const json = await res.json();
    if (json.success && json.data) curriculumData = json.data;
  } catch { console.warn('Curriculum fetch failed'); }
  updateFormVisibility(); updateSidebar();
}

async function updateSubjects() {
  const cls      = document.getElementById('class')?.value;
  const examType = document.getElementById('examType')?.value;
  const compExam = document.getElementById('competitiveExam')?.value;
  const subjSel  = document.getElementById('subject');
  const chapSel  = document.getElementById('chapter');
  if (!subjSel) return;

  subjSel.innerHTML = '<option value="">Loading…</option>';
  if (chapSel) chapSel.innerHTML = '<option value="">Select topic…</option>';

  let lookupKey = cls || '10';
  if (examType === 'competitive' && compExam) lookupKey = compExam;
  if (!lookupKey) { subjSel.innerHTML = '<option value="">Select class first…</option>'; return; }

  if (!curriculumData[lookupKey]) {
    try {
      const res  = await fetch(`/chapters?class=${lookupKey}`);
      const json = await res.json();
      if (json.success && json.data) curriculumData[lookupKey] = json.data;
    } catch {}
  }

  const data = curriculumData[lookupKey];
  subjSel.innerHTML = '<option value="">Select subject…</option>';
  if (data) {
    Object.keys(data).forEach(s => {
      const opt = document.createElement('option');
      opt.value = s; opt.textContent = s; subjSel.appendChild(opt);
    });
  }
  updateSidebar();
}

function updateChapters() {
  const cls      = document.getElementById('class')?.value;
  const subj     = document.getElementById('subject')?.value;
  const chapSel  = document.getElementById('chapter');
  const examType = document.getElementById('examType')?.value;
  const compExam = document.getElementById('competitiveExam')?.value;
  if (!chapSel) return;

  let lookupKey = cls || '10';
  if (examType === 'competitive' && compExam) lookupKey = compExam;

  chapSel.innerHTML = '<option value="">Select topic…</option>';
  if (!subj || !curriculumData[lookupKey]) { updateSidebar(); return; }

  const chapters = curriculumData[lookupKey][subj] || [];
  chapters.forEach(ch => {
    const opt = document.createElement('option');
    opt.value = ch; opt.textContent = ch; chapSel.appendChild(opt);
  });
  updateSidebar();
}

// ── Form Visibility ───────────────────────────────────────────────────
function updateFormVisibility() {
  const examType = document.getElementById('examType')?.value;
  const stateC   = document.getElementById('stateCard');
  const compC    = document.getElementById('competitiveCard');
  const scopeC   = document.getElementById('scopeCard');
  const chapCard = document.getElementById('chapterCard');
  const subjCard = document.getElementById('subjectCard');
  const boardScopeRow = document.getElementById('boardScopeRow');
  const compScopeRow  = document.getElementById('compScopeRow');
  const chapterLabel  = document.getElementById('chapterLabel');

  if (stateC) stateC.classList.toggle('collapsed', examType !== 'state-board');
  if (compC)  compC.classList.toggle('collapsed',  examType !== 'competitive');

  if (scopeC) {
    scopeC.classList.toggle('collapsed', !examType);
    if (boardScopeRow) boardScopeRow.style.display = (examType === 'state-board')  ? '' : 'none';
    if (compScopeRow)  compScopeRow.style.display  = (examType === 'competitive') ? '' : 'none';
  }

  if (examType === 'state-board') {
    if (subjCard) subjCard.style.display = '';
    if (chapCard) chapCard.style.display = boardScope === 'single' ? '' : 'none';
    if (chapterLabel) chapterLabel.textContent = 'Chapter';
    const subjLabel = document.getElementById('subjectLabel');
    if (subjLabel) subjLabel.textContent = 'Subject';
  } else if (examType === 'competitive') {
    if (subjCard) subjCard.style.display = '';
    if (chapCard) chapCard.style.display = compScope === 'topic' ? '' : 'none';
    if (chapterLabel) chapterLabel.textContent = 'Topic';
    const subjLabel = document.getElementById('subjectLabel');
    if (subjLabel) subjLabel.textContent = compScope === 'all' ? 'Subject (optional)' : 'Subject / Paper';
  } else {
    if (subjCard) subjCard.style.display = '';
    if (chapCard) chapCard.style.display = '';
  }
}

// ── Paper Type Selection ──────────────────────────────────────────────
// BUG FIX: was querying '.type-tile' (doesn't exist) — now '.type-card'
window.selectType = function(val) {
  document.querySelectorAll('.type-card').forEach(t => t.classList.remove('active'));
  const tile = document.getElementById(val === 'state-board' ? 'tile-state' : 'tile-comp');
  if (tile) tile.classList.add('active');
  document.getElementById('examType').value = val;

  if (val === 'state-board') {
    boardScope = 'single';
    document.getElementById('scopeSelect').value = 'single';
    document.querySelectorAll('#boardScopeRow .scope-card').forEach(b => b.classList.remove('active'));
    const def = document.getElementById('bscope-single'); if (def) def.classList.add('active');
    setHint('Select Andhra Pradesh or Telangana, then choose paper scope.');
  } else {
    compScope = 'topic';
    document.getElementById('scopeSelect').value = 'single';
    document.querySelectorAll('#compScopeRow .scope-card').forEach(b => b.classList.remove('active'));
    const def = document.getElementById('cscope-topic'); if (def) def.classList.add('active');
    setHint('Select competitive exam, then choose how broad the paper should be.');
  }

  updateFormVisibility();
  updateSubjects();
  updateSidebar();
};

// ── Board Scope ───────────────────────────────────────────────────────
window.selectBoardScope = function(val) {
  boardScope = val;
  document.getElementById('scopeSelect').value = val === 'all' ? 'all' : 'single';
  document.querySelectorAll('#boardScopeRow .scope-card').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById(val === 'all' ? 'bscope-all' : 'bscope-single');
  if (btn) btn.classList.add('active');
  updateFormVisibility();
  applySmartMarkDefault(val);
  updateSidebar();
  setHint(val === 'all' ? 'Full syllabus — select subject and class.' : 'One chapter — select subject and specific chapter.');
};

// ── Competitive Scope ─────────────────────────────────────────────────
window.selectCompScope = function(val) {
  compScope = val;
  document.getElementById('scopeSelect').value = val === 'all' ? 'all' : 'single';
  document.querySelectorAll('#compScopeRow .scope-card').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById(`cscope-${val}`);
  if (btn) btn.classList.add('active');
  updateFormVisibility();
  updateSidebar();
  const hints = {
    topic:   'One Topic — choose a subject and specific topic for a focused paper.',
    subject: 'Full Subject — choose a subject; all its topics will be covered.',
    all:     'All Subjects — complete syllabus paper across all subjects.',
  };
  setHint(hints[val] || '');
};

// ── Competitive Info Box ──────────────────────────────────────────────
function updateCompInfo() {
  const exam    = document.getElementById('competitiveExam')?.value;
  const infoBox = document.getElementById('compInfoBox');
  const infoTxt = document.getElementById('compInfoText');
  if (!infoBox || !infoTxt) return;
  if (!exam || !COMP_INFO[exam]) { infoBox.style.display = 'none'; return; }
  const info = COMP_INFO[exam];
  infoTxt.innerHTML = `<b>${exam}</b>: ${info.papers}<br>
    <span style="opacity:.8">Marks: ${info.marks} · Time: ${info.time} · ${info.marking}</span><br>
    <span style="color:var(--accent-2)">💡 ${info.tip}</span>`;
  infoBox.style.display = 'block';
  updateSubjects().then(() => updateChapters());
}

// ── Class/Subject change handlers ─────────────────────────────────────
window.onClassChange   = async function() { await updateSubjects(); updateFormVisibility(); updateSidebar(); };
window.onSubjectChange = function() { updateChapters(); updateSidebar(); };

// ── Difficulty ────────────────────────────────────────────────────────
function getDifficulty() {
  const el = document.querySelector('input[name="difficulty"]:checked');
  return el ? el.value : 'Medium';
}
window.selectDiff = function(val, btn) {
  document.querySelectorAll('.diff-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const radioId = val === 'Easy' ? 'r-easy' : val === 'Medium' ? 'r-med' : 'r-hard';
  const radio = document.getElementById(radioId);
  if (radio) radio.checked = true;
  updateSidebar();
};

// ── Marks ─────────────────────────────────────────────────────────────
window.selectMark = function(btn) {
  document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  const cw = document.getElementById('customMarkWrap');
  if (cw) cw.style.display = 'none';
  document.getElementById('totalMarks').value = btn.dataset.val;
  updateSidebar();
};

window.toggleCustomMark = function(btn) {
  document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  const cw = document.getElementById('customMarkWrap');
  const ci = document.getElementById('customMarkInput');
  if (cw) { cw.style.display = 'flex'; if (ci) ci.focus(); }
};

window.applyCustomMark = function(val) {
  const num = parseInt(val, 10);
  if (num > 0) { document.getElementById('totalMarks').value = num; updateSidebar(); }
};

function applySmartMarkDefault(scope) {
  // Don't override if custom is selected
  const customChip = document.getElementById('chipCustom');
  if (customChip && customChip.classList.contains('active')) return;

  const target = '100';
  document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
  const cw = document.getElementById('customMarkWrap');
  if (cw) cw.style.display = 'none';
  const chip = document.querySelector(`.chip[data-val="${target}"]`);
  if (chip) chip.classList.add('active');
  document.getElementById('totalMarks').value = target;
  updateSidebar();
}

// ── Loading modal ─────────────────────────────────────────────────────
let _stepInterval = null;
function showLoading(show, titleText) {
  const modal = document.getElementById('loadingModal');
  if (!modal) return;
  modal.style.display = show ? 'flex' : 'none';
  if (titleText) { const t = document.getElementById('loaderTitle'); if (t) t.textContent = titleText; }
  clearInterval(_stepInterval);
  if (show) {
    const ids    = ['ls1','ls2','ls3','ls4','ls5'];
    const delays = [0, 5000, 12000, 19000, 28000];
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.remove('active','done');
    });
    const el0 = document.getElementById(ids[0]);
    if (el0) el0.classList.add('active');
    ids.slice(1).forEach((id, idx) => {
      setTimeout(() => {
        const prev = document.getElementById(ids[idx]);
        if (prev) { prev.classList.remove('active'); prev.classList.add('done'); }
        const cur = document.getElementById(id);
        if (cur) cur.classList.add('active');
      }, delays[idx + 1]);
    });
  }
}

// ── Toast / Hint ──────────────────────────────────────────────────────
function showToast(msg) {
  const toast = document.getElementById('notificationToast');
  if (!toast) return;
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 3500);
}
function setHint(text) { const el = document.getElementById('hintText'); if (el) el.textContent = text; }

// ── Preview Tabs ──────────────────────────────────────────────────────
window.switchPreviewTab = function(tab, btn) {
  document.querySelectorAll('.ptab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-paper').style.display = tab === 'paper' ? 'block' : 'none';
  document.getElementById('tab-key').style.display   = tab === 'key'   ? 'block' : 'none';
};

// ── Generate ──────────────────────────────────────────────────────────
async function generatePaper() {
  const examType = document.getElementById('examType')?.value;
  if (!examType) { showToast('Please select a paper type first'); return; }

  const cls        = document.getElementById('class')?.value;
  const subject    = document.getElementById('subject')?.value;
  const chapter    = document.getElementById('chapter')?.value;
  const marks      = getTotalMarks();
  const difficulty = getDifficulty();
  const suggestions = document.getElementById('suggestions')?.value || '';

  const payload = {
    class: cls, subject, marks, difficulty, suggestions, examType,
    includeKey: document.getElementById('includeKey')?.checked || false
  };

  if (examType === 'state-board') {
    payload.state = document.getElementById('stateSelect')?.value || '';
    if (!payload.state)   { showToast('Please select a state board'); return; }
    if (!cls)             { showToast('Please select a class'); return; }
    if (!subject)         { showToast('Please select a subject'); return; }
    if (boardScope === 'single') {
      if (!chapter) { showToast('Please select a chapter'); return; }
      payload.chapter = chapter;
    } else {
      payload.chapter = '';
      payload.all_chapters = true;
    }
    payload.scope = boardScope;
  }

  if (examType === 'competitive') {
    payload.competitiveExam = document.getElementById('competitiveExam')?.value || '';
    if (!payload.competitiveExam) { showToast('Please select a competitive exam'); return; }
    if (!cls) { showToast('Please select a class'); return; }
    if (compScope === 'topic') {
      if (!subject) { showToast('Please select a subject'); return; }
      if (!chapter) { showToast('Please select a topic'); return; }
      payload.chapter = chapter;
    } else if (compScope === 'subject') {
      if (!subject) { showToast('Please select a subject'); return; }
      payload.chapter = '';
    } else {
      payload.subject = subject || '';
      payload.chapter = '';
      payload.all_chapters = true;
    }
    payload.scope = compScope;
  }

  showLoading(true, 'Crafting your paper…');
  setHint('Generating — usually 25-50 seconds…');

  try {
    const res    = await fetch('/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const result = await res.json();
    showLoading(false);

    if (!result.success) {
      showToast(result.error || 'Generation failed — please try again');
      setHint('Something went wrong. Check selections and try again.');
      return;
    }

    currentPaper     = result.paper     || '';
    currentAnswerKey = result.answer_key || '';

    const boardText = result.board || payload.state || payload.competitiveExam || '';
    currentMeta = {
      board: boardText,
      subject: payload.subject || result.subject || '',
      chapter: payload.chapter || result.chapter || 'Full Syllabus',
      marks, difficulty
    };

    const paperOut = document.getElementById('paperOutput');
    const keyOut   = document.getElementById('answerKeyOutput');
    if (paperOut) paperOut.value = currentPaper;
    if (keyOut)   keyOut.value   = currentAnswerKey;

    const keyTab = document.getElementById('ptab-key');
    if (keyTab) keyTab.style.display = currentAnswerKey ? 'inline-flex' : 'none';

    const panel = document.getElementById('resultsPanel');
    if (panel) {
      panel.style.display = 'block';
      setTimeout(() => panel.scrollIntoView({ behavior: 'smooth', block: 'start' }), 120);
    }

    setHint('Paper ready! Review below, then Download PDF.');
    showToast('Paper generated! ✓');
    addToHistory(currentMeta, currentPaper, currentAnswerKey);
  } catch (err) {
    showLoading(false);
    showToast('Server error: ' + err.message);
  }
}

// ── PDF Download ──────────────────────────────────────────────────────
async function triggerPDFDownload(payload, board, subject, chapter, withKey) {
  showLoading(true, 'Rendering PDF…');
  try {
    const res = await fetch('/download-pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      let errMsg = `Server error ${res.status}`;
      try { const j = await res.json(); errMsg = j.error || errMsg; } catch {}
      showToast('PDF error: ' + errMsg); showLoading(false); return;
    }
    const blob = await res.blob();
    if (blob.size === 0) { showToast('PDF was empty — try regenerating'); showLoading(false); return; }
    const url = URL.createObjectURL(blob);
    const a   = document.createElement('a');
    const safe = [board, subject, chapter || 'Paper'].filter(Boolean).join('_').replace(/\s+/g,'_').replace(/[\/\\:*?"<>|]/g,'-');
    a.href = url; a.download = safe + (withKey ? '_with_key' : '') + '.pdf';
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    showLoading(false); showToast('PDF downloaded ✓');
  } catch (err) {
    showLoading(false); showToast('Download failed: ' + err.message);
  }
}

window.downloadPDF = async function(withKey) {
  if (!currentPaper?.trim()) { showToast('Generate a paper first'); return; }
  const includeKey = withKey === true ? true : withKey === false ? false : (document.getElementById('includeKey')?.checked || false);
  await triggerPDFDownload(
    {
      paper: currentPaper,
      answer_key: currentAnswerKey || '',
      subject: currentMeta.subject,
      chapter: currentMeta.chapter !== 'Full Syllabus' ? currentMeta.chapter : '',
      board: currentMeta.board,
      includeKey,
      marks: currentMeta.marks
    },
    currentMeta.board, currentMeta.subject, currentMeta.chapter, includeKey
  );
};

function copyPaper() {
  if (!currentPaper) { showToast('Nothing to copy'); return; }
  navigator.clipboard.writeText(currentPaper).then(() => showToast('Copied ✓')).catch(() => showToast('Copy failed'));
}

// ── Init ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Restore theme
  let savedIdx  = 0, savedDark = true;
  try {
    savedIdx  = parseInt(localStorage.getItem('themeIdx') || '0', 10);
    savedDark = localStorage.getItem('themeDark') !== '0';
  } catch {}
  appThemeIdx = Math.min(savedIdx, APP_THEMES.length - 1);
  isDark = savedDark;
  applyAppTheme(appThemeIdx, isDark);
  startAppThemeRotation();

  renderHistory();
  initCurriculum();

  document.getElementById('paperForm')?.addEventListener('submit', e => { e.preventDefault(); generatePaper(); });

  // Set initial state
  updateFormVisibility();
  updateSidebar();
  applySmartMarkDefault('single');
});
