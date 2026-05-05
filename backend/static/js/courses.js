/* ═══════════════════════════════════════════════════════════
   courses.js  —  Structured Learning Paths, Modules & Lessons
   ═══════════════════════════════════════════════════════════ */

let allCourses = [];
let currentCourse = null;
let currentLesson = null;
let courseProgress = { completed_lessons: [], bookmarks: [], notes: {} };

async function loadCourses() {
    const grid = document.getElementById('course-grid');
    grid.innerHTML = '<p class="text-muted">Fetching learning paths...</p>';
    
    try {
        const d = await api('GET', '/courses/');
        allCourses = d.courses;
        
        if (!allCourses.length) {
            grid.innerHTML = '<p class="text-muted">No courses available yet.</p>';
            return;
        }

        grid.innerHTML = allCourses.map(c => `
            <div class="card" style="padding:0; overflow:hidden; display:flex; flex-direction:column; transition:transform .2s;" onmouseover="this.style.transform='translateY(-5px)'" onmouseout="this.style.transform='none'">
                <div style="height:140px; background:url('${c.thumbnail}') center/cover; position:relative;">
                    ${c.is_recommended ? `<span class="badge badge-primary" style="position:absolute; top:12px; left:12px; box-shadow:0 4px 10px rgba(99,102,241,0.4);">✨ Recommended</span>` : ''}
                    <div style="position:absolute; bottom:0; left:0; width:100%; height:4px; background:rgba(255,255,255,0.1);">
                        <div style="height:100%; width:${c.progress}%; background:var(--primary);"></div>
                    </div>
                </div>
                <div style="padding:20px; flex:1; display:flex; flex-direction:column;">
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;">${c.subject} • ${c.difficulty}</div>
                    <h3 style="font-size:1.05rem; margin-bottom:12px; line-height:1.4;">${c.title}</h3>
                    <div style="margin-top:auto; display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size:0.85rem; color:var(--text-muted);">📊 ${c.progress}% done</span>
                        <button class="btn btn-sm btn-primary" onclick="openCourse('${c._id}')">${c.progress > 0 ? 'Resume' : 'Start'} →</button>
                    </div>
                </div>
            </div>
        `).join('');

        // Update Global Stats
        document.getElementById('course-xp-val').textContent = d.total_xp || 0;
        document.getElementById('course-streak-val').textContent = `${d.streak || 0} Days`;
    } catch (e) {
        grid.innerHTML = `<p class="text-danger">Error: ${e.message}</p>`;
    }
}

async function openCourse(courseId) {
    try {
        const d = await api('GET', `/courses/${courseId}`);
        currentCourse = d.course;
        courseProgress = { 
            completed_lessons: d.completed_lessons, 
            bookmarks: d.bookmarks, 
            notes: d.notes,
            lesson_stats: d.lesson_stats || {}
        };

        document.getElementById('courses-list-view').style.display = 'none';
        document.getElementById('course-player-view').style.display = 'block';
        document.getElementById('current-course-title').textContent = currentCourse.title;

        renderCourseModules();
        
        // Auto-resume logic
        const lastLessonId = currentCourse.last_lesson || currentCourse.modules[0].lessons[0].id;
        playLesson(lastLessonId);
        
    } catch (e) {
        toast("Could not load course details", "error");
    }
}

