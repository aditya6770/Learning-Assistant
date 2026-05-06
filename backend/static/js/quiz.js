// ── Quiz State ────────────────────────────────────────────────
let QS = {
  mode: 'standard', questions: [], currentIdx: 0, answers: [],
  streak: 0, maxStreak: 0, combo: 1.0, score: 0, bonusScore: 0,
  startTime: null, qStartTime: null, timerInterval: null, battleTimer: null,
  battleTimeLeft: 90, difficulty: 'medium', incorrectStreak: 0,
  responseTimes: [], personalBest: null, wrongAnswers: [],
  topicMap: {}, quizId: null, docText: '', fixList: []
};
let QTab = 'generate';

// ── Init ──────────────────────────────────────────────────────
async function initQuiz() {
  await Promise.all([
    loadPersonalBest(),
    loadQuizDocs()
  ]);
  quizTab('generate');
}

async function loadPersonalBest() {
  try {
    const d = await api('GET', '/quiz/personal_best');
    QS.personalBest = d;
    const el = document.getElementById('q-personal-best');
    if (el) el.innerHTML = d.total_attempts > 0
      ? `🏆 Best: <strong>${d.best_score} pts</strong> &nbsp;|&nbsp; Last: ${d.last_score} pts &nbsp;|&nbsp; ${d.total_attempts} attempts`
      : '🎯 No attempts yet — take your first quiz!';
    const banner = document.getElementById('q-beat-banner');
    if (banner && d.total_attempts > 0) {
      banner.style.display = 'flex';
      banner.innerHTML = `<span>🔥 Beat your last: <strong>${d.last_score} pts</strong></span><span style="color:#10b981">Best: ${d.best_score} pts</span>`;
    }
  } catch (e) { }
}

// ── Tabs ──────────────────────────────────────────────────────
function quizTab(tab) {
  QTab = tab;
  document.querySelectorAll('.q-tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.q-tab-pane').forEach(p => p.style.display = 'none');
  const btn = document.querySelector(`[data-qtab="${tab}"]`);
  if (btn) btn.classList.add('active');
  const pane = document.getElementById(`qtab-${tab}`);
  if (pane) pane.style.display = 'block';
  if (tab === 'board') loadQuizLeaderboard('global');
  if (tab === 'fix') renderFixList();
  if (tab === 'mastery') renderMastery();
}

// ── Docs ──────────────────────────────────────────────────────
async function loadQuizDocs() {
  try {
    const d = await api('GET', '/learning/documents');
    const sel = document.getElementById('q-doc-select');
    if (!sel) return;
    sel.innerHTML = '<option value="">— Select Document —</option>' +
      (d.documents || []).map(doc => `<option value="${doc._id}">${doc.original_name || doc.filename}</option>`).join('');
  } catch (e) { console.error('Failed to load quiz docs:', e); }
}

async function quizUpload(input) {
  if (!input.files || !input.files[0]) return;
  const file = input.files[0];
  const formData = new FormData();
  formData.append('file', file);
  try {
    toast('Uploading document...', 'info');
    const res = await api('POST', '/learning/upload', formData, true);
    toast('Document uploaded!', 'success');
    await loadQuizDocs();
    document.getElementById('q-doc-select').value = res.document._id;
  } catch (e) { toast('Upload failed: ' + e.message, 'error'); }
}

