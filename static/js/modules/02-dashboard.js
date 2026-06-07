// Auto-generated module — see static/js/app.js for full app
// Part of MediScan Health OS

// Dashboard: hero cards, wellness strip, weekly chart, calorie breakdown

async function loadDashboard() {
  const today = new Date().toISOString().split('T')[0];
  const [doses, fitnessStats, reportStats, foodDay, profile] = await Promise.all([
    fetch('/api/medicines/today').then(r => r.json()).catch(() => []),
    fetch('/api/fitness/stats').then(r => r.json()).catch(() => ({})),
    fetch('/api/stats').then(r => r.json()).catch(() => ({})),
    fetch(`/api/food/log/${today}`).then(r => r.json()).catch(() => null),
    fetch('/api/food/profile').then(r => r.json()).catch(() => null)
  ]);

  // Hero cards — show medicines card only if user has medicines
  const remaining = doses.filter(d => !d.taken).length;
  const dosesCard   = document.getElementById('dash-doses-card');
  const reportsCard = document.getElementById('dash-reports-card');
  if (doses.length > 0 && dosesCard) {
    dosesCard.style.display = '';
    setText('dash-doses-today', doses.length);
    setText('dash-doses-sub', `${remaining} remaining today`);
  }
  setText('dash-active-min', fitnessStats.week?.duration || 0);
  // Show reports card only if user has at least one report
  const totalReports = reportStats.total || 0;
  if (totalReports > 0 && reportsCard) {
    reportsCard.style.display = '';
    setText('dash-reports', totalReports);
  }

  // Calorie balance hero card
  const todayCalBurned  = fitnessStats.week?.calories || 0;  // weekly, approximate
  const todayCalEaten   = foodDay?.summary?.totals?.calories || 0;
  const targetCal       = profile?.targets?.target_calories || 2000;
  const netBalance      = Math.round(targetCal - todayCalEaten); // deficit = target - eaten
  const deficitCard     = document.getElementById('dash-caldeficit-card');
  const deficitEl       = document.getElementById('dash-cal-deficit');
  const deficitSubEl    = document.getElementById('dash-cal-deficit-sub');
  if (deficitEl) deficitEl.textContent = (netBalance >= 0 ? '' : '+') + Math.abs(netBalance);
  if (deficitSubEl) deficitSubEl.textContent = netBalance >= 0 ? 'kcal remaining' : 'kcal over goal';
  if (deficitCard) {
    deficitCard.classList.remove('hero-card--amber','hero-card--green','hero-card--red');
    deficitCard.classList.add(netBalance >= 0 ? 'hero-card--amber' : 'hero-card--red');
  }

  // Dashboard nutrition bar
  if (foodDay && foodDay.summary?.log_count > 0) {
    const t = foodDay.summary.totals;
    const nb = document.getElementById('dash-nutrition-bar');
    if (nb) nb.style.display = 'flex';
    setText('dnb-cal',   Math.round(t.calories));
    setText('dnb-prot',  Math.round(t.protein) + 'g');
    setText('dnb-carb',  Math.round(t.carbs) + 'g');
    setText('dnb-fat',   Math.round(t.fat) + 'g');
    setText('dnb-fiber', Math.round(t.fiber) + 'g');
  }

  // Medicine list
  const medList = document.getElementById('dash-medicine-list');
  if (medList) {
    if (doses.length === 0) {
      medList.innerHTML = '<div style="color:var(--gray-400);font-size:13px;padding:16px 0;text-align:center">No medicines scheduled today.<br><a href="#" onclick="switchView(\'medicines\');return false" style="color:var(--teal-600)">Add medicine →</a></div>';
    } else {
      medList.innerHTML = doses.slice(0,5).map(d => `
        <div class="dash-dose-item ${d.taken ? 'taken' : ''}" onclick="markDoseTaken('${d.med_id}','${d.time}',this)">
          <div class="dash-dose-icon">${d.icon}</div>
          <div class="dash-dose-info">
            <div class="dash-dose-name">${escHtml(d.med_name)}</div>
            <div class="dash-dose-detail">${d.dosage} ${d.unit}${d.with_food ? ' · with food' : ''}</div>
          </div>
          <div class="dash-dose-time">${d.time}</div>
          <div class="dash-dose-check ${d.taken ? 'done' : ''}">${d.taken ? '✓' : ''}</div>
        </div>
      `).join('');
    }
  }

  // Suggestions
  const sugs = document.getElementById('dash-suggestions');
  if (sugs) renderSuggestions(sugs, fitnessStats.suggestions || []);

  // Weekly chart
  renderWeeklyChart(fitnessStats.weekly_days || {});

  // Nav badge
  const badge = document.getElementById('nav-dose-badge');
  if (badge) {
    if (remaining > 0) { badge.textContent = remaining; badge.style.display = 'inline-block'; }
    else badge.style.display = 'none';
  }

  // Consistency streak badge in dashboard header
  fetch('/api/fitness/consistency').then(r => r.json()).then(con => {
    const sb = document.getElementById('dash-streak-badge');
    if (sb) {
      const streak = con.current_streak || 0;
      if (streak > 0) { sb.textContent = `🔥${streak}`; sb.style.display = 'inline-block'; }
      else sb.style.display = 'none';
    }
  }).catch(() => {});
}

