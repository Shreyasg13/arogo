// Auto-generated module — see static/js/app.js for full app
// Part of MediScan Health OS

// Medicine tracker: doses, schedule, adherence, stock/refill

function openMedModal() {
  document.getElementById('med-modal-overlay').style.display = 'flex';
}

async function loadMedicines() {
  const [meds, doses] = await Promise.all([
    fetch('/api/medicines').then(r => r.json()).catch(() => []),
    fetch('/api/medicines/today').then(r => r.json()).catch(() => [])
  ]);
  renderTodayTimeline(doses);
  renderMedicinesGrid(meds);
  const mc = document.getElementById('med-count');
  if (mc) mc.textContent = `${meds.filter(m=>m.active).length} active`;
}

function renderTodayTimeline(doses) {
  const el = document.getElementById('today-dose-timeline');
  if (!el) return;
  const total = doses.length, taken = doses.filter(d => d.taken).length;
  const fill = document.getElementById('med-progress-fill');
  const label = document.getElementById('med-progress-label');
  if (fill) fill.style.width = total ? `${(taken/total*100).toFixed(0)}%` : '0%';
  if (label) label.textContent = `${taken} of ${total} taken`;
  if (doses.length === 0) {
    el.innerHTML = '<div style="color:var(--gray-400);font-size:13px;padding:16px 0;text-align:center">No doses scheduled. <a href="#" onclick="openMedModal();return false" style="color:var(--teal-600)">Add a medicine →</a></div>';
    return;
  }
  // Group by time
  const byTime = {};
  doses.forEach(d => { if (!byTime[d.time]) byTime[d.time] = []; byTime[d.time].push(d); });
  const times = Object.keys(byTime).sort();
  const now = new Date().toTimeString().slice(0,5);
  el.innerHTML = times.map((time, idx) => {
    const group = byTime[time];
    const allTaken = group.every(d => d.taken);
    const isPast = time < now;
    const dotClass = allTaken ? 'taken' : (isPast ? 'missed' : '');
    return `
      <div class="dose-slot">
        <div class="dose-time-col"><span class="dose-time-label">${time}</span></div>
        <div class="dose-line-col">
          <div class="dose-dot ${dotClass}"></div>
          ${idx < times.length - 1 ? '<div class="dose-vline"></div>' : ''}
        </div>
        <div class="dose-cards-col">
          ${group.map(d => `
            <div class="dose-card ${d.taken ? 'taken' : ''}" onclick="markDoseTaken('${d.med_id}','${d.time}',this)">
              <div class="dose-card-emoji">${d.icon}</div>
              <div class="dose-card-info">
                <div class="dose-card-name">${escHtml(d.med_name)}</div>
                <div class="dose-card-detail">${d.dosage} ${d.unit}${d.with_food ? ' · 🍽️ with food' : ''}</div>
              </div>
              <div class="dose-card-check">${d.taken ? '✓' : ''}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }).join('');
}

