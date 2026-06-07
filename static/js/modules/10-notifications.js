// Auto-generated module — see static/js/app.js for full app
// Part of MediScan Health OS

// Notification centre: feed, filters, daily nudges, badge updates

async function loadNotifications() {
  const r = await fetch('/api/notifications?limit=100').then(r => r.json()).catch(() => null);
  if (!r) return;
  _allNotifs = r.notifications || [];
  updateNotifBadge(r.unread);
  const totalEl = document.getElementById('notif-unread-total');
  if (totalEl) totalEl.textContent = r.unread > 0 ? `${r.unread} unread` : '';
  renderNotifications();
}

function renderNotifications() {
  const el = document.getElementById('notif-list');
  if (!el) return;

  let items = _allNotifs;
  if (_notifFilter !== 'all') items = items.filter(n => n.type === _notifFilter);

  if (!items.length) {
    el.innerHTML = `<div class="notif-empty">
      <div class="notif-empty-icon">🔔</div>
      <div class="notif-empty-title">All clear!</div>
      <div class="notif-empty-sub">${_notifFilter === 'all' ? 'No notifications yet' : 'No ' + _notifFilter + ' notifications'}</div>
    </div>`;
    return;
  }

  // Group by date
  const byDate = {};
  items.forEach(n => {
    const d = n.created_at.slice(0,10);
    (byDate[d] = byDate[d]||[]).push(n);
  });

  const today = new Date().toISOString().slice(0,10);
  const yesterday = new Date(Date.now()-86400000).toISOString().slice(0,10);

  const NOTIF_STYLES = {
    medicine: {bg:'#EFF6FF', border:'#BFDBFE', icon:'💊'},
    refill:   {bg:'#FFFBEB', border:'#FDE68A', icon:'⚠️'},
    todo:     {bg:'#ECFDF5', border:'#A7F3D0', icon:'✅'},
    symptom:  {bg:'#FEF2F2', border:'#FECACA', icon:'🩺'},
    fitness:  {bg:'#F5F3FF', border:'#DDD6FE', icon:'🏃'},
    food:     {bg:'#FFF7ED', border:'#FED7AA', icon:'🍽️'},
    sleep:    {bg:'#EEF2FF', border:'#C7D2FE', icon:'🌙'},
    hydration:{bg:'#E0F2FE', border:'#BAE6FD', icon:'💧'},
    system:   {bg:'#F9FAFB', border:'#E5E7EB', icon:'🔔'},
  };

  el.innerHTML = Object.entries(byDate).map(([date, notifs]) => {
    const label = date === today ? 'Today' : date === yesterday ? 'Yesterday' : new Date(date+'T12:00:00').toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric'});
    const rows = notifs.map(n => {
      const style = NOTIF_STYLES[n.type] || NOTIF_STYLES.system;
      const ago   = timeAgo(n.created_at);
      return `<div class="notif-row ${n.read?'':'unread'}" onclick="markNotifRead('${n.id}')">
        <div class="notif-icon" style="background:${style.bg};border:1px solid ${style.border}">${NOTIF_ICONS[n.type]||style.icon}</div>
        <div class="notif-body">
          <div class="notif-title">${escHtml(n.title)}</div>
          ${n.body ? `<div class="notif-text">${escHtml(n.body)}</div>` : ''}
        </div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex-shrink:0">
          <div class="notif-time">${ago}</div>
          ${!n.read ? '<div class="notif-unread-dot"></div>' : ''}
        </div>
      </div>`;
    }).join('');
    return `<div class="notif-date-group"><div class="notif-date-label">${label}</div>${rows}</div>`;
  }).join('');
}

function timeAgo(isoStr) {
  const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
  if (diff < 60)   return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + 'm ago';
  if (diff < 86400)return Math.floor(diff/3600) + 'h ago';
  return Math.floor(diff/86400) + 'd ago';
}

async function markNotifRead(id) {
  const r = await fetch(`/api/notifications/${id}/read`, {method:'POST'}).then(r=>r.json()).catch(()=>null);
  if (r) updateNotifBadge(r.unread);
  loadNotifications();
}

async function markAllRead() {
  await fetch('/api/notifications/read-all', {method:'POST'});
  updateNotifBadge(0);
  loadNotifications();
}

function updateNotifBadge(count) {
  const badge = document.getElementById('nav-notif-badge');
  if (!badge) return;
  if (count > 0) { badge.textContent = count; badge.style.display = 'inline-block'; }
  else badge.style.display = 'none';
}

async function logNotification(type, title, body = '') {
  await fetch('/api/notifications', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({type, title, body})
  });
  // Refresh badge
  const r = await fetch('/api/notifications?unread=1').then(r=>r.json()).catch(()=>null);
  if (r) updateNotifBadge(r.unread);
}

// Check for low stock medicines and log notification
async function checkLowStock() {
  const r = await fetch('/api/medicines/low-stock').then(r=>r.json()).catch(()=>[]);
  const banner = document.getElementById('low-stock-banner');
  if (r.length > 0) {
    r.forEach(m => {
      logNotification('refill', `Refill needed: ${m.name}`,
        `Only ${m.days_left} days of supply remaining (${m.pill_count} pills left)`);
    });
    // Show banner on medicine page
    if (banner) {
      const names = r.map(m=>`<strong>${m.name}</strong> (${m.days_left}d left)`).join(', ');
      banner.innerHTML = `<div class="low-stock-banner-icon">⚠️</div><div class="low-stock-banner-text">Low stock: ${names}</div>`;
      banner.style.display = 'flex';
    }
  } else if (banner) banner.style.display = 'none';
}

// Poll unread count every 2 min
setInterval(async () => {
  const r = await fetch('/api/notifications?unread=1').then(r=>r.json()).catch(()=>null);
  if (r) updateNotifBadge(r.unread);
}, 120000);

// ════════════════════════════════════════════════════════════
// PROGRESS VIEW
// ════════════════════════════════════════════════════════════

// ════════════════════════════════════════════════════════════
// GOAL PROGRESS — Rich charts & per-metric analysis
// ════════════════════════════════════════════════════════════

let _progressData = null;
let _progressPeriod = 'month';

function setProgressPeriod(p) {
  _progressPeriod = p;
  document.querySelectorAll('.prog-period-btn').forEach(b => b.classList.toggle('active', b.dataset.period === p));
  if (_progressData) renderProgress(_progressData);
}