// ── Standard Generate ─────────────────────────────────────────
// FIX 1: Normalize question IDs after receiving from API
async function generateQuiz() {
  const docId = document.getElementById('q-doc-select').value;
  const topic = document.getElementById('q-topic-input').value.trim();
  const nMcq = Math.min(parseInt(document.getElementById('q-n-mcq').value) || 5, 10);
  const diff = document.getElementById('q-difficulty').value;

  if (!docId && !topic) {
    toast('Select a document or enter a topic first', 'error');
    return;
  }

    const btn = document.getElementById('q-gen-btn');
    btn.disabled = true; btn.textContent = '⏳ Generating…';
    
    // Reset state before generation to prevent stale UI
    QS.questions = [];
    QS.currentIdx = 0;
    
    try {
    const url = docId ? `/quiz/generate/${docId}` : `/quiz/generate/topic`;
    const payload = { n_mcq: nMcq, difficulty: diff };
    if (!docId) payload.topic = topic;

    let d;
    try {
      d = await api('POST', url, payload);
    } catch (apiErr) {
      toast('Server error: ' + apiErr.message, 'error');
      return;
    }

    // Guard: if the backend returned an error or empty quiz
    if (!d || !d.quiz) {
      toast('Quiz generation failed. Server returned no data.', 'error');
      return;
    }
    if (!Array.isArray(d.quiz.questions) || d.quiz.questions.length === 0) {
      toast('No questions returned. Try a different topic or document.', 'error');
      return;
    }

    // ✅ FIX 1: Filter nulls then normalize IDs
    QS.questions = d.quiz.questions
      .filter(q => q && typeof q === 'object' && q.question)
      .map((q, i) => ({
        ...q,
        id: q.id || q._id || `q${i + 1}`,
        options: q.options || [],
        correct_answer: q.correct_answer || ''
      }));

    if (QS.questions.length === 0) {
      toast('Questions were malformed. Please try again.', 'error');
      return;
    }

    // Safe access guard
    if (!d || !d.quiz) {
      toast('Quiz generation failed. No quiz returned from server.', 'error');
      return;
    }
    QS.quizId = d.quiz._id || d.quiz.id || '';
    QS.docText = ''; QS.mode = 'standard'; QS.difficulty = diff;
    resetSessionState();
    quizTab('taking');
    renderQuestion();
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
  finally { btn.disabled = false; btn.textContent = '🧠 Generate Quiz'; }
}

function resetSessionState() {
  QS.currentIdx = 0; QS.answers = []; QS.streak = 0; QS.maxStreak = 0;
  QS.combo = 1.0; QS.score = 0; QS.bonusScore = 0;
  QS.incorrectStreak = 0; QS.responseTimes = []; QS.wrongAnswers = [];
  QS.topicMap = {}; QS.startTime = Date.now(); clearInterval(QS.timerInterval);
}

// ── Render Question ───────────────────────────────────────────
// FIX 2: Guard against questions missing options array
function renderQuestion() {
  if (!QS.questions || QS.questions.length === 0) {
    toast('No questions available to display.', 'error');
    quizTab('generate');
    return;
  }
  const q = QS.questions[QS.currentIdx];
  if (!q) { finishQuiz(); return; }

  // ✅ FIX 2: Skip broken questions that have no options and are not fill_in_blank
  if (!q.options && q.type !== 'fill_in_blank') {
    QS.currentIdx++;
    renderQuestion();
    return;
  }

  QS.qStartTime = Date.now();
  updateHUD();
  const isFib = q.type === 'fill_in_blank';
  document.getElementById('q-question-num').textContent = `Q${QS.currentIdx + 1} / ${QS.questions.length}`;
  document.getElementById('q-question-text').textContent = q.question;
  document.getElementById('q-difficulty-badge').textContent = (QS.difficulty || 'medium').toUpperCase();
  document.getElementById('q-options-area').innerHTML = isFib
    ? `<input id="q-fib-input" class="form-input" placeholder="Type your answer…" style="margin-top:12px;"/>
       <button class="btn btn-primary" style="margin-top:8px;" onclick="submitAnswer()">Submit</button>`
    : (q.options || []).map((opt, i) => `
        <button class="q-opt-btn" onclick="submitAnswer(${i})"
          style="width:100%;text-align:left;padding:14px 18px;margin:6px 0;border-radius:10px;
          border:1px solid var(--border);background:var(--surface2);cursor:pointer;
          font-size:0.9rem;transition:all .2s;">
          <span style="opacity:0.5;margin-right:10px;">${['A', 'B', 'C', 'D'][i]}.</span>${opt}
        </button>`).join('');
  const prog = ((QS.currentIdx) / QS.questions.length) * 100;
  document.getElementById('q-progress-bar').style.width = prog + '%';
  startQuestionTimer();
  detectEmotionState();
}

function updateHUD() {
  const streak = document.getElementById('q-streak');
  const combo = document.getElementById('q-combo');
  const score = document.getElementById('q-score');
  if (streak) streak.textContent = `🔥 ${QS.streak}`;
  if (combo) combo.textContent = `⚡ ${QS.combo.toFixed(2)}x`;
  if (score) score.textContent = `⭐ ${QS.score}`;
}

function startQuestionTimer() {
  clearInterval(QS.timerInterval);
  let secs = QS.mode === 'battle' ? 20 : 60;
  const timerEl = document.getElementById('q-timer');
  QS.timerInterval = setInterval(() => {
    secs--;
    if (timerEl) {
      timerEl.textContent = `⏱ ${secs}s`;
      timerEl.style.color = secs < 10 ? '#ef4444' : 'var(--text-muted)';
    }
    if (secs <= 0) { clearInterval(QS.timerInterval); submitAnswer(-1); }
  }, 1000);
}

// ── Answer Submission ─────────────────────────────────────────
// FIX 4: Use safe question_id fallback
function submitAnswer(optIdx) {
  clearInterval(QS.timerInterval);
  const q = QS.questions[QS.currentIdx];
  if (!q) return;
  const elapsed = (Date.now() - QS.qStartTime) / 1000;
  QS.responseTimes.push(elapsed);

  let userAns, correct;
  if (q.type === 'fill_in_blank') {
    const inp = document.getElementById('q-fib-input');
    userAns = (inp ? inp.value.trim() : '');
    correct = (q.correct_answer || '').trim();
  } else if (optIdx === -1) {
    userAns = ''; correct = q.correct_answer || '';
  } else {
    userAns = q.options[optIdx];
    correct = q.correct_answer || '';
  }

  // Enhanced comparison logic
  let isCorrect = userAns.toLowerCase().trim() === correct.toLowerCase().trim();

  // If direct match fails, try fallback heuristics (common with AI-generated questions)
  if (!isCorrect && optIdx >= 0) {
    const letters = ['A', 'B', 'C', 'D'];
    const cleanCorrect = correct.toString().trim().toUpperCase();
    const cleanUser = userAns.toString().trim().toLowerCase();

    // 1. Handle Letter match (e.g., "A", "B", "C", "D")
    if (cleanCorrect.length === 1 && letters[optIdx] === cleanCorrect) {
      isCorrect = true;
    } 
    // 2. Handle Index match (e.g., "0", "1", "2", "3")
    else if (cleanCorrect === optIdx.toString()) {
      isCorrect = true;
    }
    // 3. Handle "Option A" or "A. Option" match
    else if (cleanCorrect.startsWith(letters[optIdx]) && cleanCorrect.length > 2) {
      isCorrect = true;
    }
    // 4. Handle correct answer text being part of the response (e.g., "The answer is Python")
    else if (cleanCorrect.includes(cleanUser) || cleanUser.includes(correct.toString().toLowerCase().trim())) {
      isCorrect = true;
    }
  }

  // Update topic map
  const topic = q.topic || 'General Concepts';
  if (!QS.topicMap[topic]) QS.topicMap[topic] = [0, 0];
  QS.topicMap[topic][1]++;
  if (isCorrect) QS.topicMap[topic][0]++;

  // Gamification
  if (isCorrect) {
    QS.streak++;
    QS.incorrectStreak = 0;
    if (QS.streak > QS.maxStreak) QS.maxStreak = QS.streak;
    if (QS.streak >= 3) QS.combo = Math.min(2.0, 1.0 + (QS.streak - 1) * 0.25);
    const base = 10;
    const speed = elapsed < 5 ? 5 : 0;
    const pts = Math.round((base + speed) * QS.combo);
    QS.score += pts;
    showFeedbackFlash('✅ Correct! +' + pts, '#10b981');
    if (QS.streak === 3) showComboAnim('🔥 3x Streak!');
    if (QS.streak === 5) showComboAnim('⚡ 5x Combo!');
    if (QS.streak === 10) showComboAnim('🏆 10x Legendary!');
  } else {
    QS.streak = 0; QS.combo = 1.0; QS.incorrectStreak++;
    QS.wrongAnswers.push({
      question: q.question, user_answer: userAns,
      correct_answer: correct, topic
    });
    showFeedbackFlash(`❌ Correct: ${correct}`, '#ef4444');
  }

  // ✅ FIX 4: Safe question_id with multiple fallbacks
  QS.answers.push({
    question_id: q.id || q._id || `q${QS.currentIdx + 1}`,
    user_answer: userAns,
    correct_answer: correct,
    is_correct: isCorrect,
    topic,
    time: elapsed
  });

  // Highlight option
  if (q.type !== 'fill_in_blank' && optIdx >= 0) {
    document.querySelectorAll('.q-opt-btn').forEach((b, i) => {
      b.disabled = true;
      if (i === optIdx) b.style.background = isCorrect ? '#10b981' : '#ef4444';
      if (q.options[i] === correct) b.style.background = '#10b981';
      b.style.color = 'white';
    });
  }

  adjustDifficulty();
  setTimeout(() => { QS.currentIdx++; renderQuestion(); }, 900);
}

function showFeedbackFlash(msg, color) {
  const el = document.getElementById('q-flash');
  if (!el) return;
  el.textContent = msg; el.style.color = color; el.style.opacity = '1';
  setTimeout(() => { el.style.opacity = '0'; }, 800);
}

function showComboAnim(msg) {
  const el = document.getElementById('q-combo-anim');
  if (!el) return;
  el.textContent = msg; el.style.opacity = '1'; el.style.transform = 'scale(1.3)';
  setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'scale(1)'; }, 1200);
}

