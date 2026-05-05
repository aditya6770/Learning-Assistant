/* ═══════════════════════════════════════════════════════════
   emotion.js  —  Enhanced Emotion Intelligence System
   Replaces the old focus-mode logic entirely.
   Depends on: core.js (api, toast, TOKEN, API, documents)
   ═══════════════════════════════════════════════════════════ */

// ── State ─────────────────────────────────────────────────────
let emPuzzleCompleted = false;
let emPuzzleActive = false;
let emCameraStream   = null;
let emInterval       = null;
let emSnapshots      = [];
let emSessionId      = null;
let emSessionStart   = null;
let emTotalPoints    = 0;
let emCurrentState   = "unknown";
let emCurrentDelta   = 0;
let emCurrentDiff    = "medium";   // synced with quiz difficulty
let emScoreHistory   = [];         // [{time, score, state}]
let emQuizContext    = { wrong_streak:0, avg_time_per_question:0, recent_accuracy:1.0 };
let emTypingContext  = { wpm:0, backspace_rate:0, pause_count:0, idle_seconds:0 };
let emInsightTimer   = null;
let emSpeedModeUnlocked = false;

// Emotion color map
const EM_COLORS = {
  frustrated: "#ef4444", anxious: "#f97316", confused: "#f59e0b",
  unknown:    "#64748b", focused: "#06b6d4", curious:  "#8b5cf6",
  engaged:    "#10b981", bored:   "#a855f7",
};
const EM_ICONS = {
  frustrated:"😤", anxious:"😰", confused:"😕", unknown:"❓",
  focused:"🎯", curious:"🔍", engaged:"🚀", bored:"😴",
};

// ── DOM Helpers ───────────────────────────────────────────────
function emEl(id) { return document.getElementById(id); }
function emSetText(id, txt) { const e=emEl(id); if(e) e.textContent=txt; }
function emSetHtml(id, html){ const e=emEl(id); if(e) e.innerHTML=html; }

// ── Camera ────────────────────────────────────────────────────
async function startCamera() {
  try {
    emCameraStream = await navigator.mediaDevices.getUserMedia({ video: true });
    emEl("webcam-preview").srcObject = emCameraStream;
    emEl("start-cam-btn").style.display = "none";
    emEl("stop-cam-btn").style.display  = "inline-flex";
    emSessionId    = crypto.randomUUID();
    emSessionStart = Date.now();
    emSnapshots    = [];
    emScoreHistory = [];
    emInterval     = setInterval(emCapture, 1000);   // every 1 s
    emStartInsightPolling();
    emEl("em-session-badge").style.display = "inline-flex";
    emRenderTimeline();
    toast("Focus session started 📡", "info");
  } catch(e) { toast("Camera access denied or unavailable", "error"); }
}

function stopCamera() {
  if (emCameraStream) emCameraStream.getTracks().forEach(t => t.stop());
  clearInterval(emInterval);
  clearInterval(emInsightTimer);
  emEl("start-cam-btn").style.display = "inline-flex";
  emEl("stop-cam-btn").style.display  = "none";
  emEl("em-session-badge").style.display = "none";
  if (emSnapshots.length > 0) emEndSession();
}

// ── Capture & Analyze ─────────────────────────────────────────
async function emCapture() {
  const video  = emEl("webcam-preview");
  const canvas = document.createElement("canvas");
  canvas.width = 640; canvas.height = 480;
  canvas.getContext("2d").drawImage(video, 0, 0, 320, 240);
  const b64 = canvas.toDataURL("image/jpeg", 0.9).split(",")[1];

  try {
    const d = await api("POST", "/emotion/analyze", {
      frame:       b64,
      session_id:  emSessionId,
      typing_data: emTypingContext,
      quiz_data:   emQuizContext,
    });

    emCurrentState = d.dominant_state || d.emotion;
    emCurrentDelta = d.difficulty_delta || 0;
    const snap = {
      dominant_state:   emCurrentState,
      engagement_score: d.engagement_score || d.attention_score * 100,
      raw_emotion:      d.emotion,
      timestamp:        Date.now(),
    };
    emSnapshots.push(snap);
    emScoreHistory.push({
      time:  Math.round((Date.now() - emSessionStart) / 1000),
      score: snap.engagement_score,
      state: emCurrentState,
    });

    emUpdateLivePanels(d);
    emHandleTriggers(d.triggers || []);
    emAdaptDifficulty(d);
    emRenderTimeline();
    emRenderScoreChart();
  } catch(e) { console.error("Emotion capture error", e); }
}