async function playLesson(lessonId) {
    let lesson = null;
    for (const m of currentCourse.modules) {
        const found = m.lessons.find(l => l.id === lessonId);
        if (found) { lesson = found; break; }
    }
    if (!lesson) return;
    currentLesson = lesson;

    // Show custom play overlay
    document.getElementById('video-custom-overlay').style.display = 'flex';

    // Build URL without autoplay initially
    const cleanUrl = new URL(lesson.video);
    cleanUrl.searchParams.set('modestbranding', '1');
    cleanUrl.searchParams.set('rel', '0');
    cleanUrl.searchParams.set('iv_load_policy', '3');
    cleanUrl.searchParams.set('controls', '1');
    cleanUrl.searchParams.set('enablejsapi', '1'); // For programmatic control

    // Find parent module for metadata
    let modTitle = "Module 1";
    for (const m of currentCourse.modules) {
        if (m.lessons.find(l => l.id === lessonId)) {
            modTitle = m.title.split(':')[0] || m.title;
            break;
        }
    }

    // Update UI
    document.getElementById('lesson-player').src = cleanUrl.toString();
    document.getElementById('current-lesson-title').textContent = lesson.title;
    document.getElementById('current-lesson-meta').textContent = `${modTitle}`;
    document.getElementById('lesson-notes-input').value = courseProgress.notes[lessonId] || "";
    
    // Switch to summary tab
    switchCourseTab('summary');
    loadLessonSummary(lessonId);
}

function startLessonVideo() {
    const overlay = document.getElementById('video-custom-overlay');
    const player = document.getElementById('lesson-player');
    
    overlay.style.display = 'none';
    
    // Append autoplay=1 to trigger playback
    let currentSrc = player.src;
    if (currentSrc.indexOf('autoplay=1') === -1) {
        player.src = currentSrc + (currentSrc.indexOf('?') === -1 ? '?' : '&') + 'autoplay=1';
    }
}

async function resetModule(idx) {
    if (!confirm("Are you sure? This will clear all progress and notes for this module.")) return;
    try {
        const res = await api('POST', `/courses/module/${idx}/reset`);
        courseProgress = res.progress;
        toast("Module reset successfully", "success");
        renderCourseModules();
    } catch (e) { toast("Reset failed", "error"); }
}

