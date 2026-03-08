/* ── Font Switcher ─────────────────────────────────────────── */
const FONT_MODES = [
  { id:'serif', label:'Serif', font:"'Cormorant Garamond', Georgia, serif" },
  { id:'sans',  label:'Sans',  font:"'Inter','Segoe UI',system-ui,sans-serif" },
  { id:'mono',  label:'Mono',  font:"'Space Mono','Courier New',monospace" },
];
let fontIdx = 0;

function applyFont(idx) {
  const f = FONT_MODES[idx];
  document.documentElement.setAttribute('data-font', f.id);
  document.documentElement.style.setProperty('--serif', f.font);
  const lbl = document.getElementById('fontLabel');
  const icon = document.getElementById('fontIcon');
  if (lbl) lbl.textContent = f.label;
  if (icon) { icon.style.fontFamily = f.font; icon.textContent = 'Aa'; }
  try { localStorage.setItem('fontIdx', idx); } catch {}
}

window.cycleFontMode = function() {
  fontIdx = (fontIdx + 1) % FONT_MODES.length;
  applyFont(fontIdx);
  showToast('Font: ' + FONT_MODES[fontIdx].label);
};

/* ═══════════════════════════════════════════════════════════════
   ExamCraft — Frontend Controller v5
   All original logic preserved + UI enhancement layer
═══════════════════════════════════════════════════════════════ */

var curriculumData   = {};
var currentPaper     = '';
var currentAnswerKey = '';
var currentMeta      = {};

var compScope  = 'topic';   // 'topic' | 'subject' | 'all'
var boardScope = 'single';  // 'single' | 'all'

/* ── Theme System ──────────────────────────────────────────── */
const APP_THEMES = [
  { name:'Gold',    accent:'#C8A96E', a2:'#E2C98A', a3:'#F0DFB0', glow:'rgba(200,169,110,.35)', dim:'rgba(200,169,110,.10)', orb1:'#1a1008', orb2:'#120c05', orb3:'#0d0d0a', orb4:'#180808', orb5:'#080d15' },
  { name:'Copper',  accent:'#B87348', a2:'#D49060', a3:'#E8B890', glow:'rgba(184,115,72,.35)',  dim:'rgba(184,115,72,.10)',  orb1:'#180c06', orb2:'#120805', orb3:'#0f0a06', orb4:'#1a0c04', orb5:'#0a0d12' },
  { name:'Silver',  accent:'#A0A8B8', a2:'#C0C8D8', a3:'#D8DDE8', glow:'rgba(160,168,184,.30)', dim:'rgba(160,168,184,.10)', orb1:'#0e1018', orb2:'#0a0c14', orb3:'#0c0e12', orb4:'#10121a', orb5:'#080a10' },
  { name:'Crimson', accent:'#C04848', a2:'#D87070', a3:'#E8A0A0', glow:'rgba(192,72,72,.32)',   dim:'rgba(192,72,72,.10)',   orb1:'#200808', orb2:'#180405', orb3:'#180308', orb4:'#1a0505', orb5:'#0a0a14' },
  { name:'Jade',    accent:'#5A9A7A', a2:'#7AC09A', a3:'#A0D8B8', glow:'rgba(90,154,122,.32)',  dim:'rgba(90,154,122,.10)',  orb1:'#081410', orb2:'#060e0a', orb3:'#081210', orb4:'#0a1810', orb5:'#060c08' },
  { name:'Ink',     accent:'#8A8AC8', a2:'#A8A8E0', a3:'#C8C8F0', glow:'rgba(138,138,200,.30)', dim:'rgba(138,138,200,.10)', orb1:'#0c0c20', orb2:'#080810', orb3:'#0a0a18', orb4:'#10101e', orb5:'#060612' },
];

let appThemeIdx = 0;
let isDark = true;

function applyAppTheme(idx, dark) {
  const t = APP_THEMES[idx];
  const r = document.documentElement;
  r.style.setProperty('--ac',   t.accent);
  r.style.setProperty('--ac2',  t.a2);
  r.style.setProperty('--ac3',  t.a3);
  r.style.setProperty('--acg',  t.glow);
  r.style.setProperty('--acd',  t.dim);
  r.style.setProperty('--acdb', t.dim.replace(/[\d.]+\)$/, m => (parseFloat(m)*0.55).toFixed(3)+')'));
  if (dark) {
    
    r.style.setProperty('--orb2', t.orb2);
    r.style.setProperty('--orb3', t.orb3);
    r.style.setProperty('--orb4', t.orb4);
    r.style.setProperty('--orb5', t.orb5);
  }
  r.setAttribute('data-theme', dark ? 'dark' : 'light');
  const lbl = document.getElementById('themeLabel');
  if (lbl) lbl.textContent = t.name;
  try { localStorage.setItem('themeIdx', idx); localStorage.setItem('themeDark', dark ? '1' : '0'); } catch {}
  // Update chart colors if exists
  updatePaperStats();
}

window.cycleTheme = function() {
  appThemeIdx = (appThemeIdx + 1) % APP_THEMES.length;
  applyAppTheme(appThemeIdx, isDark);
  showToast('Theme: ' + APP_THEMES[appThemeIdx].name);
};
window.toggleDark = function() { isDark = !isDark; applyAppTheme(appThemeIdx, isDark); };
window.toggleTheme = window.toggleDark;
window.toggleDarkMode = function() {
  isDark = !isDark;
  applyAppTheme(appThemeIdx, isDark);
  // Update icon
  const icon = document.getElementById('modeIcon');
  if (icon) icon.textContent = isDark ? '☀' : '☾';
  showToast(isDark ? 'Night mode' : 'Day mode');
  try { localStorage.setItem('themeDark', isDark ? '1' : '0'); } catch {}
};

/* ── Competitive exam info ─────────────────────────────────── */
const COMP_INFO = {
  NTSE: { papers:'MAT (Mental Ability) + SAT (Sci 40Q + Social 40Q + Maths 20Q)', marks:'100 marks each', time:'2 Hours/paper', marking:'Stage 1: +1/0. Stage 2: +1/−⅓.', tip:'Select "MAT" as subject for the Mental Ability paper.' },
  NSO:  { papers:"Logical Reasoning (10Q) + Science (35Q) + Achiever's (5Q×3M)", marks:'60 marks', time:'1 Hour', marking:'No negative marking.', tip:"Select class and science chapter. Achiever's Section auto-generates as HOT questions." },
  IMO:  { papers:"Logical Reasoning (10Q) + Maths (25Q) + Everyday Maths (10Q) + Achiever's (5Q×3M)", marks:'60 marks', time:'1 Hour', marking:'No negative marking.', tip:'Select class and maths chapter for a focused paper.' },
  IJSO: { papers:'Integrated Science: Physics (27Q) + Chemistry (27Q) + Biology (26Q)', marks:'80Q × +3/−1 = 240 max', time:'2 Hours', marking:'+3 correct, −1 wrong.', tip:'Select class and chapter, or Full Syllabus for a mixed paper.' },
};