// ── Live Panels ───────────────────────────────────────────────
function emUpdateLivePanels(d) {
  const state = d.dominant_state || d.emotion;
  const col   = EM_COLORS[state] || "#64748b";
  const icon  = EM_ICONS[state]  || "❓";
  const score = Math.round(d.engagement_score || d.attention_score * 100);

  // Badge
  const badge = emEl("emotion-badge");
  if (badge) {
    badge.textContent = `${icon} ${state.charAt(0).toUpperCase()+state.slice(1)}`;
    badge.style.background = col + "22";
    badge.style.color      = col;
    badge.style.border     = `1px solid ${col}66`;
  }

  // Attention bar
  const bar = emEl("attention-bar");
  if (bar) { bar.style.width = score + "%"; bar.style.background = col; }
  emSetText("attention-value", score + "%");

  // Engagement score ring
  emSetText("em-score-value", score);
  const ring = emEl("em-score-ring");
  if (ring) {
    const circ = 2 * Math.PI * 45;
    const offset = circ - (score / 100) * circ;
    ring.style.strokeDasharray  = circ;
    ring.style.strokeDashoffset = offset;
    ring.style.stroke = col;
  }

  // State label & motivation
  emSetHtml("em-state-label", `<span style="color:${col};font-weight:700;">${icon} ${state}</span>`);
  emSetText("em-motivation-text", d.motivation || "");

  // Points accumulation
  emTotalPoints = Math.round(score * 0.1) + emTotalPoints;
  emSetText("em-points-value", emTotalPoints);

  // Session stats
  const elapsed = Math.round((Date.now() - emSessionStart) / 1000);
  const avgScore = emSnapshots.length
    ? Math.round(emSnapshots.reduce((s,x)=>s+x.engagement_score,0)/emSnapshots.length)
    : score;
  emSetHtml("session-stats",
    `Frames: <b>${emSnapshots.length}</b> | 
     Avg engagement: <b>${avgScore}%</b> | 
     Session: <b>${Math.floor(elapsed/60)}:${String(elapsed%60).padStart(2,"0")}</b>`
  );
}

// ── Triggers (Frustration / Boredom) ─────────────────────────
function emHandleTriggers(triggers) {
  const panel = emEl("em-trigger-panel");
  // Reset when no frustration triggers
if (!triggers.some(t => t.action === "show_puzzle")) {
  emPuzzleCompleted = false;
}
  if (!panel) return;
  if (!triggers.length) { panel.style.display = "none"; return; }

  triggers.forEach(t => {
    if (t.action === "show_puzzle") {
        emShowPuzzleStack(t.puzzles);
    }

    if (t.action === "unlock_speed_quiz" && !emSpeedModeUnlocked) {
      emSpeedModeUnlocked = true;
      panel.style.display = "block";
      emSetHtml("em-trigger-content",
        `<div style="display:flex;align-items:center;gap:12px;">
          <span style="font-size:1.6rem;">😴</span>
          <div>
            <div style="font-weight:600;color:#a855f7;margin-bottom:4px;">Boredom Detected — Speed Mode Unlocked!</div>
            <div style="font-size:0.85rem;color:var(--text-muted);">⚡ Speed Quiz mode has been unlocked in the Quizzes section.</div>
          </div>
        </div>
        <button class="btn btn-sm btn-primary" style="margin-top:10px;" onclick="emGoSpeedQuiz()">
          ⚡ Start Speed Quiz Now
        </button>`
      );
      // Notify quiz.js that speed mode is available
      window.emSpeedModeAvailable = true;
      emShowSpeedModeInQuiz();
    }
  });
}