function renderCourseModules() {
    const el = document.getElementById('course-modules-list');
    const stats = courseProgress.lesson_stats || {};
    
    el.innerHTML = currentCourse.modules.map((mod, mIdx) => {
        let modXp = 0;
        let modCorrect = 0;
        let modTotal = 0;
        let completedInMod = 0;
        let totalSeconds = 0;
        
        mod.lessons.forEach(l => {
            const lStat = stats[l.id] || {};
            if (lStat.completed) {
                completedInMod++;
                modXp += 50; 
            }
            modCorrect += lStat.correct || 0;
            modTotal += lStat.total || 0;
            modXp += lStat.quiz_xp || 0;
            
            // Sum duration
            const parts = l.duration.split(':').map(Number);
            totalSeconds += (parts[0] * 60) + (parts[1] || 0);
        });

        const modMinutes = Math.floor(totalSeconds / 60);

        return `
            <div class="module-group" style="border-bottom:1px solid var(--border);">
                <div style="padding:16px; background:rgba(255,255,255,0.02); display:flex; justify-content:space-between; align-items:flex-start;">
                    <div>
                        <div style="font-size:0.7rem; color:var(--text-muted); text-transform:uppercase; font-weight:700; letter-spacing:0.05em;">Module ${mIdx + 1}</div>
                        <div style="font-weight:700; font-size:0.9rem;">${mod.title}</div>
                        <button class="btn btn-link btn-sm" onclick="resetModule(${mIdx})" style="padding:0; margin-top:8px; font-size:0.7rem; color:var(--danger); opacity:0.7;">↺ Reset Progress</button>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:0.85rem; color:var(--accent); font-weight:700;">+${modXp} XP</div>
                        <div style="font-size:0.7rem; color:var(--text-muted);">${completedInMod}/${mod.lessons.length} Lessons</div>
                    </div>
                </div>
                
                <div style="padding:8px 16px; background:rgba(99,102,241,0.05); display:flex; gap:16px; font-size:0.75rem;">
                    <span title="Practice Accuracy">🎯 <strong>${modCorrect}/${modTotal}</strong> Right</span>
                    <span title="Lessons Completed">📚 <strong>${Math.round((completedInMod/mod.lessons.length)*100)}%</strong> Done</span>
                </div>

                <div class="lessons-list">
                    ${mod.lessons.map(lesson => {
                        const isDone = courseProgress.completed_lessons.includes(lesson.id);
                        const isActive = currentLesson && currentLesson.id === lesson.id;
                        return `
                            <div class="lesson-item ${isDone ? 'completed' : ''} ${isActive ? 'active' : ''}" 
                                onclick="playLesson('${lesson.id}')"
                                style="padding:12px 16px; display:flex; align-items:center; gap:12px; cursor:pointer; transition:all 0.2s;">
                                <div class="status-icon" style="width:20px; height:20px; border-radius:50%; border:2px solid ${isDone ? '#10b981' : 'var(--border)'}; display:flex; align-items:center; justify-content:center; font-size:0.7rem;">
                                    ${isDone ? '✓' : ''}
                                </div>
                                <div style="flex:1;">
                                    <div style="font-size:0.85rem; font-weight:500;">${lesson.title}</div>
                                </div>
                                ${stats[lesson.id]?.correct ? `<span style="font-size:0.7rem; background:rgba(16,185,129,0.1); color:#10b981; padding:2px 6px; border-radius:4px;">${stats[lesson.id].correct}/${stats[lesson.id].total} Q</span>` : ''}
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        `;
    }).join('');
}

// State
let courseSummaries = {}; // Cache for summaries



async function loadLessonSummary(lessonId) {
    const el = document.getElementById('ai-summary-text');
    
    const parseMD = (text) => {
        try {
            // 1. Check for modern marked.parse
            if (typeof marked !== 'undefined' && marked.parse) {
                return marked.parse(text);
            }
            // 2. Check for legacy marked() function
            if (typeof marked === 'function') {
                return marked(text);
            }
            // 3. Check for window-level scoped marked
            if (window.marked && window.marked.parse) {
                return window.marked.parse(text);
            }
        } catch (e) {
            console.error("Markdown parsing failed:", e);
        }
        // 4. Ultimate fallback: Simple regex for common MD patterns if library fails
        return text
            .replace(/^# (.*$)/gim, '<h3>$1</h3>')
            .replace(/^## (.*$)/gim, '<h4>$1</h4>')
            .replace(/\*\*(.*)\*\*/gim, '<strong>$1</strong>')
            .replace(/\n/g, '<br>');
    };

    if (courseSummaries[lessonId]) {
        el.innerHTML = `
            ${parseMD(courseSummaries[lessonId])}
            <div style="margin-top:20px; border-top:1px solid var(--border); padding-top:15px; text-align:center;">
                <button class="btn btn-sm btn-secondary" onclick="generateLessonSummary('${lessonId}')">🔄 Regenerate Unique Summary</button>
            </div>
        `;
        return;
    }

    el.innerHTML = `
        <div class="text-center" style="padding:40px;">
            <div style="font-size:3rem; margin-bottom:15px;">📖</div>
            <h3>Lesson Guide</h3>
            <p class="text-muted" style="margin-bottom:20px;">Generate a custom technical summary with Nemotron AI</p>
            <button class="btn btn-primary" onclick="generateLessonSummary('${lessonId}')">✨ Generate AI Summary</button>
        </div>
    `;
}

async function generateLessonSummary(lessonId) {
    const el = document.getElementById('ai-summary-text');
    el.innerHTML = '<div class="text-center" style="padding:40px;"><div class="spinner"></div><p>Nemotron AI is analyzing the topic...</p></div>';
    
    try {
        const res = await api('GET', `/courses/lesson/${lessonId}/summary?refresh=true`);
        courseSummaries[lessonId] = res.summary;
        loadLessonSummary(lessonId); // Re-render with the regenerate button
    } catch (e) { 
        el.innerHTML = `<p class="text-danger">Failed to generate summary. <button class="btn btn-link" onclick="generateLessonSummary('${lessonId}')">Try again</button></p>`; 
    }
}

async function markComplete() {
    if (!currentLesson) return;
    const lessonId = currentLesson.id;
    
    try {
        const d = await api('POST', `/courses/lesson/${lessonId}/complete`);
        toast(`Lesson Complete! +${d.xp_gained} XP`, "success");
        
        courseProgress = d.progress; // Update full progress from backend
        renderCourseModules();
        
        // Find next lesson
        // (Simplified for now)
    } catch (e) {
        toast("Failed to update progress", "error");
    }
}

async function saveLessonNotes() {
    const content = document.getElementById('lesson-notes-input').value;
    try {
        await api('POST', `/courses/lesson/${currentLesson.id}/notes`, { content });
        courseProgress.notes[currentLesson.id] = content;
        toast("Notes saved", "success");
    } catch (e) { toast("Failed to save notes", "error"); }
}

let quizState = { correct: 0, total: 0, answered: 0 };

async function switchCourseTab(tab) {
    const tabs = ['summary', 'notes', 'quiz'];
    tabs.forEach(t => {
        document.getElementById(`course-tab-${t}`).style.display = (t === tab) ? 'block' : 'none';
    });
    
    document.querySelectorAll('.course-tab').forEach(btn => {
        btn.classList.toggle('active', btn.textContent.toLowerCase().includes(tab));
    });

    if (tab === 'quiz' && currentLesson) {
        renderQuizInitial();
    }
}

function renderQuizInitial() {
    const container = document.getElementById('lesson-quiz-suggestion');
    const isCompleted = courseProgress.completed_lessons.includes(currentLesson.id);
    
    if (!isCompleted) {
        container.innerHTML = `<div class="alert alert-info">🔥 Complete this lesson to unlock the practice quiz!</div>`;
        return;
    }

    container.innerHTML = `
        <div class="text-center" style="padding:40px;">
            <div style="font-size:3rem; margin-bottom:20px;">🎯</div>
            <h3>Test Your Knowledge</h3>
            <p class="text-muted" style="margin-bottom:24px;">Generate a custom quiz for ${currentLesson.title}</p>
            <button class="btn btn-primary" onclick="generateLessonQuiz()">🧠 Generate Practice Questions</button>
        </div>
    `;
}

async function generateLessonQuiz() {
    const container = document.getElementById('lesson-quiz-suggestion');
    container.innerHTML = `<div class="text-center" style="padding:40px;"><div class="spinner"></div><p>Nemotron AI is crafting your quiz...</p></div>`;
    
    try {
        const res = await api('GET', `/courses/lesson/${currentLesson.id}/quiz`);
        const quiz = res.quiz;
        quizState = { correct: 0, total: quiz.length, answered: 0 };
        
        container.innerHTML = `
            <div style="padding:10px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
                    <h4 style="margin:0;">Practice Quiz</h4>
                    <span class="badge badge-primary" id="quiz-progress-text">0/${quiz.length} Answered</span>
                </div>
                <div id="quiz-questions-list">
                    ${quiz.map((q, i) => `
                        <div class="card" style="margin-bottom:16px; background:rgba(255,255,255,0.03);">
                            <p style="font-weight:600; margin-bottom:12px;">${i+1}. ${q.question}</p>
                            <div style="display:grid; gap:8px;">
                                ${q.options.map(opt => {
                                    const esc = (s) => (s || "").replace(/'/g, "\\'");
                                    return `
                                        <button class="btn btn-sm btn-secondary quiz-opt" 
                                            onclick="checkLessonAnswer(this, '${esc(opt)}', '${esc(q.answer)}', '${esc(q.explanation)}')"
                                            style="text-align:left; justify-content:flex-start;">
                                            ${opt}
                                        </button>
                                    `;
                                }).join('')}
                            </div>
                        </div>
                    `).join('')}
                </div>
                <div id="quiz-finish-area" style="display:none; text-center; padding:20px; border-top:1px solid var(--border);">
                    <button class="btn btn-primary btn-block" onclick="finishLessonQuiz()">Finish Quiz & Claim XP</button>
                </div>
            </div>`;
    } catch (e) {
        container.innerHTML = `<p class="text-danger">Failed to generate quiz. Try again.</p>`;
    }
}

function checkLessonAnswer(btn, selected, correct, explanation) {
    const parent = btn.parentElement;
    const allBtns = parent.querySelectorAll('.quiz-opt');
    allBtns.forEach(b => b.disabled = true);
    
    quizState.answered++;
    if (selected === correct) {
        quizState.correct++;
        btn.style.background = '#10b981';
        btn.innerHTML += ' ✅';
    } else {
        btn.style.background = '#ef4444';
        btn.innerHTML += ' ❌';
        allBtns.forEach(b => { if (b.textContent.trim() === correct) b.style.border = '2px solid #10b981'; });
    }
    
    const expDiv = document.createElement('div');
    expDiv.style = "margin-top:10px; font-size:0.85rem; color:var(--text-muted); padding:8px; border-left:3px solid var(--accent); background:rgba(99,102,241,0.05);";
    expDiv.innerHTML = `<strong>Explanation:</strong> ${explanation}`;
    parent.parentElement.appendChild(expDiv);

    document.getElementById('quiz-progress-text').textContent = `${quizState.answered}/${quizState.total} Answered`;
    
    if (quizState.answered === quizState.total) {
        document.getElementById('quiz-finish-area').style.display = 'block';
    }
}

async function finishLessonQuiz() {
    const xpGained = quizState.correct * 20;
    try {
        await api('POST', `/courses/lesson/${currentLesson.id}/quiz_result`, { 
            correct: quizState.correct, 
            total: quizState.total 
        });
        
        toast(`Quiz Finished! Gained ${xpGained} XP`, 'success');
        
        // Refresh local data
        if (!courseProgress.lesson_stats) courseProgress.lesson_stats = {};
        courseProgress.lesson_stats[currentLesson.id] = {
            correct: quizState.correct,
            total: quizState.total,
            quiz_xp: xpGained,
            completed: true
        };
        
        renderCourseModules(); // Refresh module list UI with new stats
        
        const container = document.getElementById('lesson-quiz-suggestion');
        container.innerHTML = `
            <div class="text-center" style="padding:40px;">
                <div style="font-size:3rem; margin-bottom:10px;">🎉</div>
                <h3>Quiz Complete!</h3>
                <div style="display:flex; justify-content:center; gap:24px; margin:20px 0;">
                    <div class="card" style="padding:15px; min-width:120px;">
                        <div style="font-size:0.75rem; color:var(--text-muted);">PRACTICED</div>
                        <div style="font-size:1.5rem; font-weight:700;">${quizState.total}</div>
                    </div>
                    <div class="card" style="padding:15px; min-width:120px;">
                        <div style="font-size:0.75rem; color:var(--text-muted);">ACCURACY</div>
                        <div style="font-size:1.5rem; font-weight:700; color:#10b981;">${Math.round((quizState.correct/quizState.total)*100)}%</div>
                    </div>
                </div>
                <button class="btn btn-secondary" onclick="renderQuizInitial()">Try Another Quiz</button>
            </div>
        `;
        
        // Refresh XP in UI
        const xpEl = document.getElementById('course-xp-val');
        if (xpEl) xpEl.textContent = parseInt(xpEl.textContent) + xpGained;
        
    } catch (e) { toast("Failed to award XP", "error"); }
}

function backToCourses() {
    document.getElementById('course-player-view').style.display = 'none';
    document.getElementById('courses-list-view').style.display = 'block';
    document.getElementById('lesson-player').src = ''; // Stop video
    loadCourses(); // Refresh grid
}