/* ── History — split storage so metadata always survives ────── */
const HISTORY_KEY  = 'ec_history_v3';   // metadata only (small, always saves)
const HISTORY_MAX  = 10;
const _pKey = id => 'ec_p_' + id;
const _kKey = id => 'ec_k_' + id;

function loadHistory() {
  try {
    const meta = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    return meta.map(item => ({
      ...item,
      paper:     _tryGet(_pKey(item.id)),
      answerKey: _tryGet(_kKey(item.id))
    }));
  } catch { return []; }
}
function _tryGet(key) { try { return localStorage.getItem(key) || ''; } catch { return ''; } }

function saveHistory(h) {
  try {
    // Always save metadata (tiny — never fails due to quota)
    const meta = h.map(({ paper, answerKey, ...rest }) => rest);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(meta));
  } catch(e) {}
  // Save paper content per-item (large — catch individually)
  h.forEach(item => {
    try { localStorage.setItem(_pKey(item.id), item.paper     || ''); } catch {}
    try { localStorage.setItem(_kKey(item.id), item.answerKey || ''); } catch {}
  });
  // Prune orphaned keys
  _pruneOldPapers(h.map(i => i.id));
  // Update lifetime counter
  _bumpLifetime();
}

function _pruneOldPapers(liveIds) {
  try {
    Object.keys(localStorage)
      .filter(k => k.startsWith('ec_p_') || k.startsWith('ec_k_'))
      .forEach(k => {
        const id = Number(k.replace('ec_p_','').replace('ec_k_',''));
        if (!liveIds.includes(id)) localStorage.removeItem(k);
      });
  } catch {}
}

/* Lifetime counter (total papers ever generated on this device) */
const LIFETIME_KEY = 'ec_lifetime_total';
function _bumpLifetime() {
  try {
    const n = parseInt(localStorage.getItem(LIFETIME_KEY) || '0', 10) + 1;
    localStorage.setItem(LIFETIME_KEY, String(n));
    const el = document.getElementById('lifetimeCount');
    if (el) { el.textContent = n; el.classList.add('bump'); setTimeout(() => el.classList.remove('bump'), 600); }
  } catch {}
}
function _loadLifetime() {
  try { return parseInt(localStorage.getItem(LIFETIME_KEY) || '0', 10); } catch { return 0; }
}

function addToHistory(meta, paper, key) {
  const h = loadHistory();
  h.unshift({ id: Date.now(), timestamp: new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}), date: new Date().toLocaleDateString([],{day:'numeric',month:'short'}), ...meta, paper, answerKey: key });
  if (h.length > HISTORY_MAX) h.length = HISTORY_MAX;
  saveHistory(h); renderHistory();
  // Flash the newest item to draw attention
  requestAnimationFrame(() => {
    const first = document.querySelector('.history-item');
    if (first) {
      first.classList.add('new-flash');
      setTimeout(() => first.classList.remove('new-flash'), 900);
    }
    // Scroll sidebar to top so history is visible
    const sbInner = document.querySelector('.sb-inner');
    if (sbInner) sbInner.scrollTop = 0;
  });
}

function renderHistory() {
  const list = document.getElementById('historyList');
  if (!list) return;
  const h = loadHistory();
  const cntEl = document.getElementById('histCount');
  if (cntEl) {
    cntEl.textContent = h.length || '';
    cntEl.classList.toggle('zero', h.length === 0);
  }
  if (!h.length) {
    list.innerHTML = `
      <div class="history-list-inner">
        <div class="history-empty">
          <div class="history-empty-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          </div>
          <p>Generate your first paper — it will appear here automatically</p>
        </div>
      </div>`;
    return;
  }
  list.innerHTML = '<div class="history-list-inner">' + h.map((e, idx) => `
    <div class="history-item">
      <div class="history-item-top">
        <div class="history-item-name">${e.subject || 'Paper'}${e.chapter && e.chapter !== 'Full Syllabus' ? '<br><small style="font-family:var(--mono);font-weight:400;font-size:8px;color:var(--muted2)">' + e.chapter + '</small>' : ''}</div>
        <div class="history-item-time">${e.date || ''}<br>${e.timestamp || ''}</div>
      </div>
      <div class="history-item-meta">
        ${e.board ? `<span class="history-tag tag-board">${e.board.replace(' State Board','')}</span>` : ''}
        ${e.marks ? `<span class="history-tag">${e.marks}M</span>` : ''}
        ${e.difficulty ? `<span class="history-tag">${e.difficulty}</span>` : ''}
      </div>
      <div class="history-item-btns">
        <button class="history-dl-btn" onclick="downloadFromHistory(${idx}, false)">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>Paper
        </button>
        ${e.answerKey ? `<button class="history-dl-btn key" onclick="downloadFromHistory(${idx}, true)">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>+ Key
        </button>` : ''}
      </div>
    </div>`).join('') + '</div>';
}

window.clearHistory = function() {
  try {
    const h = loadHistory();
    h.forEach(item => {
      try { localStorage.removeItem(_pKey(item.id)); } catch {}
      try { localStorage.removeItem(_kKey(item.id)); } catch {}
    });
    localStorage.removeItem(HISTORY_KEY);
  } catch {}
  renderHistory(); showToast('History cleared');
};

async function downloadFromHistory(idx, withKey) {
  const e = loadHistory()[idx]; if (!e) return;
  await triggerPDFDownload({ paper:e.paper, answer_key:e.answerKey||'', subject:e.subject, chapter:e.chapter !== 'Full Syllabus' ? e.chapter : '', board:e.board, includeKey:withKey, marks:e.marks }, e.board, e.subject, e.chapter, withKey);
}

/* ── Sidebar summary ───────────────────────────────────────── */
function setSidebarValue(id, val) { const el = document.getElementById(id); if (el) el.textContent = val || '—'; }

function updateSidebar() {
  const examType = document.getElementById('examType')?.value;
  const subject  = document.getElementById('subject')?.value;
  const chapter  = document.getElementById('chapter')?.value;
  const cls      = document.getElementById('class')?.value;
  const marks    = getTotalMarks();
  const diff     = getDifficulty();

  let boardText = '';
  if (examType === 'state-board')      boardText = document.getElementById('stateSelect')?.value || '';
  else if (examType === 'competitive') boardText = document.getElementById('competitiveExam')?.value || '';

  let scopeText = '—';
  if (examType === 'state-board') {
    scopeText = boardScope === 'all' ? 'All Chapters' : 'One Chapter';
  } else if (examType === 'competitive') {
    scopeText = compScope === 'all' ? 'All Subjects' : compScope === 'subject' ? 'Full Subject' : 'One Topic';
  }

  // ── Update the "sel-step" selection panel ──────────────────
  function setSelStep(n, val) {
    const row = document.getElementById('ssel-' + n);
    const vEl = document.getElementById('ssel-' + n + '-v');
    if (!row || !vEl) return;
    const filled = val && val !== '—';
    vEl.textContent = val || '—';
    row.classList.toggle('filled', filled);
  }
  setSelStep(1, examType === 'state-board' ? 'State Board' : examType === 'competitive' ? 'Competitive' : '');
  setSelStep(2, boardText);
  setSelStep(3, examType ? scopeText : '');
  setSelStep(4, [subject, chapter && chapter !== 'Full Syllabus' ? chapter : null].filter(Boolean).join(' · ') || (cls ? 'Class ' + cls : ''));
  setSelStep(5, marks && examType ? marks + ' marks · ' + diff : '');

  updatePaperStats();
}

