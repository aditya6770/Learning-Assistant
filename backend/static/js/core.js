/* ═══════════════════════════════════════════════════════════
   core.js  —  State, API helpers, Auth, App Init, Documents, Q&A
   ═══════════════════════════════════════════════════════════ */

// ── Global State ─────────────────────────────────────────────
const API = 'http://127.0.0.1:5000/api';
let TOKEN = sessionStorage.getItem('token') || '';
let USER = JSON.parse(sessionStorage.getItem('user') || 'null');
let documents = [];

let cameraStream = null, emotionInterval = null;
let sessionSnapshots = [], sessionId = crypto.randomUUID();
let mediaRecorder = null, audioChunks = [], isRecording = false;

// ── API Helper ────────────────────────────────────────────────
async function api(method, path, body, isForm = false) {
  const opts = { method, headers: { Authorization: `Bearer ${TOKEN}` } };
  if (body) {
    if (isForm) { opts.body = body; }
    else { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  }
  const res = await fetch(API + path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Request failed');
  return data;
}

// ── Toast ─────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

function toggleLoader(show) {
  const loader = document.getElementById('global-loader');
  if (loader) {
    loader.style.display = show ? 'flex' : 'none';
  }
}

// ── Auth ──────────────────────────────────────────────────────
function switchAuthTab(tab) {
  document.querySelectorAll('.auth-tab').forEach((t, i) =>
    t.classList.toggle('active', i === (tab === 'login' ? 0 : 1))
  );
  document.getElementById('login-form').style.display = tab === 'login' ? 'block' : 'none';
  document.getElementById('register-form').style.display = tab === 'register' ? 'block' : 'none';
}

async function login() {
  const email = document.getElementById('login-email').value;
  const password = document.getElementById('login-password').value;
  if (!email || !password) return toast("Please enter credentials", "warning");

  toggleLoader(true);
  try {
    const d = await api('POST', '/auth/login', { email, password });
    TOKEN = d.token; USER = d.user;
    // Normalize user ID across all fields so quiz/leaderboard both work
    if (USER) {
      USER.user_id = USER._id || USER.user_id || USER.id || '';
      USER._id     = USER.user_id;
    }
    sessionStorage.setItem('token', TOKEN);
    sessionStorage.setItem('user', JSON.stringify(USER));
    initApp();
  } catch (e) { 
    toggleLoader(false);
    toast(e.message, 'error'); 
  }
}

async function register() {
  const username = document.getElementById('reg-username').value;
  const email = document.getElementById('reg-email').value;
  const password = document.getElementById('reg-password').value;
  const preferred_language = document.getElementById('reg-lang').value;
  if (!username || !email || !password) return toast("All fields are required", "warning");

  toggleLoader(true);
  try {
    const d = await api('POST', '/auth/register', { username, email, password, preferred_language });
    TOKEN = d.token; USER = d.user;
    if (USER) {
      USER.user_id = USER._id || USER.user_id || USER.id || '';
      USER._id     = USER.user_id;
    }
    sessionStorage.setItem('token', TOKEN);
    sessionStorage.setItem('user', JSON.stringify(USER));
    initApp();
  } catch (e) { 
    toggleLoader(false);
    toast(e.message, 'error'); 
  }
}

function logout() {
  sessionStorage.clear(); localStorage.clear(); TOKEN = ''; USER = null;
  
  // Clear login form fields to prevent leaking to next user
  const loginEmail = document.getElementById('login-email');
  const loginPass = document.getElementById('login-password');
  if (loginEmail) loginEmail.value = '';
  if (loginPass) loginPass.value = '';
  
  // Clear registration form fields too
  const regUser = document.getElementById('reg-username');
  const regEmail = document.getElementById('reg-email');
  const regPass = document.getElementById('reg-password');
  if (regUser) regUser.value = '';
  if (regEmail) regEmail.value = '';
  if (regPass) regPass.value = '';

  document.getElementById('auth-screen').style.display = 'flex';
  document.getElementById('app').style.display = 'none';
}

// ── App Init ──────────────────────────────────────────────────
async function initApp() {
  document.getElementById('auth-screen').style.display = 'none';
  document.getElementById('app').style.display = 'flex';
  
  if (USER) {
    const nameEl = document.getElementById('user-name');
    if (nameEl) nameEl.textContent = USER.username;

    const welcomeEl = document.getElementById('welcome-name');
    if (welcomeEl) welcomeEl.textContent = USER.username;

    // Sidebar avatar handling
    const sideAvEl = document.getElementById('sidebar-avatar-text');
    if (sideAvEl) sideAvEl.textContent = USER.username[0].toUpperCase();

    // Clear potentially stale UI from previous sessions
    const containers = [
      'daily-challenge-card-container', 
      'daily-attempts-list', 
      'assessments-pending-list', 
      'assessments-completed-list'
    ];
    containers.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = '';
    });
  }

  // Ensure loader is showing during initial data fetch
  toggleLoader(true);

  try {
    // Reset navigation to Dashboard and load critical assets concurrently
    await Promise.all([
      showPage('dashboard'),
      loadDocuments()
    ]);
  } catch (e) {
    console.error("App initialization data load failed:", e);
  } finally {
    // Give a small delay for DOM to settle before hiding loader
    setTimeout(() => toggleLoader(false), 800);
  }
}

