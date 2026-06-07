// Auto-generated module — see static/js/app.js for full app
// Part of MediScan Health OS

// Core: app state, init, navigation, UI helpers, modals

// ── State ──
let selectedTags = [], selectedFile = null, selectedIcon = '💊', selectedColor = 'teal', selectedActivityType = 'running';
let notifPermission = 'default';
let reminderIntervals = [];

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
  setGreeting();
  setDates();
  setupNavigation();
  setupDropzone();
  setupTagPicker();
  setupUploadForm();
  setupMedForm();
  setupActivityForm();
  setupIconColorPicker();
  setupFreqPicker();
  setupActivityTypePicker();
  setupFilters();
  loadDashboard();
  updateSidebarUser();
  checkNotifPermission();
  scheduleReminderChecks();
  scheduleTodoReminderChecks();
  // Init date pickers
  const tdp = document.getElementById('thoughts-date-picker');
  if (tdp) tdp.value = new Date().toISOString().split('T')[0];
});

// ── Greeting & Date ──
function setGreeting() {
  const h = new Date().getHours();
  const g = h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
  const el = document.getElementById('greeting');
  if (el) el.textContent = g;
  const hd = document.getElementById('header-date');
  if (hd) hd.textContent = new Date().toLocaleDateString('en-US', { weekday:'long', month:'long', day:'numeric', year:'numeric' });
  const mt = document.getElementById('med-today-date');
  if (mt) mt.textContent = new Date().toLocaleDateString('en-US', { weekday:'short', month:'short', day:'numeric' });
}

function setDates() {
  const today = new Date().toISOString().split('T')[0];
  ['report-date','med-start-date','activity-date'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = today;
  });
}

// ── Navigation ──
function setupNavigation() {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', e => {
      e.preventDefault();
      switchView(item.dataset.view);
    });
  });
}

function switchView(view) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const viewEl = document.getElementById(`view-${view}`);
  const navEl = document.querySelector(`[data-view="${view}"]`);
  if (viewEl) viewEl.classList.add('active');
  if (navEl) navEl.classList.add('active');
  if (view === 'dashboard')   loadDashboard();
  if (view === 'reports')     loadReports();
  if (view === 'medicines')   loadMedicines();
  if (view === 'fitness')     { loadFitness(); loadConnectedServices(); }
  if (view === 'consistency') loadConsistency();
  if (view === 'food')      loadFoodTracker();
  if (view === 'thoughts')  loadThoughts();
  if (view === 'todos')         loadTodos();
  if (view === 'progress')      loadProgress();
  if (view === 'report')        loadReport();
  if (view === 'notifications') loadNotifications();
  if (view === 'export')        initExportView();
}

// ── Dashboard ──