// ── Adaptive Difficulty ───────────────────────────────────────
function adjustDifficulty() {
  const last5 = QS.answers.slice(-5);
  if (last5.length < 3) return;
  const acc = last5.filter(a => a.is_correct).length / last5.length;
  const avgTime = last5.reduce((s, a) => s + a.time, 0) / last5.length;
  if (acc >= 0.8 && avgTime < 8) QS.difficulty = 'hard';
  else if (acc < 0.4 || QS.incorrectStreak >= 3) QS.difficulty = 'easy';
  else QS.difficulty = 'medium';
}

function detectEmotionState() {
  const hint = document.getElementById('q-hint-area');
  if (!hint) return;
  if (QS.incorrectStreak >= 3) {
    hint.style.display = 'block';
    hint.innerHTML = `<div style="padding:10px 14px;background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.3);border-radius:8px;font-size:0.82rem;color:#fbbf24;">
      💡 Take a breath! You've missed a few. Switching to easier questions to rebuild confidence.</div>`;
  } else { hint.style.display = 'none'; }
}

// ── Finish Quiz ───────────────────────────────────────────────
// FIX 3: Correct total and correct count calculation
async function finishQuiz() {
  clearInterval(QS.timerInterval);
  clearInterval(QS.battleTimer);
  
  // Clear stale UI from previous session
  const feedbackArea = document.getElementById('q-feedback-area');
  const summaryArea = document.getElementById('q-ai-summary');
  if (feedbackArea) feedbackArea.innerHTML = '';
  if (summaryArea) { summaryArea.innerHTML = ''; summaryArea.style.display = 'none'; }

  quizTab('results');

  // ✅ FIX 3: Use correct count logic — total is all answers, correct filters by is_correct
  const total = QS.answers.length;
  const correct = QS.answers.filter(a => a.is_correct).length;
  const pct = total ? Math.round(correct / total * 100) : 0;
  const elapsed = Math.round((Date.now() - QS.startTime) / 1000);

  document.getElementById('q-res-score').textContent = `${correct}/${total}`;
  document.getElementById('q-res-pct').textContent = `${pct}%`;
  document.getElementById('q-res-streak').textContent = `🔥 Best Streak: ${QS.maxStreak}`;
  document.getElementById('q-res-pts').textContent = `⭐ ${QS.score} pts`;
  document.getElementById('q-res-time').textContent = `⏱ ${elapsed}s`;

  // Beat your best banner
  const pb = QS.personalBest;
  if (pb && pct > pb.best_percentage) {
    document.getElementById('q-new-best').style.display = 'block';
    document.getElementById('q-new-best').innerHTML = `🎉 New Personal Best! ${pct}% (was ${pb.best_percentage}%)`;
  }

  // Submit to backend
  try {
    const response = await api('POST', '/quiz/submit', {
      quiz_id: QS.quizId,
      answers: QS.answers.map(a => ({ 
        question_id: a.question_id, 
        user_answer: a.user_answer,
        is_correct: a.is_correct  // Pass the frontend's verdict
      })),
      time_taken_seconds: elapsed
    });
    
    // Update Results with backend-verified data
    if (response.percentage !== undefined) {
      document.getElementById('q-res-score').textContent = `${response.score}/${response.total}`;
      document.getElementById('q-res-pct').textContent = `${Math.round(response.percentage)}%`;
      document.getElementById('q-res-pts').textContent = `⭐ ${response.skill_score} pts`;
    }
    
    loadPersonalBest();
  } catch (e) { }

  // Deep feedback (Gemini)
  if (QS.wrongAnswers.length > 0) {
    try {
      const fb = await api('POST', '/quiz/feedback', { wrong_answers: QS.wrongAnswers.slice(0, 5) });
      renderFeedbacks(QS.wrongAnswers, fb.feedbacks || []);
    } catch (e) { }
  }

  // AI Summary (Gemini)
  const weak = Object.entries(QS.topicMap).filter(([, v]) => v[0] / v[1] < 0.5).map(([k]) => k);
  const strong = Object.entries(QS.topicMap).filter(([, v]) => v[0] / v[1] >= 0.7).map(([k]) => k);
  try {
    const sum = await api('POST', '/quiz/summary', { results: { score: correct, total, weak_topics: weak, strong_topics: strong } });
    renderSummary(sum);
  } catch (e) { }

  // Store for fix mistakes
  QS.fixList = QS.wrongAnswers.map(w => ({ ...w, fixed: false, variant: null }));
}

