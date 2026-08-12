/* ═══════════════════════════════════════════════════════════
   AEGIS Frontend Application
   ═══════════════════════════════════════════════════════════ */

const API = 'http://127.0.0.1:7430/api';

/* ── State ─────────────────────────────────────────────────── */
let _collections   = [];
let _pendingFiles  = [];
let _ingestPoll    = null;
let _currentDoc    = null;          // doc being viewed in panel
let _entityType    = 'ALL';
let _annFilter     = 'all';
let _activeModel   = null;
let _lastDocs      = [];    // most recently rendered documents table rows, for lookups by id

/* ── Graph engine state ────────────────────────────────────── */
const G = {
  nodes: [], edges: [], filter: '',
  offsetX: 0, offsetY: 0, scale: 1,
  drag: null, animFrame: null,
  canvas: null, ctx: null,
};

/* ── Utils ─────────────────────────────────────────────────── */
const $   = id => document.getElementById(id);
const esc = s  => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const ts  = s  => {
  const d = Date.now()/1000 - s;
  if (d < 60)    return 'just now';
  if (d < 3600)  return `${Math.floor(d/60)}m ago`;
  if (d < 86400) return `${Math.floor(d/3600)}h ago`;
  return new Date(s * 1000).toLocaleDateString();
};

async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return r.json();
}

function statusBadge(s) {
  const cls = { indexed:'badge-indexed', pending:'badge-pending',
                processing:'badge-processing', error:'badge-error' };
  return `<span class="badge ${cls[s]||'badge-type'}">${esc(s)}</span>`;
}
function typeBadge(t) {
  return `<span class="badge badge-type">${esc(t||'document')}</span>`;
}

/* ═══════════════════════════════════════════════════════════
   VIEW ROUTER
   ═══════════════════════════════════════════════════════════ */
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(a => a.classList.remove('active'));
  $(`view-${name}`)?.classList.add('active');
  document.querySelector(`[data-view="${name}"]`)?.classList.add('active');
  ({
    collections:  loadCollections,
    documents:    loadDocuments,
    search:       populateSearchCollections,
    ai:           populateAICollections,
    entities:     loadEntities,
    graph:        initGraph,
    annotations:  loadAnnotations,
    coverage:     loadCoverage,
    audit:        loadAuditLog,
    settings:     loadSettings,
  })[name]?.();
}

/* ═══════════════════════════════════════════════════════════
   AI STATUS
   ═══════════════════════════════════════════════════════════ */
async function checkAIStatus() {
  try {
    const s = await api('/ai/status');
    const dot = $('ollama-dot'), lbl = $('ollama-label');
    if (s.ollama_online) {
      dot.className = 'status-dot green';
      lbl.textContent = s.llm_ready ? 'LLM ready' : 'Ollama online';
    } else {
      dot.className = 'status-dot red';
      lbl.textContent = 'Ollama offline';
    }
  } catch {
    $('ollama-dot').className = 'status-dot red';
    $('ollama-label').textContent = 'Backend offline';
  }
}

/* ═══════════════════════════════════════════════════════════
   COLLECTIONS
   ═══════════════════════════════════════════════════════════ */
async function loadCollections() {
  try {
    _collections = await api('/collections');
    renderCollections();
    populateAllSelects();
  } catch (e) { console.error(e); }
}

function renderCollections() {
  const grid = $('collections-grid');
  if (!_collections.length) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
      No collections yet.<p>Create one to start importing documents.</p></div>`;
    return;
  }
  grid.innerHTML = _collections.map(c => `
    <div class="collection-card">
      <h3>${esc(c.name)}</h3>
      <div class="cc-desc">${esc(c.description || 'No description')}</div>
      <div class="cc-stats">
        <div class="cc-stat"><strong>${c.doc_count}</strong>documents</div>
        <div class="cc-stat" style="margin-left:auto;font-size:11px">${ts(c.created_at)}</div>
      </div>
      <div class="cc-actions">
        <button class="btn-secondary btn-sm" onclick="openCollection('${esc(c.id)}')">Open</button>
        <button class="btn-secondary btn-sm" onclick="exportReport('${esc(c.id)}')">Export report</button>
        <button class="btn-danger btn-sm" onclick="deleteCollection('${esc(c.id)}',event)">Delete</button>
      </div>
    </div>
  `).join('');
}

function openCollection(id) {
  $('doc-collection-filter').value = id;
  showView('documents');
}

async function exportReport(collId) {
  window.open(`${API}/reports/collection/${collId}`, '_blank');
}

async function deleteCollection(id, e) {
  e.stopPropagation();
  const c = _collections.find(x => x.id === id);
  if (!confirm(`Delete collection "${c?.name}" and all its documents?\nThis cannot be undone.`)) return;
  await api(`/collections/${id}`, { method: 'DELETE' });
  loadCollections();
}

function openNewCollectionModal() {
  $('modal-title').textContent = 'New collection';
  $('modal-body').innerHTML = `
    <label>Name <input type="text" id="nc-name" placeholder="e.g. Siemens S7-1500 Assessment"></label>
    <label>Description <textarea id="nc-desc" placeholder="Optional context…"></textarea></label>
    <label>Vendor / manufacturer country (optional - improves cultural coverage checks)
      <input type="text" id="nc-vendor-country" placeholder="e.g. Germany, Japan, China…"></label>
    <label>Bias policy
      <select id="nc-bias-policy">
        <option value="off">Off</option>
        <option value="suggestive" selected>Suggestive</option>
        <option value="proactive">Proactive</option>
      </select></label>
    <div class="modal-actions">
      <button class="btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn-primary" onclick="createCollection()">Create</button>
    </div>`;
  $('modal-overlay').style.display = 'flex';
  setTimeout(() => $('nc-name').focus(), 50);
}

async function createCollection() {
  const name = $('nc-name').value.trim();
  if (!name) { $('nc-name').focus(); return; }
  try {
    await api('/collections', { method:'POST',
      body: JSON.stringify({
        name, description: $('nc-desc').value,
        vendor_country: $('nc-vendor-country').value.trim() || null,
        bias_policy: $('nc-bias-policy').value,
      }) });
    closeModal();
    loadCollections();
  } catch (e) { showToast('Error: ' + e.message, 'error'); }
}

function closeModal() { $('modal-overlay').style.display = 'none'; }

/* ── Read-only info modal (e.g. AI summaries) ─────────────── */
function showInfoModal(title, bodyHtml) {
  $('modal-title').textContent = title;
  $('modal-body').innerHTML = bodyHtml;
  $('modal-overlay').style.display = 'flex';
}

/* ── Toast notifications (replaces jarring native alert()) ── */
const TOAST_ICONS = { success: '✓', error: '✕', warn: '!', info: 'i' };
function showToast(message, type = 'info', duration = 4500) {
  const container = $('toast-container');
  if (!container) { console.log(`[${type}] ${message}`); return; }
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span class="toast-icon">${TOAST_ICONS[type] || TOAST_ICONS.info}</span><span class="toast-msg">${esc(message)}</span>`;
  const remove = () => {
    el.classList.add('leaving');
    setTimeout(() => el.remove(), 150);
  };
  el.addEventListener('click', remove);
  container.appendChild(el);
  setTimeout(remove, duration);
}