function emLaunchQuickWin() {
  // Get easiest quiz for the user or navigate to quiz with easy preset
  if (typeof showPage === "function") showPage("quiz");
  setTimeout(() => {
    const diffSel = document.getElementById("quiz-difficulty");
    const mcqInp  = document.getElementById("quiz-n-mcq");
    if (diffSel) diffSel.value = "easy";
    if (mcqInp)  mcqInp.value  = "3";
    toast("🎯 Quick Win mode set: 3 easy questions!", "success");
  }, 300);
}

function emGoSpeedQuiz() {
  if (typeof showPage === "function") showPage("quiz");
  setTimeout(() => {
    emShowSpeedModeInQuiz();
    toast("⚡ Speed Quiz mode is ready!", "success");
  }, 300);
}

function emShowSpeedModeInQuiz() {
  const existing = document.getElementById("speed-mode-banner");
  if (existing) return;
  const quizPane = document.getElementById("quiz-generate-pane");
  if (!quizPane) return;
  const banner = document.createElement("div");
  banner.id = "speed-mode-banner";
  banner.style.cssText =
    "background:linear-gradient(135deg,rgba(168,85,247,.15),rgba(99,102,241,.15));" +
    "border:1px solid rgba(168,85,247,.3);border-radius:10px;padding:14px 18px;" +
    "margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;gap:12px;";
  banner.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;">
      <span style="font-size:1.5rem;">⚡</span>
      <div>
        <div style="font-weight:700;color:#a855f7;">Speed Quiz Mode Unlocked!</div>
        <div style="font-size:0.8rem;color:var(--text-muted);">10 questions, 30s each — detected boredom by emotion AI</div>
      </div>
    </div>
    <button class="btn btn-sm" style="background:linear-gradient(135deg,#a855f7,#6366f1);color:white;" onclick="emStartSpeedQuiz()">▶ Start</button>`;
  quizPane.insertBefore(banner, quizPane.firstChild);
}

function emStartSpeedQuiz() {
  const diffSel = document.getElementById("quiz-difficulty");
  const mcqInp  = document.getElementById("quiz-n-mcq");
  const fibInp  = document.getElementById("quiz-n-fib");
  if (diffSel) diffSel.value = "hard";
  if (mcqInp)  mcqInp.value = "8";
  if (fibInp)  fibInp.value = "0";
  toast("⚡ Speed Quiz: 8 hard questions, go!", "info");
  if (typeof generateQuiz === "function") generateQuiz();
}

// ── Difficulty Adaptation ─────────────────────────────────────
function emAdaptDifficulty(d) {
  const delta = d.difficulty_delta || 0;
  if (delta === 0) return;

  const levels   = ["very_easy","easy","medium","hard","very_hard"];
  const cur      = levels.indexOf(emCurrentDiff);
  const next     = Math.max(0, Math.min(4, cur + delta));
  const newDiff  = levels[next];
  if (newDiff === emCurrentDiff) return;
  emCurrentDiff = newDiff;

  const action   = delta > 0 ? "increased" : "decreased";
  const col      = delta > 0 ? "#10b981" : "#f59e0b";
  const msg      = `${delta > 0 ? "📈" : "📉"} Difficulty ${action} to <strong>${newDiff}</strong> based on your emotion (${emCurrentState})`;

  // Show banner in Quiz section
  emShowAdaptBanner("quiz-generate-pane",  msg, col, "quiz-adapt-banner");
  // Show banner in QA section
  emShowAdaptBanner("page-qa",             msg, col, "qa-adapt-banner");
  // Show banner in Revision section
  emShowAdaptBanner("rev-results",         msg, col, "rev-adapt-banner");

  // Also update quiz difficulty selector silently
  const diffSel = document.getElementById("quiz-difficulty");
  if (diffSel) diffSel.value = newDiff;

  emSetHtml("em-adapt-status",
    `<div style="color:${col};font-size:0.85rem;">${msg}</div>`
  );
}

function emShowAdaptBanner(parentId, msg, col, bannerId) {
  let banner = document.getElementById(bannerId);
  if (!banner) {
    banner = document.createElement("div");
    banner.id = bannerId;
    banner.style.cssText =
      `border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:0.82rem;` +
      `display:flex;align-items:center;gap:8px;`;
    const parent = document.getElementById(parentId);
    if (parent) parent.insertBefore(banner, parent.firstChild);
  }
  banner.style.background = col + "22";
  banner.style.border      = `1px solid ${col}44`;
  banner.style.color       = col;
  banner.innerHTML         = `🧠 Emotion AI: ` + msg;
  setTimeout(() => { banner.style.opacity = "0.5"; }, 8000);
}

// ── Session Timeline ──────────────────────────────────────────
function emRenderTimeline() {
  const container = emEl("em-timeline");
  if (!container || emSnapshots.length < 2) return;

  const total    = emSnapshots.length;
  let html       = `<div style="display:flex;gap:2px;height:28px;border-radius:6px;overflow:hidden;">`;
  let prevState  = emSnapshots[0].dominant_state;
  let segStart   = 0;

  const flush = (end, state) => {
    const pct = ((end - segStart) / total * 100).toFixed(1);
    const col  = EM_COLORS[state] || "#64748b";
    const icon = EM_ICONS[state]  || "?";
    html += `<div title="${icon} ${state}" style="flex:${pct};background:${col};opacity:0.8;transition:flex .3s;"></div>`;
  };

  for (let i = 1; i < total; i++) {
    const s = emSnapshots[i].dominant_state;
    if (s !== prevState) { flush(i, prevState); prevState = s; segStart = i; }
  }
  flush(total, prevState);
  html += `</div>`;

  // Labels below
  html += `<div style="display:flex;justify-content:space-between;margin-top:4px;font-size:0.68rem;color:var(--text-muted);">
    <span>0:00</span>
    <span>${Math.round(total * 4 / 60)}:${String(Math.round(total * 4 % 60)).padStart(2,"0")}</span>
  </div>`;

  // State legend
  const seen = [...new Set(emSnapshots.map(s => s.dominant_state))];
  html += `<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;">`;
  seen.forEach(s => {
    const col = EM_COLORS[s] || "#64748b";
    html += `<span style="display:flex;align-items:center;gap:4px;font-size:0.72rem;color:${col};">
      <span style="width:8px;height:8px;border-radius:50%;background:${col};display:inline-block;"></span>
      ${EM_ICONS[s]} ${s}
    </span>`;
  });
  html += `</div>`;
  container.innerHTML = html;
}

