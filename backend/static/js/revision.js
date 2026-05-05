let revGlobalTopics = [];
let revGlobalDep = null;
let revGlobalFile = null;

function revHandleTextInput() {
  const text = document.getElementById('rev-text-input').value.trim();
  const btn = document.getElementById('rev-analyze-btn');
  if (text.length >= 3) {
    btn.disabled = false;
  } else if (!revGlobalFile) {
    btn.disabled = true;
  }
}

function revHandleFile(input) {
  const file = input.files[0];
  if (!file) return;
  const valid = ['application/pdf', 'text/plain', 'text/markdown'];
  if (!valid.includes(file.type) && !file.name.endsWith('.md')) {
    const err = document.getElementById('rev-error');
    err.textContent = 'Invalid format. Use PDF, TXT, or MD.';
    err.style.display = 'block';
    return;
  }
  document.getElementById('rev-error').style.display = 'none';
  revGlobalFile = file;

  document.getElementById('rev-file-chip').style.display = 'flex';
  document.getElementById('rev-file-name').textContent = file.name;
  document.getElementById('rev-file-size').textContent = (file.size / 1024).toFixed(1) + ' KB';
  document.getElementById('rev-analyze-btn').disabled = false;
}

function revHandleDrop(e) {
  e.preventDefault();
  e.currentTarget.classList.remove('drag-over');
  if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
    document.getElementById('rev-file-input').files = e.dataTransfer.files;
    revHandleFile(document.getElementById('rev-file-input'));
  }
}

async function revAnalyze() {
  const text = document.getElementById('rev-text-input').value.trim();
  if (!revGlobalFile && text.length < 3) return;

  const btn = document.getElementById('rev-analyze-btn');
  const loader = document.getElementById('rev-loader');
  const results = document.getElementById('rev-results');
  const err = document.getElementById('rev-error');

  btn.disabled = true;
  btn.innerHTML = '<div style="width:16px;height:16px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;display:inline-block;vertical-align:middle;margin-right:8px;"></div> Analyzing...';
  loader.style.display = 'block';
  results.style.display = 'none';
  err.style.display = 'none';

  try {
    const formData = new FormData();
    if (revGlobalFile) formData.append('file', revGlobalFile);
    if (text) formData.append('text_prompt', text);

    const data = await api('POST', '/revision/analyze', formData, true);

    revGlobalTopics = data.topics || [];
    revGlobalDep = revBuildDependencyMap(revGlobalTopics); // Build initial graph from full topics

    // Auto-switch to 'topics' tab and update slider
    revSwitchTab('topics');
    const overviewText = document.getElementById('rev-overview-text');
    if (data.overview) {
      overviewText.textContent = data.overview;
      document.getElementById('rev-overview-card').style.display = 'block';
    } else {
      document.getElementById('rev-overview-card').style.display = 'none';
    }

    loader.style.display = 'none';
    results.style.display = 'block';

    const slider = document.getElementById('rev-days-slider');
    revOnSlider(slider.value);

  } catch (e) {
    loader.style.display = 'none';
    err.textContent = e.message || 'Analysis failed.';
    err.style.display = 'block';
  } finally {
    btn.innerHTML = '✨ Generate Revision Plan';
    btn.disabled = false;
  }
}

