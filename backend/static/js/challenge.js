/**
 * Challenge & Assessment System - static/js/challenge.js
 */

window.challengeState = {
    questions: [],
    currentIndex: 0,
    answers: {}, // {qid: [indices]}
    startTime: null,
    timerInterval: null,
    type: 'daily',
    id: null,
    violationCount: 0,
    proctorInterval: null,
    timeLeft: 15 * 60,
    modelsLoaded: false
};

// Global models
let cocoModel = null;
let faceModel = null;

async function loadProctoringModels() {
    if (window.challengeState.modelsLoaded) return;
    try {
        console.log("[🛡️] Loading local proctoring models...");
        // Load COCO-SSD for objects (phones, etc.)
        cocoModel = await cocoSsd.load();
        // Load BlazeFace for fast face detection
        faceModel = await blazeface.load();
        window.challengeState.modelsLoaded = true;
        console.log("[🛡️] Local models loaded successfully.");
    } catch (e) {
        console.error("Model loading error:", e);
    }
}

async function loadChallengePage() {
    const container = document.getElementById('daily-challenge-card-container');
    if (container) {
        container.innerHTML = `
            <div class="card" style="padding:60px; text-align:center; display:flex; flex-direction:column; align-items:center; gap:20px; background:rgba(255,255,255,0.02); border:1px dashed var(--border);">
                <div class="loading-spinner"></div>
                <div>
                    <h4 style="margin-bottom:8px; color:var(--text-bright);">Generating Daily Challenge</h4>
                    <p style="color:var(--text-muted); font-size:0.85rem; animation: pulse 2s infinite;">
                        Our AI (Llama 3.3 70b) is curating 20 technical questions for you...
                    </p>
                </div>
            </div>
        `;
    }

    try {
        const [dailyRes, pendingRes, historyRes] = await Promise.all([
            api('GET', '/challenge/daily'),
            api('GET', '/challenge/pending-assessments'),
            api('GET', '/challenge/history')
        ]);

        renderDailyChallenge(dailyRes);
        renderPendingAssessments(pendingRes);
        renderChallengeHistory(historyRes);

        // Start countdown for refresh
        if (dailyRes && dailyRes.expires_at) {
            startRefreshCountdown(dailyRes.expires_at);
        }

        // Update assessment badge
        const badge = document.getElementById('assessment-badge');
        if (pendingRes && pendingRes.length > 0) {
            badge.textContent = `${pendingRes.length} Pending Assessments`;
            badge.style.display = 'block';
        } else {
            badge.style.display = 'none';
        }
    } catch (err) {
        console.error("Load Challenge Error:", err);
    }
}
function renderDailyChallenge(challenge) {
    const container = document.getElementById('daily-challenge-card-container');
    if (!challenge || challenge.error) {
        container.innerHTML = `<div class="card" style="padding:40px; text-align:center;">Challenge unavailable. Check back later.</div>`;
        return;
    }

    if (challenge.has_completed) {
        container.innerHTML = `
            <div class="card" style="padding:24px; border-left:6px solid #10b981; background:rgba(16,185,129,0.03); display:flex; align-items:center; justify-content:space-between;">
                <div>
                    <h3 style="color:#10b981; margin-bottom:4px;">✅ Challenge Completed</h3>
                    <p style="font-size:0.85rem; color:var(--text-muted);">You've already mastered today's topics! Come back in a few hours for the next refresh.</p>
                </div>
                <div style="font-size:2rem;">🏅</div>
            </div>
        `;
        return;
    }

    container.innerHTML = `
        <div class="card" style="padding:32px; border-left:6px solid #f59e0b; background:rgba(245,158,11,0.03);">
            <div style="display:flex; justify-content:space-between; align-items:start; margin-bottom:24px;">
                <div>
                    <h2 style="margin-bottom:8px;">${challenge.subject || 'Technical'} Mastery Challenge</h2>
                    <div style="display:flex; gap:12px;">
                        <span class="badge" style="background:#f59e0b22; color:#f59e0b;">⏱ 15 Mins</span>
                        <span class="badge" style="background:#6366f122; color:#6366f1;">❓ 20 Questions</span>
                        <span class="badge" style="background:#10b98122; color:#10b981;">🔥 200 Max XP</span>
                    </div>
                </div>
                <button class="btn btn-primary" style="background:linear-gradient(135deg,#f59e0b,#ef4444); padding:12px 24px; border-radius:12px;" onclick="startChallenge('daily', '${challenge._id}')">
                    🚀 Start Challenge
                </button>
            </div>
            <p style="color:var(--text-muted); line-height:1.6;">
                This challenge expires in a few hours. Test your knowledge across core subjects and earn bonus points for your dashboard.
                Proctoring is enabled to ensure fair play.
            </p>
        </div>
    `;
}

