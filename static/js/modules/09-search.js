// Auto-generated module — see static/js/app.js for full app
// Part of MediScan Health OS

// Global search: Ctrl+K overlay, date parsing, highlights, keyboard nav

function openGlobalSearch() {
  const wrap = document.getElementById('global-search-wrap');
  if (!wrap) return;
  wrap.style.display = 'flex';
  setTimeout(() => document.getElementById('global-search-input')?.focus(), 50);
  // Show hints on open
  document.getElementById('gs-hints').style.display = 'block';
  document.getElementById('global-search-results').innerHTML = '';
}

function closeGlobalSearch() {
  const wrap = document.getElementById('global-search-wrap');
  if (wrap) wrap.style.display = 'none';
  const inp = document.getElementById('global-search-input');
  if (inp) inp.value = '';
  _gsSelectedIdx = -1;
}

function fillSearch(text) {
  const inp = document.getElementById('global-search-input');
  if (!inp) return;
  inp.value = text;
  inp.focus();
  document.getElementById('gs-hints').style.display = 'none';
  runGlobalSearch(text);
}

function setSearchType(type) {
  _gsSearchType = type;
  document.querySelectorAll('.gs-filter-btn').forEach(b => b.classList.toggle('active', b.dataset.type === type));
  const q = document.getElementById('global-search-input')?.value;
  if (q?.length >= 2) runGlobalSearch(q);
}

function handleSearchKey(e) {
  const rows = document.querySelectorAll('.gs-result-row');
  if (e.key === 'Escape')  { closeGlobalSearch(); return; }
  if (e.key === 'ArrowDown') { _gsSelectedIdx = Math.min(_gsSelectedIdx+1, rows.length-1); highlightRow(rows); e.preventDefault(); }
  if (e.key === 'ArrowUp')   { _gsSelectedIdx = Math.max(_gsSelectedIdx-1, 0); highlightRow(rows); e.preventDefault(); }
  if (e.key === 'Enter' && _gsSelectedIdx >= 0) { rows[_gsSelectedIdx]?.click(); }
}

function highlightRow(rows) {
  rows.forEach((r,i) => r.classList.toggle('selected', i === _gsSelectedIdx));
  rows[_gsSelectedIdx]?.scrollIntoView({block:'nearest'});
}

// Ctrl+K / Cmd+K
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); openGlobalSearch(); }
});

// Helper: highlight matched text
function hlText(text, query) {
  if (!query || !text) return escHtml(text||'');
  const clean = query.replace(/last\s+\w+|this\s+\w+|yesterday|today/g,'').trim();
  if (!clean || clean.length < 2) return escHtml(text);
  try {
    const re = new RegExp('(' + clean.replace(/[.*+?^${}()|[\]\]/g,'\$&') + ')', 'gi');
    return escHtml(text).replace(re, '<mark>$1</mark>');
  } catch { return escHtml(text); }
}

async function runGlobalSearch(q) {
  clearTimeout(_gsTimer);
  const res   = document.getElementById('global-search-results');
  const hints = document.getElementById('gs-hints');
  if (!res) return;
  if (q.length < 2) {
    res.innerHTML = '';
    if (hints) hints.style.display = 'block';
    return;
  }
  if (hints) hints.style.display = 'none';
  res.innerHTML = '<div class="gs-empty" style="padding:20px;font-size:13px">Searching…</div>';
  _gsTimer = setTimeout(async () => {
    const params = new URLSearchParams({q});
    if (_gsSearchType !== 'all') params.set('type', _gsSearchType);
    const r = await fetch(`/api/search?${params}`).then(r => r.json()).catch(() => null);
    if (!r) return;

    // Show date range tag if a date was parsed
    let dateTag = '';
    if (r.date_range) {
      const [from, to] = r.date_range;
      dateTag = `<div class="gs-date-tag">📅 Showing results for ${from === to ? from : from + ' → ' + to}</div>`;
    }

    if (r.total === 0) {
      res.innerHTML = dateTag + `<div class="gs-empty">
        <div class="gs-empty-icon">🔍</div>
        <div class="gs-empty-text">No results for "${escHtml(q)}"</div>
        <div class="gs-empty-sub">Try different keywords or a date range like "last week"</div>
      </div>`;
      return;
    }

    // Filter sections if type filter is active
    const sections = _gsSearchType === 'all' ? r.sections : r.sections.filter(s => s.type === _gsSearchType);

    res.innerHTML = dateTag + sections.map(s => {
      const rows = s.items.map(item => {
        let title='', meta='', badge='';

        if (s.type==='food')     { title=item.food_name; meta=`${item.date_key} · ${item.meal_type||''} · ${Math.round(item.calories||0)} kcal`; }
        if (s.type==='thought')  { title=item.content?.slice(0,90)+(item.content?.length>90?'…':''); meta=`${item.date_key} · ${MOOD_EMOJI[item.mood]||''} ${item.mood||''}`; }
        if (s.type==='symptom')  { title=item.name; meta=`${item.date_key} · ${(item.time_of_day||'').replace('_',' ')} · ${item.severity}/10 severity${item.notes?' · '+item.notes:''}`; }
        if (s.type==='todo')     {
          title=item.title;
          meta=`${item.priority} priority${item.due_date?' · Due '+item.due_date:''}`;
          badge=`<span class="gs-result-badge ${item.status}">${item.status}</span>`;
        }
        if (s.type==='activity') { title=item.name||item.type; meta=`${item.date} · ${item.duration||0}min · ${item.calories||0} kcal${item.distance?' · '+item.distance+'km':''}`; }
        if (s.type==='report')   { title=item.filename||'Report'; meta=`${item.date||''} · ${item.severity||''}`; }
        if (s.type==='medicine') { title=item.name; meta=`${item.dosage} ${item.unit} · ${(item.frequency||'').replace('_',' ')}`; }

        return `<div class="gs-result-row" onclick="closeGlobalSearch();switchView('${VIEW_MAP[s.type]||s.type}')">
          <div class="gs-result-icon">${TYPE_ICON[s.type]||'📄'}</div>
          <div class="gs-result-main">
            <div class="gs-result-title">${hlText(title, q)}</div>
            <div class="gs-result-meta">${escHtml(meta)}</div>
          </div>
          ${badge}
        </div>`;
      }).join('');
      return `<div class="gs-section-label">${s.icon} ${s.label}<span class="gs-section-count">${s.items.length}</span></div>${rows}`;
    }).join('');
    _gsSelectedIdx = -1;
  }, 200);
}

// ════════════════════════════════════════════════════════════
// NOTIFICATION CENTRE
// ════════════════════════════════════════════════════════════

const NOTIF_ICONS = {
  medicine:'💊', todo:'✅', hydration:'💧', sleep:'🌙', food:'🍽️',
  fitness:'🏃', symptom:'🩺', vital:'❤️', system:'🔔', refill:'⚠️'
};

let _notifFilter = 'all';
let _allNotifs   = [];

function setNotifFilter(f) {
  _notifFilter = f;
  document.querySelectorAll('.notif-filter-btn').forEach(b => b.classList.toggle('active', b.dataset.f === f));
  renderNotifications();
}