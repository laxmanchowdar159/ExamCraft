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
    r.style.setProperty('--orb1', t.orb1);
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
  if (window._marksChart) updateMarksChart();
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
  showToast('Theme: ' + APP_THEMES[appThemeIdx].name);
  startAppThemeRotation();
};
window.toggleDark  = function() { isDark = !isDark; applyAppTheme(appThemeIdx, isDark); };
window.toggleTheme = window.toggleDark;

/* ── Competitive exam info ─────────────────────────────────── */
const COMP_INFO = {
  NTSE: { papers:'MAT (Mental Ability) + SAT (Sci 40Q + Social 40Q + Maths 20Q)', marks:'100 marks each', time:'2 Hours/paper', marking:'Stage 1: +1/0. Stage 2: +1/−⅓.', tip:'Select "MAT" as subject for the Mental Ability paper.' },
  NSO:  { papers:"Logical Reasoning (10Q) + Science (35Q) + Achiever's (5Q×3M)", marks:'60 marks', time:'1 Hour', marking:'No negative marking.', tip:"Select class and science chapter. Achiever's Section auto-generates as HOT questions." },
  IMO:  { papers:"Logical Reasoning (10Q) + Maths (25Q) + Everyday Maths (10Q) + Achiever's (5Q×3M)", marks:'60 marks', time:'1 Hour', marking:'No negative marking.', tip:'Select class and maths chapter for a focused paper.' },
  IJSO: { papers:'Integrated Science: Physics (27Q) + Chemistry (27Q) + Biology (26Q)', marks:'80Q × +3/−1 = 240 max', time:'2 Hours', marking:'+3 correct, −1 wrong.', tip:'Select class and chapter, or Full Syllabus for a mixed paper.' },
};

/* ── History ───────────────────────────────────────────────── */
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

window.clearHistory = function() {
  try { localStorage.removeItem(HISTORY_KEY); } catch {}
  renderHistory(); showToast('History cleared');
};

async function downloadFromHistory(idx, withKey) {
  const e = loadHistory()[idx]; if (!e) return;
  await triggerPDFDownload({ paper:e.paper, answer_key:e.answerKey||'', subject:e.subject, chapter:e.chapter !== 'Full Syllabus' ? e.chapter : '', board:e.board, includeKey:withKey, marks:e.marks }, e.board, e.subject, e.chapter, withKey);
}

/* ── Sidebar summary ───────────────────────────────────────── */
function setSidebarValue(id, val) { const el = document.getElementById(id); if (el) el.textContent = val || '—'; }