/* ── Marks ─────────────────────────────────────────────────── */
function getTotalMarks() { return document.getElementById('totalMarks')?.value || '100'; }

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
  const n = parseInt(val, 10);
  if (n > 0) { document.getElementById('totalMarks').value = n; updateSidebar(); }
};

function applySmartMarkDefault(scope) {
  const custom = document.getElementById('chipCustom');
  if (custom && custom.classList.contains('active')) return;
  const container = document.getElementById('marksChips');
  if (container) {
    container.querySelectorAll('.chip:not(#chipCustom)').forEach(c => {
      const v = parseInt(c.dataset.val, 10);
      c.style.display = scope === 'single' ? (v===20||v===40 ? '' : 'none') : (v===80||v===100 ? '' : 'none');
    });
  }
  const target = scope === 'single' ? '40' : '100';
  document.querySelectorAll('.chip:not(#chipCustom)').forEach(c => c.classList.remove('active'));
  const cw = document.getElementById('customMarkWrap');
  if (cw) cw.style.display = 'none';
  const chip = document.querySelector(`.chip[data-val="${target}"]`);
  if (chip) chip.classList.add('active');
  document.getElementById('totalMarks').value = target;
  updateSidebar();
}

/* ── Difficulty ────────────────────────────────────────────── */
function getDifficulty() {
  const el = document.querySelector('input[name="difficulty"]:checked');
  return el ? el.value : 'Medium';
}
window.selectDiff = function(val, btn) {
  document.querySelectorAll('.diff-btn').forEach(b => b.classList.remove('active','easy','medium','hard'));
  btn.classList.add('active', val.toLowerCase());
  const radioId = val === 'Easy' ? 'r-easy' : val === 'Medium' ? 'r-med' : 'r-hard';
  const radio = document.getElementById(radioId);
  if (radio) radio.checked = true;
  updateSidebar();
};

/* ── Curriculum ────────────────────────────────────────────── */
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
    Object.keys(data).forEach(s => { const o = document.createElement('option'); o.value = s; o.textContent = s; subjSel.appendChild(o); });
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
  chapters.forEach(ch => { const o = document.createElement('option'); o.value = ch; o.textContent = ch; chapSel.appendChild(o); });
  updateSidebar();
}

/* ── Form Visibility ───────────────────────────────────────── */
function updateFormVisibility() {
  const examType = document.getElementById('examType')?.value;
  const stateC   = document.getElementById('stateCard');
  const compC    = document.getElementById('competitiveCard');
  const scopeC   = document.getElementById('scopeCard');
  const chapCard = document.getElementById('chapterCard');
  const subjCard = document.getElementById('subjectCard');
  const boardRow = document.getElementById('boardScopeRow');
  const compRow  = document.getElementById('compScopeRow');
  const chapLbl  = document.getElementById('chapterLabel');
  const subjLbl  = document.getElementById('subjectLabel');

  if (stateC) stateC.classList.toggle('collapsed', examType !== 'state-board');
  if (compC)  compC.classList.toggle('collapsed',  examType !== 'competitive');

  if (scopeC) {
    scopeC.classList.toggle('collapsed', !examType);
    if (boardRow) boardRow.style.display = examType === 'state-board'  ? '' : 'none';
    if (compRow)  compRow.style.display  = examType === 'competitive'  ? '' : 'none';
  }

  if (examType === 'state-board') {
    if (subjCard) subjCard.style.display = '';
    if (chapCard) chapCard.style.display = boardScope === 'single' ? '' : 'none';
    if (chapLbl)  chapLbl.textContent = 'Chapter';
    if (subjLbl)  subjLbl.textContent = 'Subject';
  } else if (examType === 'competitive') {
    // FIX: hide subject when "All Subjects" is selected — no need to ask again
    if (subjCard) subjCard.style.display = compScope === 'all' ? 'none' : '';
    if (chapCard) chapCard.style.display = compScope === 'topic' ? '' : 'none';
    if (chapLbl)  chapLbl.textContent = 'Topic';
    if (subjLbl)  subjLbl.textContent = 'Subject / Paper';
  } else {
    if (subjCard) subjCard.style.display = '';
    if (chapCard) chapCard.style.display = '';
  }
}

/* ── Paper Type ────────────────────────────────────────────── */
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
  updateFormVisibility(); updateSubjects(); updateSidebar();
  setActiveStep(2);
};

/* ── Board / Comp Scope ────────────────────────────────────── */
window.selectBoardScope = function(val) {
  boardScope = val;
  document.getElementById('scopeSelect').value = val === 'all' ? 'all' : 'single';
  document.querySelectorAll('#boardScopeRow .scope-card').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById(val === 'all' ? 'bscope-all' : 'bscope-single');
  if (btn) btn.classList.add('active');
  updateFormVisibility(); applySmartMarkDefault(val); updateSidebar();
  setHint(val === 'all' ? 'Full syllabus — select subject and class.' : 'One chapter — select subject and specific chapter.');
  setActiveStep(3);
};

window.selectCompScope = function(val) {
  compScope = val;
  document.getElementById('scopeSelect').value = val === 'all' ? 'all' : 'single';
  document.querySelectorAll('#compScopeRow .scope-card').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById('cscope-' + val); if (btn) btn.classList.add('active');
  updateFormVisibility(); applySmartMarkDefault(val === 'topic' ? 'single' : 'all'); updateSidebar();
  const hints = { topic:'One Topic — pick subject and topic.', subject:'Full Subject — all topics covered.', all:'All Subjects — complete exam syllabus.' };
  setHint(hints[val] || '');
  setActiveStep(3);
};

/* ── Competitive Info ──────────────────────────────────────── */
function updateCompInfo() {
  const exam    = document.getElementById('competitiveExam')?.value;
  const infoBox = document.getElementById('compInfoBox');
  const infoTxt = document.getElementById('compInfoText');
  if (!infoBox || !infoTxt) return;
  if (!exam || !COMP_INFO[exam]) { infoBox.style.display = 'none'; return; }
  const info = COMP_INFO[exam];
  infoTxt.innerHTML = `<b>${exam}</b>: ${info.papers}<br>
    <span style="opacity:.8">Marks: ${info.marks} · Time: ${info.time} · ${info.marking}</span><br>
    <span style="color:var(--ac2)">💡 ${info.tip}</span>`;
  infoBox.style.display = 'block';
  updateSubjects().then(() => updateChapters());
}