function renderFeedbacks(wrongs, feedbacks) {
  const el = document.getElementById('q-feedback-area');
  if (!el) return;
  el.innerHTML = '<h4 style="margin-bottom:12px;color:#f59e0b;">📖 Why You Were Wrong</h4>' +
    wrongs.map((w, i) => {
      const f = feedbacks[i] || {};
      return `<div style="background:var(--surface2);border-left:3px solid #ef4444;border-radius:8px;padding:14px;margin-bottom:12px;">
        <div style="font-weight:600;margin-bottom:6px;">${w.question}</div>
        <div style="font-size:0.82rem;color:var(--text-muted);margin-bottom:4px;">❌ <em>${f.why_wrong || 'Incorrect choice.'}</em></div>
        <div style="font-size:0.82rem;color:#10b981;margin-bottom:4px;">✅ ${f.why_correct || w.correct_answer}</div>
        <div style="font-size:0.8rem;color:#818cf8;">💡 ${f.tip || 'Review this concept.'}</div>
      </div>`;
    }).join('');
}

function renderSummary(sum) {
  const el = document.getElementById('q-ai-summary');
  if (!el) return;
  el.style.display = 'block';
  el.innerHTML = `
    <div style="font-style:italic;color:var(--text-muted);margin-bottom:10px;">${sum.mastery_summary || ''}</div>
    ${(sum.next_steps || []).map(s => `<div style="padding:6px 10px;margin:4px 0;background:rgba(99,102,241,0.08);border-radius:6px;font-size:0.85rem;">→ ${s}</div>`).join('')}
    <div style="margin-top:10px;color:#10b981;font-size:0.85rem;font-style:italic;">${sum.motivation || ''}</div>`;
}