function renderPendingAssessments(data) {
    const pendingList = document.getElementById('assessments-pending-list');
    const completedList = document.getElementById('assessments-completed-list');

    if (!data) return;

    // Render Pending
    if (!data.pending || data.pending.length === 0) {
        pendingList.innerHTML = `<p class="text-muted" style="grid-column:1/-1; text-align:center; padding:40px;">No pending assessments. Complete course modules to unlock them!</p>`;
    } else {
        pendingList.innerHTML = data.pending.map(a => `
            <div class="card" style="padding:20px; border-top:3px solid #6366f1;">
                <div style="font-size:0.7rem; color:var(--text-muted); text-transform:uppercase; margin-bottom:8px;">${a.course_id}</div>
                <h3 style="margin-bottom:12px; font-size:1rem;">${a.module_title || 'Module Assessment'}</h3>
                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:20px;">
                    <span style="font-size:0.8rem; color:var(--text-muted);">20 Questions</span>
                    <button class="btn btn-sm btn-primary" onclick="startChallenge('assessment', '${a.module_id}')">Start</button>
                </div>
            </div>
        `).join('');
    }

    // Render Completed
    if (!data.completed || data.completed.length === 0) {
        completedList.innerHTML = `<p class="text-muted" style="grid-column:1/-1; text-align:center; padding:40px;">No completed assessments yet.</p>`;
    } else {
        completedList.innerHTML = data.completed.map(a => {
            const att = a.attempt;
            const color = att.percentage >= 60 ? '#10b981' : '#ef4444';
            return `
                <div class="card" style="padding:20px; border-top:3px solid ${color}; opacity:0.8;">
                    <div style="font-size:0.7rem; color:var(--text-muted); text-transform:uppercase; margin-bottom:8px;">${a.course_id}</div>
                    <h3 style="margin-bottom:8px; font-size:1rem;">${a.module_title || 'Module Assessment'}</h3>
                    <div style="background:var(--surface2); padding:10px; border-radius:8px; margin-top:15px; display:flex; justify-content:space-between; align-items:center;">
                        <div>
                            <div style="font-weight:700; color:${color}; font-size:1rem;">${att.score} / ${att.total}</div>
                            <div style="font-size:0.6rem; color:var(--text-muted);">SCORE</div>
                        </div>
                        <div style="text-align:right;">
                            <div style="font-weight:700; font-size:1rem;">${att.percentage}%</div>
                            <div style="font-size:0.6rem; color:var(--text-muted);">ACCURACY</div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }
}

function renderChallengeHistory(history) {
    const list = document.getElementById('daily-attempts-list');
    if (!history || history.length === 0) {
        list.innerHTML = `<p class="text-muted" style="grid-column:1/-1; text-align:center; padding:20px;">No attempts yet. Take your first challenge!</p>`;
        return;
    }

    list.innerHTML = history.map(a => {
        const dObj = a.submitted_at ? new Date(a.submitted_at) : null;
        const date = (dObj && !isNaN(dObj)) ? dObj.toLocaleDateString() : 'Recent';
        const points = a.points_gained !== undefined ? a.points_gained : (a.score * (a.type === 'daily' ? 10 : 25));
        const color = a.percentage >= 60 ? '#10b981' : '#ef4444';

        return `
            <div class="card" style="padding:16px; border-top:3px solid ${color}; display:flex; flex-direction:column; gap:8px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:0.75rem; color:var(--text-muted); font-weight:600;">${date} • ${a.type.toUpperCase()}</span>
                    <span style="font-size:0.75rem; color:#f59e0b; font-weight:700;">+${points} XP</span>
                </div>
                <h4 style="margin:4px 0;">${a.subject || 'Challenge'}</h4>
                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px;">
                    <div>
                        <div style="font-weight:700; font-size:1.1rem; color:${color};">${a.score} / ${a.total}</div>
                        <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase;">Questions</div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-weight:700; font-size:1.1rem;">${a.percentage}%</div>
                        <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase;">Accuracy</div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function startRefreshCountdown(expiresAt) {
    const el = document.getElementById('challenge-countdown');
    if (!el || !expiresAt) return;

    const dObj = new Date(expiresAt);
    if (isNaN(dObj)) {
        el.textContent = "Updating...";
        return;
    }
    const target = dObj.getTime();

    // Clear any existing interval to prevent overlapping
    if (window.refreshInterval) clearInterval(window.refreshInterval);

    window.refreshInterval = setInterval(() => {
        const now = new Date().getTime();
        const dist = target - now;

        if (dist < 0) {
            clearInterval(window.refreshInterval);

            // Prevent infinite loop if server/client clocks are slightly out of sync
            const nowTime = Date.now();
            if (!window.lastChallengeRefresh || (nowTime - window.lastChallengeRefresh > 10000)) {
                window.lastChallengeRefresh = nowTime;
                el.textContent = "Refreshing...";
                loadChallengePage();
            } else {
                el.textContent = "00:00:00";
            }
            return;
        }

        const h = Math.floor((dist % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
        const m = Math.floor((dist % (1000 * 60 * 60)) / (1000 * 60));
        const s = Math.floor((dist % (1000 * 60)) / 1000);

        el.textContent = [h, m, s].map(v => v.toString().padStart(2, '0')).join(':');
    }, 1000);
}

function switchChallengeTab(tab) {
    document.querySelectorAll('.challenge-tab-btn').forEach(b => b.classList.remove('active'));
    event.currentTarget.classList.add('active');

    document.querySelectorAll('.challenge-pane').forEach(p => p.style.display = 'none');
    const target = document.getElementById(`challenge-tab-${tab}`);
    if (target) target.style.display = 'block';

    // Show/Hide Next Refresh badge
    const refreshBadge = document.getElementById('daily-refresh-badge');
    if (refreshBadge) {
        refreshBadge.style.display = (tab === 'daily') ? 'block' : 'none';
    }
}

async function startChallenge(type, id) {
    toast('Preparing challenge and loading models...', 'info');
    try {
        await loadProctoringModels();

        let url = type === 'daily' ? `/challenge/daily` : `/challenge/generate-assessment`;
        let options = type === 'daily' ? { method: 'GET' } : {
            method: 'POST',
            body: { module_id: id }
        };

        const res = await api(options.method, url, options.body);
        if (!res || res.error) throw new Error(res.error || "Failed to load questions");

        window.challengeState = {
            ...window.challengeState,
            questions: res.questions,
            currentIndex: 0,
            answers: {},
            startTime: new Date(),
            type: type,
            id: res._id,
            violationCount: 0,
            timeLeft: 15 * 60
        };

        // UI Prep
        document.getElementById('challenge-overlay').style.display = 'flex';
        document.getElementById('challenge-results').style.display = 'none';
        document.getElementById('ch-question-area').style.display = 'block';
        document.getElementById('ch-prev-btn').style.display = 'block';
        document.getElementById('ch-next-btn').style.display = 'block';
        document.getElementById('ch-submit-btn').style.display = 'none';

        renderChallengeQuestion(0);
        startTimer(15);
        startProctoring();

    } catch (err) {
        alert("Error starting challenge: " + err.message);
    }
}

function renderChallengeQuestion(index) {
    const q = window.challengeState.questions[index];
    window.challengeState.currentIndex = index;

    document.getElementById('ch-question-counter').textContent = `Question ${index + 1} / ${window.challengeState.questions.length}`;

    const area = document.getElementById('ch-question-area');
    const selected = window.challengeState.answers[q.id] || [];

    area.innerHTML = `
        <div style="margin-bottom:30px;">
            <div style="background:rgba(99,102,241,0.1); color:#6366f1; padding:4px 12px; border-radius:8px; display:inline-block; font-size:0.75rem; font-weight:700; text-transform:uppercase; margin-bottom:12px;">
                ${q.type === 'mcq' ? 'Single Select' : 'Multiple Select'}
            </div>
            <h2 style="font-size:1.5rem; line-height:1.4;">${q.question}</h2>
        </div>
        <div style="display:flex; flex-direction:column; gap:12px;">
            ${q.options.map((opt, i) => {
        const isActive = selected.includes(i);
        return `
                    <button class="btn btn-outline" 
                            style="justify-content:start; padding:18px 24px; text-align:left; font-size:1.05rem; border-radius:12px; transition:all 0.2s; ${isActive ? 'background:rgba(99,102,241,0.15); border-color:#6366f1;' : ''}"
                            onclick="handleChallengeOptionSelect(${i})">
                        <div style="width:24px; height:24px; border-radius:${q.type === 'mcq' ? '50%' : '4px'}; border:2px solid ${isActive ? '#6366f1' : 'var(--border)'}; display:flex; align-items:center; justify-content:center; margin-right:16px; flex-shrink:0;">
                            ${isActive ? `<div style="width:12px; height:12px; background:#6366f1; border-radius:${q.type === 'mcq' ? '50%' : '2px'};"></div>` : ''}
                        </div>
                        ${opt}
                    </button>
                `;
    }).join('')}
        </div>
    `;

    document.getElementById('ch-prev-btn').disabled = (index === 0);
    if (index === window.challengeState.questions.length - 1) {
        document.getElementById('ch-next-btn').style.display = 'none';
        document.getElementById('ch-submit-btn').style.display = 'block';
    } else {
        document.getElementById('ch-next-btn').style.display = 'block';
        document.getElementById('ch-submit-btn').style.display = 'none';
    }
}

function handleChallengeOptionSelect(idx) {
    const q = window.challengeState.questions[window.challengeState.currentIndex];
    let selected = window.challengeState.answers[q.id] || [];

    if (q.type === 'mcq') {
        selected = [idx];
    } else {
        if (selected.includes(idx)) {
            selected = selected.filter(i => i !== idx);
        } else {
            selected.push(idx);
        }
    }

    window.challengeState.answers[q.id] = selected;
    renderChallengeQuestion(window.challengeState.currentIndex);
}

function prevChallengeQuestion() {
    if (window.challengeState.currentIndex > 0) renderChallengeQuestion(window.challengeState.currentIndex - 1);
}

function nextChallengeQuestion() {
    if (window.challengeState.currentIndex < window.challengeState.questions.length - 1) renderChallengeQuestion(window.challengeState.currentIndex + 1);
}

function startTimer(minutes) {
    if (window.challengeState.timerInterval) clearInterval(window.challengeState.timerInterval);

    window.challengeState.timeLeft = minutes * 60;
    const el = document.getElementById('ch-timer');

    window.challengeState.timerInterval = setInterval(() => {
        window.challengeState.timeLeft--;

        const m = Math.floor(window.challengeState.timeLeft / 60);
        const s = window.challengeState.timeLeft % 60;
        el.textContent = `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;

        if (window.challengeState.timeLeft < 120) {
            el.style.color = '#ef4444';
        } else {
            el.style.color = 'inherit';
        }

        if (window.challengeState.timeLeft <= 0) {
            clearInterval(window.challengeState.timerInterval);
            submitChallenge(true);
        }
    }, 1000);
}

async function startProctoring() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true });
        const video = document.getElementById('proctor-video');
        video.srcObject = stream;

        window.challengeState.violationCount = 0;
        document.getElementById('proctor-warning-badge').style.display = 'none';
        document.getElementById('ch-warning').style.display = 'none';

        // Local Proctoring - Every 1 second (Stricter for testing)
        window.challengeState.proctorInterval = setInterval(async () => {
            if (!window.challengeState.modelsLoaded) return;

            try {
                let violation = false;
                let reason = "";

                // 1. Brightness Check (Stricter: 50)
                const brightness = getBrightness(video);
                if (brightness < 50) {
                    violation = true;
                    reason = "Environment too dark. Please improve lighting.";
                }

                // 2. Face Detection (BlazeFace)
                const faces = await faceModel.estimateFaces(video, false);
                if (faces.length === 0) {
                    violation = true;
                    reason = "No face detected. Please stay in view.";
                } else if (faces.length > 1) {
                    violation = true;
                    reason = "Multiple people detected in frame.";
                } else {
                    // Face Confidence Check
                    const face = faces[0];
                    if (face.probability[0] < 0.85) {
                        violation = true;
                        reason = "Face partially obscured. Please clear your face.";
                    } else {
                        // Simple "Looking Away" Detection
                        const xCenter = (face.topLeft[0] + face.bottomRight[0]) / 2;
                        const vWidth = video.videoWidth || 640;
                        if (xCenter < vWidth * 0.2 || xCenter > vWidth * 0.8) {
                            violation = true;
                            reason = "Please look directly at the camera.";
                        }
                    }
                }

                // 3. Electronic Device Detection (COCO-SSD)
                if (!violation) {
                    const predictions = await cocoModel.detect(video);
                    const restricted = ["cell phone", "laptop", "tablet", "book", "remote"];
                    const found = predictions.find(p => restricted.includes(p.class) && p.score > 0.4);
                    if (found) {
                        violation = true;
                        reason = `Restricted object detected: ${found.class}.`;
                    }
                }

                if (violation) {
                    handleProctoringResult({ violation: true, reason: reason });
                } else {
                    document.getElementById('ch-warning').style.display = 'none';
                    document.getElementById('proctor-warning-badge').style.display = 'none';
                }
            } catch (e) {
                console.error("Local proctoring error:", e);
            }
        }, 2000);

        // 4. Tab Switching Detection
        window.challengeState.visibilityHandler = () => {
            if (document.visibilityState === 'hidden') {
                handleProctoringResult({
                    violation: true,
                    reason: "Tab switching detected. Stay on this page!"
                });
            }
        };
        document.addEventListener('visibilitychange', window.challengeState.visibilityHandler);

    } catch (err) {
        console.error("Webcam Error:", err);
        alert("Camera access is required for this challenge.");
        closeChallengeOverlay();
    }
}

function getBrightness(video) {
    const canvas = document.createElement('canvas');
    canvas.width = 160;
    canvas.height = 120;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = imageData.data;
    let colorSum = 0;
    for (let i = 0; i < data.length; i += 4) {
        colorSum += (data[i] + data[i + 1] + data[i + 2]) / 3;
    }
    return colorSum / (canvas.width * canvas.height);
}

function handleProctoringResult(result) {
    if (result && result.violation) {
        window.challengeState.violationCount++;
        const warning = document.getElementById('ch-warning');
        const text = document.getElementById('ch-warning-text');
        const badge = document.getElementById('proctor-warning-badge');

        text.textContent = result.reason;
        warning.style.display = 'block';
        badge.style.display = 'block';

        if (window.challengeState.violationCount >= 4) { // 10 strikes for testing
            alert("Violations detected. Your challenge is being automatically submitted.");
            submitChallenge(true);
        }
    }
}

async function submitChallenge(autoSubmitted = false) {
    if (window.challengeState.timerInterval) clearInterval(window.challengeState.timerInterval);
    if (window.challengeState.proctorInterval) clearInterval(window.challengeState.proctorInterval);

    const video = document.getElementById('proctor-video');
    if (video && video.srcObject) {
        video.srcObject.getTracks().forEach(t => t.stop());
        video.srcObject = null;
    }

    if (window.challengeState.visibilityHandler) {
        document.removeEventListener('visibilitychange', window.challengeState.visibilityHandler);
        window.challengeState.visibilityHandler = null;
    }

    toast('Submitting results...', 'info');
    try {
        const payload = {
            challenge_id: window.challengeState.id,
            type: window.challengeState.type,
            answers: window.challengeState.answers,
            violations: window.challengeState.violationCount,
            auto_submitted: autoSubmitted
        };

        const res = await api('POST', '/challenge/submit', payload);
        renderChallengeResults(res);

    } catch (err) {
        alert("Submission error: " + err.message);
    }
}

function renderChallengeResults(res) {
    document.getElementById('ch-question-area').style.display = 'none';
    document.getElementById('ch-prev-btn').style.display = 'none';
    document.getElementById('ch-next-btn').style.display = 'none';
    document.getElementById('ch-submit-btn').style.display = 'none';
    document.getElementById('ch-warning').style.display = 'none';

    const resultsArea = document.getElementById('challenge-results');
    resultsArea.style.display = 'block';

    let current = 0;
    const target = res.percentage;
    const pctEl = document.getElementById('ch-res-pct');
    const circle = document.getElementById('ch-res-circle');

    const color = target >= 60 ? '#10b981' : '#ef4444';
    circle.style.borderColor = color;
    document.getElementById('ch-res-status').textContent = target >= 60 ? 'Success!' : 'Keep Practicing!';
    document.getElementById('ch-res-status').style.color = color;

    const interval = setInterval(() => {
        if (current >= target) {
            pctEl.textContent = `${target}%`;
            clearInterval(interval);
        } else {
            current += 1;
            pctEl.textContent = `${current}%`;
        }
    }, 20);

    document.getElementById('ch-res-fraction').textContent = `${res.score} / ${res.total} Correct`;
    document.getElementById('ch-res-correct').textContent = res.score;
    document.getElementById('ch-res-wrong').textContent = res.total - res.score;
    document.getElementById('ch-res-skipped').textContent = res.total - Object.keys(window.challengeState.answers).length;

    const accordion = document.getElementById('ch-res-accordion');
    accordion.innerHTML = res.results.map((r, i) => {
        const q = window.challengeState.questions.find(q => q.id === r.id);
        return `
            <div class="card" style="padding:16px; border-left:4px solid ${r.correct ? '#10b981' : '#ef4444'};">
                <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                    <span style="font-size:0.75rem; font-weight:700;">Q${i + 1}</span>
                    <span style="font-size:0.75rem; color:${r.correct ? '#10b981' : '#ef4444'}; font-weight:700;">${r.correct ? 'CORRECT' : 'WRONG'}</span>
                </div>
                <div style="font-weight:600; margin-bottom:12px;">${q.question}</div>
                <div style="font-size:0.85rem; color:var(--text-muted); background:var(--surface2); padding:12px; border-radius:8px;">
                    <strong>Explanation:</strong> ${r.explanation}
                </div>
            </div>
        `;
    }).join('');

    if (window.challengeState.type === 'daily') {
        const ptsEl = document.getElementById('stat-challenge-pts');
        if (ptsEl) ptsEl.textContent = parseInt(ptsEl.textContent || 0) + res.points_gained;
    } else {
        const ptsEl = document.getElementById('stat-assessment-pts');
        if (ptsEl) ptsEl.textContent = parseInt(ptsEl.textContent || 0) + res.points_gained;
    }
}

function confirmExitChallenge() {
    if (confirm("Are you sure you want to exit? Your progress will be lost.")) {
        closeChallengeOverlay();
    }
}

function closeChallengeOverlay() {
    if (window.challengeState.timerInterval) clearInterval(window.challengeState.timerInterval);
    if (window.challengeState.proctorInterval) clearInterval(window.challengeState.proctorInterval);

    const video = document.getElementById('proctor-video');
    if (video && video.srcObject) {
        video.srcObject.getTracks().forEach(t => t.stop());
        video.srcObject = null;
    }

    if (window.challengeState.visibilityHandler) {
        document.removeEventListener('visibilitychange', window.challengeState.visibilityHandler);
        window.challengeState.visibilityHandler = null;
    }

    document.getElementById('challenge-overlay').style.display = 'none';
    loadChallengePage();
}

/**
 * Movable Proctoring Camera (Drag & Drop for Mobile/Desktop)
 */
function initDraggableProctor() {
    const el = document.getElementById('proctor-pip-container');
    if (!el) return;

    let offset = [0, 0];
    let isDown = false;

    function move(e) {
        if (!isDown) return;
        e.preventDefault(); // Prevent scrolling while dragging

        let x = e.clientX || (e.touches && e.touches[0].clientX);
        let y = e.clientY || (e.touches && e.touches[0].clientY);

        // Calculate new position
        let newX = x + offset[0];
        let newY = y + offset[1];

        // Boundary checks (Keep within viewport)
        const maxX = window.innerWidth - el.offsetWidth;
        const maxY = window.innerHeight - el.offsetHeight;

        newX = Math.max(0, Math.min(newX, maxX));
        newY = Math.max(0, Math.min(newY, maxY));

        el.style.left = newX + 'px';
        el.style.top = newY + 'px';
        el.style.right = 'auto'; // Break initial 'right:30px' anchor
    }

    function start(e) {
        isDown = true;
        let x = e.clientX || (e.touches && e.touches[0].clientX);
        let y = e.clientY || (e.touches && e.touches[0].clientY);

        offset = [
            el.offsetLeft - x,
            el.offsetTop - y
        ];
        el.style.opacity = '0.8';
        el.style.transition = 'none'; // Snappy dragging
    }

    function end() {
        isDown = false;
        el.style.opacity = '1';
    }

    // Desktop
    el.addEventListener('mousedown', start);
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', end);

    // Mobile
    el.addEventListener('touchstart', start, { passive: false });
    window.addEventListener('touchmove', move, { passive: false });
    window.addEventListener('touchend', end);
}

// Auto-initialize once DOM is ready
document.addEventListener('DOMContentLoaded', initDraggableProctor);
// Re-init if dynamically rendered (safeguard)
setTimeout(initDraggableProctor, 2000);