function revLocalFilter(days) {
  let s = [...revGlobalTopics].sort((a, b) => b.importance_score - a.importance_score);
  let f = [];
  let m = '', a = '';

  if (days >= 28) {
    f = s;
    m = 'Full Study Mode';
    a = 'You have plenty of time! Cover all topics thoroughly.';
  } else if (days >= 26) {
    f = [...s.filter(t => (t.priority || 'Medium') !== 'Low'), ...s.filter(t => (t.priority || 'Medium') === 'Low').slice(0, Math.ceil(s.filter(t => (t.priority || 'Medium') === 'Low').length * 0.8))];
    m = 'Paced Mode'; a = 'Skip the least important Low priority topics.';
  } else if (days >= 24) {
    f = [...s.filter(t => (t.priority || 'Medium') !== 'Low'), ...s.filter(t => (t.priority || 'Medium') === 'Low').slice(0, Math.ceil(s.filter(t => (t.priority || 'Medium') === 'Low').length * 0.5))];
    m = 'Paced Mode'; a = 'Focus on main topics, half of Low priority can be skipped.';
  } else if (days >= 22) {
    f = [...s.filter(t => (t.priority || 'Medium') !== 'Low'), ...s.filter(t => (t.priority || 'Medium') === 'Low').slice(0, Math.ceil(s.filter(t => (t.priority || 'Medium') === 'Low').length * 0.2))];
    m = 'Focused Mode'; a = 'Almost all Low priority topics removed.';
  } else if (days >= 20) {
    f = s.filter(t => (t.priority || 'Medium') !== 'Low');
    m = 'Focused Mode'; a = 'Only High and Medium topics remain.';
  } else if (days >= 18) {
    f = [...s.filter(t => (t.priority || 'Medium') === 'High'), ...s.filter(t => (t.priority || 'Medium') === 'Medium').slice(0, Math.ceil(s.filter(t => (t.priority || 'Medium') === 'Medium').length * 0.8))];
    m = 'Efficiency Mode'; a = 'Trimming some Medium priority topics.';
  } else if (days >= 16) {
    f = [...s.filter(t => (t.priority || 'Medium') === 'High'), ...s.filter(t => (t.priority || 'Medium') === 'Medium').slice(0, Math.ceil(s.filter(t => (t.priority || 'Medium') === 'Medium').length * 0.6))];
    m = 'Efficiency Mode'; a = 'More focus on High priority now.';
  } else if (days >= 14) {
    f = [...s.filter(t => (t.priority || 'Medium') === 'High'), ...s.filter(t => (t.priority || 'Medium') === 'Medium').slice(0, Math.ceil(s.filter(t => (t.priority || 'Medium') === 'Medium').length * 0.4))];
    m = 'Priority Mode'; a = 'Over half of Medium topics are skipped.';
  } else if (days >= 12) {
    f = [...s.filter(t => (t.priority || 'Medium') === 'High'), ...s.filter(t => (t.priority || 'Medium') === 'Medium').slice(0, Math.ceil(s.filter(t => (t.priority || 'Medium') === 'Medium').length * 0.2))];
    m = 'Priority Mode'; a = 'Only the most important Medium topics remain.';
  } else if (days >= 10) {
    f = s.filter(t => (t.priority || 'Medium') === 'High');
    m = 'Urgent Mode'; a = 'Only High Priority topics remain.';
  } else if (days >= 8) {
    let high = s.filter(t => (t.priority || 'Medium') === 'High');
    f = high.slice(0, Math.max(8, Math.ceil(high.length * 0.8)));
    m = 'Urgent Mode'; a = 'Trimming some High priority topics to fit the schedule.';
  } else if (days >= 6) {
    let high = s.filter(t => (t.priority || 'Medium') === 'High');
    f = high.slice(0, Math.max(6, Math.ceil(high.length * 0.6)));
    m = 'Critical Mode'; a = 'Focusing on top High priority topics.';
  } else if (days >= 4) {
    let high = s.filter(t => (t.priority || 'Medium') === 'High');
    f = high.slice(0, Math.max(5, Math.ceil(high.length * 0.4)));
    m = 'Critical Mode'; a = 'Almost at the wire. Core topics only.';
  } else if (days >= 2) {
    let high = s.filter(t => (t.priority || 'Medium') === 'High');
    f = high.slice(0, Math.max(4, Math.ceil(high.length * 0.2)));
    m = 'Crisis Mode 🚨'; a = 'Just memorize these key points.';
  } else {
    f = s.filter(t => (t.priority || 'Medium') === 'High').slice(0, 3);
    if (!f.length) f = s.slice(0, 3);
    m = 'Crisis Mode 🚨'; a = 'Absolute bare minimum. Do not sleep.';
  }

  f.forEach(t => t.days_context = `~${Math.min(t.estimated_hours || 2, 3)}h focused.`);
  return { topics: f, mode: m, advice: a, topics_shown: f.length, topics_total: revGlobalTopics.length, days_left: days };
}

function revOnSlider(val) {
  document.getElementById('rev-days-num').textContent = val;
  const filtered = revLocalFilter(parseInt(val, 10));
  revRenderResults(filtered);

  // Dynamically build dependency map from the currently visible topics
  const dynamicDep = revBuildDependencyMap(filtered.topics);
  revGlobalDep = dynamicDep; // Update global so switching tabs uses it
  revRenderDepMap(dynamicDep);
}

