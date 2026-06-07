// Auto-generated module — see static/js/app.js for full app
// Part of MediScan Health OS

// Goal progress page (charts) + weekly health report (PDF export)

async function loadProgress() {
  const el = document.getElementById('progress-content');
  if (!el) return;
  el.innerHTML = '<div style="padding:40px;text-align:center;color:var(--gray-400)"><div class="report-gen-spinner" style="margin:0 auto 12px"></div>Calculating your progress…</div>';
  const r = await fetch('/api/progress').then(r => r.json()).catch(() => null);
  if (!r) { el.innerHTML = '<div style="padding:40px;color:var(--gray-400)">Could not load progress data.</div>'; return; }
  _progressData = r;
  renderProgress(r);
}

function renderProgress(r) {
  const el = document.getElementById('progress-content');
  if (!el) return;

  const p = _progressPeriod; // 'month' or 'week'
  const GOAL_LABELS = {lose_fast:'Lose weight fast 🔥',lose:'Lose weight 📉',maintain:'Maintain weight ⚖️',gain:'Gain muscle 📈',gain_fast:'Build mass 💪'};

  // ── Score calculations ──
  const workoutPct = p === 'month' ? (r.workouts?.frequency_pct||0) : Math.round((r.workouts?.daily?.slice(-7).filter(d=>d.cal>0).length||0)/7*100);
  const sleepAvg   = p === 'month' ? r.sleep?.avg_30 : r.sleep?.avg_7;
  const sleepPct   = sleepAvg ? Math.min(Math.round(sleepAvg/7.5*100),100) : 0;
  const habitPct   = r.habits?.completion_pct || 0;
  const calPct     = Math.min(r.nutrition?.adherence_pct||0, 100);
  const scores     = [workoutPct, sleepPct, habitPct, calPct].filter(s => s > 0);
  const overall    = scores.length ? Math.round(scores.reduce((a,b)=>a+b)/scores.length) : 0;
  const overallColor = overall >= 75 ? '#22C55E' : overall >= 50 ? '#F59E0B' : '#EF4444';
  const overallLabel = overall >= 75 ? 'On track! 🎯' : overall >= 50 ? 'Getting there 💪' : 'Needs focus 📋';

  // Update score strip
  const strip = document.getElementById('prog-score-strip');
  if (strip) {
    strip.style.display = 'flex';
    // Overall ring
    const ringEl = document.getElementById('psi-overall-ring');
    const r2 = 20, C = 2*Math.PI*r2;
    const offset = C - (overall/100)*C;
    if (ringEl) ringEl.innerHTML = `<svg width="56" height="56" viewBox="0 0 56 56">
      <circle cx="28" cy="28" r="${r2}" fill="none" stroke="rgba(255,255,255,.15)" stroke-width="5"/>
      <circle cx="28" cy="28" r="${r2}" fill="none" stroke="${overallColor}" stroke-width="5"
        stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"
        stroke-linecap="round" transform="rotate(-90 28 28)"/>
    </svg>
    <div class="prog-score-inner"><div class="prog-score-num">${overall}</div><div class="prog-score-sub">score</div></div>`;
    setText('psi-sleep',    sleepAvg ? sleepAvg+'h' : '—');
    setText('psi-workouts', r.workouts?.this_month + (p==='month'?' days':''));
    setText('psi-habits',   habitPct+'%');
    setText('psi-cals',     calPct+'%');
    const sub = document.getElementById('prog-subtitle');
    if (sub) sub.textContent = overallLabel;
  }

  // ── Build 30 or 7 days of data slices ──
  const daysSlice = d => p === 'week' ? (d||[]).slice(-7) : d;

  // Weight chart data
  const weights = r.weight_trend || [];
  const wMin = weights.length ? Math.min(...weights.map(w=>w.weight)) - 1 : 0;
  const wMax = weights.length ? Math.max(...weights.map(w=>w.weight)) + 1 : 100;

  // Build SVG weight chart
  let weightSVG = '';
  if (weights.length >= 2) {
    const W = 600, H = 80;
    const pts = weights.map((w, i) => {
      const x = i/(weights.length-1) * W;
      const y = H - ((w.weight - wMin)/(wMax - wMin||1)) * (H-12) - 6;
      return {x, y, w};
    });
    const path = pts.map((p,i) => (i===0?'M':'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1)).join(' ');
    const area = `M${pts[0].x},${H} ` + pts.map(p=>`L${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ') + ` L${pts[pts.length-1].x},${H} Z`;
    const dots = pts.map(p => `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4" fill="var(--teal-500)" stroke="#fff" stroke-width="2" class="weight-dot"><title>${p.w.weight}kg · ${p.w.date}</title></circle>`).join('');
    const firstDate = weights[0]?.date?.slice(5) || '';
    const lastDate  = weights[weights.length-1]?.date?.slice(5) || '';
    weightSVG = `<div style="position:relative">
      <svg viewBox="0 0 ${W} ${H+20}" class="prog-weight-chart" preserveAspectRatio="none" style="width:100%;height:90px">
        <defs><linearGradient id="wGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--teal-400)" stop-opacity=".25"/><stop offset="100%" stop-color="var(--teal-400)" stop-opacity="0"/></linearGradient></defs>
        <path d="${area}" fill="url(#wGrad)"/>
        <path d="${path}" fill="none" stroke="var(--teal-500)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
        ${dots}
        <text x="0" y="${H+14}" font-size="10" fill="#9CA3AF">${firstDate}</text>
        <text x="${W}" y="${H+14}" font-size="10" fill="#9CA3AF" text-anchor="end">${lastDate}</text>
        <text x="0" y="10" font-size="10" fill="#9CA3AF">${wMax.toFixed(1)}</text>
        <text x="0" y="${H-4}" font-size="10" fill="#9CA3AF">${wMin.toFixed(1)}</text>
      </svg>
    </div>`;
  } else {
    weightSVG = `<div style="padding:24px 0;text-align:center;color:var(--gray-300);font-size:13px">Log body metrics to see trend</div>`;
  }

  // Workout mini bars (30 days)
  const workoutDays  = daysSlice(r.workouts?.daily) || [];
  const maxCal = Math.max(...workoutDays.map(d=>d.cal), 1);
  const workoutBars  = workoutDays.map((d, i) => {
    const pct   = d.cal > 0 ? Math.max(Math.round((d.cal/maxCal)*100), 12) : 0;
    const color = d.cal > 0 ? 'var(--teal-500)' : 'var(--gray-100)';
    const label = i === 0 || i === workoutDays.length-1 ? d.date.slice(5) : '';
    return `<div style="display:flex;flex-direction:column;align-items:center;flex:1;gap:2px">
      <div class="prog-mini-bar" style="height:${pct}%;background:${color};width:100%" title="${d.date}: ${d.cal} kcal"></div>
      <div style="font-size:8px;color:var(--gray-300);white-space:nowrap">${label}</div>
    </div>`;
  }).join('');

  // Sleep dots
  const sleepDays = daysSlice(r.sleep?.daily) || [];
  const SLEEP_COLORS = {1:'#EF4444',2:'#F59E0B',3:'#D1D5DB',4:'#34D399',5:'#0E8F7E'};
  const sleepDots = sleepDays.map(s => {
    const h = Math.min(s.h/9, 1) * 100;
    return `<div class="prog-sleep-dot" style="height:${Math.max(h,8)}%;background:${SLEEP_COLORS[s.q]||'#D1D5DB'}" title="${s.date}: ${s.h}h · Quality ${s.q}/5"></div>`;
  }).join('');
  const noSleepMsg = sleepDays.length === 0 ? `<div style="padding:20px 0;text-align:center;color:var(--gray-300);font-size:13px">No sleep data — log from Thoughts page</div>` : '';

  // Calorie adherence bars
  const calDays = daysSlice(r.nutrition?.daily) || [];
  const targetCal = r.nutrition?.target_daily || 2000;
  const calBars = calDays.map((d,i) => {
    const pct = d.cal > 0 ? Math.min(Math.round((d.cal/targetCal)*100), 150) : 0;
    const color = pct > 115 ? '#EF4444' : pct > 95 ? '#22C55E' : pct > 70 ? '#F59E0B' : 'var(--gray-200)';
    return `<div class="prog-cal-bar ${pct>115?'over':''}" style="height:${Math.max(pct,4)}%;background:${color}" title="${d.date}: ${d.cal} kcal (${pct}% of goal)"></div>`;
  }).join('');
  const noCalMsg = calDays.every(d=>d.cal===0) ? `<div style="padding:20px 0;text-align:center;color:var(--gray-300);font-size:13px">Log meals to see calorie data</div>` : '';

  // Habit breakdown
  const habits = r.habits?.detail || [];
  const habitRows = habits.map(h => `
    <div class="prog-habit-row">
      <div class="prog-habit-emoji">${h.emoji}</div>
      <div class="prog-habit-name">${escHtml(h.name)}</div>
      <div class="prog-habit-bar-wrap">
        <div class="prog-habit-bar" style="width:${h.pct}%;background:${h.color}"></div>
      </div>
      <div class="prog-habit-pct">${h.pct}%</div>
      <div class="prog-habit-streak">🔥${h.streak}</div>
    </div>`).join('');
  const noHabitMsg = habits.length === 0 ? `<div style="padding:20px 0;text-align:center;color:var(--gray-300);font-size:13px">No habits tracked — add habits on the Consistency page</div>` : '';

  // Status badge helper
  const badge = (pct, good=70, warn=40) => {
    const cls = pct >= good ? 'good' : pct >= warn ? 'warn' : 'bad';
    const txt = pct >= good ? '✅ On target' : pct >= warn ? '⚠️ Almost there' : '📋 Needs work';
    return `<span class="prog-status-badge ${cls}">${txt}</span>`;
  };

  const latest = weights[weights.length-1];

  el.innerHTML = `
  <div class="prog-sections">

    <!-- Goal header -->
    <div class="prog-section">
      <div class="prog-section-head">
        <div class="prog-section-title">🎯 Current Goal</div>
        <div class="prog-section-meta">${r.targets?.target_calories||'—'} kcal/day · ${r.targets?.protein_g||'—'}g protein</div>
      </div>
      <div class="prog-section-body" style="display:flex;align-items:center;gap:20px">
        <div style="font-size:22px;font-weight:700;color:var(--gray-900)">${GOAL_LABELS[r.profile?.goal]||'—'}</div>
        ${latest ? `<div style="font-size:13px;color:var(--gray-500)">Current weight: <strong>${latest.weight}kg</strong> · BMI: <strong>${latest.bmi||'—'}</strong></div>` : ''}
        <div style="margin-left:auto;font-size:13px;color:${overallColor};font-weight:700">${overallLabel}</div>
      </div>
    </div>

    <!-- Weight + Workouts row -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">

      <div class="prog-section">
        <div class="prog-section-head">
          <div class="prog-section-title">⚖️ Weight Trend</div>
          ${latest ? badge(r.profile?.goal==='lose'||r.profile?.goal==='lose_fast' ? (weights.length>=2 && weights[0].weight > latest.weight ? 100 : 20) : 70) : ''}
        </div>
        <div class="prog-section-body">${weightSVG}</div>
      </div>

      <div class="prog-section">
        <div class="prog-section-head">
          <div class="prog-section-title">🏃 Workout Frequency</div>
          ${badge(workoutPct)}
        </div>
        <div class="prog-section-body">
          <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:12px">
            <span style="font-size:32px;font-weight:800;font-family:'DM Serif Display',serif;color:var(--gray-900)">${p==='month'?r.workouts?.this_month:workoutDays.filter(d=>d.cal>0).length}</span>
            <span style="font-size:14px;color:var(--gray-400)">active days · target 4/week</span>
          </div>
          <div style="display:flex;align-items:flex-end;gap:2px;height:50px">${workoutBars}</div>
          <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--gray-300);margin-top:2px">
            <span>${workoutDays[0]?.date?.slice(5)||''}</span><span>${workoutDays[workoutDays.length-1]?.date?.slice(5)||''}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Sleep + Calories row -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">

      <div class="prog-section">
        <div class="prog-section-head">
          <div class="prog-section-title">🌙 Sleep Consistency</div>
          ${badge(sleepPct, 90, 70)}
        </div>
        <div class="prog-section-body">
          <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:12px">
            <span style="font-size:32px;font-weight:800;font-family:'DM Serif Display',serif;color:var(--gray-900)">${sleepAvg||'—'}</span>
            <span style="font-size:14px;color:var(--gray-400)">h avg · target 7.5h</span>
          </div>
          ${noSleepMsg}
          ${sleepDays.length ? `<div style="display:flex;align-items:flex-end;gap:3px;height:60px">${sleepDots}</div>
          <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--gray-300);margin-top:4px">
            <span>😩 Poor</span>
            <span style="display:flex;gap:8px">
              <span style="width:10px;height:10px;border-radius:2px;background:#EF4444;display:inline-block"></span>Poor
              <span style="width:10px;height:10px;border-radius:2px;background:#34D399;display:inline-block"></span>Good
              <span style="width:10px;height:10px;border-radius:2px;background:#0E8F7E;display:inline-block"></span>Great
            </span>
          </div>` : ''}
        </div>
      </div>

      <div class="prog-section">
        <div class="prog-section-head">
          <div class="prog-section-title">🍽️ Calorie Adherence</div>
          ${badge(calPct)}
        </div>
        <div class="prog-section-body">
          <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:12px">
            <span style="font-size:32px;font-weight:800;font-family:'DM Serif Display',serif;color:var(--gray-900)">${calPct}%</span>
            <span style="font-size:14px;color:var(--gray-400)">of daily goal (${targetCal} kcal)</span>
          </div>
          ${noCalMsg}
          ${!noCalMsg ? `<div style="position:relative">
            <div style="display:flex;align-items:flex-end;gap:2px;height:60px">${calBars}</div>
            <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--gray-300);margin-top:2px">
              <span>${calDays[0]?.date?.slice(5)||''}</span>
              <span style="display:flex;gap:8px"><span style="color:#22C55E">■ On target</span><span style="color:#EF4444">■ Over</span><span style="color:var(--gray-300)">■ Not logged</span></span>
              <span>${calDays[calDays.length-1]?.date?.slice(5)||''}</span>
            </div>
          </div>` : ''}
        </div>
      </div>
    </div>

    <!-- Habit breakdown -->
    <div class="prog-section">
      <div class="prog-section-head">
        <div class="prog-section-title">⭐ Habit Completion</div>
        ${badge(habitPct)}
      </div>
      <div class="prog-section-body">
        ${noHabitMsg}
        ${habits.length ? `<div style="display:flex;align-items:baseline;gap:8px;margin-bottom:16px">
          <span style="font-size:32px;font-weight:800;font-family:'DM Serif Display',serif;color:var(--gray-900)">${habitPct}%</span>
          <span style="font-size:14px;color:var(--gray-400)">overall · ${r.habits?.total||0} habits · ${r.habits?.done_count||0} total check-ins</span>
        </div>
        <div class="prog-habit-rows">${habitRows}</div>` : ''}
      </div>
    </div>

    ${r.refill_alerts?.length ? `
    <div class="prog-section" style="border-color:#F59E0B">
      <div class="prog-section-head">
        <div class="prog-section-title">💊 Medicine Refill Alerts</div>
        <span class="prog-status-badge bad">⚠️ Action needed</span>
      </div>
      <div class="prog-section-body">
        ${r.refill_alerts.map(m=>`
          <div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--gray-50)">
            <span style="font-size:20px">${m.icon||'💊'}</span>
            <div style="flex:1"><div style="font-size:14px;font-weight:600">${escHtml(m.name)}</div><div style="font-size:12px;color:var(--red-500)">${m.pill_count} pills · ${m.days_left} days remaining</div></div>
            <button class="btn-outline" style="font-size:12px;padding:5px 12px" onclick="openRestockModal('${m.id}','${escHtml(m.name)}',${m.pill_count},${m.pills_per_dose||1},${m.refill_threshold||7})">Restock →</button>
          </div>`).join('')}
      </div>
    </div>` : ''}

  </div>`;
}


// ════════════════════════════════════════════════════════════
// WEEKLY HEALTH REPORT
// ════════════════════════════════════════════════════════════

// ════════════════════════════════════════════════════════════
// WEEKLY HEALTH REPORT — Rich in-app display + PDF export
// ════════════════════════════════════════════════════════════

async function loadReport() {
  const el = document.getElementById('report-content');
  if (!el) return;
  el.innerHTML = `<div class="report-generating">
    <div class="report-gen-spinner"></div>
    <div class="report-gen-text">Analysing your last 7 days…</div>
  </div>`;

  const r = await fetch('/api/report/weekly').then(r=>r.json()).catch(()=>null);
  if (!r) { el.innerHTML = '<div style="padding:40px;color:var(--gray-400)">Could not load report data.</div>'; return; }

  const Q_LABEL = {1:'Very Poor',2:'Poor',3:'Fair',4:'Good',5:'Excellent'};
  const Q_EMOJI = {1:'😩',2:'😕',3:'😐',4:'😊',5:'😴'};
  const GOAL_LABELS = {lose_fast:'Lose weight fast',lose:'Lose weight',maintain:'Maintain weight',gain:'Gain muscle',gain_fast:'Build mass'};

  // Compute overall health score (0–100) from available data
  let scoreComponents = [], scoreTotal = 0;
  if (r.sleep?.avg_hours) {
    const s = Math.min(r.sleep.avg_hours / 7.5, 1) * 100;
    scoreComponents.push(s); scoreTotal += s;
  }
  if (r.fitness?.workout_days != null) {
    const s = Math.min(r.fitness.workout_days / 4, 1) * 100;
    scoreComponents.push(s); scoreTotal += s;
  }
  if (r.nutrition?.adherence_pct != null) {
    const s = Math.min(r.nutrition.adherence_pct, 100);
    scoreComponents.push(s); scoreTotal += s;
  }
  if (r.habits?.completion_pct != null) {
    scoreComponents.push(r.habits.completion_pct); scoreTotal += r.habits.completion_pct;
  }
  const healthScore = scoreComponents.length ? Math.round(scoreTotal / scoreComponents.length) : null;
  const scoreColor = healthScore >= 80 ? '#22C55E' : healthScore >= 60 ? '#F59E0B' : '#EF4444';
  const scoreLabel = healthScore >= 80 ? 'Excellent' : healthScore >= 60 ? 'Good' : healthScore >= 40 ? 'Fair' : 'Needs attention';

  // Build the period label
  const d1 = new Date(r.period?.start + 'T12:00:00');
  const d2 = new Date(r.period?.end + 'T12:00:00');
  const periodStr = d1.toLocaleDateString('en-US',{month:'short',day:'numeric'}) + ' – ' +
                    d2.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'});
  const generatedStr = new Date().toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric',year:'numeric'});

  // Metric bar helper
  const metricBar = (val, max, color) => {
    const pct = Math.min(Math.round((val/max)*100),100);
    return `<div class="rpt-bar-wrap"><div class="rpt-bar-fill" style="width:${pct}%;background:${color}"></div></div>`;
  };

  el.innerHTML = `
  <!-- Action bar -->
  <div class="report-action-bar">
    <div class="report-action-bar-left">
      <div class="report-period-chip">📅 ${periodStr}</div>
      ${healthScore!=null ? `<div class="report-score-chip" style="background:${scoreColor}18;color:${scoreColor};border-color:${scoreColor}40">
        <span style="font-weight:800">${healthScore}</span>/100 · ${scoreLabel}
      </div>` : ''}
    </div>
    <button class="btn-primary" onclick="printReport()">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
      Download PDF
    </button>
  </div>

  <!-- Printable report starts here -->
  <div id="printable-report" class="rpt-doc">

    <!-- Header -->
    <div class="rpt-header">
      <div class="rpt-header-left">
        <div class="rpt-patient-name">${escHtml(r.profile?.name||'Health Report')}</div>
        <div class="rpt-period">Weekly Summary · ${periodStr}</div>
        <div class="rpt-generated">Generated ${generatedStr}</div>
        <div class="rpt-goal-chip">${GOAL_LABELS[r.profile?.goal]||'—'}</div>
      </div>
      <div class="rpt-header-right">
        ${healthScore != null ? `
        <div class="rpt-score-circle" style="--score-color:${scoreColor}">
          <svg viewBox="0 0 80 80" class="rpt-score-ring">
            <circle cx="40" cy="40" r="34" fill="none" stroke="rgba(255,255,255,.15)" stroke-width="7"/>
            <circle cx="40" cy="40" r="34" fill="none" stroke="${scoreColor}" stroke-width="7"
              stroke-dasharray="${2*Math.PI*34}" stroke-dashoffset="${2*Math.PI*34*(1-healthScore/100)}"
              stroke-linecap="round" transform="rotate(-90 40 40)"/>
          </svg>
          <div class="rpt-score-inner">
            <div class="rpt-score-num">${healthScore}</div>
            <div class="rpt-score-sub">Health score</div>
          </div>
        </div>` : ''}
      </div>
    </div>

    <!-- 6-metric grid -->
    <div class="rpt-grid">

      <!-- Sleep -->
      <div class="rpt-section">
        <div class="rpt-section-head">🌙 Sleep</div>
        <div class="rpt-big">${r.sleep?.avg_hours ?? '—'}<span class="rpt-unit">h avg</span></div>
        <div class="rpt-sub">${r.sleep?.nights||0} nights logged</div>
        ${r.sleep?.avg_hours ? metricBar(r.sleep.avg_hours, 9, '#818CF8') : ''}
        <div class="rpt-detail-rows">
          ${r.sleep?.avg_quality ? `<div class="rpt-detail-row"><span>Quality</span><span>${Q_EMOJI[Math.round(r.sleep.avg_quality)]} ${Q_LABEL[Math.round(r.sleep.avg_quality)]}</span></div>` : ''}
          <div class="rpt-detail-row"><span>Target</span><span>7.5h / night</span></div>
          ${r.sleep?.avg_hours ? `<div class="rpt-detail-row ${r.sleep.avg_hours>=7?'rpt-row--good':'rpt-row--warn'}"><span>Status</span><span>${r.sleep.avg_hours>=7?'✅ On target':'⚠️ Below target'}</span></div>` : ''}
        </div>
      </div>

      <!-- Fitness -->
      <div class="rpt-section">
        <div class="rpt-section-head">🏃 Fitness</div>
        <div class="rpt-big">${r.fitness?.workout_days??0}<span class="rpt-unit">active days</span></div>
        <div class="rpt-sub">${r.fitness?.activities||0} workouts completed</div>
        ${metricBar(r.fitness?.workout_days||0, 7, '#34D399')}
        <div class="rpt-detail-rows">
          <div class="rpt-detail-row"><span>Calories burned</span><span>${(r.fitness?.calories_burned||0).toLocaleString()} kcal</span></div>
          <div class="rpt-detail-row"><span>Target</span><span>4 days / week</span></div>
          ${r.fitness?.workout_days!=null ? `<div class="rpt-detail-row ${r.fitness.workout_days>=4?'rpt-row--good':'rpt-row--warn'}"><span>Status</span><span>${r.fitness.workout_days>=4?'✅ On target':'⚠️ Below target'}</span></div>` : ''}
        </div>
      </div>

      <!-- Nutrition -->
      <div class="rpt-section">
        <div class="rpt-section-head">🍽️ Nutrition</div>
        <div class="rpt-big">${r.nutrition?.adherence_pct != null ? Math.round(r.nutrition.adherence_pct)+'%' : '—'}<span class="rpt-unit">adherence</span></div>
        <div class="rpt-sub">${(r.nutrition?.calories_eaten||0).toLocaleString()} kcal consumed</div>
        ${r.nutrition?.adherence_pct != null ? metricBar(r.nutrition.adherence_pct, 100, '#FB923C') : ''}
        <div class="rpt-detail-rows">
          <div class="rpt-detail-row"><span>Weekly target</span><span>${(r.nutrition?.weekly_target||0).toLocaleString()} kcal</span></div>
          <div class="rpt-detail-row"><span>Daily target</span><span>${(r.nutrition?.target||0).toLocaleString()} kcal/day</span></div>
          <div class="rpt-detail-row"><span>Avg hydration</span><span>${r.nutrition?.avg_hydration_ml||0} ml/day</span></div>
        </div>
      </div>

      <!-- Habits -->
      <div class="rpt-section">
        <div class="rpt-section-head">⭐ Habits</div>
        <div class="rpt-big">${r.habits?.completion_pct != null ? r.habits.completion_pct+'%' : '—'}<span class="rpt-unit">completion</span></div>
        <div class="rpt-sub">${r.habits?.total||0} habits tracked</div>
        ${r.habits?.completion_pct != null ? metricBar(r.habits.completion_pct, 100, '#A78BFA') : ''}
        <div class="rpt-detail-rows">
          <div class="rpt-detail-row"><span>Done</span><span>${r.habits?.done_count||0} of ${(r.habits?.total||0)*7} check-ins</span></div>
          ${r.habits?.completion_pct != null ? `<div class="rpt-detail-row ${r.habits.completion_pct>=70?'rpt-row--good':'rpt-row--warn'}"><span>Status</span><span>${r.habits.completion_pct>=70?'✅ Great':'⚠️ Keep going'}</span></div>` : ''}
        </div>
      </div>

      <!-- Symptoms -->
      <div class="rpt-section">
        <div class="rpt-section-head">🩺 Symptoms</div>
        <div class="rpt-big">${r.symptoms?.length??0}<span class="rpt-unit">unique</span></div>
        <div class="rpt-sub">this week</div>
        <div class="rpt-symptom-list">
          ${r.symptoms?.length ? r.symptoms.map(s => `
            <div class="rpt-symptom-row">
              <span class="rpt-symptom-name">${escHtml(s.name)}</span>
              <span class="rpt-symptom-count">×${s.count}</span>
            </div>`).join('') : '<div style="color:var(--gray-400);font-size:13px;margin-top:8px">No symptoms logged ✅</div>'}
        </div>
      </div>

      <!-- Body & Vitals -->
      <div class="rpt-section">
        <div class="rpt-section-head">⚖️ Body & Vitals</div>
        ${r.body?.weight_kg ? `
          <div class="rpt-big">${r.body.weight_kg}<span class="rpt-unit">kg</span></div>
          <div class="rpt-sub">BMI: ${r.body.bmi ?? '—'}</div>` :
          '<div class="rpt-sub" style="margin-top:8px">No body metrics logged</div>'}
        <div class="rpt-detail-rows" style="margin-top:10px">
          ${r.vitals?.blood_pressure ? `<div class="rpt-detail-row"><span>Blood Pressure</span><span>${r.vitals.blood_pressure.value1}/${r.vitals.blood_pressure.value2} mmHg</span></div>` : ''}
          ${r.vitals?.blood_sugar ? `<div class="rpt-detail-row"><span>Blood Sugar</span><span>${r.vitals.blood_sugar.value1} mg/dL</span></div>` : ''}
          ${r.vitals?.heart_rate ? `<div class="rpt-detail-row"><span>Heart Rate</span><span>${r.vitals.heart_rate.value1} bpm</span></div>` : ''}
          ${!r.vitals?.blood_pressure && !r.vitals?.blood_sugar && !r.vitals?.heart_rate ? '<div style="color:var(--gray-400);font-size:13px">No vitals recorded</div>' : ''}
        </div>
      </div>

    </div>

    <!-- Doctor note footer -->
    <div class="rpt-footer">
      <div class="rpt-footer-note">
        <strong>For your doctor:</strong> This is a personal health summary generated by MediScan Health OS.
        Data is self-reported and should be reviewed alongside clinical assessments.
      </div>
      <div class="rpt-footer-brand">MediScan Health OS · ${generatedStr}</div>
    </div>

  </div><!-- /printable-report -->
  `;
}

function printReport() {
  const el = document.getElementById('printable-report');
  if (!el) { showToast('Click "Generate Report" first', 'error'); return; }

  // Build a full-CSS print window
  const win = window.open('', '_blank', 'width=900,height=700');
  win.document.write(`<!DOCTYPE html><html><head>
<title>Weekly Health Report</title>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'DM Sans',sans-serif;background:#fff;color:#1a1a1a;padding:28px}
  .rpt-doc{max-width:820px;margin:0 auto}

  /* Header */
  .rpt-header{display:flex;align-items:flex-start;justify-content:space-between;
    background:linear-gradient(135deg,#0D1117,#0A2E28);border-radius:12px;
    padding:28px 32px;margin-bottom:24px;color:#fff}
  .rpt-patient-name{font-size:24px;font-weight:700;margin-bottom:6px}
  .rpt-period{font-size:14px;color:rgba(255,255,255,.6);margin-bottom:3px}
  .rpt-generated{font-size:12px;color:rgba(255,255,255,.4);margin-bottom:10px}
  .rpt-goal-chip{display:inline-block;padding:3px 12px;border-radius:99px;
    background:rgba(255,255,255,.1);font-size:12px;color:rgba(255,255,255,.7)}
  .rpt-score-circle{position:relative;width:80px;height:80px}
  .rpt-score-ring{position:absolute;inset:0;width:80px;height:80px}
  .rpt-score-inner{position:absolute;inset:0;display:flex;flex-direction:column;
    align-items:center;justify-content:center}
  .rpt-score-num{font-size:22px;font-weight:800;color:#fff}
  .rpt-score-sub{font-size:9px;color:rgba(255,255,255,.5);text-transform:uppercase;letter-spacing:.05em}

  /* Grid */
  .rpt-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:20px}
  .rpt-section{border:1px solid #e5e7eb;border-radius:10px;padding:18px;break-inside:avoid}
  .rpt-section-head{font-size:11px;font-weight:700;text-transform:uppercase;
    letter-spacing:.07em;color:#6b7280;margin-bottom:10px}
  .rpt-big{font-size:30px;font-weight:800;color:#111;line-height:1}
  .rpt-unit{font-size:14px;font-weight:500;color:#6b7280;margin-left:4px}
  .rpt-sub{font-size:12px;color:#9ca3af;margin-top:3px;margin-bottom:8px}
  .rpt-bar-wrap{height:6px;background:#f3f4f6;border-radius:99px;overflow:hidden;margin:8px 0}
  .rpt-bar-fill{height:100%;border-radius:99px}
  .rpt-detail-rows{display:flex;flex-direction:column;gap:5px;margin-top:8px}
  .rpt-detail-row{display:flex;justify-content:space-between;font-size:12px;color:#374151}
  .rpt-detail-row span:first-child{color:#6b7280}
  .rpt-row--good span:last-child{color:#16a34a;font-weight:600}
  .rpt-row--warn span:last-child{color:#d97706;font-weight:600}
  .rpt-symptom-list{display:flex;flex-direction:column;gap:4px;margin-top:8px}
  .rpt-symptom-row{display:flex;justify-content:space-between;font-size:12.5px}
  .rpt-symptom-name{color:#374151}
  .rpt-symptom-count{color:#ef4444;font-weight:600}

  /* Footer */
  .rpt-footer{border-top:1px solid #e5e7eb;padding-top:14px;
    display:flex;justify-content:space-between;align-items:flex-start;gap:20px}
  .rpt-footer-note{font-size:11.5px;color:#6b7280;flex:1;line-height:1.6}
  .rpt-footer-brand{font-size:11px;color:#9ca3af;white-space:nowrap;padding-top:2px}

  @media print{
    body{padding:0}
    @page{size:A4;margin:16mm}
    .rpt-doc{max-width:100%}
  }
</style>
</head><body>
<div class="rpt-doc">${el.innerHTML}</div>
</body></html>`);
  win.document.close();
  setTimeout(() => { win.print(); }, 600);
}

// ════════════════════════════════════════════════════════════
// MEDICINE STOCK — Check on app load
// ════════════════════════════════════════════════════════════
// Patch loadMedicines to check low stock after loading
const __loadMeds = loadMedicines;
loadMedicines = async function() {
  await __loadMeds.apply(this, arguments);
  checkLowStock();
};

// ════════════════════════════════════════════════════════════
// MEDICINE STOCK — Restock modal + low stock banner
// ════════════════════════════════════════════════════════════