// ── Battle Mode ───────────────────────────────────────────────
async function startBattle() {
  const topic = document.getElementById('q-battle-topic').value.trim() || 'Computer Science';
  const btn = document.getElementById('q-battle-btn');
  btn.disabled = true; btn.textContent = '⚡ Loading Battle…';
  try {
    const d = await api('POST', '/quiz/battle/start', { topic });
    QS.quizId = d.quiz_id;

    // ✅ Filter nulls and normalize IDs for battle mode
    QS.questions = (d.questions || [])
      .filter(q => q && typeof q === 'object' && q.question)
      .map((q, i) => ({
        ...q,
        id: q.id || q._id || `bq${i + 1}`,
        options: q.options || [],
        correct_answer: q.correct_answer || ''
      }));

    QS.mode = 'battle';
    QS.battleTimeLeft = 90;
    resetSessionState();
    quizTab('taking');
    renderQuestion();
    startBattleCountdown();
  } catch (e) { toast('Battle failed: ' + e.message, 'error'); }
  finally { btn.disabled = false; btn.textContent = '⚡ Start Battle!'; }
}

function startBattleCountdown() {
  const el = document.getElementById('q-battle-clock');
  QS.battleTimer = setInterval(() => {
    QS.battleTimeLeft--;
    if (el) {
      el.textContent = `⏰ ${QS.battleTimeLeft}s`;
      el.style.color = QS.battleTimeLeft < 20 ? '#ef4444' : '#f59e0b';
    }
    if (QS.battleTimeLeft <= 0) { clearInterval(QS.battleTimer); finishQuiz(); }
  }, 1000);
}