window.onClassChange   = async function() { await updateSubjects(); updateFormVisibility(); updateSidebar(); setActiveStep(4); };
window.onSubjectChange = function() { updateChapters(); updateSidebar(); setActiveStep(4); };

/* ── Toast / Hint ──────────────────────────────────────────── */
function showToast(msg) {
  const t = document.getElementById('notificationToast'); if (!t) return;
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3500);
}
function setHint(text) { const el = document.getElementById('hintText'); if (el) el.textContent = text; }

/* ── Preview Tabs ──────────────────────────────────────────── */
window.switchPreviewTab = function(tab, btn) {
  document.querySelectorAll('.ptab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-paper').style.display = tab === 'paper' ? 'block' : 'none';
  document.getElementById('tab-key').style.display   = tab === 'key'   ? 'block' : 'none';
};

/* ── Generate ──────────────────────────────────────────────── */
async function generatePaper() {
  const examType = document.getElementById('examType')?.value;
  if (!examType) { showToast('Please select a paper type first'); return; }

  const cls         = document.getElementById('class')?.value;
  const subject     = document.getElementById('subject')?.value;
  const chapter     = document.getElementById('chapter')?.value;
  const marks       = getTotalMarks();
  const difficulty  = getDifficulty();
  const suggestions = document.getElementById('suggestions')?.value || '';
  const payload     = { class:cls, subject, marks, difficulty, suggestions, examType, includeKey: document.getElementById('includeKey')?.checked || false };

  if (examType === 'state-board') {
    payload.state = document.getElementById('stateSelect')?.value || '';
    if (!payload.state)  { showToast('Please select a state board'); return; }
    if (!cls)            { showToast('Please select a class'); return; }
    if (!subject)        { showToast('Please select a subject'); return; }
    if (boardScope === 'single') {
      if (!chapter) { showToast('Please select a chapter'); return; }
      payload.chapter = chapter;
    } else { payload.chapter = ''; payload.all_chapters = true; }
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
    } else { payload.subject = subject || ''; payload.chapter = ''; payload.all_chapters = true; }
    payload.scope = compScope;
  }

  // Hide success panel before generating
  const sp = document.getElementById('successPanel'); if (sp) sp.style.display = 'none';
  window._pdfDirect = null;

  showLoading(true, 'Crafting your paper…');
  setHint('Generating — usually 25–50 seconds…');
  setActiveStep(6);

  try {
    const res    = await fetch('/generate', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
    const result = await res.json();
    showLoading(false);

    if (!result.success) {
      showToast(result.error || 'Generation failed — please try again');
      setHint('Something went wrong. Check selections and try again.');
      return;
    }

    currentPaper     = result.paper     || '';
    currentAnswerKey = result.answer_key || '';
    const boardText  = result.board || payload.state || payload.competitiveExam || '';
    currentMeta = { board:boardText, subject:payload.subject||result.subject||'', chapter:payload.chapter||result.chapter||'Full Syllabus', marks, difficulty, class: payload.class||'' };

    window._pdfDirect = { paper:result.pdf_b64||null, withKey:result.pdf_key_b64||null, board:boardText, subject:currentMeta.subject, chapter:currentMeta.chapter };

    // Auto-download
    if (window._pdfDirect.paper) _b64Download(window._pdfDirect.paper, _safeName(window._pdfDirect, false));

    addToHistory(currentMeta, currentPaper, currentAnswerKey);
    showSuccessPanel();
    launchConfetti();
    setActiveStep(6);

  } catch (err) { showLoading(false); showToast('Server error: ' + err.message); }
}