/* ═══════════════════════════════════════════════════════════
   SHARED SELECT POPULATION
   ═══════════════════════════════════════════════════════════ */
async function populateAllSelects() {
  if (!_collections.length) _collections = await api('/collections');
  const opts = [['','All collections'], ..._collections.map(c => [c.id, c.name])];
  const html  = opts.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('');
  ['doc-collection-filter','upload-collection-select','cve-collection-select',
   'search-collection','ai-collection-select','entities-collection',
   'graph-collection','ann-collection-filter','coverage-collection'].forEach(id => {
    const el = $(id);
    if (el) el.innerHTML = html;
  });
}
function populateSearchCollections() { populateAllSelects(); }
async function populateAICollections() {
  await populateAllSelects();
  refreshConversationList();
  showProactiveSuggestion();
}

async function showProactiveSuggestion() {
  try {
    const p = await api('/profile');
    const banner = $('ai-suggestion-banner');
    if (p.suggestion) {
      banner.textContent = p.suggestion;
      banner.style.display = 'block';
    } else {
      banner.style.display = 'none';
    }
  } catch { $('ai-suggestion-banner').style.display = 'none'; }
}

/* ═══════════════════════════════════════════════════════════
   DOCUMENTS
   ═══════════════════════════════════════════════════════════ */
async function loadDocuments() {
  const cid    = $('doc-collection-filter')?.value || '';
  const status = $('doc-status-filter')?.value || '';
  try {
    const [docs, countData] = await Promise.all([
      api(`/documents?collection_id=${cid}&status=${status}&limit=200`),
      api(`/documents/count?collection_id=${cid}&status=${status}`),
    ]);
    renderDocuments(docs);
    const footer = $('doc-count-footer');
    if (footer) {
      const showing = docs.length;
      const total   = countData.total;
      footer.textContent = showing < total
        ? `Showing ${showing.toLocaleString()} of ${total.toLocaleString()} documents`
        : `${total.toLocaleString()} document${total !== 1 ? 's' : ''} total`;
    }
  } catch (e) { console.error(e); }
}

function renderDocuments(docs) {
  _lastDocs = docs;
  const tbody  = $('documents-tbody');
  const collMap = Object.fromEntries(_collections.map(c => [c.id, c.name]));
  if (!docs.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:40px">No documents found. Import files to get started.</td></tr>';
    return;
  }
  tbody.innerHTML = docs.map(d => `
    <tr>
      <td><a style="cursor:pointer;color:var(--accent)" onclick="openDocPanel('${esc(d.id)}')">${esc(d.filename)}</a></td>
      <td style="color:var(--muted)">${esc(collMap[d.collection_id] || d.collection_id.slice(0,8))}</td>
      <td>${typeBadge(d.doc_type)}</td>
      <td style="color:var(--muted)">${d.page_count || 0}</td>
      <td style="color:var(--muted)">${(d.word_count || 0).toLocaleString()}</td>
      <td>${statusBadge(d.ingest_status)}${d.ingest_error
        ? `<span title="${esc(d.ingest_error)}" style="color:var(--red);cursor:help;margin-left:4px">!</span>` : ''}</td>
      <td style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn-secondary btn-sm" onclick="openDocPanel('${esc(d.id)}')">View</button>
        <button class="btn-secondary btn-sm" onclick="summariseDoc('${esc(d.id)}')">Summarise</button>
        <button class="btn-danger btn-sm" onclick="deleteDoc('${esc(d.id)}')">✕</button>
      </td>
    </tr>`).join('');
}

/* ── File upload ─────────────────────────────────────────── */
function uploadFiles() {
  _pendingFiles = Array.from($('file-upload').files);
  if (!_pendingFiles.length) return;
  populateAllSelects();
  const cid = $('doc-collection-filter').value;
  if (cid) $('upload-collection-select').value = cid;
  $('upload-bar-label').textContent = `${_pendingFiles.length} file(s) ready - upload to:`;
  $('upload-collection-bar').style.display = 'flex';
}

async function confirmUpload() {
  const cid = $('upload-collection-select').value;
  if (!cid) { showToast('Please select a collection.', 'warn'); return; }
  $('upload-collection-bar').style.display = 'none';
  const prog = $('ingest-progress');
  prog.style.display = 'flex';
  $('progress-label').textContent = `Uploading ${_pendingFiles.length} file(s)…`;

  const fd = new FormData();
  fd.append('collection_id', cid);
  _pendingFiles.forEach(f => fd.append('files', f));
  try {
    const r = await fetch(`${API}/documents/ingest`, { method:'POST', body: fd });
    const data = await r.json();
    $('progress-label').textContent = `Queued ${data.queued} file(s) for processing…`;
    $('progress-fill').style.width = '15%';
    pollIngestProgress(data.doc_ids);
  } catch (e) {
    prog.style.display = 'none';
    showToast('Upload failed: ' + e.message, 'error');
  }
  _pendingFiles = [];
  $('file-upload').value = '';
}

function cancelUpload() {
  _pendingFiles = [];
  $('file-upload').value = '';
  $('upload-collection-bar').style.display = 'none';
}

/* ── CVE JSON Import ─────────────────────────────────────── */
function openCVEImport() {
  const file = $('cve-file-input').files[0];
  if (!file) return;
  populateAllSelects();
  const cid = $('doc-collection-filter').value;
  if (cid) $('cve-collection-select').value = cid;
  $('upload-collection-bar').style.display = 'none';
  $('cve-import-bar').style.display = 'flex';
}

function cancelCVEUpload() {
  $('cve-file-input').value = '';
  $('cve-import-bar').style.display = 'none';
}

async function confirmCVEUpload() {
  const cid  = $('cve-collection-select').value;
  const file = $('cve-file-input').files[0];
  if (!cid)  { showToast('Please select a collection.', 'warn'); return; }
  if (!file) { showToast('No file selected.', 'warn'); return; }

  $('cve-import-bar').style.display = 'none';
  const prog = $('cve-progress');
  prog.style.display = 'flex';
  $('cve-progress-fill').style.width = '5%';
  $('cve-progress-label').textContent = `Uploading ${file.name} (${(file.size/1048576).toFixed(1)} MB)…`;

  const fd = new FormData();
  fd.append('collection_id', cid);
  fd.append('file', file);
  try {
    const r    = await fetch(`${API}/cve/import`, { method: 'POST', body: fd });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || JSON.stringify(data));
    $('cve-progress-fill').style.width = '15%';
    $('cve-progress-label').textContent = `CVE import running in background - ${data.file_size_mb} MB queued…`;
    pollCVEProgress(cid);
  } catch (e) {
    prog.style.display = 'none';
    showToast('CVE import failed: ' + e.message, 'error');
  }
  $('cve-file-input').value = '';
}

