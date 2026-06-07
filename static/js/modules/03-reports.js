// Auto-generated module — see static/js/app.js for full app
// Part of MediScan Health OS

// Medical reports: upload, list, detail view, tags

function openUploadModal() {
  document.getElementById('upload-modal-overlay').style.display = 'flex';
}

async function loadReports() {
  const search = document.getElementById('search-input')?.value || '';
  const severity = document.getElementById('severity-filter')?.value || '';
  const tag = document.getElementById('tag-filter')?.value || '';
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (severity) params.set('severity', severity);
  if (tag) params.set('tag', tag);
  const reports = await fetch(`/api/reports?${params}`).then(r => r.json()).catch(() => []);
  const label = document.getElementById('reports-count-label');
  if (label) label.textContent = `${reports.length} report${reports.length !== 1 ? 's' : ''}`;
  const grid = document.getElementById('reports-grid');
  if (!grid) return;
  if (reports.length === 0) {
    grid.innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">No reports found</div><div class="empty-sub">Upload your first medical report</div><button class="btn-primary" onclick="openUploadModal()">Upload Report</button></div>`;
    return;
  }
  grid.innerHTML = reports.map(r => `
    <div class="report-card" onclick="openReportDetail(${JSON.stringify(r).replace(/"/g,'&quot;')})">
      <div class="report-card-header">
        <div class="report-card-file-icon">${fileIcon(r.file_ext)}</div>
        <div class="report-card-info">
          <div class="report-card-title" title="${escHtml(r.original_name)}">${escHtml(r.original_name)}</div>
          <div class="report-card-patient">${escHtml(r.patient_name)}${r.doctor ? ' · ' + escHtml(r.doctor) : ''}</div>
        </div>
        <span class="severity-badge sev-badge-${r.severity}">${r.severity}</span>
      </div>
      ${r.tags?.length ? `<div class="report-card-tags">${r.tags.slice(0,4).map(t=>`<span class="report-tag">${escHtml(t)}</span>`).join('')}${r.tags.length>4?`<span class="report-tag">+${r.tags.length-4}</span>`:''}</div>` : ''}
      ${r.analysis_notes ? `<div class="report-card-notes">${escHtml(r.analysis_notes)}</div>` : ''}
      <div class="report-card-footer">
        <span class="report-card-date">${r.report_date}</span>
        <div class="report-card-actions">
          <button class="btn-icon" title="Download" onclick="event.stopPropagation();downloadFile('/uploads/${r.filename}',r.original_name)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          </button>
          <button class="btn-icon" title="Delete" onclick="event.stopPropagation();deleteReport('${r.id}')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6M9 6V4h6v2"/></svg>
          </button>
        </div>
      </div>
    </div>
  `).join('');
}