function revBuildDependencyMap(topicsList) {
  const dep = { overview: "Concept map of currently visible topics.", foundational: [], intermediate: [], advanced: [] };
  const getP = (t) => {
    const s = (t.priority || 'Medium').toString().trim().toLowerCase();
    if (s.includes('high')) return 'High';
    if (s.includes('low')) return 'Low';
    return 'Medium';
  };

  topicsList.forEach(t => {
    const p = getP(t);
    const node = {
      name: (t.topic || 'Untitled').replace(/[^\w\s]/gi, ''), // Clean name for graph IDs
      importance: t.importance_score || 5,
      why_it_matters: t.explanation || '',
      depends_on: []
    };
    if (p === 'High') dep.foundational.push(node);
    else if (p === 'Medium') dep.intermediate.push(node);
    else dep.advanced.push(node);
  });

  // Create mock dependencies for visual connections
  if (dep.foundational.length > 0) {
    dep.intermediate.forEach((node, i) => {
      node.depends_on.push(dep.foundational[i % dep.foundational.length].name);
    });
    dep.advanced.forEach((node, i) => {
      if (dep.intermediate.length > 0) {
        node.depends_on.push(dep.intermediate[i % dep.intermediate.length].name);
      } else {
        node.depends_on.push(dep.foundational[i % dep.foundational.length].name);
      }
    });
  }
  return dep;
}

function revRenderResults(data) {
  const { topics, mode, advice, topics_shown } = data;
  const pill = document.getElementById('rev-mode-pill');
  pill.textContent = mode;

  const modeMap = {
    'Full': 'background:rgba(16,185,129,.12);color:#10b981;border:1px solid rgba(16,185,129,.25)',
    'Paced': 'background:rgba(16,185,129,.12);color:#10b981;border:1px solid rgba(16,185,129,.25)',
    'Focused': 'background:rgba(6,182,212,.12);color:#06b6d4;border:1px solid rgba(6,182,212,.25)',
    'Efficiency': 'background:rgba(6,182,212,.12);color:#06b6d4;border:1px solid rgba(6,182,212,.25)',
    'Priority': 'background:rgba(245,158,11,.12);color:#f59e0b;border:1px solid rgba(245,158,11,.25)',
    'Urgent': 'background:rgba(245,158,11,.12);color:#f59e0b;border:1px solid rgba(245,158,11,.25)',
    'Critical': 'background:rgba(239,68,68,.12);color:#ef4444;border:1px solid rgba(239,68,68,.25)',
    'Crisis': 'background:rgba(239,68,68,.12);color:#ef4444;border:1px solid rgba(239,68,68,.25)',
  };
  const mk = Object.keys(modeMap).find(k => mode.includes(k)) || 'Focused';
  pill.style.cssText = `text-align:center;padding:8px 16px;border-radius:20px;font-size:0.78rem;font-weight:700;${modeMap[mk]}`;

  document.getElementById('rev-advice-box').innerHTML = '💡 ' + advice;
  document.getElementById('rev-s-shown').textContent = topics_shown;
  const getP = (t) => {
    const s = (t.priority || 'Medium').toString().trim().toLowerCase();
    if (s.includes('high')) return 'High';
    if (s.includes('low')) return 'Low';
    return 'Medium';
  };

  document.getElementById('rev-s-high').textContent = topics.filter(t => getP(t) === 'High').length;
  document.getElementById('rev-s-med').textContent = topics.filter(t => getP(t) === 'Medium').length;
  document.getElementById('rev-s-low').textContent = topics.filter(t => getP(t) === 'Low').length;

  const grid = document.getElementById('rev-topics-grid');
  if (!topics.length) {
    grid.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:32px;width:100%;">No topics to show for this filter.</p>';
    return;
  }

  const PC = { High: 'var(--danger)', Medium: 'var(--warning)', Low: 'var(--success)' };

  grid.innerHTML = topics.map((t, i) => {
    const p = getP(t);
    const c = PC[p] || 'var(--primary)';
    const sw = ((t.importance_score || 5) / 10) * 100;
    const pts = (t.key_points || []).map(p => `<li style="display:flex;gap:7px;font-size:.8rem;color:#cbd5e1;margin-bottom:3px;"><span style="color:#a855f7;font-weight:700;">›</span><span>${p}</span></li>`).join('');
    return `<div class="rev-topic-card ${p.toLowerCase()}" style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:10px;">
        <div style="font-size:.96rem;font-weight:700;flex:1;">${t.topic || 'Untitled Topic'}</div>
        <div style="display:flex;gap:6px;flex-shrink:0;align-items:center;">
          <span style="padding:3px 9px;border-radius:10px;font-size:.68rem;font-weight:700;background:${c}22;color:${c};">${p}</span>
          <span style="background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:2px 8px;font-size:.74rem;font-weight:600;color:#a855f7;">⭐ ${t.importance_score || 5}/10</span>
        </div>
      </div>
      <div style="height:3px;background:var(--border);border-radius:2px;overflow:hidden;margin-bottom:10px;">
        <div style="height:100%;width:${sw}%;background:linear-gradient(90deg,${c},${c}aa);border-radius:2px;transition:width .6s ease;"></div>
      </div>
      <p style="font-size:.84rem;color:var(--text-muted);line-height:1.6;margin-bottom:${pts ? '10px' : '0'};">${t.explanation || ''}</p>
      ${pts ? `<div style="margin-bottom:10px;"><div style="font-size:.68rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);margin-bottom:5px;">Key Points</div><ul style="list-style:none;">${pts}</ul></div>` : ''}
      <div style="display:flex;gap:12px;flex-wrap:wrap;padding-top:10px;border-top:1px solid var(--border);">
        <span style="font-size:.74rem;color:var(--text-muted);">⏱ ~${t.estimated_hours || 1}h estimated</span>
        ${t.days_context ? `<span style="font-size:.74rem;color:var(--text-muted);">💡 ${t.days_context}</span>` : ''}
        <div style="display:flex;align-items:center;gap:12px;margin-top:16px;">
          <button class="btn btn-sm btn-primary" style="flex:1;border-radius:6px;font-size:0.75rem;padding:8px;" onclick="revLoadMasterclass('${(t.topic || '').replace(/'/g, "\\'")}')">
            🔥 Masterclass Detail
          </button>
        </div>
      </div>
    </div>`;
  }).join('');
}