function pollCVEProgress(cid) {
  let lastCount = 0;
  let stableRounds = 0;
  // Poll every 10s; declare done only after 3 minutes of no change (18 rounds)
  const POLL_MS     = 10000;
  const STABLE_DONE = 18;
  const poll = setInterval(async () => {
    try {
      const s = await fetch(`${API}/cve/stats?collection_id=${cid}`).then(r => r.json());
      const n = s.cve_documents || 0;
      const pct = Math.min(95, 15 + Math.round(n / 80));
      $('cve-progress-fill').style.width = pct + '%';
      $('cve-progress-label').textContent =
        `Importing CVEs… ${n.toLocaleString()} indexed` +
        (stableRounds > 0 ? ` (no change for ${Math.round(stableRounds * POLL_MS / 60000)} min)` : '');
      if (n === lastCount) { stableRounds++; } else { stableRounds = 0; lastCount = n; }
      if (stableRounds >= STABLE_DONE && n > 0) {
        clearInterval(poll);
        $('cve-progress-fill').style.width = '100%';
        $('cve-progress-label').textContent = `Done - ${n.toLocaleString()} CVEs indexed`;
        setTimeout(() => { $('cve-progress').style.display = 'none'; loadDocuments(); }, 3000);
      }
    } catch { clearInterval(poll); }
  }, POLL_MS);
}

function pollIngestProgress(docIds) {
  if (_ingestPoll) clearInterval(_ingestPoll);
  const total = docIds.length;
  _ingestPoll = setInterval(async () => {
    try {
      const docs = await api(`/documents?limit=500`);
      const tracked = docs.filter(d => docIds.includes(d.id));
      const done = tracked.filter(d => ['indexed','error'].includes(d.ingest_status)).length;
      const pct = Math.max(15, Math.round((done / total) * 100));
      $('progress-fill').style.width = pct + '%';
      $('progress-label').textContent = `Processing… ${done}/${total} complete`;
      if (done >= total) {
        clearInterval(_ingestPoll);
        $('progress-fill').style.width = '100%';
        $('progress-label').textContent = `Done - ${done} document(s) indexed`;
        setTimeout(() => { $('ingest-progress').style.display = 'none'; loadDocuments(); }, 2000);
      }
    } catch { clearInterval(_ingestPoll); }
  }, 2500);
}

async function deleteDoc(id) {
  if (!confirm('Remove this document from the index?')) return;
  await api(`/documents/${id}`, { method:'DELETE' });
  loadDocuments();
}

function toggleDeleteAll() {
  const cid = $('doc-collection-filter')?.value || '';
  const btn = $('btn-delete-all-docs');
  if (btn) btn.style.display = cid ? 'inline-block' : 'none';
}

async function deleteAllDocs() {
  const cid = $('doc-collection-filter')?.value;
  if (!cid) return;
  const col = _collections.find(c => c.id === cid);
  const countData = await api(`/documents/count?collection_id=${cid}`).catch(() => ({ total: '?' }));
  if (!confirm(`Delete all ${countData.total} documents in "${col?.name || cid}"?\n\nThis removes all files, chunks and entities. The collection itself is kept.\n\nThis cannot be undone.`)) return;
  try {
    const r = await api(`/documents?collection_id=${cid}`, { method: 'DELETE' });
    loadDocuments();
    showToast(`Deleted ${r.deleted} document(s) from "${col?.name || cid}".`, 'success');
  } catch (e) {
    showToast('Delete failed: ' + e.message, 'error');
  }
}

async function summariseDoc(docId) {
  const filename = _lastDocs.find(d => d.id === docId)?.filename;
  showInfoModal(filename ? `Summary - ${filename}` : 'Document summary', `
    <div class="modal-loading"><span class="spinner"></span> Generating summary… this can take up to a minute on CPU.</div>`);
  try {
    const r = await api(`/ai/summarise/${docId}`, { method:'POST', body:'{}' });
    $('modal-body').innerHTML = `
      <div class="summary-text" id="summary-text">${esc(r.summary)}</div>
      <div class="modal-actions">
        <button class="btn-secondary btn-sm" onclick="copySummaryText(this)">Copy</button>
        <button class="btn-primary btn-sm" onclick="closeModal()">Close</button>
      </div>`;
    loadDocuments();
  } catch (e) {
    $('modal-body').innerHTML = `
      <div class="modal-error">Summarisation failed: ${esc(e.message)}</div>
      <div class="modal-actions"><button class="btn-primary btn-sm" onclick="closeModal()">Close</button></div>`;
  }
}

function copySummaryText(btn) {
  const text = $('summary-text')?.textContent || '';
  navigator.clipboard?.writeText(text).then(() => {
    const orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  }).catch(() => showToast('Could not copy to clipboard', 'error'));
}

/* ═══════════════════════════════════════════════════════════
   DOCUMENT PANEL
   ═══════════════════════════════════════════════════════════ */
async function openDocPanel(docId) {
  _currentDoc = docId;
  $('doc-panel').style.display = 'flex';
  $('doc-tab-chunks').innerHTML = '<div style="color:var(--muted);padding:20px">Loading…</div>';
  $('doc-tab-entities').innerHTML = '';
  $('doc-tab-anns').innerHTML = '';
  switchDocTab('chunks', document.querySelector('.doc-tab'));

  try {
    const doc = await api(`/documents/${docId}`);
    $('doc-panel-title').textContent = doc.filename;
    $('doc-panel-meta').innerHTML = `
      ${typeBadge(doc.doc_type)} ${statusBadge(doc.ingest_status)}
      <span>${doc.page_count || 0} pages</span>
      <span>${(doc.word_count || 0).toLocaleString()} words</span>
      ${doc.manufacturer ? `<span>Mfr: ${esc(doc.manufacturer)}</span>` : ''}
      ${doc.part_number  ? `<span>Part: ${esc(doc.part_number)}</span>`  : ''}
      <button class="btn-secondary btn-sm" onclick="showAnnBar()" style="margin-left:auto">+ Annotate</button>`;

    // Chunks tab
    const summaryHtml = doc.summary
      ? `<div class="chunk-card" style="border-color:rgba(88,166,255,.35)">
           <div class="chunk-num">AI Summary</div>${esc(doc.summary)}</div>` : '';
    const chunks = await api(`/documents/${docId}/chunks?limit=40`);
    $('doc-tab-chunks').innerHTML = summaryHtml + chunks.map(c => `
      <div class="chunk-card">
        <div class="chunk-num">Chunk ${c.chunk_index + 1} · page ${c.page_number}</div>
        ${esc(c.text)}
        <button class="btn-secondary btn-sm chunk-ann-btn"
          onclick="showAnnBar('${esc(c.id)}')">+ Note</button>
      </div>`).join('');

    // Entities tab
    const ents = await api(`/documents/${docId}/entities`);
    $('doc-tab-entities').innerHTML = ents.length
      ? ents.map(e => `
          <div class="entity-row">
            <span class="badge badge-type">${esc(e.entity_type)}</span>
            <span class="entity-value">${esc(e.value)}</span>
            <button class="btn-secondary btn-sm entity-freq"
              onclick="searchForEntity('${esc(e.value)}')">Search</button>
          </div>`).join('')
      : '<div style="color:var(--muted);padding:20px">No entities extracted yet.</div>';

    // Annotations tab
    await refreshDocAnnotations(docId);
  } catch (e) {
    $('doc-tab-chunks').textContent = 'Error: ' + e.message;
  }
}