function updateSidebar() {
  setSidebarValue('sb-class',      document.getElementById('class')?.value);
  setSidebarValue('sb-subject',    document.getElementById('subject')?.value);
  setSidebarValue('sb-marks',      getTotalMarks());
  setSidebarValue('sb-difficulty', getDifficulty());
  setSidebarValue('sb-key',        document.getElementById('includeKey')?.checked ? 'Yes' : 'No');

  const examType = document.getElementById('examType')?.value;
  let boardText = '';
  if (examType === 'state-board')      boardText = document.getElementById('stateSelect')?.value || '';
  else if (examType === 'competitive') boardText = document.getElementById('competitiveExam')?.value || '';
  setSidebarValue('sb-board', boardText);

  if (examType === 'state-board') {
    if (boardScope === 'all') { setSidebarValue('sb-scope','All Chapters');  setSidebarValue('sb-chapter','—'); }
    else                      { setSidebarValue('sb-scope','One Chapter');   setSidebarValue('sb-chapter', document.getElementById('chapter')?.value || '—'); }
  } else if (examType === 'competitive') {
    if (compScope === 'all')            { setSidebarValue('sb-scope','All Subjects'); setSidebarValue('sb-chapter','—'); }
    else if (compScope === 'subject')   { setSidebarValue('sb-scope','Full Subject'); setSidebarValue('sb-chapter','—'); }
    else                                { setSidebarValue('sb-scope','One Topic');    setSidebarValue('sb-chapter', document.getElementById('chapter')?.value || '—'); }
  } else {
    setSidebarValue('sb-scope','—');
    setSidebarValue('sb-chapter','—');
  }
  updateMarksChart();
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
    if (subjCard) subjCard.style.display = '';
    if (chapCard) chapCard.style.display = compScope === 'topic' ? '' : 'none';
    if (chapLbl)  chapLbl.textContent = 'Topic';
    if (subjLbl)  subjLbl.textContent = compScope === 'all' ? 'Subject (optional)' : 'Subject / Paper';
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

/* ── Loading Modal ─────────────────────────────────────────── */
let _stepTimers = [];
function showLoading(show, title) {
  const modal = document.getElementById('loadingModal');
  if (!modal) return;
  modal.style.display = show ? 'flex' : 'none';
  if (title) { const t = document.getElementById('loaderTitle'); if (t) t.textContent = title; }
  _stepTimers.forEach(clearTimeout); _stepTimers = [];
  const ids = ['ls1','ls2','ls3','ls4','ls5'];
  ids.forEach(id => { const el = document.getElementById(id); if (el) el.classList.remove('active','done'); });
  if (!show) return;
  const delays = [0, 5000, 12000, 19000, 28000];
  ids.forEach((id, i) => {
    _stepTimers.push(setTimeout(() => {
      if (i > 0) { const prev = document.getElementById(ids[i-1]); if (prev) { prev.classList.remove('active'); prev.classList.add('done'); } }
      const cur = document.getElementById(id); if (cur) cur.classList.add('active');
    }, delays[i]));
  });
}

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
    currentMeta = { board:boardText, subject:payload.subject||result.subject||'', chapter:payload.chapter||result.chapter||'Full Syllabus', marks, difficulty };

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
    const b64 = withKey ? (d.withKey || d.paper) : (d.paper || d.withKey);
    if (b64 && _b64Download(b64, _safeName(d, withKey))) { showToast(withKey ? 'Key PDF downloaded ✓' : 'Paper downloaded ✓'); return; }
  }
  // Fallback to server
  if (!currentPaper?.trim()) { showToast('Generate a paper first'); return; }
  const includeKey = withKey === true ? true : withKey === false ? false : (document.getElementById('includeKey')?.checked || false);
  triggerPDFDownload({ paper:currentPaper, answer_key:currentAnswerKey||'', subject:currentMeta.subject, chapter:currentMeta.chapter!=='Full Syllabus'?currentMeta.chapter:'', board:currentMeta.board, includeKey, marks:currentMeta.marks }, currentMeta.board, currentMeta.subject, currentMeta.chapter, includeKey);
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
  if (dk) dk.style.display = (d?.withKey && d.withKey !== d.paper) ? 'flex' : 'none';
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
window._marksChart = null;
function updateMarksChart() {
  const ctx = document.getElementById('marksChart'); if (!ctx) return;
  const total = parseInt(getTotalMarks(), 10) || 100;
  const diff  = getDifficulty();
  const ratios = { Easy:[.32,.30,.24,.14], Medium:[.26,.26,.28,.20], Hard:[.20,.22,.30,.28] };
  const r    = ratios[diff] || ratios.Medium;
  const vals = r.map(v => Math.round(v * total));
  const acColor = getComputedStyle(document.documentElement).getPropertyValue('--ac').trim() || '#6d5bff';
  const makeAlpha = (hex, a) => { const c = parseInt(hex.replace('#',''),16); return `rgba(${c>>16},${(c>>8)&255},${c&255},${a})`; };
  const colors = [makeAlpha(acColor,.88), makeAlpha(acColor,.65), makeAlpha(acColor,.44), makeAlpha(acColor,.28)];

  if (window._marksChart) {
    window._marksChart.data.datasets[0].data = vals;
    window._marksChart.data.datasets[0].backgroundColor = colors;
    window._marksChart.update('active');
    return;
  }
  window._marksChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['MCQ','Short Ans','Long Ans','Application'],
      datasets: [{ data: vals, backgroundColor: colors, borderWidth: 0, hoverOffset: 5 }]
    },
    options: {
      cutout: '68%',
      plugins: {
        legend: { position:'bottom', labels:{ color:'rgba(154,163,200,.8)', font:{ family:"'JetBrains Mono'", size:9 }, padding:10, boxWidth:8, boxHeight:8, usePointStyle:true, pointStyleWidth:8 } },
        tooltip: { backgroundColor:'rgba(11,16,40,.95)', titleColor:'#edf0fc', bodyColor:'#9aa3c8', borderColor:'rgba(109,91,255,.25)', borderWidth:1, padding:10, callbacks:{ label: c => ` ${c.label}: ${c.raw}M` } }
      },
      animation: { animateScale:true, duration:600 }
    }
  });
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
  if (ov) ov.classList.toggle('open', open);
};
window.closeMobileSidebar = function() {
  document.getElementById('sidebar')?.classList.remove('mob-open');
  document.getElementById('mob-overlay')?.classList.remove('open');
};