function revSwitchTab(tabId) {
  document.querySelectorAll('.rev-tab').forEach(b => {
    b.classList.remove('active');
    b.style.background = 'transparent';
    b.style.color = 'var(--text-muted)';
    b.style.boxShadow = 'none';
  });
  const activeBtn = document.querySelector(`.rev-tab[onclick*="'${tabId}'"]`);
  activeBtn.classList.add('active');
  activeBtn.style.background = 'linear-gradient(135deg,#a855f7,#6366f1)';
  activeBtn.style.color = 'white';
  activeBtn.style.boxShadow = '0 2px 8px rgba(168,85,247,0.35)';

  ['topics', 'map', 'chat'].forEach(id => {
    document.getElementById(`rev-tab-${id}`).style.display = (id === tabId) ? 'block' : 'none';
  });
  if (tabId === 'map') setTimeout(() => revRenderDepMap(revGlobalDep), 50);
}

// ── Dependency Map ────────────────────────────────────────────
function revRenderDepMap(dep) {
  if (!dep) return;
  const el = document.getElementById('rev-dep-content');
  const LC = { Foundational: 'var(--success)', Intermediate: 'var(--warning)', Advanced: 'var(--danger)' };
  const LI = { Foundational: '🟢', Intermediate: '🟡', Advanced: '🔴' };

  let html = `<p style="font-size:0.86rem;color:var(--text-muted);margin-bottom:14px;line-height:1.5;">${dep.overview}</p>`;

  // Render Roadmap Flow
  const roadmap = document.getElementById('rev-roadmap-flow');
  if (roadmap) {
    const sequence = [...(dep.foundational || []), ...(dep.intermediate || []), ...(dep.advanced || [])];
    roadmap.innerHTML = sequence.map((s, i) => `
      <div style="flex-shrink:0;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 16px;min-width:180px;text-align:center;position:relative;">
        <div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;margin-bottom:4px;">Step ${i + 1}</div>
        <div style="font-weight:600;font-size:0.85rem;">${s.name}</div>
        ${i < sequence.length - 1 ? '<div style="position:absolute;right:-14px;top:50%;transform:translateY(-50%);color:var(--border);font-size:1.2rem;">→</div>' : ''}
      </div>
    `).join('');
  }

  ['foundational', 'intermediate', 'advanced'].forEach(level => {
    if (!dep[level] || !dep[level].length) return;
    const lvlName = level.charAt(0).toUpperCase() + level.slice(1);
    html += `<div style="margin-bottom:16px;">
      <h4 style="font-size:0.8rem;color:${LC[lvlName]};margin-bottom:8px;text-transform:uppercase;letter-spacing:.05em;">${LI[lvlName]} ${lvlName}</h4>
      <div style="display:flex;flex-direction:column;gap:8px;">
        ${dep[level].map(c => `
          <div class="card" style="border-left:4px solid ${LC[lvlName]};background:var(--surface);padding:10px 14px;border-radius:4px;box-shadow:0 2px 4px rgba(0,0,0,.1);">
            <div style="font-weight:600;margin-bottom:4px;">${c.name}</div>
            <div style="font-size:0.85rem;color:var(--text-muted);line-height:1.5;">
              ${(c.why_it_matters || 'No explanation available.').split('.').slice(0, 2).join('.') + '.'}
            </div>
            ${c.depends_on && c.depends_on.length ? `<div style="font-size:0.75rem;margin-top:8px;color:var(--text-muted);">Requires: ${c.depends_on.join(', ')}</div>` : ''}
          </div>
        `).join('')}
      </div>
    </div>`;
  });
  el.innerHTML = html;
  revDrawCanvasTree(dep);
}

