/* ═══════════════════════════════════════════════════════════
   groq.js  —  Groq AI Tutor chat + explain concept
   Depends on: core.js (api, toast, documents)
   ═══════════════════════════════════════════════════════════ */

let dsHistory = [];
let dsTotalTokens = 0;
let dsMsgCount = 0;
let dsStreaming = false;

// ── Populate Document Select ──────────────────────────────────
function populateDsDocSelect() {
  const sel = document.getElementById('ds-doc-select');
  if (!sel || typeof documents === 'undefined') return;
  const current = sel.value;
  sel.innerHTML = '<option value="">🌐 No document (general chat)</option>' +
    documents.map(d => `<option value="${d._id}">${d.original_name}</option>`).join('');
  if (current) sel.value = current;
}

// ── Mode Switcher (chat ↔ explain) ────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const modeSelect = document.getElementById('ds-model-mode');
  if (modeSelect) {
    modeSelect.addEventListener('change', () => {
      const isExplain = modeSelect.value === 'explain';
      document.getElementById('ds-explain-panel').style.display = isExplain ? 'block' : 'none';
      document.getElementById('ds-input-row').style.display = isExplain ? 'none' : 'flex';
      document.getElementById('ds-suggestions').style.display = isExplain ? 'none' : 'flex';
    });
  }
});

function handleDsKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendGroqChat(); }
}

function setDsPrompt(text) {
  const inp = document.getElementById('ds-input');
  inp.value = text;
  inp.style.height = 'auto';
  inp.style.height = Math.min(inp.scrollHeight, 140) + 'px';
  inp.focus();
}

// ── Markdown Renderer ─────────────────────────────────────────
function renderMarkdown(text) {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => `<pre><code class="lang-${lang}">${code.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>').replace(/^## (.+)$/gm, '<h2>$1</h2>').replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
    .replace(/^[\*\-] (.+)$/gm, '<li>$1</li>').replace(/(<li>.*<\/li>\n?)+/g, s => `<ul>${s}</ul>`)
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    .replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>');
}

// ── Append Messages ───────────────────────────────────────────
function appendDsUser(text) {
  const box = document.getElementById('ds-chat-box');
  const div = document.createElement('div');
  div.className = 'ds-msg ds-msg-user';
  div.textContent = text;
  box.appendChild(div); box.scrollTop = box.scrollHeight;
}

function appendDsAi(html, timestamp) {
  const box = document.getElementById('ds-chat-box');
  const outer = document.createElement('div');
  outer.className = 'ds-msg ds-msg-ai';
  const ts = timestamp || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  outer.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
      <span style="font-size:1rem;">🤖</span>
      <strong style="color:#06b6d4;font-size:0.82rem;">Groq</strong>
      <span style="font-size:0.72rem;color:#475569;margin-left:auto;">${ts}</span>
    </div>
    <div class="ds-msg-ai-inner" id="ds-ai-inner-${Date.now()}">${html}</div>`;
  box.appendChild(outer); box.scrollTop = box.scrollHeight;
  return outer.querySelector('.ds-msg-ai-inner');
}

function updateDsStats() {
  document.getElementById('ds-token-count').innerHTML = `🔢 Tokens used: <strong style="color:#e2e8f0">${dsTotalTokens.toLocaleString()}</strong>`;
  document.getElementById('ds-msg-count').innerHTML = `💬 Messages: <strong style="color:#e2e8f0">${dsMsgCount}</strong>`;
}

// ── Send Chat ─────────────────────────────────────────────────
async function sendGroqChat() {
  if (dsStreaming) return;
  const inp = document.getElementById('ds-input');
  const message = inp.value.trim();
  if (!message) return;
  const doc_id = document.getElementById('ds-doc-select').value;

  inp.value = ''; inp.style.height = 'auto';
  appendDsUser(message);
  dsHistory.push({ role: 'user', content: message });
  dsMsgCount++;

  document.getElementById('ds-typing').style.display = 'block';
  document.getElementById('ds-send-btn').disabled = true;
  dsStreaming = true;

  try {
    const data = await api('POST', '/groq/chat', {
      message, document_id: doc_id || null, history: dsHistory.slice(-20)
    });
    document.getElementById('ds-typing').style.display = 'none';
    appendDsAi('<p>' + renderMarkdown(data.answer) + '</p>');
    dsHistory.push({ role: 'assistant', content: data.answer });
    dsTotalTokens += data.tokens_used || 0;
    dsMsgCount++;
    updateDsStats();
  } catch (e) {
    document.getElementById('ds-typing').style.display = 'none';
    appendDsAi(`<span style="color:red">Error: ${e.message}</span>`);
  } finally {
    dsStreaming = false;
    document.getElementById('ds-send-btn').disabled = false;
  }
}

// ── Explain Concept ───────────────────────────────────────────
async function sendGroqExplain() {
  const concept = document.getElementById('ds-concept-input').value.trim();
  if (!concept) return toast('Enter a concept to explain', 'error');
  const level = document.getElementById('ds-explain-level').value;
  const doc_id = document.getElementById('ds-doc-select').value;

  document.getElementById('ds-typing').style.display = 'block';
  appendDsUser(`Explain: "${concept}" (${level})`);

  try {
    const data = await api('POST', '/groq/explain', { concept, level, document_id: doc_id || null });
    document.getElementById('ds-typing').style.display = 'none';
    appendDsAi('<p>' + renderMarkdown(data.explanation) + '</p>');
    dsMsgCount += 2; updateDsStats();
  } catch (e) {
    document.getElementById('ds-typing').style.display = 'none';
    appendDsAi(`<span style="color:#ef4444">⚠️ ${e.message}</span>`);
  }
  document.getElementById('ds-concept-input').value = '';
}

// ── Clear Chat ────────────────────────────────────────────────
function clearGroqChat() {
  if (!confirm('Clear conversation history?')) return;
  dsHistory = []; dsTotalTokens = 0; dsMsgCount = 0; dsStreaming = false;
  updateDsStats();
  const box = document.getElementById('ds-chat-box');
  box.innerHTML = `
    <div class="ds-msg ds-msg-ai" style="background:linear-gradient(135deg,rgba(6,182,212,0.12),rgba(129,140,248,0.12));border:1px solid rgba(6,182,212,0.25);border-radius:14px;padding:16px 20px;max-width:90%;align-self:flex-start;font-size:0.9rem;line-height:1.6;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
        <span style="font-size:1.2rem;">🤖</span>
        <strong style="color:#06b6d4;">Groq AI Tutor</strong>
      </div>
      Conversation cleared. How can I help you study today?
    </div>`;
  document.getElementById('ds-typing').style.display = 'none';
  box.scrollTop = box.scrollHeight;
}