async function showPage(page) {
  // Mobile: Close sidebar when navigating
  closeSidebarOnMobile();

  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.querySelectorAll('.mobile-nav-item').forEach(n => n.classList.remove('active'));

  const pageEl = document.getElementById('page-' + page);
  if (pageEl) pageEl.classList.add('active');

  // Highlight Sidebar items
  document.querySelectorAll('.nav-item').forEach(n => {
    const oc = n.getAttribute('onclick') || "";
    if (oc.includes("'" + page + "'")) n.classList.add('active');
  });

  // Highlight Mobile Nav items
  const mNavItem = document.getElementById('m-nav-' + page);
  if (mNavItem) mNavItem.classList.add('active');

  // Gather all async loading promises for this page
  const loads = [];
  if (page === 'dashboard') loads.push(loadDashboard());
  if (page === 'analytics') loads.push(loadAnalytics());
  if (page === 'recommendations') loads.push(loadRecommendations());
  if (page === 'courses') loads.push(loadCourses());
  if (page === 'quiz' || page === 'quizzes') loads.push(initQuiz());
  if (page === 'challenge') loads.push(loadChallengePage());
  if (page === 'qa' || page === 'voice') populateQaDocSelect(); // Synchronous
  if (page === 'groq' || page === 'groq_ai') populateDsDocSelect(); // Synchronous
  if (page === 'notes') { 
    loads.push(loadNotes()); 
    populateNotesDocSelect(); 
  }
  
  await Promise.all(loads);
}

function toggleSidebar() {
  const sidebar = document.getElementById('main-sidebar');
  if (sidebar) sidebar.classList.toggle('active');
}

function closeSidebarOnMobile() {
  const sidebar = document.getElementById('main-sidebar');
  if (sidebar && window.innerWidth <= 768) {
    sidebar.classList.remove('active');
  }
}


// ── Dashboard ─────────────────────────────────────────────────
// ── Dashboard & Profile ───────────────────────────────────────
async function loadDashboard() {
  try {
    const d = await api('GET', '/analytics/dashboard');

    // Stats Grid
    if (document.getElementById('stat-docs')) document.getElementById('stat-docs').textContent = d.total_documents || 0;
    if (document.getElementById('stat-score')) document.getElementById('stat-score').textContent = (d.accuracy || 0) + '%';
    if (document.getElementById('stat-streak')) document.getElementById('stat-streak').textContent = d.streak_days || 0;
    if (document.getElementById('stat-xp')) document.getElementById('stat-xp').textContent = d.total_xp || 0;

    // Detailed Stats Calculations
    const quizAcc = d.quiz_total > 0 ? (d.quiz_correct / d.quiz_total * 100) : 0;
    const courseAcc = d.course_total > 0 ? (d.course_correct / d.course_total * 100) : 0;
    const totalAcc = d.accuracy || 0;

    // Detailed Stats Population
    if (document.getElementById('stat-lessons')) document.getElementById('stat-lessons').textContent = d.lessons_completed || 0;
    if (document.getElementById('stat-course-xp')) document.getElementById('stat-course-xp').textContent = d.course_xp || 0;
    if (document.getElementById('stat-course-score')) document.getElementById('stat-course-score').textContent = `${d.course_correct || 0}/${d.course_total || 0}`;
    if (document.getElementById('stat-course-bar')) document.getElementById('stat-course-bar').style.width = courseAcc + '%';

    if (document.getElementById('stat-quiz-attempts')) document.getElementById('stat-quiz-attempts').textContent = d.total_attempts || 0;
    if (document.getElementById('stat-quiz-score')) document.getElementById('stat-quiz-score').textContent = `${d.quiz_correct || 0}/${d.quiz_total || 0}`;
    if (document.getElementById('stat-quiz-bar')) document.getElementById('stat-quiz-bar').style.width = quizAcc + '%';
    if (document.getElementById('stat-quiz-acc')) document.getElementById('stat-quiz-acc').textContent = quizAcc.toFixed(1) + '%';

    if (document.getElementById('stat-total-score')) document.getElementById('stat-total-score').textContent = `${d.total_solved || 0}/${d.total_attempted || 0}`;
    if (document.getElementById('stat-total-bar')) document.getElementById('stat-total-bar').style.width = totalAcc + '%';

    if (document.getElementById('stat-emotion')) document.getElementById('stat-emotion').textContent = d.emotion_points || 0;

    // Challenge Stats
    if (document.getElementById('stat-challenge-pts')) {
      document.getElementById('stat-challenge-pts').textContent = d.daily_challenge_points || 0;
    }
    if (document.getElementById('stat-assessment-pts')) {
      document.getElementById('stat-assessment-pts').textContent = d.assessment_points || 0;
    }

    // Profile Highlights
    if (document.getElementById('prof-xp')) document.getElementById('prof-xp').textContent = d.total_xp || 0;
    if (document.getElementById('prof-acc')) document.getElementById('prof-acc').textContent = (d.accuracy || 0) + '%';
    if (document.getElementById('prof-solved')) document.getElementById('prof-solved').textContent = d.total_solved || 0;

    // Recent Activity
    const activityEl = document.getElementById('recent-activity');
    if (activityEl) {
      if (d.recent_activity && d.recent_activity.length) {
        activityEl.innerHTML = d.recent_activity.map(a => `
          <div class="doc-item" style="margin-bottom:8px; border:1px solid var(--border); padding:10px; border-radius:8px;">
            <div class="doc-icon">🎯</div>
            <div class="doc-meta">
              <div class="doc-name">Quiz: ${a.topic || 'General'}</div>
              <div class="doc-date">${a.completed_at ? new Date(a.completed_at).toLocaleDateString() : 'Just now'} — ${a.score}/${a.total_questions} Correct</div>
            </div>
            <span class="badge ${a.percentage >= 75 ? 'badge-success' : a.percentage >= 50 ? 'badge-warning' : 'badge-danger'}">${a.percentage}%</span>
          </div>`).join('');
      } else {
        activityEl.innerHTML = '<p class="text-muted">No recent quiz activity.</p>';
      }
    }

    // Load Leaderboard & Profile Detail in parallel
    await Promise.all([
      loadLeaderboard(),
      loadProfile()
    ]);

  } catch (e) { console.error('Dashboard Error:', e); }
}