function revDrawCanvasTree(dep) {
  const canvas = document.getElementById('rev-tree-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  // Set dimensions properly - Dynamic height based on number of nodes
  const rect = canvas.parentElement.getBoundingClientRect();
  const totalNodes = (dep.foundational || []).length + (dep.intermediate || []).length + (dep.advanced || []).length;
  canvas.width = rect.width;
  canvas.height = Math.max(600, totalNodes * 25); // Dynamic height to prevent vertical clumping

  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const nodes = [];
  const LC = { Foundational: '#10b981', Intermediate: '#f59e0b', Advanced: '#ef4444' };

  const levels = ['foundational', 'intermediate', 'advanced'];
  const ySpacing = canvas.height / 4;

  levels.forEach((lvl, i) => {
    const arr = dep[lvl] || [];
    const lvlY = ySpacing * (i + 1);

    arr.forEach((c, j) => {
      // Improved Staggered layout with wider horizontal spread
      const xSpacing = canvas.width / (arr.length + 1);
      const staggeredY = lvlY + (j % 3 === 0 ? -60 : (j % 3 === 1 ? 0 : 60));

      nodes.push({
        id: (c.name || '').toLowerCase().replace(/\s+/g, '_'),
        name: c.name,
        x: xSpacing * (j + 1),
        y: staggeredY,
        color: LC[lvl.charAt(0).toUpperCase() + lvl.slice(1)] || '#a855f7',
        depends: (c.depends_on || []).map(d => d.toLowerCase().replace(/\s+/g, '_'))
      });
    });
  });

  // Draw edges
  ctx.lineWidth = 1.5;
  nodes.forEach(n => {
    n.depends.forEach(depId => {
      const target = nodes.find(x => x.id === depId);
      if (target) {
        ctx.beginPath();
        ctx.moveTo(target.x, target.targetY || target.y);
        // smooth curve
        ctx.bezierCurveTo(target.x, (n.y + target.y) / 2, n.x, (n.y + target.y) / 2, n.x, n.y);
        ctx.strokeStyle = 'rgba(148,163,184,0.3)';
        ctx.stroke();
      }
    });
  });

  // Draw nodes
  nodes.forEach(n => {
    // Active Node Highlight
    if (typeof revActiveNode !== 'undefined' && revActiveNode === n.name) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, 20, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(129,140,248,0.6)';
      ctx.lineWidth = 4;
      ctx.stroke();
    }

    ctx.beginPath();
    ctx.arc(n.x, n.y, 14, 0, Math.PI * 2);
    ctx.fillStyle = '#0f172a';
    ctx.fill();
    ctx.lineWidth = 3;
    ctx.strokeStyle = n.color;
    ctx.stroke();

    // Text wrapping for long topic names
    ctx.fillStyle = '#f8fafc';
    ctx.font = '600 10px Inter, sans-serif';
    ctx.textAlign = 'center';
    const words = n.name.split(' ');
    let line = '';
    let yOffset = 24;
    for (let nWord = 0; nWord < words.length; nWord++) {
      let testLine = line + words[nWord] + ' ';
      let metrics = ctx.measureText(testLine);
      if (metrics.width > 80 && nWord > 0) {
        ctx.fillText(line, n.x, n.y + yOffset);
        line = words[nWord] + ' ';
        yOffset += 12;
      } else {
        line = testLine;
      }
    }
    ctx.fillText(line, n.x, n.y + yOffset);
  });

  // Click Handler removed as quiz is deleted
  canvas.onclick = null;
}