function openReportDetail(r) {
  document.getElementById('rdetail-title').textContent = r.original_name;
  document.getElementById('rdetail-body').innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:18px">
      <div style="font-size:40px">${fileIcon(r.file_ext)}</div>
      <div>
        <div style="font-size:13px;color:var(--gray-400)">${escHtml(r.patient_name)}${r.doctor?' · Dr. '+escHtml(r.doctor):''}</div>
        <span class="severity-badge sev-badge-${r.severity}" style="margin-top:6px;display:inline-block">${r.severity}</span>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px">
      ${[['Type',r.report_type],['Date',r.report_date],['Uploaded',new Date(r.upload_date).toLocaleDateString()],['Format',(r.file_ext||'').toUpperCase()]].map(([l,v])=>`<div><div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--gray-400);margin-bottom:3px">${l}</div><div style="font-size:13.5px;font-family:'JetBrains Mono',monospace;color:var(--gray-800)">${v}</div></div>`).join('')}
    </div>
    ${r.tags?.length?`<div style="margin-bottom:18px"><div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--gray-400);margin-bottom:8px">Tags</div><div style="display:flex;flex-wrap:wrap;gap:6px">${r.tags.map(t=>`<span class="report-tag">${escHtml(t)}</span>`).join('')}</div></div>`:''}
    ${r.analysis_notes?`<div style="margin-bottom:18px"><div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--gray-400);margin-bottom:8px">Analysis Notes</div><div style="font-size:13.5px;line-height:1.7;color:var(--gray-700);background:var(--gray-25);border:1px solid var(--gray-100);border-radius:var(--r-md);padding:12px">${escHtml(r.analysis_notes)}</div></div>`:''}
    <div class="form-actions" style="margin-top:16px;padding-top:16px">
      <button class="btn-primary" onclick="downloadFile('/uploads/${r.filename}','${r.original_name}')">Download</button>
      <button class="btn-danger" onclick="deleteReport('${r.id}');closeModal('report-detail-overlay')">Delete</button>
    </div>
  `;
  document.getElementById('report-detail-overlay').style.display = 'flex';
}

async function deleteReport(id) {
  if (!confirm('Delete this report?')) return;
  await fetch(`/api/reports/${id}`, { method:'DELETE' });
  showToast('Report deleted', 'success');
  loadReports();
  loadDashboard();
}

// ── Upload Form ──
function setupDropzone() {
  const dz = document.getElementById('dropzone');
  const fi = document.getElementById('file-input');
  if (!dz || !fi) return;
  dz.addEventListener('click', e => { if (e.target === dz || e.target.closest('.dropzone') === dz) fi.click(); });
  fi.addEventListener('change', () => { if (fi.files[0]) setFile(fi.files[0]); });
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag-over'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
  dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('drag-over'); if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); });
}

function setFile(file) {
  selectedFile = file;
  const icons = { pdf:'📄', png:'🖼️', jpg:'🖼️', jpeg:'🖼️', txt:'📝', csv:'📊' };
  const ext = file.name.split('.').pop().toLowerCase();
  document.getElementById('file-preview-icon').textContent = icons[ext] || '📄';
  document.getElementById('file-preview-name').textContent = file.name;
  document.getElementById('file-preview-size').textContent = fmtBytes(file.size);
  document.getElementById('dropzone').style.display = 'none';
  document.getElementById('file-preview').style.display = 'flex';
}

function clearFile() {
  selectedFile = null;
  document.getElementById('file-input').value = '';
  document.getElementById('dropzone').style.display = 'flex';
  document.getElementById('file-preview').style.display = 'none';
}

function setupTagPicker() {
  document.querySelectorAll('.tag-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tag = btn.dataset.tag;
      if (btn.classList.contains('selected')) { selectedTags = selectedTags.filter(t=>t!==tag); btn.classList.remove('selected'); }
      else { selectedTags.push(tag); btn.classList.add('selected'); }
      renderSelectedTags();
    });
  });
}

function addCustomTag() {
  const input = document.getElementById('custom-tag-input');
  const val = input.value.trim();
  if (val && !selectedTags.includes(val)) { selectedTags.push(val); renderSelectedTags(); input.value = ''; }
}

document.getElementById('custom-tag-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addCustomTag(); } });

function renderSelectedTags() {
  const el = document.getElementById('selected-tags');
  if (!el) return;
  el.innerHTML = selectedTags.map(tag => `
    <span class="selected-tag">${escHtml(tag)}<span class="selected-tag-remove" onclick="removeTag('${escHtml(tag)}')">×</span></span>
  `).join('');
}

function removeTag(tag) {
  selectedTags = selectedTags.filter(t => t !== tag);
  const btn = document.querySelector(`.tag-btn[data-tag="${tag}"]`);
  if (btn) btn.classList.remove('selected');
  renderSelectedTags();
}

function setupUploadForm() {
  document.getElementById('upload-form')?.addEventListener('submit', async e => {
    e.preventDefault();
    if (!selectedFile) { showToast('Please select a file', 'error'); return; }
    const form = e.target;
    const fd = new FormData();
    fd.append('file', selectedFile);
    ['patient_name','doctor','report_type','report_date','analysis_notes'].forEach(n => fd.append(n, form[n]?.value || ''));
    fd.append('severity', form.querySelector('input[name="severity"]:checked')?.value || 'normal');
    selectedTags.forEach(t => fd.append('tags', t));
    const btn = document.getElementById('submit-btn');
    btn.disabled = true; btn.textContent = 'Uploading…';
    try {
      const res = await fetch('/api/upload', { method:'POST', body:fd });
      const data = await res.json();
      if (data.success) {
        showToast('Report uploaded!', 'success');
        form.reset(); clearFile(); selectedTags = []; renderSelectedTags();
        document.querySelectorAll('.tag-btn.selected').forEach(b => b.classList.remove('selected'));
        setDates();
        closeModal('upload-modal-overlay');
        loadReports();
      } else showToast(data.error || 'Upload failed', 'error');
    } catch { showToast('Network error', 'error'); }
    finally { btn.disabled = false; btn.textContent = 'Upload & Save'; }
  });
}

// ── Medicines ──