async function openCalorieBreakdown() {
  const today = new Date().toISOString().split('T')[0];
  const [foodDay, profile] = await Promise.all([
    fetch(`/api/food/log/${today}`).then(r => r.json()).catch(() => null),
    fetch('/api/food/profile').then(r => r.json()).catch(() => null)
  ]);

  const targets  = profile?.targets || {};
  const totals   = foodDay?.summary?.totals || {};
  const logCount = foodDay?.summary?.log_count || 0;

  const targetCal = targets.target_calories || 2000;
  const eaten     = Math.round(totals.calories || 0);
  const net       = Math.round(targetCal - eaten);      // positive = still has room
  const pct       = Math.min(Math.round((eaten / targetCal) * 100), 150);

  // Date label
  const d = new Date(today + 'T12:00:00');
  setText('cbd-date-label', d.toLocaleDateString('en-US', { weekday:'long', month:'long', day:'numeric' }));

  // Equation values
  setText('cbd-target-val', targetCal + ' kcal');
  setText('cbd-eaten-val',  eaten + ' kcal');
  setText('cbd-result-val', Math.abs(net) + ' kcal');

  const resultBlock = document.getElementById('cbd-result-block');
  const resultLabel = document.getElementById('cbd-result-label');
  const resultIcon  = document.getElementById('cbd-result-icon');
  if (resultBlock) {
    resultBlock.className = 'cbd-eq-block cbd-eq-block--result ' +
      (net < -100 ? 'surplus' : net > 100 ? 'deficit' : 'balanced');
  }
  if (resultLabel) resultLabel.textContent = net < -100 ? 'Over goal' : net > 100 ? 'Remaining' : 'Balanced!';
  if (resultIcon)  resultIcon.textContent  = net < -100 ? '⚠️' : net > 100 ? '✅' : '⚖️';

  // Progress bar
  const fill = document.getElementById('cbd-progress-fill');
  if (fill) {
    fill.style.width = Math.min(pct, 100) + '%';
    fill.classList.toggle('over', pct > 105);
  }
  setText('cbd-progress-pct-label', `${pct}% of daily goal`);
  setText('cbd-target-label', targetCal + ' kcal');

  // Macro bars
  const macros = [
    { id:'prot', val: Math.round(totals.protein||0), target: targets.protein_g||56, unit:'g' },
    { id:'carb', val: Math.round(totals.carbs||0),   target: targets.carbs_g||250,  unit:'g' },
    { id:'fat',  val: Math.round(totals.fat||0),     target: targets.fat_g||65,     unit:'g' },
    { id:'fiber',val: Math.round(totals.fiber||0),   target: targets.fiber_g||30,   unit:'g' },
  ];
  macros.forEach(m => {
    const bar = document.getElementById(`cbd-bar-${m.id}`);
    const val = document.getElementById(`cbd-${m.id}-val`);
    if (bar) bar.style.width = Math.min((m.val/m.target)*100, 100).toFixed(0) + '%';
    if (val) val.textContent = `${m.val}${m.unit} / ${m.target}${m.unit}`;
  });

  // Formula explanation
  const formulaEl = document.getElementById('cbd-formula-rows');
  if (formulaEl) {
    const p = profile?.profile || {};
    const goalLabels = { lose_fast:'Lose fast (−500)', lose:'Lose weight (−250)',
      maintain:'Maintain (±0)', gain:'Gain muscle (+250)', gain_fast:'Bulk (+500)' };
    formulaEl.innerHTML = `
      <div class="cbd-formula-row">
        <span class="cbd-formula-key">BMR (${p.gender||'male'}, ${p.age||25} yrs, ${p.weight_kg||70}kg, ${p.height_cm||170}cm)</span>
        <span class="cbd-formula-val">${targets.bmr||'—'} kcal</span>
      </div>
      <div class="cbd-formula-row">
        <span class="cbd-formula-key">× Activity multiplier (${(p.activity_level||'moderate').replace('_',' ')})</span>
        <span class="cbd-formula-val">${targets.tdee||'—'} kcal (TDEE)</span>
      </div>
      <div class="cbd-formula-row">
        <span class="cbd-formula-key">Goal adjustment</span>
        <span class="cbd-formula-val">${goalLabels[p.goal||'maintain']}</span>
      </div>
      <div class="cbd-formula-row">
        <span class="cbd-formula-key">Daily calorie target</span>
        <span class="cbd-formula-val highlight">${targetCal} kcal</span>
      </div>
    `;
  }

  // CTA text
  const ctaEl = document.getElementById('cbd-cta-text');
  if (ctaEl) {
    if (logCount === 0) {
      ctaEl.textContent = "You haven't logged any food today. Add your meals to see the full picture.";
    } else if (net > 300) {
      ctaEl.textContent = `You still have ${net} kcal left. Log your next meal to stay on track.`;
    } else if (net < -100) {
      ctaEl.textContent = `You're ${Math.abs(net)} kcal over your goal. Consider a lighter dinner.`;
    } else {
      ctaEl.textContent = "Great balance today! Keep logging to maintain accuracy.";
    }
  }

  document.getElementById('calorie-breakdown-overlay').style.display = 'flex';
}