// ── Fix Mistakes ──────────────────────────────────────────────
function renderFixList() {
  const el = document.getElementById('q-fix-list');
  if (!el) return;
  if (!QS.fixList.length) {
    el.innerHTML = '<p class="text-muted" style="text-align:center;padding:40px;">✅ No mistakes to fix! Complete a quiz first.</p>';
    return;
  }
  el.innerHTML = QS.fixList.map((item, i) => `
    <div id="fix-card-${i}" style="background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:12px;">
      <div style="font-weight:600;margin-bottom:8px;">${item.question}</div>
      <div style="font-size:0.82rem;color:#ef4444;margin-bottom:10px;">Your answer: ${item.user_answer} | Correct: ${item.correct_answer}</div>
      ${item.fixed
      ? '<div style="color:#10b981;font-weight:600;">✅ Recovered!</div>'
      : `<button class="btn btn-sm btn-primary" onclick="loadFixVariant(${i})">🔄 Practice Variant</button>`}
      <div id="fix-variant-${i}"></div>
    </div>`).join('');
}

async function loadFixVariant(idx) {
  const item = QS.fixList[idx];
  const varEl = document.getElementById(`fix-variant-${idx}`);
  
  // Animated Loader for Practice Variant
  varEl.innerHTML = `
    <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; padding:20px; gap:12px;">
      <div class="spinner" style="width:24px; height:24px; border-width:3px;"></div>
      <div style="color:var(--text-muted); font-size:0.8rem; font-weight:500; letter-spacing:0.5px; animation: pulse 1.5s infinite;">Generating AI Practice Variant...</div>
    </div>`;

  try {
    const q = await api('POST', '/quiz/fix_mistake', {
      question: item.question, 
      correct_answer: item.correct_answer, 
      topic: item.topic
    });

    if (!q || !q.question) throw new Error("AI failed to generate a valid variant.");

    varEl.style.opacity = '0';
    varEl.innerHTML = `
      <div style="margin-top:16px; padding:16px; background:rgba(99,102,241,0.06); border:1px solid rgba(99,102,241,0.15); border-radius:12px; animation: slideUp 0.4s ease forwards;">
        <div style="font-weight:700; margin-bottom:12px; color:var(--text); line-height:1.4;">${q.question}</div>
        <div style="display:grid; grid-template-columns:1fr; gap:8px;">
          ${(q.options || []).map((opt, j) => `
            <button class="q-opt-btn" style="width:100%; text-align:left; padding:12px 16px;"
              onclick="checkFixAnswer(${idx}, this, '${opt.replace(/'/g, "\\'")}', '${(q.correct_answer || '').replace(/'/g, "\\'")}', '${(q.explanation || '').replace(/'/g, "\\")}')">
              <span style="opacity:0.5; margin-right:8px; font-weight:800;">${['A', 'B', 'C', 'D'][j]}</span> ${opt}
            </button>`).join('')}
        </div>
      </div>`;
    setTimeout(() => { varEl.style.opacity = '1'; }, 10);
  } catch (e) { 
    varEl.innerHTML = `
      <div style="color:#ef4444; font-size:0.82rem; padding:12px; background:rgba(239,68,68,0.05); border-radius:8px; margin-top:10px; border:1px solid rgba(239,68,68,0.2);">
        ⚠️ <strong>Error:</strong> ${e.message}. <button class="link-btn" onclick="loadFixVariant(${idx})" style="color:#ef4444; font-weight:700; text-decoration:underline; cursor:pointer;">Retry?</button>
      </div>`; 
  }
}