function _renderAnnotationBody(a) {
  if (a.kind === 'architecture_insight') {
    try {
      const r = JSON.parse(a.note);
      const line = (label, arr) => arr && arr.length ? `<div><strong>${label}:</strong> ${arr.map(esc).join(', ')}</div>` : '';
      return line('Firmware modules', r.firmware_modules) + line('Comm interfaces', r.comm_interfaces) +
        line('Trust domains', r.trust_domains) + line('Attack surfaces', r.attack_surfaces) +
        line('Dependencies', r.external_dependencies) || '<em style="color:var(--muted)">No architectural signals detected.</em>';
    } catch { return esc(a.note || '-'); }
  }
  if (a.kind === 'schematic_graph') {
    try {
      const r = JSON.parse(a.note);
      return `<div style="color:var(--muted);font-size:12px;margin-bottom:6px">${esc(r.caveat || '')}</div>` +
        `<div><strong>${(r.labels||[]).length}</strong> OCR label(s) detected, ` +
        `<strong>${(r.connections||[]).length}</strong> candidate connection(s):</div>` +
        (r.connections||[]).slice(0, 25).map(c => `<div>${esc(c.source)} - ${esc(c.target)} <span style="color:var(--muted)">(${esc(c.relation)}, conf ${Math.round((c.confidence||0)*100)}%)</span></div>`).join('');
    } catch { return esc(a.note || '-'); }
  }
  return esc(a.note || '-');
}

async function refreshDocAnnotations(docId) {
  const anns = await api(`/annotations?doc_id=${docId}`);
  $('doc-tab-anns').innerHTML = anns.length
    ? anns.map(a => `
        <div class="chunk-card">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
            <span class="ann-kind-badge kind-${esc(a.kind)}">${esc(a.kind)}</span>
            <span style="color:var(--muted);font-size:11px;margin-left:auto">${ts(a.created_at)}</span>
          </div>
          <div style="font-size:13px">${_renderAnnotationBody(a)}</div>
          <button class="btn-danger btn-sm" style="margin-top:8px"
            onclick="deleteAnnotation('${esc(a.id)}','${esc(docId)}')">Delete</button>
        </div>`).join('')
    : '<div style="color:var(--muted);padding:20px">No annotations yet. Use the + Annotate button.</div>';
}

function switchDocTab(tab, btn) {
  ['chunks','entities','anns'].forEach(t => {
    $(`doc-tab-${t}`).style.display = t === tab ? 'flex' : 'none';
  });
  document.querySelectorAll('.doc-tab').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
}

function closeDocPanel() {
  $('doc-panel').style.display = 'none';
  _currentDoc = null;
  hideAnnBar();
}

/* ── Annotation add bar in panel ─────────────────────────── */
let _pendingChunkId = null;

function showAnnBar(chunkId) {
  _pendingChunkId = chunkId || null;
  $('ann-add-bar').style.display = 'flex';
  $('ann-note-input').focus();
}

function hideAnnBar() {
  $('ann-add-bar').style.display = 'none';
  $('ann-note-input').value = '';
  _pendingChunkId = null;
}

async function submitAnnotation() {
  if (!_currentDoc) return;
  const note = $('ann-note-input').value.trim();
  const kind = $('ann-kind-select').value;
  try {
    await api('/annotations', {
      method: 'POST',
      body: JSON.stringify({
        doc_id:   _currentDoc,
        chunk_id: _pendingChunkId,
        kind,
        note,
      }),
    });
    hideAnnBar();
    await refreshDocAnnotations(_currentDoc);
    switchDocTab('anns', document.querySelectorAll('.doc-tab')[2]);
  } catch (e) { showToast('Failed to save annotation: ' + e.message, 'error'); }
}

async function deleteAnnotation(annId, docId) {
  if (!confirm('Delete this annotation?')) return;
  await api(`/annotations/${annId}`, { method:'DELETE' });
  await refreshDocAnnotations(docId);
}

/* ═══════════════════════════════════════════════════════════
   SEARCH
   ═══════════════════════════════════════════════════════════ */
async function doSearch() {
  const query = $('search-input').value.trim();
  if (!query) return;
  const t0 = Date.now();
  $('search-meta').textContent = 'Searching…';
  $('search-results').innerHTML = '';
  try {
    const hits = await api('/search', {
      method: 'POST',
      body: JSON.stringify({
        query,
        collection_id: $('search-collection').value || null,
        mode:  $('search-mode').value,
        limit: 25,
      }),
    });
    $('search-meta').textContent = `${hits.length} result(s) - ${Date.now()-t0}ms · ${$('search-mode').value}`;
    const cvePattern = /^CVE-\d{4}-\d{4,7}$/i;
    const emptyMsg = cvePattern.test(query)
      ? `<div class="empty-state"><strong>${esc(query)}</strong> is not in the indexed dataset.<br><span style="color:var(--muted);font-size:13px">The CVE may not have been included in the imported JSON file, or the import may still be in progress.</span></div>`
      : '<div class="empty-state">No results. Try different keywords or switch search mode.</div>';
    $('search-results').innerHTML = hits.length
      ? hits.map(h => `
          <div class="search-hit" onclick="openDocPanel('${esc(h.doc_id)}')">
            <div class="hit-meta">
              <span class="hit-doc">${esc(h.doc_title || h.filename)}</span>
              <span class="hit-page">p.${h.page_number || 1}</span>
              <span class="hit-source-badge src-${esc(h.source)}">${esc(h.source)}</span>
              <span class="hit-score">${(h.score || 0).toFixed(4)}</span>
            </div>
            <div class="hit-text">${esc(h.text)}</div>
          </div>`).join('')
      : emptyMsg;
  } catch (e) { $('search-meta').textContent = 'Error: ' + e.message; }
}