function renderSuggestions(el, suggestions) {
  if (suggestions.length === 0) {
    el.innerHTML = '<div style="color:var(--gray-400);font-size:13px;padding:8px 0">Log workouts to get personalized suggestions.</div>';
    return;
  }
  el.innerHTML = suggestions.map(s => `
    <div class="suggestion-item suggestion-item--${s.type}">
      <div class="sug-icon">${s.icon}</div>
      <div class="sug-text">${escHtml(s.text)}</div>
    </div>
  `).join('');
}

function renderWeeklyChart(days) {
  const el = document.getElementById('weekly-chart');
  if (!el) return;
  const entries = Object.entries(days);
  if (entries.length === 0) { el.innerHTML = '<div style="color:var(--gray-400);font-size:13px">No activity data yet</div>'; return; }
  const maxCal = Math.max(...entries.map(([,v]) => v.calories), 1);
  const maxMin = Math.max(...entries.map(([,v]) => v.duration), 1);
  const dayNames = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  el.innerHTML = entries.map(([date, data], i) => {
    const calH = Math.round((data.calories / maxCal) * 90);
    const minH = Math.round((data.duration / maxMin) * 90);
    const isToday = date === new Date().toISOString().split('T')[0];
    return `
      <div class="week-bar-col">
        <div class="week-bar-wrap">
          <div class="week-bar week-bar--cal" style="height:${calH}px;opacity:${isToday?1:.7}" title="${data.calories} cal"></div>
          <div class="week-bar week-bar--min" style="height:${minH}px;opacity:${isToday?1:.7}" title="${data.duration} min"></div>
        </div>
        <div class="week-bar-label" style="font-weight:${isToday?'600':'400'};color:${isToday?'var(--teal-600)':'var(--gray-400)'}">${dayNames[i]}</div>
        <div class="week-bar-count">${data.calories > 0 ? data.calories : ''}</div>
      </div>`;
  }).join('');
}

// ── Reports ──