async function loadLeaderboard() {
  const el = document.getElementById('dashboard-leaderboard-list');
  if (!el) return;

  // Show Skeleton Loading Animation
  el.innerHTML = Array(5).fill(0).map(() => `
    <div style="display:flex; align-items:center; gap:12px; padding:10px 14px; border-radius:10px; background:var(--surface2); opacity:0.6; animation: pulse 1.5s infinite ease-in-out;">
      <div style="width:24px; height:24px; background:var(--border); border-radius:4px;"></div>
      <div style="width:32px; height:32px; background:var(--border); border-radius:8px;"></div>
      <div style="flex:1;">
         <div style="width:60%; height:12px; background:var(--border); border-radius:4px; margin-bottom:6px;"></div>
         <div style="width:40%; height:8px; background:var(--border); border-radius:3px;"></div>
      </div>
      <div style="width:30px; height:16px; background:var(--border); border-radius:4px;"></div>
    </div>
  `).join('');

  try {
    console.log("[🏆] Fetching leaderboard...");
    const d = await api('GET', '/analytics/leaderboard');
    console.log("[🏆] Leaderboard Data Received:", d);

    if (!d.leaderboard || !d.leaderboard.length) {
      console.warn("[🏆] No leaderboard data found.");
      el.innerHTML = '<div style="text-align:center; padding:20px; color:var(--text-muted);">No rankings yet. Be the first!</div>';
      return;
    }

    el.innerHTML = d.leaderboard.map((u, i) => {
      const isMe = u.user_id === (USER && (USER._id || USER.user_id || USER.id));
      const m = u.metrics || {};
      return `
      <div class="leaderboard-row" style="display:flex; align-items:center; gap:12px; padding:12px 16px; border-radius:12px; background:${isMe ? 'rgba(99,102,241,0.12)' : 'var(--surface2)'}; border:${isMe ? '1px solid rgba(99,102,241,0.3)' : '1px solid transparent'}; margin-bottom:8px; transition:all 0.2s ease;">
        <div style="font-weight:900; font-size:1.1rem; width:28px; color:${i === 0 ? '#fbbf24' : i === 1 ? '#94a3b8' : i === 2 ? '#b45309' : 'var(--text-muted)'};">
          ${i < 3 ? ['🥇', '🥈', '🥉'][i] : '#' + u.rank}
        </div>
        <img src="${u.avatar || `https://ui-avatars.com/api/?name=${u.username}&background=random`}" style="width:38px; height:38px; border-radius:10px; object-fit:cover; border:2px solid ${isMe ? '#6366f1' : 'transparent'};">
        <div style="flex:1;">
           <div style="font-weight:700; font-size:0.9rem; display:flex; align-items:center; gap:8px; color:var(--text);">
             ${u.username} ${isMe ? '<span class="badge badge-primary" style="font-size:0.55rem; padding:2px 6px;">YOU</span>' : ''}
           </div>
           <div style="display:flex; align-items:center; gap:10px; margin-top:2px;">
             <span style="font-size:0.7rem; color:var(--text-muted); display:flex; align-items:center; gap:3px;">🎯 ${m.accuracy || 0}%</span>
             <span style="font-size:0.7rem; color:var(--text-muted); display:flex; align-items:center; gap:3px;">📖 ${m.lessons || 0}</span>
             <span style="font-size:0.7rem; color:var(--text-muted); display:flex; align-items:center; gap:3px;">🔥 ${m.streak || 0}</span>
           </div>
        </div>
        <div style="text-align:right;">
          <div style="font-weight:800; color:#6366f1; font-size:1.1rem; line-height:1;">${u.score}</div>
          <div style="font-size:0.6rem; color:var(--text-muted); font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Score</div>
        </div>
      </div>`;
    }).join('');

  } catch (e) {
    console.error('[🏆] Leaderboard Error:', e);
    el.innerHTML = `<div style="text-align:center; padding:20px; color:var(--danger);">Error loading rankings.</div>`;
  }
}

async function loadProfile() {
  try {
    const u = await api('GET', '/auth/profile');
    USER = u;
    // Keep ID normalized after profile refresh
    if (USER) {
      USER.user_id = USER._id || USER.user_id || USER.id || '';
      USER._id     = USER.user_id;
    }
    sessionStorage.setItem('user', JSON.stringify(USER));
    // Update Profile Card
    if (document.getElementById('user-display-name')) document.getElementById('user-display-name').textContent = u.username;
    if (document.getElementById('user-bio')) document.getElementById('user-bio').textContent = u.profile.bio || "No bio added yet.";
    if (u.profile.avatar && document.getElementById('main-user-avatar')) document.getElementById('main-user-avatar').src = u.profile.avatar;

    // Skills
    const skillEl = document.getElementById('user-skills');
    if (skillEl) {
      if (u.profile.skills && u.profile.skills.length) {
        skillEl.innerHTML = u.profile.skills.map(s => `<span class="tag">${s}</span>`).join('');
      } else {
        skillEl.innerHTML = '<span class="text-muted" style="font-size:0.7rem;">No skills listed</span>';
      }
    }

    // Links
    const links = u.profile.links || {};
    const linkIds = ['github', 'linkedin', 'leetcode', 'portfolio'];
    linkIds.forEach(id => {
      const el = document.getElementById('link-' + id);
      if (el) {
        if (links[id]) {
          el.href = links[id].startsWith('http') ? links[id] : 'https://' + links[id];
          el.style.opacity = '1';
          el.style.pointerEvents = 'auto';
        } else {
          el.style.opacity = '0.3';
          el.style.pointerEvents = 'none';
        }
      }
    });

  } catch (e) { console.error('Profile Error:', e); }
}

function openProfileEdit() {
  const modal = document.getElementById('profile-edit-modal');
  if (!modal) return;

  document.getElementById('edit-username').value = USER.username;
  document.getElementById('edit-bio').value = USER.profile.bio || "";
  document.getElementById('edit-avatar').value = USER.profile.avatar || "";
  document.getElementById('edit-skills').value = (USER.profile.skills || []).join(', ');

  const links = USER.profile.links || {};
  document.getElementById('edit-linkedin').value = links.linkedin || "";
  document.getElementById('edit-github').value = links.github || "";
  document.getElementById('edit-leetcode').value = links.leetcode || "";
  document.getElementById('edit-portfolio').value = links.portfolio || "";

  modal.style.display = 'flex';
}

async function saveProfileChanges() {
  const data = {
    username: document.getElementById('edit-username').value.trim(),
    profile: {
      bio: document.getElementById('edit-bio').value,
      avatar: document.getElementById('edit-avatar').value,
      skills: document.getElementById('edit-skills').value.split(',').map(s => s.trim()).filter(s => s),
      links: {
        linkedin: document.getElementById('edit-linkedin').value,
        github: document.getElementById('edit-github').value,
        leetcode: document.getElementById('edit-leetcode').value,
        portfolio: document.getElementById('edit-portfolio').value,
      }
    }
  };

  try {
    toast('Updating profile...', 'info');
    await api('PUT', '/auth/profile', data);
    toast('Profile updated!', 'success');
    document.getElementById('profile-edit-modal').style.display = 'none';
    loadDashboard();
  } catch (e) { toast(e.message, 'error'); }
}

// ── Documents ─────────────────────────────────────────────────
async function loadDocuments() {
  try {
    const d = await api('GET', '/learning/documents');
    documents = d.documents;
    renderDocuments();
    if (typeof loadQuizDocs === 'function') loadQuizDocs();
    if (typeof populateNotesDocSelect === 'function') populateNotesDocSelect();
  } catch (e) { console.error(e); }
}

function renderDocuments() {
  const el = document.getElementById('documents-list');
  if (!documents.length) { el.innerHTML = '<p class="text-muted">No documents yet. Upload one above!</p>'; return; }
  el.innerHTML = documents.map(d => `
    <div class="doc-item">
      <div class="doc-icon">📄</div>
      <div class="doc-meta">
        <div class="doc-name">${d.original_name}</div>
        <div class="doc-date">${new Date(d.uploaded_at).toLocaleDateString()}</div>
        <div class="doc-topics">${(d.key_topics || []).slice(0, 5).map(t => `<span class="tag">${t}</span>`).join('')}</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;flex-shrink:0;">
        <button class="btn btn-sm btn-secondary" onclick="showSummary('${d._id}','${d.original_name}')">📋 Summary</button>
        <button class="btn btn-sm btn-danger" onclick="deleteDoc('${d._id}')">🗑</button>
      </div>
    </div>`).join('');
}

async function uploadFile(input) {
  const file = input.files[0]; if (!file) return;
  const fd = new FormData(); fd.append('file', file);
  toast('Uploading & analyzing…', 'info');
  try {
    await api('POST', '/learning/upload', fd, true);
    toast('Document uploaded successfully!', 'success');
    await loadDocuments();
  } catch (e) { toast(e.message, 'error'); }
}

function handleDrop(e) {
  e.preventDefault();
  document.getElementById('upload-zone').classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) {
    const dt = new DataTransfer(); dt.items.add(file);
    const inp = document.getElementById('file-input');
    inp.files = dt.files; uploadFile(inp);
  }
}

async function deleteDoc(id) {
  if (!confirm('Delete this document?')) return;
  try { await api('DELETE', '/learning/document/' + id); toast('Deleted', 'success'); await loadDocuments(); }
  catch (e) { toast(e.message, 'error'); }
}

async function showSummary(id, name) {
  const modal = document.getElementById('summary-modal');
  const content = document.getElementById('summary-content');
  const title = document.getElementById('summary-modal-title');

  title.textContent = `AI Summary: ${name}`;
  content.innerHTML = '<div style="text-align:center; padding:20px;"><div class="spinner" style="margin:0 auto 10px;"></div>Generating detailed summary...</div>';
  modal.style.display = 'flex';

  try {
    const d = await api('POST', '/learning/summarize/' + id, {});
    // Format for 10 lines: ensures readability
    content.textContent = d.summary;
  } catch (e) {
    content.innerHTML = `<div style="color:var(--danger)">Error: ${e.message}</div>`;
    toast(e.message, 'error');
  }
}

function copySummary() {
  const text = document.getElementById('summary-content').textContent;
  navigator.clipboard.writeText(text).then(() => {
    toast('Summary copied to clipboard!', 'success');
  }).catch(err => {
    toast('Failed to copy', 'error');
  });
}

// ── Q&A ───────────────────────────────────────────────────────
function populateQaDocSelect() {
  ['qa-doc-select', 'voice-doc-select'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = '<option value="">— choose a document —</option>' +
      documents.map(d => `<option value="${d._id}">${d.original_name}</option>`).join('');
  });
}

let lastAnswer = '';
async function sendQuestion() {
  const doc_id = document.getElementById('qa-doc-select').value;
  const question = document.getElementById('qa-input').value.trim();
  const language = document.getElementById('qa-lang').value;
  if (!doc_id) return toast('Please select a document first', 'error');
  if (!question) return;
  addChat(question, 'user');
  document.getElementById('qa-input').value = '';
  addChat('Thinking…', 'ai', 'thinking');
  try {
    const d = await api('POST', '/learning/ask', { document_id: doc_id, question, language });
    document.querySelector('.thinking')?.remove();
    lastAnswer = d.answer;
    addChat(`${d.answer}\n\n<span style="color:var(--text-muted);font-size:0.8rem;">Confidence: ${Math.round(d.confidence * 100)}%</span>`, 'ai');
  } catch (e) {
    document.querySelector('.thinking')?.remove();
    addChat('Sorry, I could not find an answer. Try rephrasing or selecting the correct document.', 'ai');
  }
}

function addChat(text, role, cls = '') {
  const box = document.getElementById('chat-box');
  const div = document.createElement('div');
  div.className = `msg msg-${role} ${cls}`;
  div.innerHTML = text.replace(/\n/g, '<br>');
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function readLastAnswer() {
  if (lastAnswer) speakTextDirect(lastAnswer, document.getElementById('qa-lang').value);
}

// ── Analytics ─────────────────────────────────────────────────
// ── Advanced Analytics Logic (Enhanced) ───────────────────────
let anCharts = {};

async function loadAnalytics() {
  switchAnalyticsTab('overview');
  try {
    const [adv, board] = await Promise.all([
      api('GET', '/analytics/advanced'),
      api('GET', '/analytics/leaderboard')
    ]);

    // 1. Populate 12 Metrics
    const s = adv.stats;
    const map = {
      'an2-docs': s.docs, 'an2-accuracy': s.accuracy + '%', 'an2-streak': s.streak,
      'an2-total-xp': s.total_xp, 'an2-lessons': s.lessons, 'an2-course-xp': s.course_xp,
      'an2-course-score': s.course_score, 'an2-quiz-attempts': s.quiz_attempts,
      'an2-quiz-score': s.quiz_score, 'an2-quiz-acc': s.quiz_acc + '%',
      'an2-total-solved': s.total_solved, 'an2-emotion': s.emotion_points
    };
    Object.entries(map).forEach(([id, val]) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    });

    // 2. Dual Axis Accuracy vs Speed
    renderChart('an-speed-accuracy-chart', 'line', {
      labels: adv.speed_acc_data.map(i => i.date),
      datasets: [
        {
          label: 'Accuracy %',
          data: adv.speed_acc_data.map(i => i.percentage),
          borderColor: '#6366f1',
          yAxisID: 'y',
          tension: 0.3,
          fill: false
        },
        {
          label: 'Time (sec)',
          data: adv.speed_acc_data.map(i => i.time_seconds),
          borderColor: '#f59e0b',
          borderDash: [5, 5],
          yAxisID: 'y1',
          tension: 0.3,
          fill: false
        }
      ]
    }, {
      scales: {
        y: { type: 'linear', display: true, position: 'left', min: 0, max: 100, title: { display: true, text: 'Accuracy %' } },
        y1: { type: 'linear', display: true, position: 'right', grid: { drawOnChartArea: false }, title: { display: true, text: 'Time (seconds)' } }
      }
    });

    // 3. Regular Progress Chart
    renderChart('an-progress-chart', 'line', {
      labels: adv.line_data.map(i => i.date),
      datasets: [{ label: 'Score %', data: adv.line_data.map(i => i.score), borderColor: '#a855f7', backgroundColor: 'rgba(168,85,247,0.1)', fill: true }]
    });

    // 4. Mastery Pie
    const m = adv.mastery;
    renderChart('an-pie-chart', 'doughnut', {
      labels: ['Strong', 'Average', 'Weak'],
      datasets: [{ data: [m.strong.length, m.average.length, m.weak.length], backgroundColor: ['#10b981', '#f59e0b', '#ef4444'], borderWidth: 0 }]
    }, { plugins: { legend: { position: 'right' } } });

    // 5. Topic Columns & History
    ['strong', 'average', 'weak'].forEach(lvl => {
      const el = document.getElementById(`an-list-${lvl}`);
      el.innerHTML = m[lvl].map(t => `<div class="card" style="padding:10px; font-size:0.8rem; background:var(--surface2); border:1px solid var(--border);">
        <div class="flex justify-between" style="margin-bottom:4px;"><b>${t.topic}</b><span>${t.mastery}%</span></div>
        <div class="progress-bar" style="height:4px;"><div class="progress-fill" style="width:${t.mastery}%; background:${lvl === 'strong' ? '#10b981' : lvl === 'average' ? '#f59e0b' : '#ef4444'}"></div></div>
      </div>`).join('') || '<div class="text-muted" style="font-size:0.7rem;">None</div>';
    });

    document.getElementById('an-quiz-history').innerHTML = adv.history.map(h => `
      <div class="card" style="padding:12px; border-left:3px solid ${h.percentage >= 75 ? '#10b981' : h.percentage >= 50 ? '#f59e0b' : '#ef4444'};">
        <div class="flex justify-between" style="margin-bottom:6px;"><b>${h.title}</b><span class="badge" style="background:var(--surface2);">${h.percentage}%</span></div>
        <div class="flex justify-between" style="font-size:0.7rem; color:var(--text-muted);"><span>${h.date}</span><span>${h.score}/${h.total}</span></div>
      </div>`).join('');

    renderCompetitorLeaderboard(board.leaderboard);

  } catch (e) { console.error(e); toast('Analytics Error', 'error'); }
}

function renderCompetitorLeaderboard(users) {
  const el = document.getElementById('an-leaderboard-list');
  el.innerHTML = (users || []).map(u => {
    const isMe = u.user_id === (USER && (USER._id || USER.user_id || USER.id));
    return `<div class="card an-comp-card" id="an-card-${u.user_id}" 
      onclick="${isMe ? '' : `openComparison('${u.user_id}', '${u.username}')`}" 
      style="padding:16px; cursor:${isMe ? 'default' : 'pointer'}; display:flex; align-items:center; gap:16px; border:1px solid var(--border); transition:all 0.3s ease; ${isMe ? 'border:2px solid #6366f1; background:rgba(99,102,241,0.08);' : ''}">
      <div style="font-weight:900; width:24px; font-size:1rem; color:var(--text-muted); opacity:0.6;">${u.rank}</div>
      <div class="avatar-circle" style="width:42px; height:42px; font-size:1.1rem; font-weight:700; background:hsl(${(u.rank * 137) % 360}, 65%, 45%); box-shadow: 0 4px 10px rgba(0,0,0,0.2);">${u.username[0].toUpperCase()}</div>
      <div style="flex:1;">
        <div style="font-weight:700; font-size:0.95rem; margin-bottom:4px;">${u.username} ${isMe ? '<span style="font-size:0.6rem; color:#6366f1; background:rgba(99,102,241,0.1); padding:2px 6px; border-radius:10px; margin-left:4px;">YOU</span>' : ''}</div>
        <div style="font-size:0.75rem; color:var(--text-muted); display:flex; gap:10px; align-items:center;">
          <span>🎯 ${u.metrics.accuracy}%</span>
          <span style="opacity:0.3;">|</span>
          <span>🔥 ${u.metrics.streak}d</span>
        </div>
      </div>
      <div style="text-align:right;">
        <div style="font-weight:900; color:#6366f1; font-size:1.1rem;">${u.score.toFixed(1)}</div>
        <div style="font-size:0.55rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px;">Points</div>
      </div>
    </div>`;
  }).join('');
}

async function openComparison(targetId, targetName) {
  // 1. Switch to Compare Tab & Show Results UI
  switchAnalyticsTab('compare');
  document.getElementById('an-compare-placeholder').style.display = 'none';
  document.getElementById('an-compare-results').style.display = 'block';

  // 2. Highlighting in Leaderboard
  document.querySelectorAll('.an-comp-card').forEach(c => {
    c.style.borderColor = 'var(--border)';
    c.style.background = 'transparent';
  });
  const activeCard = document.getElementById(`an-card-${targetId}`);
  if (activeCard) {
    activeCard.style.borderColor = '#f59e0b';
    activeCard.style.background = 'rgba(245,158,11,0.05)';
  }

  // 3. Reset Loaders
  document.getElementById('an-ai-suggestions').innerHTML = `
    <div class="skeleton" style="height:45px; border-radius:8px;"></div>
    <div class="skeleton" style="height:45px; border-radius:8px;"></div>
    <div class="skeleton" style="height:45px; border-radius:8px;"></div>
    <div class="skeleton" style="height:45px; border-radius:8px;"></div>
  `;

  try {
    const d = await api('GET', `/analytics/compare/${targetId}`);

    // Profiles
    document.getElementById('an-comp-me-avatar').textContent = USER.username[0].toUpperCase();
    document.getElementById('an-comp-them-avatar').textContent = targetName[0].toUpperCase();
    document.getElementById('an-comp-them-name').textContent = targetName;

    // Chart: 8 Metrics (Updated with Raw Speed)
    const metrics = ['lessons', 'assessments', 'challenges', 'accuracy', 'c_xp', 'a_pts', 'ch_pts', 'speed'];
    const labels = ['Lessons Done', 'Assess Done', 'Challenges Done', 'Overall Acc %', 'Course XP Score', 'Assess Pts Score', 'Challenge Pts Score', 'Avg Speed (s)'];

    renderChart('an-compare-chart', 'bar', {
      labels: labels,
      datasets: [
        { label: 'You', data: metrics.map(m => d.me.metrics.raw[m]), backgroundColor: '#6366f1', borderRadius: 4 },
        { label: targetName, data: metrics.map(m => d.competitor.metrics.raw[m]), backgroundColor: '#94a3b8', borderRadius: 4 }
      ]
    }, { indexAxis: 'y', plugins: { legend: { position: 'top' } } });

    // Topics Mastery Pills
    const pill = (t, c) => `<span class="badge" style="background:${c}15; color:${c}; border:1px solid ${c}; font-size:0.7rem; padding:4px 10px; border-radius:15px;">${t}</span>`;
    const renderPills = (data, id) => {
      const html = [
        ...data.strong.map(t => pill(t, '#10b981')),
        ...data.average.map(t => pill(t, '#f59e0b')),
        ...data.weak.map(t => pill(t, '#ef4444'))
      ].join('') || '<span class="text-muted">No data</span>';
      document.getElementById(id).innerHTML = html;
    };
    renderPills(d.me.topics, 'an-comp-me-topics');
    renderPills(d.competitor.topics, 'an-comp-them-topics');

    // Lessons Learned Rendering
    const renderLessons = (data, id, color) => {
      const html = data.map(l => `
        <div style="padding:10px; background:rgba(255,255,255,0.02); border-radius:8px; border:1px solid var(--border);">
          <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
            <span style="font-size:0.85rem; font-weight:600;">${l.title}</span>
            <span style="font-size:0.85rem; font-weight:700; color:${color};">${l.accuracy}%</span>
          </div>
          <div style="height:4px; background:rgba(255,255,255,0.05); border-radius:2px;">
            <div style="height:100%; width:${l.accuracy}%; background:${color}; border-radius:2px;"></div>
          </div>
        </div>
      `).join('') || '<div class="text-muted" style="font-size:0.85rem;">No lessons completed yet.</div>';
      document.getElementById(id).innerHTML = html;
    };
    renderLessons(d.me.lessons_learned, 'an-comp-me-lessons', '#6366f1');
    renderLessons(d.competitor.lessons_learned, 'an-comp-them-lessons', '#94a3b8');

    // AI Tactical Advice
    const sugRes = await api('POST', '/analytics/ai-suggestions', { me: d.me, competitor: d.competitor });
    document.getElementById('an-ai-suggestions').innerHTML = sugRes.suggestions.map(s => `
      <div style="padding:12px 16px; background:rgba(99,102,241,0.03); border-left:4px solid #6366f1; border-radius:6px; font-size:0.85rem; line-height:1.5; color:var(--text);">
        <span style="margin-right:8px;">🎯</span> ${s}
      </div>
    `).join('');

  } catch (e) {
    console.error(e);
    toast('Comparison Error', 'error');
    document.getElementById('an-ai-suggestions').innerHTML = '<div class="text-muted">Unable to generate AI insights at this time.</div>';
  }
}

function renderChart(canvasId, type, data, options = {}) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  if (anCharts[canvasId]) anCharts[canvasId].destroy();
  anCharts[canvasId] = new Chart(ctx, {
    type: type,
    data: data,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#94a3b8', font: { size: 10 } } } },
      ...options
    }
  });
}

function switchAnalyticsTab(name) {
  document.querySelectorAll('.an-tab-pane').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.an-tab-btn').forEach(b => b.classList.remove('active'));
  const target = document.getElementById(`an-panel-${name}`);
  if (target) target.style.display = 'block';
  const btn = document.querySelector(`.an-tab-btn[data-tab="${name}"]`);
  if (btn) btn.classList.add('active');
}

function renderChart(canvasId, type, data, options = {}) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  if (anCharts[canvasId]) anCharts[canvasId].destroy();

  anCharts[canvasId] = new Chart(ctx, {
    type: type,
    data: data,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#94a3b8', font: { size: 10 } } } },
      ...options
    }
  });
}

function closeComparisonModal() {
  document.getElementById('an-compare-modal').style.display = 'none';
}

function drawProgressChart(data) { /* Redundant now but kept for compatibility if called elsewhere */ }
function renderTopics(topics) { /* Redundant now */ }

// ── Smart Mentor & Recommendations ───────────────────────────
async function loadRecommendations() {
  const adviceEl = document.getElementById('mentor-advice-text');
  const missionEl = document.getElementById('mission-list');
  const roadmapEl = document.getElementById('roadmap-container');

  try {
    const d = await api('GET', '/learning/recommendations');
    const recs = d.recommendations;

    // 1. Advice
    adviceEl.textContent = recs.mentor_advice;

    // 2. Missions
    document.getElementById('mission-count').textContent = `${recs.missions.length} Active`;
    if (!recs.missions.length) {
      missionEl.innerHTML = '<p class="text-muted">No missions right now. Take a quiz to unlock new challenges!</p>';
    } else {
      missionEl.innerHTML = recs.missions.map((m, i) => {
        const vid = m.video || {};
        const hasEmbed = !!vid.embed_url;
        const actionUrl = hasEmbed ? vid.embed_url : vid.url;

        return `
        <div class="card" style="padding:16px; display:flex; gap:16px; align-items:center; transition:all .2s;" onmouseover="this.style.borderColor='#6366f1'" onmouseout="this.style.borderColor='var(--border)'">
          <div style="width:44px; height:44px; border-radius:12px; background:${m.type === 'challenge' ? 'rgba(245,158,11,.15)' : 'rgba(99,102,241,.15)'}; display:flex; align-items:center; justify-content:center; font-size:1.2rem;">
            ${m.type === 'challenge' ? '🏆' : m.type === 'revision' ? '📖' : '🎯'}
          </div>
          <div style="flex:1;">
            <div style="font-weight:700; font-size:0.95rem; margin-bottom:2px;">${m.title}</div>
            <div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:8px;">${m.description}</div>
            ${hasEmbed ?
            `<button class="btn btn-sm btn-primary" onclick="playMentorVideo('${actionUrl}', '${m.title}')" style="font-size:0.7rem; padding:4px 10px; background:rgba(99,102,241,0.1); color:#6366f1; border:1px solid #6366f1; cursor:pointer;">▶ Watch Lesson</button>` :
            `<a href="${actionUrl}" target="_blank" class="btn btn-sm btn-secondary" style="font-size:0.7rem; padding:4px 10px; text-decoration:none; display:inline-block; border:1px solid var(--border);">🔍 Search Lesson →</a>`
          }
          </div>
          <div style="text-align:right;">
            <div style="font-size:0.85rem; font-weight:700; color:#6366f1;">+${m.reward}</div>
            <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase;">Reward</div>
          </div>
        </div>`;
      }).join('');
    }

    // 3. Roadmap
    if (!recs.roadmap.length) {
      roadmapEl.innerHTML = '<p class="text-muted">Study more topics to generate your roadmap.</p>';
    } else {
      roadmapEl.innerHTML = recs.roadmap.map((step, i) => `
        <div style="display:flex; gap:16px; margin-bottom:20px; position:relative;">
          ${i < recs.roadmap.length - 1 ? `<div style="position:absolute; left:7px; top:20px; bottom:-20px; width:2px; background:var(--border);"></div>` : ''}
          <div style="width:16px; height:16px; border-radius:50%; background:${step.status === 'mastered' ? '#10b981' : step.status === 'learning' ? '#6366f1' : step.status === 'struggling' ? '#ef4444' : 'var(--border)'}; z-index:1; margin-top:4px; box-shadow:0 0 0 4px var(--surface);"></div>
          <div style="flex:1;">
            <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
              <span style="font-size:0.9rem; font-weight:600; color:${step.status === 'locked' ? 'var(--text-muted)' : ''};">${step.topic}</span>
              <span style="font-size:0.75rem; color:var(--text-muted);">${step.progress}%</span>
            </div>
            <div class="progress-bar" style="height:6px; background:rgba(255,255,255,0.05);">
              <div class="progress-fill" style="width:${step.progress}%; background:${step.status === 'mastered' ? '#10b981' : step.status === 'struggling' ? '#ef4444' : '#6366f1'}"></div>
            </div>
          </div>
        </div>`).join('');
    }

    // 4. Stats
    document.getElementById('rec-stat-acc').textContent = recs.metrics.avg_accuracy + '%';
    document.getElementById('rec-stat-mastery').textContent = recs.metrics.mastery_count;
    document.getElementById('rec-stat-streak').textContent = recs.metrics.top_streak;
    document.getElementById('rec-stat-speed').textContent = recs.metrics.avg_speed + 's';
    document.getElementById('rec-stat-xp').textContent = recs.metrics.course_xp || 0;
    document.getElementById('rec-stat-completed').textContent = recs.metrics.lessons_completed || 0;

  } catch (e) {
    adviceEl.textContent = "Could not load recommendations at this time.";
    console.error(e);
  }
}

let pendingMentorVideoUrl = '';

function playMentorVideo(url, title) {
  document.getElementById('mentor-video-title').textContent = title;
  pendingMentorVideoUrl = url;

  // Show the cover (custom play button) first
  document.getElementById('mentor-video-cover').style.display = 'flex';
  document.getElementById('mentor-video-iframe').src = '';

  document.getElementById('mentor-video-overlay').style.display = 'flex';
  document.body.style.overflow = 'hidden';
}

function startMentorVideo() {
  document.getElementById('mentor-video-cover').style.display = 'none';

  // Ensure we have clean parameters
  let cleanUrl = new URL(pendingMentorVideoUrl);
  cleanUrl.searchParams.set('autoplay', '1');
  cleanUrl.searchParams.set('modestbranding', '1');
  cleanUrl.searchParams.set('rel', '0');
  cleanUrl.searchParams.set('iv_load_policy', '3');
  cleanUrl.searchParams.set('enablejsapi', '1');

  document.getElementById('mentor-video-iframe').src = cleanUrl.toString();
}

function closeMentorVideo() {
  document.getElementById('mentor-video-overlay').style.display = 'none';
  document.getElementById('mentor-video-iframe').src = '';
  document.body.style.overflow = 'auto';
}

// ── Boot ──────────────────────────────────────────────────────
window.onload = () => {
  if (TOKEN && USER) initApp();
};