function checkFixAnswer(idx, btn, selected, correct, explanation) {
  const card = document.getElementById(`fix-card-${idx}`);
  const buttons = card.querySelectorAll('button');
  buttons.forEach(b => b.disabled = true);

  const cleanSel = selected.trim().toLowerCase();
  const cleanCorr = correct.trim().toLowerCase();
  const isCorrect = cleanSel === cleanCorr || cleanCorr.includes(cleanSel) || cleanSel.includes(cleanCorr);

  if (isCorrect) {
    QS.fixList[idx].fixed = true;
    btn.classList.add('correct');
    btn.style.background = '#10b981';
    btn.style.color = 'white';
    btn.style.borderColor = '#10b981';
    
    // Add success message with nice styling
    const successMsg = document.createElement('div');
    successMsg.style.cssText = 'color:#10b981; font-weight:700; margin-top:12px; padding:10px; background:rgba(16,185,129,0.08); border-radius:8px; font-size:0.85rem; animation: bounceIn 0.5s ease;';
    successMsg.innerHTML = `✨ <strong>Recovered!</strong><br><span style="font-weight:400; font-size:0.8rem; opacity:0.9;">${explanation || 'Great job on fixing this mistake!'}</span>`;
    card.appendChild(successMsg);
  } else {
    btn.classList.add('wrong');
    btn.style.background = '#ef4444';
    btn.style.color = 'white';
    btn.style.borderColor = '#ef4444';

    // Show the correct answer
    buttons.forEach(b => {
      const bText = b.textContent.toLowerCase();
      if (b !== btn && (bText.includes(cleanCorr) || cleanCorr.includes(bText.replace(/^[A-D]\.\s*/, '')))) {
        b.style.background = '#10b981';
        b.style.color = 'white';
        b.style.borderColor = '#10b981';
      }
    });

    const failMsg = document.createElement('div');
    failMsg.style.cssText = 'color:#ef4444; font-weight:600; margin-top:12px; font-size:0.85rem;';
    failMsg.textContent = '❌ Still not quite right. Review the correct answer above.';
    card.appendChild(failMsg);
  }
}

// ── Mastery Radar ─────────────────────────────────────────────
async function renderMastery() {
  const el = document.getElementById('q-mastery-topics');
  if (!el) return;
  el.innerHTML = '<div style="text-align:center;padding:20px;">Loading mastery data…</div>';

  try {
    const d = await api('GET', '/quiz/mastery');
    const topics = Object.entries(d.mastery || {});
    if (!topics.length) {
      el.innerHTML = '<p class="text-muted" style="text-align:center;padding:30px;">Complete a quiz to see mastery.</p>';
      return;
    }
    el.innerHTML = topics.map(([topic, [c, t]]) => {
      const pct = Math.round(c / t * 100);
      const color = pct >= 70 ? '#10b981' : pct >= 40 ? '#f59e0b' : '#ef4444';
      return `<div style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;font-size:0.85rem;margin-bottom:4px;">
          <span>${topic}</span><span style="color:${color};font-weight:600;">${pct}% (${c}/${t})</span>
        </div>
        <div style="height:6px;background:var(--border);border-radius:3px;">
          <div style="width:${pct}%;height:100%;background:${color};border-radius:3px;transition:width .5s;"></div>
        </div>
      </div>`;
    }).join('');
  } catch (e) { el.innerHTML = '<p class="danger">Failed to load mastery.</p>'; }
}