/* ══════════════════════════════════════════════════════════════
   DOMContentLoaded — boot sequence
══════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {

  /* ── Restore & apply theme ── */
  try {
    appThemeIdx = Math.min(parseInt(localStorage.getItem('themeIdx') || '0', 10), APP_THEMES.length-1);
    isDark = localStorage.getItem('themeDark') !== '0';
  } catch {}
  applyAppTheme(appThemeIdx, isDark);
  startAppThemeRotation();

  /* ── Init form ── */
  updateFormVisibility();
  updateSidebar();
  applySmartMarkDefault('all');
  renderHistory();
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

  /* ── Loading joke ticker ── */
  let _loaderJokeTimer = null;
  const _origShowLoading = showLoading;
  window._showLoadingHook = function(show, title) {
    _origShowLoading(show, title);
    const je = document.getElementById('loaderJoke'); if (!je) return;
    clearInterval(_loaderJokeTimer);
    if (show) {
      let li = 0; je.textContent = LOADING_JOKES[li++ % LOADING_JOKES.length]; je.style.opacity = '1';
      _loaderJokeTimer = setInterval(() => {
        je.style.opacity = '0';
        setTimeout(() => { je.textContent = LOADING_JOKES[li++ % LOADING_JOKES.length]; je.style.opacity = '1'; }, 400);
      }, 4500);
    } else { je.style.opacity = '0'; }
  };
  // Patch showLoading globally
  const _sl = showLoading;
  window.showLoading = function(show, title) {
    _sl(show, title);
    window._showLoadingHook && window._showLoadingHook(show, title);
  };

  /* ── Chart.js init ── */
  if (typeof Chart !== 'undefined') updateMarksChart();

  /* ── Custom cursor ── */
  const dot  = document.getElementById('cur-dot');
  const ring = document.getElementById('cur-ring');
  const bgGl = document.querySelector('.bg-glow');
  let mx=0,my=0,rx=0,ry=0;
  document.addEventListener('mousemove', e => {
    mx=e.clientX; my=e.clientY;
    if (dot) { dot.style.left=mx+'px'; dot.style.top=my+'px'; }
    if (bgGl) { bgGl.style.setProperty('--cx', mx+'px'); bgGl.style.setProperty('--cy', my+'px'); }
  });
  document.addEventListener('mousedown', () => ring?.classList.add('click'));
  document.addEventListener('mouseup',   () => ring?.classList.remove('click'));
  (function lerpRing() {
    rx += (mx-rx)*.11; ry += (my-ry)*.11;
    if (ring) { ring.style.left=rx+'px'; ring.style.top=ry+'px'; }
    requestAnimationFrame(lerpRing);
  })();
  document.querySelectorAll('button,.type-card,.scope-card,.chip,.diff-btn,.history-item,[role="button"]').forEach(el => {
    el.addEventListener('mouseenter', () => ring?.classList.add('hov'));
    el.addEventListener('mouseleave', () => ring?.classList.remove('hov'));
  });

  /* ── GSAP + Lenis ── */
  if (typeof gsap !== 'undefined') {
    gsap.registerPlugin(ScrollTrigger);

    /* Lenis */
    if (typeof Lenis !== 'undefined') {
      const lenis = new Lenis({ lerp:.08, smoothWheel:true, syncTouch:false });
      function rafLoop(t) { lenis.raf(t); ScrollTrigger.update(); requestAnimationFrame(rafLoop); }
      requestAnimationFrame(rafLoop);
      lenis.on('scroll', ScrollTrigger.update);
    }

    /* Page entrance */
    gsap.timeline({ defaults:{ ease:'power3.out' } })
      .from('#sidebar',    { x:-40, opacity:0, duration:.9 }, 0)
      .from('.topbar',     { y:-24, opacity:0, duration:.7 }, .1)
      .from('.hero',       { y:40,  opacity:0, duration:.9 }, .2)
      .from('.hero-h1',    { y:30,  opacity:0, duration:.8 }, .3);

    /* Scroll reveal for gcard sections */
    document.querySelectorAll('.gcard, .type-grid, .scope-grid').forEach(el => {
      gsap.from(el, {
        scrollTrigger:{ trigger:el, start:'top 88%', toggleActions:'play none none none' },
        y:26, opacity:0, duration:.65, ease:'power2.out'
      });
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
      genBtn.addEventListener('mouseenter', () => gsap.to(genBtn, { scale:1.012, duration:.28, ease:'power2.out' }));
      genBtn.addEventListener('mouseleave', () => gsap.to(genBtn, { scale:1, duration:.36, ease:'elastic.out(1,.6)' }));
    }
  }

  /* ── Keyboard support for role=button ── */
  document.querySelectorAll('[role="button"]').forEach(el => {
    el.addEventListener('keydown', e => { if (e.key==='Enter'||e.key===' ') { e.preventDefault(); el.click(); } });
  });

  /* ── Close sidebar on overlay click ── */
  document.getElementById('mob-overlay')?.addEventListener('click', closeMobileSidebar);
});