/* ═══════════════════════════════════════════════════════════
   AI / RAG - conversations, confidence, validation, coverage
   ═══════════════════════════════════════════════════════════ */
let _currentConversationId = null;

function _clearChatDOM() {
  $('ai-chat').innerHTML = '';
  $('ai-sources-panel').style.display = 'none';
  $('ai-confidence-badge').style.display = 'none';
  $('ai-coverage-label').style.display = 'none';
}

function clearAIChat() {
  _clearChatDOM();
  _currentConversationId = null;
  $('ai-conversation-select').value = '';
}

async function refreshConversationList() {
  try {
    const cid = $('ai-collection-select').value || '';
    const convs = await api(`/conversations?collection_id=${cid}&limit=50`);
    const sel = $('ai-conversation-select');
    sel.innerHTML = '<option value="">New conversation</option>' + convs.map(c =>
      `<option value="${esc(c.id)}" ${c.id === _currentConversationId ? 'selected' : ''}>
        ${esc(c.title)} (${c.message_count || 0} msgs · ${ts(c.updated_at)})
      </option>`).join('');
  } catch (e) { console.error(e); }
}

async function loadConversationSelected() {
  const id = $('ai-conversation-select').value;
  if (!id) { clearAIChat(); return; }
  _currentConversationId = id;
  try {
    const conv = await api(`/conversations/${id}`);
    _clearChatDOM();
    (conv.messages || []).forEach(m => {
      const div = document.createElement('div');
      div.className = `ai-message ${m.role === 'user' ? 'user' : 'assistant'}`;
      div.textContent = m.content;
      $('ai-chat').appendChild(div);
    });
    $('ai-chat').scrollTop = $('ai-chat').scrollHeight;
  } catch (e) { showToast('Failed to load conversation: ' + e.message, 'error'); }
}

function renderConfidenceBadge(conf) {
  const badge = $('ai-confidence-badge');
  const cls = { high:'conf-high', 'medium-high':'conf-medium-high', medium:'conf-medium',
                low:'conf-low', insufficient:'conf-insufficient' }[conf.level] || 'conf-medium';
  badge.className = 'confidence-badge ' + cls;
  badge.innerHTML = `Confidence: <strong>${esc(conf.level)}</strong> (${Math.round((conf.score||0)*100)}%) ` +
    `· ${conf.distinct_sources} source document(s)` +
    (conf.reason ? ` <span class="conf-reason">- ${esc(conf.reason)}</span>` : '');
  badge.style.display = 'block';
}

function renderCoverageLabel(coverage) {
  const el = $('ai-coverage-label');
  const parts = Object.entries(coverage).map(([lang, pct]) => `${esc(lang)} ${pct}%`).join(' / ');
  el.textContent = `Source language coverage for this answer: ${parts}`;
  el.style.display = 'block';
}

function renderValidatedAnswer(el, validation) {
  const statusClass = { known: 'claim-known', inferred: 'claim-inferred', uncertain: 'claim-uncertain' };
  el.innerHTML = (validation.claims || []).map(c =>
    `<span class="${statusClass[c.status] || ''}" title="${esc(c.status)} - lexical overlap with sources: ${Math.round((c.overlap||0)*100)}%">${esc(c.text)}</span>`
  ).join(' ');
  const summary = document.createElement('div');
  summary.className = 'validation-summary';
  summary.innerHTML =
    `<span class="claim-known">Known</span> · <span class="claim-inferred">Inferred</span> · <span class="claim-uncertain">Uncertain</span>` +
    ` - verified ${Math.round((validation.verified_ratio||0)*100)}%, ${validation.uncertain_count||0} unverified statement(s)` +
    (validation.needs_more_data ? ' · <strong>consider loading more source data</strong>' : '');
  el.after(summary);
}