function renderMedicinesGrid(meds) {
  const grid = document.getElementById('medicines-grid');
  if (!grid) return;
  if (meds.length === 0) {
    grid.innerHTML = `<div class="empty-state"><div class="empty-icon">💊</div><div class="empty-text">No medicines added</div><div class="empty-sub">Add your first medicine to track doses</div><button class="btn-primary" onclick="openMedModal()">Add Medicine</button></div>`;
    return;
  }
  grid.innerHTML = meds.map(m => {
    // Pill count / refill section
    const hasPills = m.pill_count != null;
    const freqDoses = {once_daily:1,twice_daily:2,thrice_daily:3,weekly:1/7}[m.frequency] || 1;
    const daysLeft = hasPills ? Math.floor(m.pill_count / Math.max(freqDoses * (m.pills_per_dose||1), 0.01)) : null;
    const maxDays  = m.refill_threshold ? m.refill_threshold * 4 : 28;
    const fillPct  = hasPills ? Math.min(100, Math.round((daysLeft / maxDays) * 100)) : 0;
    const isLow    = hasPills && daysLeft < (m.refill_threshold || 7);
    const stockColor = isLow ? '#EF4444' : daysLeft < (m.refill_threshold||7)*2 ? '#F59E0B' : '#22C55E';

    const pillSection = hasPills ? `
      <div class="med-pill-track">
        <div class="med-pill-track-row">
          <span class="med-pill-count-label" style="color:${stockColor}">
            ${isLow ? '⚠️' : '💊'} ${m.pill_count} pills · ${daysLeft}d left
          </span>
          <button class="med-restock-btn" onclick="openRestockModal('${m.id}','${escHtml(m.name)}',${m.pill_count},${m.pills_per_dose||1},${m.refill_threshold||7})">Restock</button>
        </div>
        <div class="med-pill-bar-track">
          <div class="med-pill-bar-fill" style="width:${fillPct}%;background:${stockColor}"></div>
        </div>
      </div>` : `
      <div class="med-pill-track med-pill-track--empty">
        <button class="med-add-stock-btn" onclick="openRestockModal('${m.id}','${escHtml(m.name)}',0,1,7)">+ Track pill count</button>
      </div>`;

    return `<div class="med-card med-card--${m.color}${isLow?' med-card--low-stock':''}">
      <div class="med-card-header">
        <div class="med-card-icon">${m.icon}</div>
        <div class="med-card-info">
          <div class="med-card-name">${escHtml(m.name)}</div>
          <div class="med-card-dose">${m.dosage} ${m.unit} · ${freqLabel(m.frequency)}</div>
        </div>
      </div>
      <div class="med-card-times">
        ${m.times?.map(t => `<span class="time-chip">⏰ ${t}</span>`).join('') || ''}
        ${m.with_food ? '<span class="med-food-badge">🍽️ With food</span>' : ''}
      </div>
      ${m.notes ? `<div style="font-size:12px;color:var(--gray-400);margin-bottom:8px">${escHtml(m.notes)}</div>` : ''}
      ${pillSection}
      <div class="med-card-footer">
        <span class="med-card-status ${m.active ? 'active' : ''}">● ${m.active ? 'Active' : 'Paused'}</span>
        <div class="med-card-actions">
          <button class="btn-icon" title="${m.active ? 'Pause' : 'Activate'}" onclick="toggleMed('${m.id}')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">${m.active ? '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>' : '<polygon points="5 3 19 12 5 21 5 3"/>'}</svg>
          </button>
          <button class="btn-icon" title="Delete" onclick="deleteMed('${m.id}')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
          </button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function markDoseTaken(medId, time, el) {
  const date = new Date().toISOString().split('T')[0];
  await fetch(`/api/medicines/${medId}/log`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ date, time, taken:true }) });
  showToast('Dose marked as taken ✓', 'success');
  loadMedicines();
  loadDashboard();
}

async function toggleMed(id) {
  await fetch(`/api/medicines/${id}/toggle`, { method:'POST' });
  loadMedicines();
}

async function deleteMed(id) {
  if (!confirm('Remove this medicine?')) return;
  await fetch(`/api/medicines/${id}`, { method:'DELETE' });
  showToast('Medicine removed', 'success');
  loadMedicines();
}

function setupMedForm() {
  document.getElementById('med-form')?.addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.target;
    const times = [...document.querySelectorAll('.time-input')].map(i => i.value).filter(Boolean);
    const body = {
      name: form.name.value,
      dosage: form.dosage.value,
      unit: form.unit.value,
      frequency: form.querySelector('input[name="frequency"]:checked')?.value || 'once_daily',
      times,
      with_food: document.getElementById('with-food-toggle')?.checked || false,
      notes: form.notes.value,
      start_date: form.start_date.value,
      end_date: form.end_date.value,
      icon: selectedIcon,
      color: selectedColor
    };
    const res = await fetch('/api/medicines', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
    const data = await res.json();
    if (data.success) {
      // Save pill count if entered
      const pillCount = parseInt(document.getElementById('med-pill-count')?.value);
      if (pillCount > 0) {
        await fetch(`/api/medicines/${data.medicine.id}/stock`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({
            pill_count:  pillCount,
            pills_per_dose: parseInt(document.getElementById('med-pills-per-dose')?.value) || 1,
            refill_threshold: parseInt(document.getElementById('med-refill-threshold')?.value) || 7
          })
        });
      }
      showToast(`${body.name} added!`, 'success');
      form.reset(); setDates();
      resetTimeSlots();
      document.getElementById('med-pill-count').value = '';
      document.getElementById('med-pills-per-dose').value = '1';
      document.getElementById('med-refill-threshold').value = '7';
      document.getElementById('refill-fields').style.display = 'none';
      document.getElementById('refill-chevron').style.transform = 'rotate(-90deg)';
      closeModal('med-modal-overlay');
      loadMedicines();
      scheduleReminderChecks();
    } else showToast('Failed to add medicine', 'error');
  });
}

function addTimeSlot() {
  const slots = document.getElementById('time-slots');
  const row = document.createElement('div');
  row.className = 'time-slot-row';
  row.innerHTML = `<input type="time" class="form-input time-input" value="12:00"><button type="button" class="btn-icon slot-remove" onclick="removeTimeSlot(this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>`;
  slots.appendChild(row);
}

function removeTimeSlot(btn) {
  const slots = document.getElementById('time-slots');
  if (slots.children.length > 1) btn.closest('.time-slot-row').remove();
}

function resetTimeSlots() {
  const slots = document.getElementById('time-slots');
  if (slots) slots.innerHTML = `<div class="time-slot-row"><input type="time" class="form-input time-input" value="08:00"><button type="button" class="btn-icon slot-remove" onclick="removeTimeSlot(this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></div>`;
}

function setupFreqPicker() {
  document.querySelectorAll('.freq-opt input').forEach(input => {
    input.addEventListener('change', () => {
      const counts = { once_daily:1, twice_daily:2, thrice_daily:3, weekly:1 };
      const count = counts[input.value] || 1;
      const slots = document.getElementById('time-slots');
      if (!slots) return;
      const defaultTimes = ['08:00','13:00','20:00'];
      while (slots.children.length < count) addTimeSlot();
      while (slots.children.length > count) slots.lastChild.remove();
      [...slots.querySelectorAll('.time-input')].forEach((inp, i) => { if (defaultTimes[i]) inp.value = defaultTimes[i]; });
    });
  });
}

function setupIconColorPicker() {
  document.querySelectorAll('.icon-opt').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.icon-opt').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      selectedIcon = btn.dataset.icon;
    });
  });
  document.querySelectorAll('.color-opt').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.color-opt').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      selectedColor = btn.dataset.color;
    });
  });
}