/* ── PDF helpers ───────────────────────────────────────────── */
function _b64Download(b64, fname) {
  try {
    const bin = atob(b64), buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([buf], {type:'application/pdf'}));
    const a = Object.assign(document.createElement('a'), {href:url, download:fname});
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 12000);
    return true;
  } catch (e) { showToast('Download error: ' + e.message); return false; }
}
function _safeName(d, withKey) {
  return ([d.board, d.subject, (d.chapter && d.chapter !== 'Full Syllabus') ? d.chapter : null]
    .filter(Boolean).join('_').replace(/\s+/g,'_').replace(/[\/\\:*?"<>|]/g,'-') || 'ExamPaper') + (withKey ? '_with_key' : '') + '.pdf';
}

async function triggerPDFDownload(payload, board, subject, chapter, withKey) {
  showLoading(true, 'Rendering PDF…');
  try {
    const res = await fetch('/download-pdf', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
    if (!res.ok) { let e = `Server error ${res.status}`; try { const j = await res.json(); e = j.error||e; } catch {} showToast('PDF error: '+e); showLoading(false); return; }
    const blob = await res.blob();
    if (!blob.size) { showToast('PDF was empty — try regenerating'); showLoading(false); return; }
    const url = URL.createObjectURL(blob);
    const safe = [board,subject,chapter||'Paper'].filter(Boolean).join('_').replace(/\s+/g,'_').replace(/[\/\\:*?"<>|]/g,'-');
    Object.assign(document.createElement('a'), {href:url, download:safe+(withKey?'_with_key':'')+'.pdf'}).click();
    URL.revokeObjectURL(url);
    showLoading(false); showToast('PDF downloaded ✓');
  } catch (err) { showLoading(false); showToast('Download failed: ' + err.message); }
}

window.downloadPDF = function(withKey) {
  const d = window._pdfDirect;
  if (d) {
    // withKey=false → paper-only (pdf_b64, no answer key appended)
    // withKey=true  → paper + answer key (pdf_key_b64)
    const b64 = withKey ? d.withKey : d.paper;
    if (b64 && _b64Download(b64, _safeName(d, withKey))) {
      showToast(withKey ? 'Answer Key PDF downloaded ✓' : 'Paper downloaded ✓');
      return;
    }
  }
  // Fallback: re-render on server
  if (!currentPaper?.trim()) { showToast('Generate a paper first'); return; }
  triggerPDFDownload({
    paper:      currentPaper,
    answer_key: currentAnswerKey || '',
    subject:    currentMeta.subject,
    chapter:    currentMeta.chapter !== 'Full Syllabus' ? currentMeta.chapter : '',
    board:      currentMeta.board,
    includeKey: !!withKey,
    marks:      currentMeta.marks
  }, currentMeta.board, currentMeta.subject, currentMeta.chapter, !!withKey);
};

function copyPaper() {
  if (!currentPaper) { showToast('Nothing to copy'); return; }
  navigator.clipboard.writeText(currentPaper).then(() => showToast('Copied ✓')).catch(() => showToast('Copy failed'));
}

/* ── Success panel ─────────────────────────────────────────── */
function showSuccessPanel() {
  const sp = document.getElementById('successPanel'); if (!sp) return;
  const me = document.getElementById('successMeta');
  const dk = document.getElementById('dlWithKey');
  const d  = window._pdfDirect;
  if (me) me.textContent = [d?.board, d?.subject, (d?.chapter && d.chapter !== 'Full Syllabus') ? d.chapter : null].filter(Boolean).join(' · ') || 'Downloaded';
  // Show "+ Answer Key" button whenever the server returned a key PDF
  // The key PDF (withKey) always exists as long as AI generated an answer key
  if (dk) dk.style.display = d?.withKey ? 'flex' : 'none';
  sp.style.display = 'block';
  sp.scrollIntoView({ behavior:'smooth', block:'nearest' });
}

window.generateAnother = function() {
  const sp = document.getElementById('successPanel'); if (sp) sp.style.display = 'none';
  window.scrollTo({ top:0, behavior:'smooth' });
};

/* ── Step tracker ──────────────────────────────────────────── */
function setActiveStep(n) {
  for (let i = 1; i <= 6; i++) {
    const s = document.getElementById('step-' + i);
    const c = document.getElementById('conn-' + i);
    if (!s) continue;
    s.classList.remove('active','done');
    if (c) c.classList.toggle('lit', i < n);
    if (i < n)       s.classList.add('done');
    else if (i === n) s.classList.add('active');
  }
}

/* ── Confetti ──────────────────────────────────────────────── */
function launchConfetti() {
  const cv = document.getElementById('confetti-canvas'); if (!cv) return;
  const ctx = cv.getContext('2d');
  cv.width = window.innerWidth; cv.height = window.innerHeight;
  const pal = ['#6d5bff','#9f8dff','#c4b8ff','#f59e0b','#22c55e','#60a5fa','#f472b6','#fff'];
  const pieces = Array.from({length:170}, () => ({
    x: Math.random()*cv.width, y: -10 - Math.random()*90,
    vx: (Math.random()-.5)*5, vy: 2.2 + Math.random()*3.2,
    angle: Math.random()*Math.PI*2, va: (Math.random()-.5)*.24,
    w: 5+Math.random()*10, h: 3+Math.random()*6,
    color: pal[Math.floor(Math.random()*pal.length)],
    isCircle: Math.random() > .52, op: 1
  }));
  let fr = 0;
  function draw() {
    ctx.clearRect(0,0,cv.width,cv.height);
    pieces.forEach(p => {
      p.x+=p.vx; p.y+=p.vy; p.angle+=p.va; p.vy+=.046;
      if (fr > 95) p.op = Math.max(0, p.op - .018);
      ctx.globalAlpha = p.op; ctx.fillStyle = p.color;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.angle);
      if (p.isCircle) { ctx.beginPath(); ctx.arc(0,0,p.w/2,0,Math.PI*2); ctx.fill(); }
      else { ctx.fillRect(-p.w/2,-p.h/2,p.w,p.h); }
      ctx.restore();
    });
    ctx.globalAlpha = 1; fr++;
    if (fr < 230) requestAnimationFrame(draw);
    else ctx.clearRect(0,0,cv.width,cv.height);
  }
  draw();
}

/* ── Chart.js marks distribution ──────────────────────────── */
/* ── Paper Stats Panel (replaces useless chart) ────────────── */
function updatePaperStats() {
  const marks  = parseInt(getTotalMarks(), 10) || 100;
  const diff   = getDifficulty();
  const hist   = loadHistory();

  // Estimate question count based on marks + difficulty
  const qMap = { Easy:{ 100:40, 80:32, 40:18, 20:10 }, Medium:{ 100:35, 80:28, 40:15, 20:8 }, Hard:{ 100:28, 80:22, 40:12, 20:6 } };
  const closest = [20,40,80,100].reduce((a,b) => Math.abs(b-marks) < Math.abs(a-marks) ? b : a);
  const qCount = (qMap[diff] || qMap.Medium)[closest] || Math.round(marks / 3);

  // Estimate time in hours/mins
  const minsPerMark = { Easy: 1.5, Medium: 1.8, Hard: 2.1 };
  const totalMins   = Math.round(marks * (minsPerMark[diff] || 1.8));
  const hrs         = Math.floor(totalMins / 60);
  const mins        = totalMins % 60;
  const timeStr     = hrs > 0 ? (mins > 0 ? `${hrs}h ${mins}m` : `${hrs}h`) : `${mins}m`;

  const setV = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  setV('stat-qs',    qCount  || '—');
  setV('stat-time',  timeStr || '—');
  setV('stat-marks', marks   || '—');
  setV('stat-hist',  hist.length);

  // Section tags
  const row = document.getElementById('statSectionsRow');
  if (row) {
    const secs = marks >= 80
      ? ['Part A · Obj', 'Part B · SA', 'Part B · LA', 'Application']
      : marks >= 40
      ? ['Objective', 'Short Ans', 'Long Ans']
      : ['MCQ', 'Short Ans'];
    row.innerHTML = secs.map(s => `<span class="sb-sec-tag active">${s}</span>`).join('');
  }
}


/* ── Jokes ─────────────────────────────────────────────────── */
const HERO_JOKES = [
  "Why do students write so small? To leave room for regrets.",
  "Exam tip: write large — the examiner gets tired. Sympathy marks exist.",
  "The speed of forgetting during an exam exceeds 3×10⁸ m/s.",
  "A+ students become professors. C students become CEOs. B students watch.",
  "I told my teacher I'd study all night. We both knew that was a lie.",
  "The correct answer is always the one you erased first.",
  "Studying: 20% reading, 80% convincing yourself you'll remember it.",
  "An exam asks: did you read? The universe already knows the answer.",
  "My exam strategy: read, panic, write something, pray, repeat.",
  "Chemistry: turning caffeine into passing grades since forever.",
  '"Show all work." Sir, my work consists entirely of vibes and hope.',
  "The only thing worse than not studying is studying the wrong chapter.",
];
const LOADING_JOKES = [
  "Consulting the NCERT syllabus so you don't have to… 📖",
  "Making wrong options convincingly wrong… 🎭",
  "Calibrating difficulty: enough to hurt, not enough to destroy ⚖️",
  "Triple-checking every answer is actually correct this time… 🔍",
  "Ensuring diagrams look like diagrams, not modern art… 🎨",
  "Counting marks so they add up. Unlike most student papers. 🧮",
  "Crafting options so close students will question their sanity… 😈",
  "Consulting the blueprint with great academic gravity… 📜",
];

let _jokeIdx = 0;
function rotateHeroJoke() {
  const el = document.getElementById('heroJoke'); if (!el) return;
  el.classList.add('fading');
  setTimeout(() => { _jokeIdx = (_jokeIdx+1) % HERO_JOKES.length; el.textContent = HERO_JOKES[_jokeIdx]; el.classList.remove('fading'); }, 340);
}

/* ── Mobile sidebar ────────────────────────────────────────── */
window.toggleMobileSidebar = function() {
  const sb = document.getElementById('sidebar');
  const ov = document.getElementById('mob-overlay');
  if (!sb) return;
  const open = sb.classList.toggle('mob-open');
  if (ov) { ov.classList.toggle('open', open); }
  // Prevent body scroll when sidebar open
  document.body.style.overflow = open ? 'hidden' : '';
};
window.closeMobileSidebar = function() {
  document.getElementById('sidebar')?.classList.remove('mob-open');
  document.getElementById('mob-overlay')?.classList.remove('open');
  document.body.style.overflow = '';
};

/* ══════════════════════════════════════════════════════════════
   DOMContentLoaded — boot sequence
══════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {

  /* ── Hello popup ── */
  setTimeout(showHelloPopup, 600);

  /* ── Font restore ── */
  try { fontIdx = Math.min(parseInt(localStorage.getItem('fontIdx') || '0', 10), FONT_MODES.length-1); } catch {}
  applyFont(fontIdx);

  /* ── Restore & apply theme ── */
  try {
    appThemeIdx = Math.min(parseInt(localStorage.getItem('themeIdx') || '0', 10), APP_THEMES.length-1);
    isDark = localStorage.getItem('themeDark') !== '0';
  } catch {}
  applyAppTheme(appThemeIdx, isDark);

  /* ── Init form ── */
  updateFormVisibility();
  updateSidebar();
  applySmartMarkDefault('all');
  renderHistory();
  // Restore lifetime counter display
  try {
    const lc = document.getElementById('lifetimeCount');
    if (lc) lc.textContent = _loadLifetime();
  } catch {}
  initCurriculum();

  /* ── Medium difficulty init ── */
  const medBtn = document.querySelector('.diff-btn[data-val="Medium"]');
  if (medBtn) medBtn.classList.add('active', 'medium');

  /* ── Form submit ── */
  document.getElementById('paperForm')?.addEventListener('submit', e => { e.preventDefault(); generatePaper(); });

  /* ── Step init ── */
  setActiveStep(1);

  /* ── Hero joke rotation ── */
  setInterval(rotateHeroJoke, 7500);

  /* Loading is handled by unified showLoading defined at bottom of file */

  /* ── Chart.js init ── */
  if (typeof Chart !== 'undefined') updatePaperStats();


  /* ── Custom cursor ── */
  /* The actual cursor dot is an OS-rendered SVG (set in CSS) — always visible.
     The ring below is a purely decorative lagging circle, no z-index dependency. */
  const ring = document.getElementById('cur-ring');
  const bgGl = document.querySelector('.bg-glow');

  let mx = -200, my = -200, rx = -200, ry = -200;

  (function lerpRing() {
    rx += (mx - rx) * 0.18;
    ry += (my - ry) * 0.18;
    if (ring) ring.style.transform = 'translate3d(' + (rx - 17) + 'px,' + (ry - 17) + 'px,0)';
    requestAnimationFrame(lerpRing);
  })();

  let _glFrame = false;
  document.addEventListener('mousemove', e => {
    mx = e.clientX; my = e.clientY;
    if (bgGl && !_glFrame) {
      _glFrame = true;
      requestAnimationFrame(() => {
        bgGl.style.setProperty('--cx', mx + 'px');
        bgGl.style.setProperty('--cy', my + 'px');
        _glFrame = false;
      });
    }
  }, { passive: true });

  document.addEventListener('mousedown', () => ring?.classList.add('click'));
  document.addEventListener('mouseup',   () => ring?.classList.remove('click'));
  document.addEventListener('mouseleave', () => { if (ring) ring.style.opacity = '0'; });
  document.addEventListener('mouseenter', () => { if (ring) ring.style.opacity = ''; });

  document.addEventListener('mouseover', e => {
    const t = e.target.closest(
      'button,a,.type-card,.scope-card,.chip,.diff-btn,' +
      '.history-item,.history-dl-btn,.game-opt,.succ-btn,' +
      '.tb-btn,.gen-btn,.sb-logo,.hist-clear,select,label,[role="button"]'
    );
    ring?.classList.toggle('hov', !!t);
  }, { passive: true });

  /* ── GSAP + Lenis ── */
  if (typeof gsap !== 'undefined') {
    gsap.registerPlugin(ScrollTrigger);

    /* Lenis disabled — it intercepts sidebar scroll events */

    /* Page entrance */
    gsap.timeline({ defaults:{ ease:'power3.out' } })
      .from('#sidebar',    { x:-40, opacity:0, duration:.9 }, 0)
      .from('.topbar',     { y:-24, opacity:0, duration:.7 }, .1)
      .from('.hero',       { y:40,  opacity:0, duration:.9 }, .2)
      .from('.hero-h1',    { y:30,  opacity:0, duration:.8 }, .3)
      .from('.hero-kicker',{ y:20,  opacity:0, duration:.7 }, .35)
      .from('.hero-sub',   { y:20,  opacity:0, duration:.7 }, .45)
      .from('.joke-box',   { y:16,  opacity:0, duration:.6 }, .55);

    /* Stagger first 6 visible cards only — rest load instantly */
    gsap.utils.toArray('.gcard, .sec-div').slice(0, 6).forEach((el, i) => {
      gsap.from(el, {
        scrollTrigger:{ trigger:el, start:'top 92%', toggleActions:'play none none none' },
        y:18, opacity:0, duration:.5, ease:'power2.out', delay: i * 0.03
      });
    });

    /* Type/scope card hover lift */
    document.querySelectorAll('.type-card, .scope-card').forEach(card => {
      card.addEventListener('mouseenter', () => gsap.to(card, { y:-3, duration:.25, ease:'power2.out' }));
      card.addEventListener('mouseleave', () => gsap.to(card, { y:0,  duration:.3,  ease:'elastic.out(1,.6)' }));
    });

    /* Logo hover spring */
    const logo = document.querySelector('.sb-logo');
    if (logo) {
      logo.addEventListener('mouseenter', () => gsap.to(logo, { scale:1.12, rotate:-8, duration:.32, ease:'back.out(2)' }));
      logo.addEventListener('mouseleave', () => gsap.to(logo, { scale:1, rotate:0, duration:.4, ease:'elastic.out(1,.5)' }));
    }

    /* Generate button spring */
    const genBtn = document.querySelector('.gen-btn');
    if (genBtn) {
      genBtn.addEventListener('mouseenter', () => gsap.to(genBtn, { scale:1.008, duration:.28, ease:'power2.out' }));
      genBtn.addEventListener('mouseleave', () => gsap.to(genBtn, { scale:1, duration:.36, ease:'elastic.out(1,.6)' }));
    }
  }

  /* ── Keyboard support for role=button ── */
  document.querySelectorAll('[role="button"]').forEach(el => {
    el.addEventListener('keydown', e => { if (e.key==='Enter'||e.key===' ') { e.preventDefault(); el.click(); } });
  });

  /* ── Sidebar: stop wheel events from bubbling to GSAP ScrollTrigger ── */
  document.getElementById('sidebar')?.addEventListener('wheel', e => {
    e.stopPropagation();
  }, { passive: true });

  /* ── Close sidebar on overlay click ── */
  document.getElementById('mob-overlay')?.addEventListener('click', closeMobileSidebar);
});


/* ══════════════════════════════════════════════════════════════
   HELLO POPUP — shown once per session on load
══════════════════════════════════════════════════════════════ */
const HELLO_JOKES = [
  "A student told the teacher: 'I don't deserve a zero on this test.' The teacher agreed — and gave them a minus five.",
  "Teaching is the only profession where you say 'I'll wait' to a room full of people who are not coming.",
  "My student asked: 'Will this be on the exam?' I said: 'Everything is on the exam.' He said: 'Even what you said just now?' I said: 'Especially that.'",
  "Day 1 of teaching: I am going to inspire these young minds. Day 200: Please just stop clicking your pen.",
  "A student wrote 'I don't know' as the answer to every question. That is actually the most self-aware exam I have ever marked.",
  "I asked the class to turn in their phones. They looked at me like I had asked for a kidney.",
  "Student: 'Can I be excused? I need to use the bathroom.' Me: 'You had 40 minutes of free time before class.' Student: 'Yes but I was on my phone.'",
  "The loudest sound in any school is the silence when a teacher asks 'does everyone understand?' and then adds 'this will be on the test.'",
  "I once caught a student cheating. He had written the entire periodic table on his arm. For an English exam.",
  "My class voted me 'Most Likely to Say One More Thing' for five years running. I have thoughts about that.",
];

const DONE_JOKES = [
  "Your exam is ready — now the only question is: who has to grade it?",
  "Paper generated. Students will later question every comma. You have been warned.",
  "Done! Remember: a good exam separates the students who studied from the ones who prayed.",
  "Paper complete. The AI worked hard. The students will have to work harder.",
  "Congratulations! You just created 45 minutes of panic for 30 students.",
  "Your paper is ready. May the passing rate be ever in your favour.",
  "Generated successfully. Einstein failed exams too — but your students are not Einstein.",
  "Paper done! Pro tip: the hardest question is always the one worth the fewest marks.",
];

let _helloShown = false;
function showHelloPopup() {
  if (_helloShown) return;
  _helloShown = true;
  const popup = document.getElementById('helloPopup');
  if (!popup) return;
  // Pick a random joke
  const jokeEl = document.getElementById('helloJoke');
  if (jokeEl) jokeEl.textContent = HELLO_JOKES[Math.floor(Math.random() * HELLO_JOKES.length)];
  popup.classList.add('visible');
}
window.closeHelloPopup = function() {
  const popup = document.getElementById('helloPopup');
  if (popup) popup.classList.remove('visible');
};

function showDonePopup(meta) {
  const popup = document.getElementById('donePopup');
  if (!popup) return;
  const jokeEl = document.getElementById('doneJoke');
  if (jokeEl) jokeEl.textContent = DONE_JOKES[Math.floor(Math.random() * DONE_JOKES.length)];
  const sub = document.getElementById('doneSubtitle');
  if (sub && meta) {
    const parts = [meta.subject, meta.board, meta.marks ? meta.marks+'M' : null].filter(Boolean);
    sub.textContent = parts.join(' · ');
  }
  popup.classList.add('visible');
}
window.closeDonePopup = function(download) {
  const popup = document.getElementById('donePopup');
  if (popup) popup.style.display = 'none';
  if (download) window.downloadPDF && window.downloadPDF(false);
};

/* ══════════════════════════════════════════════════════════════
   TRIVIA GAME — Loading Screen Mini Game
══════════════════════════════════════════════════════════════ */
const TRIVIA_QS = [
  { q:"Which instrument measures atmospheric pressure?", opts:["Barometer","Thermometer","Hygrometer","Anemometer"], a:0 },
  { q:"The powerhouse of the cell is the…", opts:["Nucleus","Ribosome","Mitochondria","Chloroplast"], a:2 },
  { q:"Which planet is known as the Red Planet?", opts:["Venus","Jupiter","Saturn","Mars"], a:3 },
  { q:"HCF of 12 and 18 is?", opts:["3","4","6","9"], a:2 },
  { q:"Light travels at approximately… m/s", opts:["3×10⁸","3×10⁶","3×10⁷","3×10⁹"], a:0 },
  { q:"Water boils at °C at standard pressure?", opts:["90","95","100","110"], a:2 },
  { q:"The smallest prime number is?", opts:["0","1","2","3"], a:2 },
  { q:"Chemical formula of water?", opts:["H₂O₂","HO","H₂O","H₃O"], a:2 },
  { q:"Newton's 2nd law: F = ?", opts:["mv","ma","m/a","m+a"], a:1 },
  { q:"The pH of pure water is?", opts:["5","6","7","8"], a:2 },
  { q:"Number of bones in adult human body?", opts:["196","206","216","226"], a:1 },
  { q:"Which gas do plants absorb for photosynthesis?", opts:["O₂","N₂","CO₂","H₂"], a:2 },
  { q:"Sum of angles in a triangle?", opts:["90°","180°","270°","360°"], a:1 },
  { q:"Speed = Distance ÷ ?", opts:["Force","Time","Mass","Area"], a:1 },
  { q:"Ohm's Law: V = ?", opts:["I+R","I×R","I/R","I²R"], a:1 },
  { q:"The unit of electric current is?", opts:["Volt","Ohm","Ampere","Watt"], a:2 },
  { q:"Which organelle is site of protein synthesis?", opts:["Mitochondria","Ribosome","Vacuole","Nucleus"], a:1 },
  { q:"Area of circle with radius r?", opts:["2πr","πr²","2πr²","πr"], a:1 },
  { q:"An atom of carbon has how many protons?", opts:["4","6","8","12"], a:1 },
  { q:"Refraction of light is caused by change in…?", opts:["Speed","Colour","Frequency","Amplitude"], a:0 },
  { q:"Which blood group is universal donor?", opts:["A","B","AB","O"], a:3 },
  { q:"Who proposed the theory of evolution?", opts:["Newton","Einstein","Darwin","Mendel"], a:2 },
  { q:"LCM of 4 and 6 is?", opts:["8","10","12","24"], a:2 },
  { q:"The human body has how many chromosomes?", opts:["23","44","46","48"], a:2 },
  { q:"Current through 5Ω if voltage is 10V?", opts:["0.5A","1A","2A","5A"], a:2 },
];

let _gameScore = 0, _gameStreak = 0, _gameCurrent = 0, _gameActive = false;
let _gameShuffled = [], _gameAnswered = false, _gameTimer = null;

function _shuffleArr(arr) {
  const a = [...arr]; for(let i=a.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]];} return a;
}

function initGame() {
  _gameScore = 0; _gameStreak = 0; _gameCurrent = 0;
  _gameShuffled = _shuffleArr(TRIVIA_QS);
  _gameActive = true;
  document.getElementById('gameScore').textContent = '0';
  document.getElementById('gameStreak').textContent = '0';
  loadGameQuestion();
}

function loadGameQuestion() {
  if (!_gameActive) return;
  _gameAnswered = false;
  clearTimeout(_gameTimer);
  const idx = _gameCurrent % _gameShuffled.length;
  const q = _gameShuffled[idx];

  const qEl = document.getElementById('gameQ');
  const fb  = document.getElementById('gameFeedback');
  if (!qEl) return;

  qEl.classList.add('fade');
  setTimeout(() => {
    qEl.textContent = q.q;
    qEl.classList.remove('fade');
    fb.textContent = '';
    fb.className = 'game-feedback';

    // Shuffle options for display
    const optIdxs = _shuffleArr([0,1,2,3]);
    for (let i = 0; i < 4; i++) {
      const btn = document.getElementById('go' + i);
      if (!btn) continue;
      btn.textContent = q.opts[optIdxs[i]];
      btn.dataset.realIdx = optIdxs[i];
      btn.className = 'game-opt';
      btn.disabled = false;
    }
    // Progress
    const fill = document.getElementById('gameProgressFill');
    if (fill) fill.style.width = ((_gameCurrent % TRIVIA_QS.length) / TRIVIA_QS.length * 100) + '%';
  }, 200);
}

window.answerQ = function(btnIdx) {
  if (_gameAnswered || !_gameActive) return;
  _gameAnswered = true;
  const idx = _gameCurrent % _gameShuffled.length;
  const q = _gameShuffled[idx];
  const btn = document.getElementById('go' + btnIdx);
  const chosen = parseInt(btn.dataset.realIdx);
  const fb = document.getElementById('gameFeedback');

  // Lock all buttons
  for (let i = 0; i < 4; i++) {
    const b = document.getElementById('go' + i);
    b.disabled = true;
    if (parseInt(b.dataset.realIdx) === q.a) b.classList.add('correct');
  }

  if (chosen === q.a) {
    _gameScore++; _gameStreak++;
    document.getElementById('gameScore').textContent = _gameScore;
    document.getElementById('gameStreak').textContent = _gameStreak;
    fb.textContent = ['Excellent! ✦', 'Correct! ★', 'Well done! ◈', 'Brilliant! ⬡'][Math.floor(Math.random()*4)];
    fb.className = 'game-feedback correct-msg';
  } else {
    btn.classList.add('wrong');
    _gameStreak = 0;
    document.getElementById('gameStreak').textContent = '0';
    fb.textContent = 'Not quite — the correct answer is highlighted above.';
    fb.className = 'game-feedback wrong-msg';
  }
  _gameCurrent++;
  _gameTimer = setTimeout(loadGameQuestion, 1800);
};

/* Populate the loading recap panel with current selections */
/* ── Big-status loader data ─────────────────────────────────── */
const LS_STAGES = [
  { num:'1', line1:'Parsing your',       line2:'requirements',      sub:'Analysing board · marks · difficulty…',  pct: 8  },
  { num:'2', line1:'Generating',         line2:'questions with AI', sub:'Gemini 2.5 Flash is writing the paper…', pct: 38 },
  { num:'3', line1:'Writing the',        line2:'answer key',        sub:'Creating model answers for every question…', pct: 62 },
  { num:'4', line1:'Formatting',         line2:'paper layout',      sub:'Applying board-standard section structure…', pct: 82 },
  { num:'5', line1:'Building your',      line2:'PDF',               sub:'Rendering to printable format…',          pct: 96 },
];

function populateLoader() {
  const examType = document.getElementById('examType')?.value;
  const subject  = document.getElementById('subject')?.value  || '';
  const chapter  = document.getElementById('chapter')?.value  || '';
  const cls      = document.getElementById('class')?.value    || '';
  const marks    = getTotalMarks();
  const diff     = getDifficulty();

  let boardText = '';
  if (examType === 'state-board')      boardText = document.getElementById('stateSelect')?.value || '';
  else if (examType === 'competitive') boardText = document.getElementById('competitiveExam')?.value || '';

  const subChap = subject + (chapter && chapter !== 'Full Syllabus' ? ' · ' + chapter : '') || (cls ? 'Class ' + cls : '—');

  // Bottom meta strip in loader-left
  const setT = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val || '—'; };
  setT('recap-subject-val', subChap);
  setT('recap-board-val',   boardText || (cls ? 'Class ' + cls : '') || '—');
  setT('recap-marks-val',   marks + ' M · ' + diff);
}