async function sendAIQuery() {
  const question = $('ai-input').value.trim();
  if (!question) return;
  $('ai-input').value = '';
  const chat = $('ai-chat');
  chat.innerHTML += `<div class="ai-message user">${esc(question)}</div>`;

  const msgEl = document.createElement('div');
  msgEl.className = 'ai-message assistant streaming';
  chat.appendChild(msgEl);
  chat.scrollTop = chat.scrollHeight;

  $('ai-sources-panel').style.display = 'none';
  $('ai-sources-list').innerHTML = '';
  $('ai-confidence-badge').style.display = 'none';
  $('ai-coverage-label').style.display = 'none';

  // Show a warning if no tokens arrive within 30s (LLM is slow on CPU)
  let firstToken = false;
  const slowWarn = document.createElement('span');
  slowWarn.className = 'ai-slow-warn';
  slowWarn.style.display = 'none';
  slowWarn.textContent = 'LLM is generating on CPU - first response takes ~2 min, please wait…';
  msgEl.after(slowWarn);
  const slowTimer = setTimeout(() => {
    if (!firstToken) slowWarn.style.display = 'block';
  }, 30000);

  try {
    const res = await fetch(`${API}/ai/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        collection_id: $('ai-collection-select').value || null,
        model: _activeModel || undefined,
        max_chunks: 4,
        conversation_id: _currentConversationId || null,
      }),
    });
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const evt = JSON.parse(line.slice(6));
          if (evt.type === 'meta') {
            const isNew = _currentConversationId !== evt.data.conversation_id;
            _currentConversationId = evt.data.conversation_id;
            if (isNew) refreshConversationList();
          } else if (evt.type === 'sources') {
            renderSources(evt.data);
          } else if (evt.type === 'confidence') {
            renderConfidenceBadge(evt.data);
          } else if (evt.type === 'coverage') {
            renderCoverageLabel(evt.data);
          } else if (evt.type === 'token') {
            if (!firstToken) { firstToken = true; clearTimeout(slowTimer); slowWarn.style.display = 'none'; }
            msgEl.textContent += evt.data;
            chat.scrollTop = chat.scrollHeight;
          } else if (evt.type === 'validation') {
            renderValidatedAnswer(msgEl, evt.data);
            chat.scrollTop = chat.scrollHeight;
          } else if (evt.type === 'done') {
            msgEl.classList.remove('streaming');
            slowWarn.remove();
          } else if (evt.type === 'error') {
            msgEl.classList.remove('streaming');
            msgEl.textContent = evt.data;
            msgEl.style.color = 'var(--red)';
            slowWarn.remove();
          }
        } catch {}
      }
    }
    msgEl.classList.remove('streaming');
    clearTimeout(slowTimer);
    slowWarn.remove();
  } catch (e) {
    clearTimeout(slowTimer);
    slowWarn.remove();
    msgEl.classList.remove('streaming');
    msgEl.textContent = 'Connection error: ' + e.message;
    msgEl.style.color = 'var(--red)';
  }
}

function renderSources(sources) {
  if (!sources.length) return;
  $('ai-sources-panel').style.display = 'block';
  $('ai-sources-list').innerHTML = sources.map(s =>
    `<span class="source-chip" onclick="openDocPanel('${esc(s.doc_id)}')"
       title="Score: ${(s.score||0).toFixed(4)}">
      ${esc(s.doc_title)} p.${s.page_number}
    </span>`).join('');
}

/* ═══════════════════════════════════════════════════════════
   ENTITIES
   ═══════════════════════════════════════════════════════════ */
async function loadEntities() {
  const cid = $('entities-collection')?.value || '';
  try {
    const rows = await api(`/search/entities?collection_id=${cid}&limit=500`);
    const types = ['ALL', ...new Set(rows.map(r => r.entity_type))].sort();

    $('entity-tabs').innerHTML = types.map(t =>
      `<button class="tab-btn ${t === _entityType ? 'active' : ''}"
        onclick="setEntityType('${esc(t)}')">${esc(t)}</button>`).join('');

    const filtered = _entityType === 'ALL' ? rows : rows.filter(r => r.entity_type === _entityType);
    $('entities-list').innerHTML = filtered.length
      ? filtered.map(r => `
          <div class="entity-row">
            <span class="badge badge-type">${esc(r.entity_type)}</span>
            <span class="entity-value">${esc(r.value)}</span>
            <span class="entity-freq">${r.freq} mention(s)</span>
            <button class="btn-secondary btn-sm" onclick="searchForEntity('${esc(r.value)}')">Search</button>
          </div>`).join('')
      : '<div class="empty-state">No entities yet. Index some documents first.</div>';
  } catch (e) { console.error(e); }
}

function setEntityType(type) { _entityType = type; loadEntities(); }

function searchForEntity(value) {
  $('search-input').value = value;
  showView('search');
  doSearch();
}

/* ═══════════════════════════════════════════════════════════
   KNOWLEDGE GRAPH - force-directed canvas
   ═══════════════════════════════════════════════════════════ */
const NODE_COLORS = {
  COMPONENT:        '#2563eb',
  PART_NUMBER:      '#60a5fa',
  MANUFACTURER:     '#15803d',
  PROTOCOL:         '#7c3aed',
  CVE:              '#dc2626',
  FIRMWARE_VERSION: '#a16207',
  VULNERABILITY_CLASS: '#db2777',
};
const LEGEND_LABELS = [
  ['COMPONENT / PART', '#2563eb'],
  ['MANUFACTURER',     '#15803d'],
  ['PROTOCOL',         '#7c3aed'],
  ['CVE',              '#dc2626'],
  ['FIRMWARE',         '#a16207'],
];

async function initGraph() {
  populateAllSelects();
  renderLegend();
  G.canvas = $('graph-canvas');
  G.ctx    = G.canvas.getContext('2d');
  bindGraphEvents();
  await loadGraph();
}

function renderLegend() {
  $('graph-legend').innerHTML = LEGEND_LABELS.map(([l, c]) =>
    `<div class="legend-item"><div class="legend-dot" style="background:${c}"></div>${l}</div>`
  ).join('');
}

async function loadGraph() {
  const cid = $('graph-collection')?.value || '';
  $('graph-empty').style.display = 'none';
  try {
    const [nodes, edges] = await Promise.all([
      api(`/graph/nodes?collection_id=${cid}&limit=300`),
      api(`/graph/edges?collection_id=${cid}&limit=600`),
    ]);

    if (!nodes.length) {
      $('graph-empty').style.display = 'flex';
      return;
    }

    // Assign initial positions in a circle
    const cx = G.canvas.parentElement.clientWidth  / 2;
    const cy = G.canvas.parentElement.clientHeight / 2;
    const r  = Math.min(cx, cy) * 0.6;

    G.nodes = nodes.map((n, i) => ({
      ...n,
      x:  cx + r * Math.cos((2 * Math.PI * i) / nodes.length),
      y:  cy + r * Math.sin((2 * Math.PI * i) / nodes.length),
      vx: 0, vy: 0,
    }));
    G.edges  = edges;
    G.filter = '';
    G.offsetX = 0;
    G.offsetY = 0;
    G.scale   = 1;

    $('graph-filter').value = '';
    updateGraphStats();
    startGraphSim();
  } catch (e) { console.error(e); }
}

function updateGraphStats() {
  const visible = G.nodes.filter(n => nodeVisible(n)).length;
  $('graph-stats').textContent =
    `${visible} nodes · ${G.edges.length} edges`;
}

function nodeVisible(n) {
  if (!G.filter) return true;
  return n.label.toLowerCase().includes(G.filter.toLowerCase()) ||
         n.node_type.toLowerCase().includes(G.filter.toLowerCase());
}

function nodeColor(n) {
  return NODE_COLORS[n.node_type] || '#9c9389';
}

function nodeRadius(n) {
  const base = Math.min(6 + (n.mention_count || 1) * 0.4, 22);
  return nodeVisible(n) ? base : base * 0.4;
}

/* ── Force simulation ─────────────────────────────────────── */
function startGraphSim() {
  if (G.animFrame) cancelAnimationFrame(G.animFrame);
  let alpha = 1.0;

  function tick() {
    alpha *= 0.97;
    if (alpha < 0.005) alpha = 0;

    if (alpha > 0) applyForces(alpha);
    drawGraph();
    G.animFrame = requestAnimationFrame(tick);
  }
  G.animFrame = requestAnimationFrame(tick);
}

function resetGraphSim() {
  const cx = G.canvas.parentElement.clientWidth  / 2;
  const cy = G.canvas.parentElement.clientHeight / 2;
  const r  = Math.min(cx, cy) * 0.55;
  G.nodes.forEach((n, i) => {
    n.x  = cx + r * Math.cos((2 * Math.PI * i) / G.nodes.length);
    n.y  = cy + r * Math.sin((2 * Math.PI * i) / G.nodes.length);
    n.vx = 0; n.vy = 0;
  });
  G.offsetX = 0; G.offsetY = 0; G.scale = 1;
  startGraphSim();
}

function applyForces(alpha) {
  const nodeMap = Object.fromEntries(G.nodes.map(n => [n.id, n]));

  // Repulsion
  for (let i = 0; i < G.nodes.length; i++) {
    for (let j = i + 1; j < G.nodes.length; j++) {
      const a = G.nodes[i], b = G.nodes[j];
      const dx = b.x - a.x, dy = b.y - a.y;
      const dist = Math.sqrt(dx*dx + dy*dy) || 1;
      const force = (1800 / (dist * dist)) * alpha;
      const fx = (dx / dist) * force, fy = (dy / dist) * force;
      a.vx -= fx; a.vy -= fy;
      b.vx += fx; b.vy += fy;
    }
  }

  // Attraction along edges
  for (const e of G.edges) {
    const a = nodeMap[e.source], b = nodeMap[e.target];
    if (!a || !b) continue;
    const dx = b.x - a.x, dy = b.y - a.y;
    const dist = Math.sqrt(dx*dx + dy*dy) || 1;
    const target = 120;
    const force = (dist - target) * 0.03 * alpha;
    const fx = (dx / dist) * force, fy = (dy / dist) * force;
    a.vx += fx; a.vy += fy;
    b.vx -= fx; b.vy -= fy;
  }

  // Centre gravity
  const cx = G.canvas.width / 2, cy = G.canvas.height / 2;
  for (const n of G.nodes) {
    n.vx += (cx - n.x) * 0.008 * alpha;
    n.vy += (cy - n.y) * 0.008 * alpha;
  }

  // Integrate + dampen
  for (const n of G.nodes) {
    if (n === G.drag) continue;
    n.vx *= 0.7; n.vy *= 0.7;
    n.x  += n.vx; n.y  += n.vy;
  }
}

/* ── Draw ─────────────────────────────────────────────────── */
function drawGraph() {
  const canvas = G.canvas;
  const wrap   = canvas.parentElement;
  if (canvas.width !== wrap.clientWidth || canvas.height !== wrap.clientHeight) {
    canvas.width  = wrap.clientWidth;
    canvas.height = wrap.clientHeight;
  }
  const ctx = G.ctx;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.translate(G.offsetX, G.offsetY);
  ctx.scale(G.scale, G.scale);

  const nodeMap = Object.fromEntries(G.nodes.map(n => [n.id, n]));
  // App is always light-themed, so the graph canvas always uses the light-on-white palette.
  const edgeColor = 'rgba(0,0,0,0.08)';
  const textColor = '#5f5750';

  // Edges
  ctx.strokeStyle = edgeColor;
  ctx.lineWidth = 0.8;
  for (const e of G.edges) {
    const a = nodeMap[e.source], b = nodeMap[e.target];
    if (!a || !b) continue;
    if (!nodeVisible(a) || !nodeVisible(b)) continue;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }

  // Nodes
  for (const n of G.nodes) {
    const r    = nodeRadius(n);
    const vis  = nodeVisible(n);
    const col  = nodeColor(n);
    ctx.globalAlpha = vis ? 1.0 : 0.15;

    ctx.beginPath();
    ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
    ctx.fillStyle = col;
    ctx.fill();

    if (vis && r > 5) {
      ctx.font = `${Math.min(11, r)}px -apple-system,sans-serif`;
      ctx.fillStyle = textColor;
      ctx.textAlign = 'center';
      ctx.fillText(n.label.slice(0, 18), n.x, n.y + r + 12);
    }
  }
  ctx.globalAlpha = 1;
  ctx.restore();
}

/* ── Graph events ─────────────────────────────────────────── */
function bindGraphEvents() {
  const canvas = G.canvas;
  let panStart = null, panOffset = null;

  canvas.addEventListener('mousedown', e => {
    const pos = canvasPos(e);
    const hit = nodeAtPos(pos);
    if (hit) { G.drag = hit; }
    else      { panStart = { x: e.clientX, y: e.clientY }; panOffset = { x: G.offsetX, y: G.offsetY }; }
  });

  canvas.addEventListener('mousemove', e => {
    if (G.drag) {
      const pos = canvasPos(e);
      G.drag.x = pos.x; G.drag.y = pos.y;
      G.drag.vx = 0; G.drag.vy = 0;
    } else if (panStart) {
      G.offsetX = panOffset.x + (e.clientX - panStart.x);
      G.offsetY = panOffset.y + (e.clientY - panStart.y);
    }
    // Tooltip
    const pos = canvasPos(e);
    const hit = nodeAtPos(pos);
    const tt  = $('graph-tooltip');
    if (hit) {
      tt.style.display = 'block';
      tt.style.left = (e.offsetX + 14) + 'px';
      tt.style.top  = (e.offsetY - 10) + 'px';
      tt.innerHTML  = `<div class="tt-label">${esc(hit.label)}</div>
        <div class="tt-type">${esc(hit.node_type)}</div>
        <div class="tt-freq">${hit.mention_count} mention(s) · ${hit.doc_count} doc(s)</div>`;
    } else {
      tt.style.display = 'none';
    }
  });

  canvas.addEventListener('mouseup', e => {
    if (G.drag && !panStart) {
      // Single click on node → search for it
      const label = G.drag.label;
      G.drag = null;
      $('graph-tooltip').style.display = 'none';
      setTimeout(() => searchForEntity(label), 100);
      return;
    }
    G.drag = null; panStart = null; panOffset = null;
  });

  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    G.scale = Math.max(0.2, Math.min(5, G.scale * factor));
  }, { passive: false });
}

function canvasPos(e) {
  return {
    x: (e.offsetX - G.offsetX) / G.scale,
    y: (e.offsetY - G.offsetY) / G.scale,
  };
}

function nodeAtPos({ x, y }) {
  for (const n of [...G.nodes].reverse()) {
    const r = nodeRadius(n);
    const dx = n.x - x, dy = n.y - y;
    if (dx*dx + dy*dy <= r*r) return n;
  }
  return null;
}

function filterGraph(val) {
  G.filter = val;
  updateGraphStats();
}

async function exportGraphJSON() {
  const cid = $('graph-collection')?.value || '';
  window.open(`${API}/graph/export?fmt=json&collection_id=${cid}`, '_blank');
}

/* ═══════════════════════════════════════════════════════════
   ANNOTATIONS VIEW
   ═══════════════════════════════════════════════════════════ */
async function loadAnnotations() {
  const cid = $('ann-collection-filter')?.value || '';
  try {
    const all = await api(`/annotations?collection_id=${cid}`);
    const filtered = _annFilter === 'all' ? all : all.filter(a => a.kind === _annFilter);
    const list = $('annotations-list');
    if (!filtered.length) {
      list.innerHTML = '<div class="empty-state">No annotations yet.<p>Open a document and add notes from the document panel.</p></div>';
      return;
    }
    list.innerHTML = filtered.map(a => `
      <div class="ann-card">
        <div class="ann-card-meta">
          <span class="ann-kind-badge kind-${esc(a.kind)}">${esc(a.kind)}</span>
          <span class="ann-doc-link" onclick="openDocPanel('${esc(a.doc_id)}')">${esc(a.filename || a.doc_id.slice(0,8))}</span>
          <span class="ann-time">${ts(a.created_at)}</span>
        </div>
        ${a.note
          ? `<div class="ann-note-text">${_renderAnnotationBody(a)}</div>`
          : `<div class="ann-no-note">No note text</div>`}
        <div class="ann-actions">
          <button class="btn-danger btn-sm"
            onclick="deleteAnnotationFromList('${esc(a.id)}')">Delete</button>
        </div>
      </div>`).join('');
  } catch (e) { console.error(e); }
}

function setAnnFilter(val, btn) {
  _annFilter = val;
  document.querySelectorAll('.ann-kind-tabs .tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  loadAnnotations();
}

async function deleteAnnotationFromList(annId) {
  if (!confirm('Delete this annotation?')) return;
  await api(`/annotations/${annId}`, { method:'DELETE' });
  loadAnnotations();
}

/* ═══════════════════════════════════════════════════════════
   CULTURAL / LANGUAGE COVERAGE
   ═══════════════════════════════════════════════════════════ */
async function loadCoverage() {
  await populateAllSelects();
  const cid = $('coverage-collection')?.value;
  const auditDiv = $('coverage-audit');
  if (!cid) {
    auditDiv.innerHTML = '<p style="color:var(--muted);font-size:13px">Select a collection above to see its language coverage audit.</p>';
    return;
  }
  try {
    const policy = await api(`/bias/policy/${cid}`);
    $('coverage-policy').value = policy.bias_policy || 'suggestive';
    $('coverage-vendor-country').value = policy.vendor_country || '';

    const audit = await api(`/bias/audit/${cid}`);
    const coverageRows = Object.entries(audit.coverage_pct || {})
      .map(([lang, pct]) => `<div class="entity-row"><span class="badge badge-type">${esc(lang)}</span><span>${pct}%</span></div>`)
      .join('') || '<p style="color:var(--muted)">No documents with detected language yet.</p>';
    auditDiv.innerHTML = `
      <h3>Corpus language coverage</h3>
      ${audit.gap_warning ? `<div class="gap-warning">⚠ ${esc(audit.gap_warning)}</div>` : '<div style="color:var(--muted);font-size:13px">No coverage gap detected.</div>'}
      ${coverageRows}
      ${audit.checklist && audit.checklist.length ? `<div style="margin-top:10px"><strong>Suggested next steps:</strong><ul>${audit.checklist.map(c=>`<li>${esc(c)}</li>`).join('')}</ul></div>` : ''}
    `;
  } catch (e) {
    auditDiv.innerHTML = `<p style="color:var(--red)">Error: ${esc(e.message)}</p>`;
  }
}

async function saveCoveragePolicy() {
  const cid = $('coverage-collection')?.value;
  if (!cid) { showToast('Select a collection first.', 'warn'); return; }
  try {
    await api('/bias/policy', { method: 'PUT', body: JSON.stringify({
      collection_id: cid,
      bias_policy: $('coverage-policy').value,
      vendor_country: $('coverage-vendor-country').value.trim() || null,
    })});
    loadCoverage();
  } catch (e) { showToast('Failed to save policy: ' + e.message, 'error'); }
}

async function runTranslate() {
  const text = $('translate-input').value.trim();
  if (!text) return;
  const out = $('translate-output');
  const sourceSel = $('translate-source').value;
  out.style.display = 'block';
  out.textContent = 'Translating…';
  try {
    const r = await api('/bias/translate', { method: 'POST', body: JSON.stringify({
      text, target_lang: $('translate-target').value,
      source_lang: sourceSel || null,
    })});
    out.innerHTML = r.engine === 'unavailable'
      ? `<em style="color:var(--muted)">No offline language package installed for this pair yet (detected source: ${esc(r.source_lang)}). Text unchanged.` +
        (sourceSel ? '' : ' If auto-detection guessed wrong (common for short text), pick the source language explicitly above and try again.') + `</em>`
      : `<div style="color:var(--muted);font-size:11px;margin-bottom:6px">Translated from ${esc(r.source_lang)}${sourceSel ? '' : ' (auto-detected)'} · engine: ${esc(r.engine)}</div>${esc(r.translated)}`;
  } catch (e) { out.textContent = 'Error: ' + e.message; }
}

/* ═══════════════════════════════════════════════════════════
   AUDIT LOG
   ═══════════════════════════════════════════════════════════ */
async function loadAuditLog() {
  try {
    const rows = await api('/audit?limit=200');
    $('audit-tbody').innerHTML = rows.length
      ? rows.map(r => {
          let detail = '';
          try { const p = JSON.parse(r.payload||'{}'); detail = p.question || p.query || JSON.stringify(p).slice(0,80); } catch {}
          return `<tr>
            <td style="color:var(--muted);white-space:nowrap">${new Date(r.ts*1000).toLocaleString()}</td>
            <td><span class="audit-action">${esc(r.action)}</span></td>
            <td style="color:var(--muted)">${esc(detail)}</td>
          </tr>`;
        }).join('')
      : '<tr><td colspan="3" style="text-align:center;color:var(--muted);padding:40px">No audit events yet.</td></tr>';
  } catch (e) { console.error(e); }
}

/* ═══════════════════════════════════════════════════════════
   SETTINGS
   ═══════════════════════════════════════════════════════════ */
async function loadSettings() {
  try {
    const s = await api('/ai/status');
    const div = $('settings-ai-status');
    if (s.ollama_online) {
      div.className = 'settings-status ok';
      div.innerHTML = `Ollama online · ${s.models.length} model(s) · LLM ready: ${s.llm_ready ? 'Yes' : 'No'} · Embeddings: ${s.embedding_ready ? 'Yes' : 'No'}`;
    } else {
      div.className = 'settings-status err';
      div.innerHTML = 'Ollama is offline. Start it with: <code>ollama serve</code>';
    }
    const sel = $('settings-model');
    sel.innerHTML = s.models.map(m => `<option ${m===_activeModel?'selected':''}>${esc(m)}</option>`).join('');
  } catch {}

  try {
    const p = await api('/profile');
    $('profile-answer-style').value = p.answer_style || 'concise';
    $('profile-proactive').checked = !!p.proactive_suggestions;
    const topics = (p.frequent_topics || []).slice(0, 8);
    $('profile-topics').innerHTML = topics.length
      ? 'Frequently asked about: ' + topics.map(t => `<span class="badge badge-type">${esc(t.topic)} (${t.count})</span>`).join(' ')
      : 'No query history yet.';
  } catch {}
}

async function saveProfile() {
  try {
    await api('/profile', { method: 'PUT', body: JSON.stringify({
      answer_style: $('profile-answer-style').value,
      proactive_suggestions: $('profile-proactive').checked,
    })});
    showToast('Preferences saved.', 'success');
  } catch (e) { showToast('Failed to save: ' + e.message, 'error'); }
}

function setActiveModel(val) { _activeModel = val; }

/* ═══════════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════════ */
window.addEventListener('DOMContentLoaded', async () => {
  await loadCollections();
  checkAIStatus();
  setInterval(checkAIStatus, 15000);

  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault(); showView('search'); $('search-input')?.focus();
    }
    if (e.key === 'Escape') { closeModal(); closeDocPanel(); }
  });
});
