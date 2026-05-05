// ════════════════════════════════════════════════════════════
//  NOTES
// ════════════════════════════════════════════════════════════
let allNotes = [];

async function loadNotes() {
  try {
    const d = await api('GET', '/notes/');
    allNotes = d.notes;
    renderNotesList(allNotes);
  } catch(e) { console.error("Failed to load notes", e); }
}

function renderNotesList(notesToRender) {
  const el = document.getElementById('notes-list');
  if(!notesToRender.length) { el.innerHTML = '<p class="text-muted">No notes found.</p>'; return; }
  el.innerHTML = notesToRender.map(n => `
    <div class="doc-item" style="cursor:pointer;" onclick="openNote('${n._id}')">
      <div class="doc-icon" onclick="event.stopPropagation(); togglePin('${n._id}', ${!n.is_pinned})" style="cursor:pointer; color:${n.is_pinned?'var(--primary)':'var(--text-muted)'}">
        ${n.is_pinned ? '📌' : '📍'}
      </div>
      <div class="doc-meta">
        <div class="doc-name">${n.title || 'Untitled'}</div>
        <div class="doc-date">${new Date(n.updated_at).toLocaleDateString()}</div>
      </div>
      <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteNote('${n._id}')">🗑</button>
    </div>
  `).join('');
}

function filterNotes() {
  const q = document.getElementById('notes-search').value.toLowerCase();
  const filtered = allNotes.filter(n => (n.title||'').toLowerCase().includes(q) || (n.content||'').toLowerCase().includes(q));
  renderNotesList(filtered);
}

function populateNotesDocSelect() {
  const sel = document.getElementById('note-doc-select');
  if (!sel) return;
  sel.innerHTML = '<option value="">— Attach a Document (Optional) —</option>' + documents.map(d=>`<option value="${d._id}">${d.original_name}</option>`).join('');
}

function newNote() {
  document.getElementById('note-id').value = '';
  document.getElementById('note-title').value = '';
  document.getElementById('note-content').value = '';
  document.getElementById('note-doc-select').value = '';
}

function openNote(id) {
  const n = allNotes.find(x => x._id === id);
  if(!n) return;
  document.getElementById('note-id').value = n._id;
  document.getElementById('note-title').value = n.title;
  document.getElementById('note-content').value = n.content;
  document.getElementById('note-doc-select').value = n.document_id || '';
  toggleNoteDocView();
}

function toggleNoteDocView() {
  const sel = document.getElementById('note-doc-select').value;
  document.getElementById('note-view-doc-btn').style.display = sel ? 'inline-block' : 'none';
}

async function uploadNoteDoc(input) {
  const file = input.files[0]; 
  if (!file) return;
  const fd = new FormData(); 
  fd.append('file', file);
  toast('Uploading document...', 'info');
  try {
    const d = await api('POST', '/learning/upload', fd, true);
    toast('Document uploaded successfully!', 'success');
    await loadDocuments(); // Reload global documents list
    populateNotesDocSelect(); // Refreshes the dropdown
    document.getElementById('note-doc-select').value = d.document._id;
    toggleNoteDocView();
  } catch(e) { toast(e.message, 'error'); }
  input.value = ''; // reset
}

async function viewNoteDoc() {
  const docId = document.getElementById('note-doc-select').value;
  if(!docId) return;
  toast('Loading document...', 'info');
  try {
    const d = await api('GET', '/learning/document/'+docId+'/content');
    document.getElementById('doc-view-title').textContent = d.original_name;
    document.getElementById('doc-view-content').textContent = d.content_text || 'No text content available.';
    document.getElementById('doc-view-modal').style.display = 'flex';
  } catch(e) { toast(e.message, 'error'); }
}

async function saveNote() {
  const id = document.getElementById('note-id').value;
  const title = document.getElementById('note-title').value.trim();
  const content = document.getElementById('note-content').value.trim();
  const document_id = document.getElementById('note-doc-select').value;
  
  if(!title || !content) return toast('Title and content required', 'error');
  
  const payload = {title, content, document_id};
  
  try {
    if(id) {
      await api('PUT', '/notes/'+id, payload);
      toast('Note updated', 'success');
    } else {
      const d = await api('POST', '/notes/', payload);
      document.getElementById('note-id').value = d.note._id;
      toast('Note created', 'success');
    }
    await loadNotes();
  } catch(e) { toast(e.message, 'error'); }
}

async function deleteNote(id) {
  if(!confirm('Delete this note?')) return;
  try {
    await api('DELETE', '/notes/'+id);
    toast('Note deleted', 'success');
    if(document.getElementById('note-id').value === id) newNote();
    await loadNotes();
  } catch(e) { toast(e.message, 'error'); }
}

async function togglePin(id, is_pinned) {
  try {
    await api('PATCH', '/notes/'+id+'/pin', {is_pinned});
    await loadNotes();
  } catch(e) { toast(e.message, 'error'); }
}

async function improveNoteWithAI() {
  const content = document.getElementById('note-content').value.trim();
  if(!content) return toast('Write some content first to improve it', 'error');
  
  toast('AI is improving your notes...', 'info');
  const btn = document.querySelector('button[onclick="improveNoteWithAI()"]');
  btn.disabled = true;
  btn.textContent = '✨ Improving...';
  
  try {
    const d = await api('POST', '/notes/improve', {content});
    // Show in suggestion card instead of directly updating
    document.getElementById('ai-suggestion-content').textContent = d.improved_content;
    document.getElementById('ai-suggestion-card').style.display = 'block';
    toast(`Notes improved using ${d.provider}`, 'success');
  } catch(e) {
    toast(e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '✨ AI Improve';
  }
}

function dismissAiSuggestion() {
  document.getElementById('ai-suggestion-card').style.display = 'none';
}

function applyAiSuggestion() {
  const suggestion = document.getElementById('ai-suggestion-content').textContent;
  if(suggestion) {
    document.getElementById('note-content').value = suggestion;
    dismissAiSuggestion();
    toast('Note updated with AI suggestion!', 'success');
  }
}

function copyAiSuggestion() {
  const suggestion = document.getElementById('ai-suggestion-content').textContent;
  navigator.clipboard.writeText(suggestion).then(()=>toast('AI Suggestion copied!', 'success'));
}

function copyNoteToClipboard() {
  const text = document.getElementById('note-content').value;
  navigator.clipboard.writeText(text).then(()=>toast('Copied to clipboard!','success'));
}