function _setLoaderStage(idx) {
  // Drive ls1–ls5 which are .ls-step-big rows; CSS handles icons via ::after
  const ids = ['ls1','ls2','ls3','ls4','ls5'];
  ids.forEach((id, i) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('active','done');
    if (i < idx)  el.classList.add('done');
    if (i === idx) el.classList.add('active');
  });

  // Mobile steps
  const mobIds = ['mls1','mls2','mls3','mls4','mls5'];
  mobIds.forEach((id, i) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('active','done');
    if (i < idx)  el.classList.add('done');
    if (i === idx) el.classList.add('active');
  });
}


/* ── Master showLoading — drives big status + game + mobile ── */
window.showLoading = function(show) {
  const modal = document.getElementById('loadingModal');
  if (!modal) return;
  modal.style.display = show ? 'flex' : 'none';

  if (window._loadStepTimers) window._loadStepTimers.forEach(clearTimeout);
  window._loadStepTimers = [];
  if (window._loadTimerInterval) clearInterval(window._loadTimerInterval);

  if (show) {
    populateLoader();
    initGame();

    // Reset all step states on show
    ['ls1','ls2','ls3','ls4','ls5'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.remove('active','done');
      const st = document.getElementById(id + '-state');
      if (st) st.innerHTML = '';
    });
    ['mls1','mls2','mls3','mls4','mls5'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.remove('active','done');
    });

    // Elapsed timer
    const timerEl = document.getElementById('loaderTimer');
    let elapsed = 0;
    if (timerEl) {
      timerEl.textContent = '00:00';
      window._loadTimerInterval = setInterval(() => {
        elapsed++;
        const m = String(Math.floor(elapsed / 60)).padStart(2,'0');
        const s = String(elapsed % 60).padStart(2,'0');
        timerEl.textContent = m + ':' + s;
      }, 1000);
    }

    // Stage transitions
    const delays = [0, 5000, 12000, 19000, 28000];
    delays.forEach((delay, i) => {
      window._loadStepTimers.push(setTimeout(() => _setLoaderStage(i), delay));
    });

  } else {
    _gameActive = false;
    clearTimeout(_gameTimer);
    clearInterval(window._loadTimerInterval);
    if (window._loadStepTimers) window._loadStepTimers.forEach(clearTimeout);
  }
};