// ── Leaderboard ───────────────────────────────────────────────
async function loadQuizLeaderboard(scope) {
  if (scope) {
    document.querySelectorAll('.q-board-btn').forEach(b => b.classList.toggle('active', b.dataset.scope === scope));
  } else {
    scope = document.querySelector('.q-board-btn.active').dataset.scope;
  }

  const time = document.getElementById('q-board-time').value;
  const topic = document.getElementById('q-board-topic').value;
  const diff = document.getElementById('q-board-diff').value;

  const el = document.getElementById('q-board-list');
  el.innerHTML = '<div style="text-align:center;padding:40px;"><div class="spinner"></div><div style="margin-top:10px;color:var(--text-muted);">Calculating rankings…</div></div>';

  try {
    const url = `/quiz/leaderboard?scope=${scope}&time=${time}&topic=${encodeURIComponent(topic)}&difficulty=${diff}`;
    const d = await api('GET', url);
    const rows = d.leaderboard || [];

    // Populate Topic Dropdown if not already done
    const topicSel = document.getElementById('q-board-topic');
    if (d.topics && topicSel.options.length <= 1) {
      d.topics.forEach(t => {
        const opt = new Option(t, t);
        topicSel.add(opt);
      });
    }

    // AI Insight logic
    const insightEl = document.getElementById('q-board-insight');
    const insightTxt = document.getElementById('q-board-insight-text');
    if (d.my_rank && scope !== 'personal') {
      insightEl.style.display = 'block';
      let msg = `🎯 Your current rank is <strong>#${d.my_rank}</strong>. `;
      if (d.my_rank === 1) msg += "You're the top learner! Keep defending your title! 🏆";
      else if (d.my_rank <= 3) msg += "You're on the podium! A little more speed could hit #1. 🥈";
      else msg += `You're in the top ${Math.round(d.my_rank / rows.length * 100) || 10}%. Focus on increasing your <strong>streak</strong> for a big point boost! 🚀`;
      insightTxt.innerHTML = msg;
    } else {
      insightEl.style.display = 'none';
    }

    if (!rows.length) {
      el.innerHTML = '<p class="text-muted" style="text-align:center;padding:40px;">No data found for these filters. Be the first to set a score! 🌟</p>';
      return;
    }

    if (scope === 'personal') {
      el.innerHTML = rows.map((r, i) => `
        <div style="background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;transition:all .2s;" onmouseover="this.style.borderColor='#6366f1'" onmouseout="this.style.borderColor='var(--border)'">
          <div>
            <div style="font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">Attempt #${rows.length - i} • ${r.topic || 'General'}</div>
            <div style="font-size:1.1rem;font-weight:700;color:${r.percentage >= 80 ? '#10b981' : r.percentage >= 50 ? '#f59e0b' : '#ef4444'}">${Math.round(r.percentage)}% <span style="font-size:0.8rem;color:var(--text-muted);font-weight:400;">(${r.score}/${r.total_questions})</span></div>
            <div style="font-size:0.8rem;color:var(--text-muted);margin-top:4px;">🔥 Streak: ${r.max_streak || 0} | ⭐ ${r.skill_score || 0} pts</div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:0.75rem;color:var(--text-muted);">${new Date(r.completed_at).toLocaleDateString()}</div>
            <div style="font-size:0.7rem;color:#6366f1;font-weight:600;margin-top:4px;text-transform:uppercase;">${r.difficulty}</div>
          </div>
        </div>`).join('');
    } else {
      el.innerHTML = `
        <div style="overflow-x:auto;">
          <table style="width:100%;border-collapse:collapse;min-width:500px;">
            <thead>
              <tr style="color:var(--text-muted);font-size:0.75rem;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid var(--border);">
                <th style="padding:12px 8px;text-align:left;">Rank</th>
                <th style="padding:12px 8px;text-align:left;">Learner</th>
                <th style="padding:12px 8px;text-align:right;">Accuracy</th>
                <th style="padding:12px 8px;text-align:right;">Best Streak</th>
                <th style="padding:12px 8px;text-align:right;">Solved</th>
                <th style="padding:12px 8px;text-align:right;">Attempts</th>
                <th style="padding:12px 8px;text-align:right;color:#6366f1;">Skill Score</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map((r, i) => `
                <tr style="border-bottom:1px solid rgba(255,255,255,0.03);${r.is_me ? 'background:rgba(99,102,241,0.08);' : ''}">
                  <td style="padding:14px 8px;">
                    <div style="display:flex;align-items:center;gap:8px;">
                      <span style="font-size:1.1rem;font-weight:800;width:24px;">${r.rank === 1 ? '🥇' : r.rank === 2 ? '🥈' : r.rank === 3 ? '🥉' : '#' + r.rank}</span>
                    </div>
                  </td>
                  <td style="padding:14px 8px;">
                    <div style="font-weight:600;display:flex;align-items:center;gap:6px;">
                      ${r.username} ${r.is_me ? '<span style="font-size:0.6rem;background:#6366f1;color:white;padding:2px 5px;border-radius:4px;">YOU</span>' : ''}
                    </div>
                  </td>
                  <td style="padding:14px 8px;text-align:right;font-weight:600;color:${r.avg_accuracy >= 80 ? '#10b981' : r.avg_accuracy >= 50 ? '#f59e0b' : '#ef4444'}">${Math.round(r.avg_accuracy)}%</td>
                  <td style="padding:14px 8px;text-align:right;color:#f59e0b;font-weight:600;">🔥 ${r.max_streak}</td>
                  <td style="padding:14px 8px;text-align:right;color:var(--text-muted);">${r.total_correct} / ${r.total_questions}</td>
                  <td style="padding:14px 8px;text-align:right;color:var(--text-muted);">${r.total_attempts}</td>
                  <td style="padding:14px 8px;text-align:right;">
                    <div style="color:#6366f1;font-weight:800;font-size:1.05rem;">${Math.round(r.best_skill_score)}</div>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>`;
    }
  } catch (e) {
    el.innerHTML = `<div style="color:var(--danger);text-align:center;padding:40px;">⚠️ Failed to load leaderboard: ${e.message}</div>`;
  }
}