// ── Reminders / Notifications ──
function checkNotifPermission() {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'default') {
    document.getElementById('notif-banner').style.display = 'flex';
  }
  notifPermission = Notification.permission;
}

function requestNotifPermission() {
  if (!('Notification' in window)) return;
  Notification.requestPermission().then(perm => {
    notifPermission = perm;
    document.getElementById('notif-banner').style.display = 'none';
    if (perm === 'granted') { showToast('Notifications enabled! 🔔', 'success'); scheduleReminderChecks(); }
  });
}

function scheduleReminderChecks() {
  reminderIntervals.forEach(clearInterval);
  reminderIntervals = [];
  if (notifPermission !== 'granted') return;
  registerNotifServiceWorker();
  const interval = setInterval(async () => {
    const doses = await fetch('/api/medicines/today').then(r => r.json()).catch(() => []);
    const now = new Date().toTimeString().slice(0,5);
    doses.forEach(d => { if (d.time === now && !d.taken) fireReminderNotification(d); });
  }, 60000);
  reminderIntervals.push(interval);
  setTimeout(async () => {
    const doses = await fetch('/api/medicines/today').then(r => r.json()).catch(() => []);
    const now = new Date().toTimeString().slice(0,5);
    doses.forEach(d => { if (d.time === now && !d.taken) fireReminderNotification(d); });
  }, 2000);
}

function fireReminderNotification(dose) {
  if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
    navigator.serviceWorker.ready.then(reg => {
      reg.showNotification('💊 Medicine Reminder', {
        body: `Time to take ${dose.med_name} — ${dose.dosage} ${dose.unit}${dose.with_food ? ' (with food)' : ''}`,
        tag: `dose-${dose.med_id}-${dose.time}`,
        requireInteraction: true,
        data: { med_id: dose.med_id, time: dose.time, med_name: dose.med_name },
        actions: [
          { action: 'taken', title: '✓ Mark as Taken' },
          { action: 'snooze', title: '⏰ Snooze 10 min' }
        ]
      });
    });
  } else {
    const n = new Notification('💊 Medicine Reminder', {
      body: `Time to take ${dose.med_name} — ${dose.dosage} ${dose.unit}${dose.with_food ? ' (with food)' : ''}`,
      tag: `dose-${dose.med_id}-${dose.time}`,
      requireInteraction: true
    });
    n.onclick = () => { window.focus(); markDoseTaken(dose.med_id, dose.time, null); n.close(); };
  }
}

function registerNotifServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  const swCode = `
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const { med_id, time, med_name } = e.notification.data || {};
  if (e.action === 'taken') {
    e.waitUntil(
      fetch('/api/medicines/' + med_id + '/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: new Date().toISOString().split('T')[0], time, taken: true })
      }).then(() =>
        self.registration.showNotification('Dose Logged', {
          body: med_name + ' marked as taken',
          tag: 'dose-confirm',
          requireInteraction: false
        })
      )
    );
    e.waitUntil(clients.matchAll({ type: 'window' }).then(list => {
      if (list.length) return list[0].focus();
      return clients.openWindow('/');
    }));
  } else if (e.action === 'snooze') {
    e.waitUntil(new Promise(resolve => {
      setTimeout(() => {
        self.registration.showNotification('Medicine Reminder (Snoozed)', {
          body: 'Still need to take ' + med_name,
          tag: 'dose-' + med_id + '-snooze',
          requireInteraction: true,
          data: { med_id, time, med_name },
          actions: [
            { action: 'taken', title: 'Mark as Taken' },
            { action: 'snooze', title: 'Snooze 10 min' }
          ]
        });
        resolve();
      }, 600000);
    }));
  } else {
    e.waitUntil(clients.matchAll({ type: 'window' }).then(list => {
      if (list.length) return list[0].focus();
      return clients.openWindow('/');
    }));
  }
});
`;
  const blob = new Blob([swCode], { type: 'application/javascript' });
  const swUrl = URL.createObjectURL(blob);
  navigator.serviceWorker.register(swUrl, { scope: '/' })
    .then(() => console.log('[SW] Registered'))
    .catch(err => console.warn('[SW] Failed:', err));
}

// ── Fitness ──