// ── Score Chart (Canvas) ──────────────────────────────────────
function emRenderScoreChart() {
  const canvas = emEl("em-score-chart");
  if (!canvas || emScoreHistory.length < 2) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.offsetWidth || 400, H = 140;
  canvas.width = W; canvas.height = H;
  ctx.clearRect(0, 0, W, H);

  // Background
  ctx.fillStyle = "#1e293b"; ctx.fillRect(0, 0, W, H);

  // Grid lines
  ctx.strokeStyle = "#334155"; ctx.lineWidth = 1;
  [25, 50, 75, 100].forEach(v => {
    const y = H - 20 - (v / 100) * (H - 30);
    ctx.beginPath(); ctx.moveTo(30, y); ctx.lineTo(W - 10, y); ctx.stroke();
    ctx.fillStyle = "#475569"; ctx.font = "9px monospace";
    ctx.fillText(v + "%", 2, y + 3);
  });

  // Emotion-colored segments
  const pts = emScoreHistory;
  const xStep = (W - 40) / (pts.length - 1 || 1);

  for (let i = 1; i < pts.length; i++) {
    const x0 = 30 + (i-1) * xStep, y0 = H - 20 - (pts[i-1].score / 100) * (H - 30);
    const x1 = 30 + i * xStep,     y1 = H - 20 - (pts[i].score   / 100) * (H - 30);
    ctx.beginPath();
    ctx.strokeStyle = EM_COLORS[pts[i].state] || "#64748b";
    ctx.lineWidth = 2.5;
    ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
  }

  // Dots
  pts.forEach((p, i) => {
    const x = 30 + i * xStep, y = H - 20 - (p.score / 100) * (H - 30);
    ctx.beginPath();
    ctx.arc(x, y, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = EM_COLORS[p.state] || "#64748b"; ctx.fill();
  });

  // Time axis label
  ctx.fillStyle = "#64748b"; ctx.font = "9px monospace";
  const totalSec = pts[pts.length - 1]?.time || 0;
  ctx.fillText("0s", 30, H - 4);
  ctx.fillText(totalSec + "s", W - 30, H - 4);

  // Emotion vs Time segments annotation
  emRenderEmotionTimeTable();
}

function emRenderEmotionTimeTable() {
  const container = emEl("em-emotion-time-table");
  if (!container || emScoreHistory.length < 3) return;

  // Build time segments
  const segs = [];
  let cur  = emScoreHistory[0].state;
  let t0   = emScoreHistory[0].time;
  let scores = [emScoreHistory[0].score];

  for (let i = 1; i < emScoreHistory.length; i++) {
    const p = emScoreHistory[i];
    if (p.state !== cur) {
      segs.push({ state: cur, from_s: t0, to_s: emScoreHistory[i-1].time, avg_score: Math.round(scores.reduce((a,b)=>a+b,0)/scores.length) });
      cur = p.state; t0 = p.time; scores = [];
    }
    scores.push(p.score);
  }
  segs.push({ state: cur, from_s: t0, to_s: emScoreHistory[emScoreHistory.length-1].time, avg_score: Math.round(scores.reduce((a,b)=>a+b,0)/scores.length) });

  const fmt = s => `${Math.floor(s/60)}:${String(s%60).padStart(2,"0")}`;
  let html = `<table style="width:100%;border-collapse:collapse;font-size:0.78rem;">
    <thead><tr style="color:var(--text-muted);border-bottom:1px solid var(--border);">
      <th style="padding:6px 8px;text-align:left;">Time</th>
      <th style="padding:6px 8px;text-align:left;">Emotion</th>
      <th style="padding:6px 8px;text-align:right;">Avg Score</th>
    </tr></thead><tbody>`;
  segs.forEach(seg => {
    const col = EM_COLORS[seg.state] || "#64748b";
    html += `<tr style="border-bottom:1px solid #1e293b;">
      <td style="padding:5px 8px;color:var(--text-muted);">${fmt(seg.from_s)} – ${fmt(seg.to_s)}</td>
      <td style="padding:5px 8px;"><span style="color:${col};">${EM_ICONS[seg.state]} ${seg.state}</span></td>
      <td style="padding:5px 8px;text-align:right;color:${col};font-weight:600;">${seg.avg_score}%</td>
    </tr>`;
  });
  html += `</tbody></table>`;
  container.innerHTML = html;
}

// ── AI Insight Polling (every 90s) ────────────────────────────
function emStartInsightPolling() {
  emInsightTimer = setInterval(async () => {
    if (emSnapshots.length < 3) return;
    await emFetchAIInsight();
  }, 90000);
}

async function emFetchAIInsight() {
  if (!emSnapshots.length) return;
  const avgScore = Math.round(emSnapshots.reduce((s,x)=>s+x.engagement_score,0)/emSnapshots.length);
  const elapsed  = Math.round((Date.now() - emSessionStart) / 60000);

  try {
    emSetHtml("em-insight-status", `<div style="font-size:0.8rem;color:var(--text-muted);">🤖 Fetching AI insight…</div>`);
    const d = await api("POST", "/emotion/ai-insight", {
      dominant_state:       emCurrentState,
      wrong_questions:      emQuizContext.wrong_streak,
      time_spent_minutes:   elapsed,
      recent_topic:         window._lastQuizTitle || "general study",
      session_avg_score:    avgScore,
      recent_question:      window._lastQaQuestion || "",
    });
    emRenderInsight(d);
  } catch(e) { console.warn("AI insight fetch failed", e); }
}

function emRenderInsight(d) {
  const col = EM_COLORS[emCurrentState] || "#64748b";

  // Motivation
  emSetHtml("em-insight-motivation", `
    <div style="background:${col}18;border:1px solid ${col}44;border-radius:10px;padding:14px 16px;">
      <div style="font-size:0.75rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:${col};margin-bottom:6px;">💬 AI Coach</div>
      <p style="font-size:0.9rem;line-height:1.6;color:var(--text);">${d.combined_motivation || ""}</p>
    </div>`
  );

  // Suggestions
  const suggs = d.suggestions || [];
  emSetHtml("em-insight-suggestions",
    `<div style="font-size:0.75rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px;">💡 Suggestions</div>` +
    suggs.map(s => `<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:6px;font-size:0.85rem;">
      <span style="color:${col};flex-shrink:0;">›</span><span>${s}</span>
    </div>`).join("")
  );

  // Feedback
  if (d.feedback) {
    const action = d.difficulty_action || "maintain";
    const aCol   = action === "increase" ? "#10b981" : action === "decrease" ? "#ef4444" : "#06b6d4";
    emSetHtml("em-insight-feedback", `
      <div style="background:var(--surface2);border-radius:10px;padding:14px 16px;margin-top:14px;">
        <div style="font-size:0.75rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">📊 Performance Feedback</div>
        <p style="font-size:0.85rem;line-height:1.6;color:var(--text-muted);">${d.feedback}</p>
        <div style="margin-top:8px;font-size:0.82rem;color:${aCol};font-weight:600;">
          ${action === "increase" ? "📈" : action === "decrease" ? "📉" : "✅"} 
          Difficulty: <strong>${action.toUpperCase()}</strong> — ${d.difficulty_reason || ""}
        </div>
      </div>`
    );
  }

  emSetHtml("em-insight-status",
    `<div style="font-size:0.72rem;color:var(--text-muted);">Last AI update: ${new Date().toLocaleTimeString()}</div>`
  );
}

// ── Session End ───────────────────────────────────────────────
async function emEndSession() {
  const duration = Math.round((Date.now() - emSessionStart) / 1000);
  try {
    const d = await api("POST", "/emotion/session/end", {
      session_id:       emSessionId,
      snapshots:        emSnapshots,
      duration_seconds: duration,
    });
    emTotalPoints += d.emotion_points || 0;
    emSetText("em-points-value", emTotalPoints);
    emRenderSessionSummary(d);
    toast(`Session ended — earned ${d.emotion_points || 0} emotion points! 🎉`, "success");
  } catch(e) { console.warn("Session end failed", e); }
}

function emRenderSessionSummary(d) {
  const el = emEl("em-session-summary");
  if (!el) return;
  const col = EM_COLORS[d.dominant_state || "focused"] || "#06b6d4";
  el.style.display = "block";
  emSetHtml("em-session-summary", `
    <div style="background:linear-gradient(135deg,${col}18,${col}08);border:1px solid ${col}33;border-radius:12px;padding:18px 20px;margin-top:16px;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
        <div style="font-weight:700;font-size:1rem;">📊 Session Summary</div>
        <div style="font-size:1.4rem;font-weight:800;color:${col};">+${d.emotion_points || 0} pts</div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px;">
        <div style="text-align:center;background:var(--surface2);border-radius:8px;padding:10px;">
          <div style="font-size:1.4rem;font-weight:700;color:${col};">${d.avg_engagement || 0}%</div>
          <div style="font-size:0.72rem;color:var(--text-muted);">Avg Engagement</div>
        </div>
        <div style="text-align:center;background:var(--surface2);border-radius:8px;padding:10px;">
          <div style="font-size:1.4rem;font-weight:700;color:${col};">${EM_ICONS[d.dominant_state]} ${d.dominant_state || "?"}</div>
          <div style="font-size:0.72rem;color:var(--text-muted);">Dominant Emotion</div>
        </div>
        <div style="text-align:center;background:var(--surface2);border-radius:8px;padding:10px;">
          <div style="font-size:1.4rem;font-weight:700;color:${col};">${d.emotion_points || 0}</div>
          <div style="font-size:0.72rem;color:var(--text-muted);">Points Earned</div>
        </div>
      </div>
      ${(d.timeline||[]).length ? `
        <div style="font-size:0.75rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">Emotion Timeline</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          ${d.timeline.map(seg => {
            const sc = EM_COLORS[seg.state] || "#64748b";
            return `<span style="background:${sc}22;color:${sc};padding:3px 10px;border-radius:12px;font-size:0.73rem;">
              ${EM_ICONS[seg.state]} ${seg.state} (${seg.start_min}–${seg.end_min} min)
            </span>`;
          }).join("")}
        </div>
      ` : ""}
    </div>`
  );
}

// ── Typing Context Tracker ────────────────────────────────────
// Called from inline oninput handlers in QA / Groq sections
let _emLastKeyTime = Date.now();
let _emKeyCount    = 0;
let _emBackspaces  = 0;
let _emWordCount   = 0;
let _emPauses      = 0;

function emTrackTyping(e) {
  const now = Date.now();
  const gap  = now - _emLastKeyTime;
  if (gap > 3000) _emPauses++;

  if (e && e.key === "Backspace") _emBackspaces++;
  else                            _emKeyCount++;

  const text  = (e?.target?.value || "");
  _emWordCount = text.trim().split(/\s+/).filter(Boolean).length;
  const elapsed = Math.max((now - (_emSessionStart || now)) / 60000, 0.01);
  const wpm     = Math.round(_emWordCount / elapsed);

  emTypingContext = {
    wpm:            wpm,
    backspace_rate: _emWordCount ? _emBackspaces / _emWordCount : 0,
    pause_count:    _emPauses,
    idle_seconds:   Math.round(gap / 1000),
  };
  _emLastKeyTime = now;
}

// ── Quiz Context Updater ──────────────────────────────────────
// Called by quiz.js after each answer
function emUpdateQuizContext(wasCorrect, timeForQuestion) {
  if (!wasCorrect) {
    emQuizContext.wrong_streak   = (emQuizContext.wrong_streak || 0) + 1;
    emQuizContext.recent_accuracy = Math.max(0,
      (emQuizContext.recent_accuracy * 0.8 + 0 * 0.2)
    );
  } else {
    emQuizContext.wrong_streak   = 0;
    emQuizContext.recent_accuracy = Math.min(1,
      (emQuizContext.recent_accuracy * 0.8 + 1 * 0.2)
    );
  }
  // Rolling avg of time per question
  emQuizContext.avg_time_per_question = Math.round(
    (emQuizContext.avg_time_per_question * 0.7 + timeForQuestion * 0.3)
  );
}

// ── Manual AI Insight Trigger ─────────────────────────────────
async function emGetManualInsight() {
  const btn = emEl("em-get-insight-btn");
  if (btn) { btn.disabled = true; btn.textContent = "⏳ Analyzing…"; }
  await emFetchAIInsight();
  if (btn) { btn.disabled = false; btn.textContent = "🤖 Get AI Insight"; }
}

// ── Load Session History ──────────────────────────────────────
async function emLoadHistory() {
  try {
    const d = await api("GET", "/emotion/session-history?limit=5");
    console.log("TOTAL POINTS:", d.total_emotion_points); 
    const el = emEl("em-history-list");
    if (!el) return;
    if (!d.sessions.length) { el.innerHTML = '<p class="text-muted">No sessions yet.</p>'; return; }

    emSetText("em-total-points-hist", d.total_emotion_points || 0);
    emSetText("em-points-value", emTotalPoints);
    el.innerHTML = d.sessions.map(s => {
      const col = EM_COLORS[s.dominant_state] || "#64748b";
      const dur = Math.round((s.duration_seconds || 0) / 60);
      return `<div style="display:flex;align-items:center;gap:12px;padding:12px 14px;background:var(--surface2);border-radius:9px;margin-bottom:8px;">
        <div style="width:36px;height:36px;border-radius:50%;background:${col}22;border:2px solid ${col};display:flex;align-items:center;justify-content:center;font-size:1.1rem;flex-shrink:0;">${EM_ICONS[s.dominant_state] || "❓"}</div>
        <div style="flex:1;">
          <div style="font-size:0.85rem;font-weight:600;">${s.dominant_state} — ${s.avg_engagement || 0}% engagement</div>
          <div style="font-size:0.72rem;color:var(--text-muted);">${dur} min · ${new Date(s.ended_at).toLocaleDateString()}</div>
        </div>
        <div style="font-weight:700;color:${col};font-size:1rem;">+${s.emotion_points || 0}pts</div>
      </div>`;
    }).join("");
  } catch(e) { console.warn("History load failed", e); }
}

// ── Page Init ─────────────────────────────────────────────────
function emInit() {
  emLoadHistory();
  // Attach typing trackers to QA and Groq inputs
  ["qa-input","ds-input","rev-chat-input"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("keydown", emTrackTyping);
  });
}