async function revLoadMasterclass(topicName) {
  const container = document.getElementById('rev-masterclass-container');
  const title = document.getElementById('rev-master-title');
  const textEl = document.getElementById('rev-master-text');

  // Switch to map tab so loading shows in concept section
  revSwitchTab('map');

  container.style.display = 'block';
  title.innerHTML = `🎓 Masterclass Deep-Dive: ${topicName}`;
  textEl.innerHTML = `
    <div style="text-align:center;padding:50px 20px;background:rgba(168,85,247,0.04);border-radius:12px;border:1px dashed rgba(168,85,247,0.25);">
      <div style="position:relative;width:70px;height:70px;margin:0 auto 20px;">
        <div style="position:absolute;inset:0;border-radius:50%;border:3px solid rgba(168,85,247,0.15);"></div>
        <div style="position:absolute;inset:0;border-radius:50%;border:3px solid transparent;border-top-color:#a855f7;animation:spin 0.9s linear infinite;"></div>
        <div style="position:absolute;inset:8px;border-radius:50%;border:3px solid transparent;border-top-color:#6366f1;animation:spin 1.3s linear infinite reverse;"></div>
        <div style="position:absolute;inset:16px;border-radius:50%;border:3px solid transparent;border-top-color:#06b6d4;animation:spin 1.7s linear infinite;"></div>
      </div>
      <div style="font-weight:700;color:var(--text);margin-bottom:8px;font-size:1.05rem;background:linear-gradient(135deg,#a855f7,#6366f1);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;">
        Generating Expert Content...
      </div>
      <div style="color:var(--text-muted);font-size:0.84rem;margin-bottom:20px;">AI is assembling a detailed masterclass for <strong style="color:#a5b4fc;">${topicName}</strong></div>
      <div style="display:flex;justify-content:center;gap:6px;">
        <div style="width:8px;height:8px;border-radius:50%;background:#a855f7;animation:revPulse 1.2s infinite 0s;"></div>
        <div style="width:8px;height:8px;border-radius:50%;background:#6366f1;animation:revPulse 1.2s infinite 0.2s;"></div>
        <div style="width:8px;height:8px;border-radius:50%;background:#06b6d4;animation:revPulse 1.2s infinite 0.4s;"></div>
      </div>
    </div>
  `;
  container.scrollIntoView({ behavior: 'smooth', block: 'center' });

  try {
    const res = await api('POST', '/revision/masterclass', { topic: topicName });
    textEl.innerText = res.explanation;
  } catch (e) {
    textEl.innerHTML = `<span style="color:var(--danger)">Failed to load masterclass: ${e.message}</span>`;
  }
}

// ── Revision AI Chat ───────────────────────────────────────────
async function revSendChat() {
  const input = document.getElementById('rev-chat-input');
  const msg = input.value.trim();
  if (!msg) return;

  const box = document.getElementById('rev-chat-box');

  // User Message
  box.innerHTML += `
    <div style="background:linear-gradient(135deg,#a855f7,#6366f1);color:white;padding:10px 14px;border-radius:12px;max-width:85%;align-self:flex-end;font-size:0.88rem;box-shadow:0 2px 8px rgba(99,102,241,0.2);">
      ${msg}
    </div>
  `;
  input.value = '';
  box.scrollTop = box.scrollHeight;

  // Loader
  const loaderId = 'chat-load-' + Date.now();
  box.innerHTML += `
    <div id="${loaderId}" style="background:var(--surface);padding:10px 14px;border-radius:12px;max-width:85%;align-self:flex-start;font-size:0.88rem;border:1px solid var(--border);display:flex;align-items:center;gap:8px;">
      <div style="width:12px;height:12px;border:2px solid #a855f7;border-top-color:transparent;border-radius:50%;animation:spin .6s linear infinite;"></div>
      Thinking...
    </div>
  `;
  box.scrollTop = box.scrollHeight;

  try {
    const data = await api('POST', '/revision/chat', { message: msg });
    document.getElementById(loaderId).remove();

    if (data.answer) {
      box.innerHTML += `
        <div style="background:var(--surface);padding:10px 14px;border-radius:12px;max-width:85%;align-self:flex-start;font-size:0.88rem;border:1px solid var(--border);line-height:1.5;">
          ${data.answer.replace(/\n/g, '<br>')}
        </div>
      `;
    } else {
      throw new Error(data.error || 'Failed to get answer');
    }
  } catch (e) {
    document.getElementById(loaderId).innerHTML = `<span style="color:var(--danger)">Error: ${e.message}</span>`;
  }
  box.scrollTop = box.scrollHeight;
}