// Wire into showPage
const _emOrigShowPage = window.showPage;
if (typeof _emOrigShowPage === "function") {
  window.showPage = function(page) {
    _emOrigShowPage(page);
    if (page === "emotion") { emInit(); }
  };
}

// ── Puzzle Stack System ─────────────────────────
let emPuzzleStack = [];
let emCurrentPuzzleIndex = 0;

function emShowPuzzleStack(puzzles) {
  if (emPuzzleActive || emPuzzleCompleted) return;   // 🚫 prevent spam

  emPuzzleActive = true;
  emPuzzleStack = puzzles;
  emCurrentPuzzleIndex = 0;
  renderCurrentPuzzle();
}

function renderCurrentPuzzle() {
  const panel = emEl("em-trigger-panel");
  panel.style.display = "block";

  if (emCurrentPuzzleIndex >= emPuzzleStack.length) {
  emSetHtml("em-trigger-content",
    `<div style="color:white;">🎉 All puzzles done! You're refreshed 🚀</div>`
  );
  emPuzzleActive = false;
  emPuzzleCompleted = true;
  setTimeout(() => {
    const panel = emEl("em-trigger-panel");
    if (panel) panel.style.display = "none";
  }, 2000);

  return;
}

  const p = emPuzzleStack[emCurrentPuzzleIndex];

if (!p) {
  emSetHtml("em-trigger-content",
    `<div style="color:white;">⚠️ No puzzles available</div>`
  );
  return;
}

  const optionsHtml = p.options.map(opt => `
    <button class="puzzle-option"
      onclick="emCheckPuzzleAnswer('${opt}','${p.answer}')">
      ${opt}
    </button>
  `).join("");

  emSetHtml("em-trigger-content", `
    <div class="puzzle-card">
      <div style="font-weight:700;">🧩 Puzzle ${emCurrentPuzzleIndex+1}/${emPuzzleStack.length}</div>
      <div style="margin:10px 0;">${p.question}</div>
      <div>${optionsHtml}</div>
      <div style="margin-top:10px;">💡 ${p.hint}</div>
    </div>
  `);
}

function emCheckPuzzleAnswer(selected, correct) {
  if (selected === correct) {
    toast("🎉 Correct! Loading next...", "success");

    emCurrentPuzzleIndex++;

    setTimeout(() => {
      renderCurrentPuzzle();
    }, 400);

  } else {
    toast("❌ Try again!", "warning");
  }
}