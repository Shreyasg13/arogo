// Auto-generated module — see static/js/app.js for full app
// Part of MediScan Health OS

// Food tracker: meal log, macro rings, suggestions, category dropdown

async function loadFoodTracker() {
  const picker = document.getElementById('food-date-picker');
  if (picker && !picker.value) picker.value = foodDate;

  const [dayData, weekData] = await Promise.all([
    fetch(`/api/food/log/${foodDate}`).then(r => r.json()).catch(() => null),
    fetch('/api/food/weekly').then(r => r.json()).catch(() => [])
  ]);

  if (!dayData) return;

  foodTargets = dayData.targets || {};
  const totals = dayData.summary?.totals || {};
  const byMeal = dayData.summary?.by_meal || {};

  // Update header label
  const lbl = document.getElementById('food-date-label');
  if (lbl) {
    const d = new Date(foodDate + 'T12:00:00');
    const today = new Date().toISOString().split('T')[0];
    lbl.textContent = foodDate === today
      ? "Today's nutrition"
      : d.toLocaleDateString('en-US', { weekday:'long', month:'short', day:'numeric' });
  }

  // Macro rings
  updateRings(totals, foodTargets);

  // Meal sections
  renderMealSections(byMeal);

  // Micronutrients
  renderMicronutrients(totals, dayData.summary?.log_count || 0);

  // Suggestions
  const sugEl = document.getElementById('food-suggestions');
  if (sugEl) {
    const sugs = dayData.suggestions || [];
    if (sugs.length === 0) {
      sugEl.innerHTML = '<div style="color:var(--gray-400);font-size:13px">Log meals to see personalised suggestions.</div>';
    } else {
      renderSuggestions(sugEl, sugs);
    }
  }

  // Weekly trend
  renderFoodWeeklyChart(weekData, foodTargets);
}

// ── Macro rings ──────────────────────────────────────────────────────────────
function updateRings(totals, targets) {
  const rings = [
    { key:'calories', id:'cal',   target: targets.target_calories || 2000, unit:'kcal', fmt: v => Math.round(v) },
    { key:'protein',  id:'prot',  target: targets.protein_g || 56,         unit:'g',    fmt: v => Math.round(v) },
    { key:'carbs',    id:'carbs', target: targets.carbs_g || 250,           unit:'g',    fmt: v => Math.round(v) },
    { key:'fat',      id:'fat',   target: targets.fat_g || 65,              unit:'g',    fmt: v => Math.round(v) },
    { key:'fiber',    id:'fiber', target: targets.fiber_g || 30,            unit:'g',    fmt: v => Math.round(v) },
  ];

  const C = 201; // stroke-dasharray = 2 * π * r(32) ≈ 201

  rings.forEach(r => {
    const val  = totals[r.key] || 0;
    const pct  = Math.min(val / r.target, 1);
    const offset = C - pct * C;
    const ring = document.getElementById(`ring-${r.id}`);
    if (ring) ring.style.strokeDashoffset = offset.toFixed(1);
    setText(`ring-${r.id}-val`,    r.fmt(val));
    setText(`ring-${r.id}-target`, `/ ${r.fmt(r.target)}${r.unit !== 'kcal' ? r.unit : ''}`);
  });
}

// ── Meal sections ─────────────────────────────────────────────────────────────
function renderMealSections(byMeal) {
  const el = document.getElementById('meal-sections');
  if (!el) return;

  const totalItems = Object.values(byMeal).reduce((s,m) => s + m.items.length, 0);
  if (totalItems === 0) {
    el.innerHTML = `<div class="empty-state" style="padding:40px 0">
      <div class="empty-icon">🍽️</div>
      <div class="empty-text">No meals logged yet</div>
      <div class="empty-sub">Tap "Add Food" to start tracking</div>
    </div>`;
    return;
  }

  el.innerHTML = MEAL_ORDER.map(mtype => {
    const meal = byMeal[mtype] || { calories:0, protein:0, carbs:0, fat:0, items:[] };
    const meta = MEAL_TYPES.find(m => m.id === mtype);
    if (meal.items.length === 0) return '';

    const itemsHtml = meal.items.map(item => `
      <div class="food-log-row">
        <div class="food-log-emoji">${item.food_name ? getFoodEmoji(item.food_id) : '🍽️'}</div>
        <div style="flex:1;min-width:0">
          <div class="food-log-name">${escHtml(item.food_name)}</div>
          <div class="food-log-qty">${item.quantity_g}g</div>
        </div>
        <div class="food-log-macros">
          <span class="food-macro-chip fmc-cal">${Math.round(item.calories)} kcal</span>
          <span class="food-macro-chip fmc-prot">${Math.round(item.protein)}g P</span>
          <span class="food-macro-chip fmc-carb">${Math.round(item.carbs)}g C</span>
          <span class="food-macro-chip fmc-fat">${Math.round(item.fat)}g F</span>
        </div>
        <button class="btn-icon" onclick="removeFoodLog('${item.id}')" title="Remove" style="color:var(--gray-300);flex-shrink:0">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>
    `).join('');

    return `<div class="meal-block">
      <div class="meal-block-header">
        <div class="meal-block-title">${meta.icon} ${meta.label}</div>
        <div class="meal-block-cal">${Math.round(meal.calories)} kcal · ${Math.round(meal.protein)}g protein</div>
      </div>
      <div class="meal-items">${itemsHtml}</div>
      <button class="meal-add-btn" onclick="openAddFoodModal('${mtype}')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        Add to ${meta.label}
      </button>
    </div>`;
  }).join('');

  // Also add empty meal blocks with add buttons for meals not yet logged
  MEAL_ORDER.forEach(mtype => {
    if (!byMeal[mtype] || byMeal[mtype].items.length === 0) {
      const meta = MEAL_TYPES.find(m => m.id === mtype);
      el.innerHTML += `<div class="meal-block">
        <div class="meal-block-header">
          <div class="meal-block-title">${meta.icon} ${meta.label}</div>
          <div class="meal-block-cal" style="color:var(--gray-300)">Nothing logged</div>
        </div>
        <button class="meal-add-btn" onclick="openAddFoodModal('${mtype}')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          Add to ${meta.label}
        </button>
      </div>`;
    }
  });
}

// ── Micronutrients panel ──────────────────────────────────────────────────────
function renderMicronutrients(totals, logCount) {
  const el = document.getElementById('micro-panel');
  if (!el) return;

  const micros = [
    { key:'vit_a',  label:'Vit A',   rda:900,  unit:'µg' },
    { key:'vit_c',  label:'Vit C',   rda:90,   unit:'mg' },
    { key:'vit_d',  label:'Vit D',   rda:20,   unit:'µg' },
    { key:'vit_b12',label:'Vit B12', rda:2.4,  unit:'µg' },
    { key:'iron',   label:'Iron',    rda:12,   unit:'mg' },
    { key:'calcium',label:'Calcium', rda:1000, unit:'mg' },
    { key:'magnesium',label:'Magnesium',rda:400,unit:'mg'},
    { key:'zinc',   label:'Zinc',    rda:11,   unit:'mg' },
    { key:'folate', label:'Folate',  rda:400,  unit:'µg' },
  ];

  if (logCount === 0) {
    el.innerHTML = '<div style="color:var(--gray-400);font-size:12.5px;text-align:center;padding:12px 0">Log food to see micronutrients</div>';
    return;
  }

  el.innerHTML = micros.map(m => {
    const val = totals[m.key] || 0;
    const pct = Math.min((val / m.rda) * 100, 120);
    const cls = pct < 30 ? 'micro-fill-deficit' : pct < 70 ? 'micro-fill-warn' : pct > 110 ? 'micro-fill-over' : 'micro-fill-ok';
    return `<div class="micro-row">
      <div class="micro-label">${m.label}</div>
      <div class="micro-bar-track"><div class="micro-bar-fill ${cls}" style="width:${Math.min(pct,100).toFixed(0)}%"></div></div>
      <div class="micro-val">${val < 10 ? val.toFixed(1) : Math.round(val)}${m.unit}</div>
    </div>`;
  }).join('');
}

// ── Weekly trend chart ────────────────────────────────────────────────────────
function renderFoodWeeklyChart(weekData, targets) {
  const el = document.getElementById('food-weekly-chart');
  if (!el || weekData.length === 0) return;
  const tCal  = targets.target_calories || 2000;
  const maxCal = Math.max(...weekData.map(d => d.calories), tCal, 1);
  const days   = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

  el.innerHTML = weekData.map((d, i) => {
    const pct  = (d.calories / maxCal * 80).toFixed(0);
    const over = d.calories > tCal * 1.1;
    const low  = d.calories < tCal * 0.4;
    const cls  = over ? 'fw-bar--over' : low ? 'fw-bar--low' : 'fw-bar--ok';
    const isToday = d.date === foodDate;
    return `<div class="fw-bar-col">
      <div class="fw-bar ${cls}" style="height:${pct}px;opacity:${isToday?1:.7}"></div>
      <div class="fw-bar-label" style="font-weight:${isToday?'700':'400'};color:${isToday?'var(--teal-600)':'var(--gray-400)'}">${days[i]}</div>
      <div class="fw-bar-count">${d.calories > 0 ? Math.round(d.calories) : ''}</div>
    </div>`;
  }).join('');
}

// ── Date navigation ───────────────────────────────────────────────────────────
function foodDateShift(delta) {
  const d = new Date(foodDate + 'T12:00:00');
  d.setDate(d.getDate() + delta);
  const today = new Date();
  if (d > today) return;
  foodDate = d.toISOString().split('T')[0];
  const picker = document.getElementById('food-date-picker');
  if (picker) picker.value = foodDate;
  loadFoodTracker();
}

function loadFoodDay(dateStr) {
  foodDate = dateStr;
  loadFoodTracker();
}

// ── Add Food Modal ────────────────────────────────────────────────────────────
function openAddFoodModal(mealType) {
  selectedMealType = mealType || 'lunch';
  document.getElementById('add-food-overlay').style.display = 'flex';
  // Init
  setTimeout(() => {
    loadFoodCategories();
    searchFoodDB('');
    document.getElementById('food-search-input')?.focus();
  }, 50);
}

// Category emoji map for the dropdown
const CAT_EMOJI = {
  'American':'🇺🇸','American Fast Food':'🍔','American Breakfast':'🥞','American Desserts':'🍰',
  'Indian Main':'🍛','Indian Bread':'🫓','Indian Snacks':'🟡','Indian Street Food':'🌆',
  'Indian Beverages':'☕','Indian Sides':'🫙','Indian Sweets':'🍬','South Indian':'🥞',
  'Pakistani':'🥘','Bangladeshi':'🐟','Sri Lankan':'🫓','Nepali':'🥟','Afghan':'🫙',
  'South Asian Sweets':'🍮','Street Food':'🌆',
  'Italian':'🍝','Mediterranean':'🫙','Thai':'🌶️','Japanese':'🍣',
  'Global Mains':'🌍','Global Breakfast':'🌅','Global Snacks':'🍿',
  'Fruits':'🍎','Vegetables':'🥦','Protein':'🥩','Dairy':'🥛',
  'Nuts & Seeds':'🌰','Dry Fruits':'🍇','Trail Mix':'🥜','Chocolates':'🍫',
  'Packaged Snacks':'📦','Supplements':'💪','Beverages':'🥤',
  'Breakfast':'🌅','Salads':'🥗','Rice & Grains':'🍚',
  'Dips & Spreads':'🫙','Fats & Oils':'🫒',
};

const CAT_GROUPS = {
  '🇺🇸 American':    ['American','American Fast Food','American Breakfast','American Desserts'],
  '🇮🇳 Indian':      ['Indian Main','Indian Bread','Indian Snacks','Indian Street Food','Indian Beverages','Indian Sides','Indian Sweets','South Indian'],
  '🌏 South Asian':  ['Pakistani','Bangladeshi','Sri Lankan','Nepali','Afghan','South Asian Sweets','Street Food'],
  '🌍 World Cuisine':['Italian','Mediterranean','Thai','Japanese','Global Mains','Global Breakfast','Global Snacks'],
  '🥗 Healthy':      ['Protein','Dairy','Fruits','Vegetables','Salads','Rice & Grains','Breakfast','Beverages'],
  '🍿 Snacks':       ['Nuts & Seeds','Dry Fruits','Trail Mix','Chocolates','Packaged Snacks','Dips & Spreads'],
  '💪 Fitness':      ['Supplements','Fats & Oils'],
};

async function loadFoodCategories() {
  const r = await fetch('/api/food/db').then(res => res.json()).catch(() => ({categories:[]}));
  const sel = document.getElementById('food-cat-select');
  if (!sel) return;
  const allCats = r.categories || [];

  sel.innerHTML = '<option value="">🌍 All Foods (' + allCats.length + ' categories)</option>';

  const grouped_flat = Object.values(CAT_GROUPS).flat();

  Object.entries(CAT_GROUPS).forEach(([groupLabel, catList]) => {
    const available = catList.filter(c => allCats.includes(c));
    if (!available.length) return;
    const grp = document.createElement('optgroup');
    grp.label = groupLabel;
    available.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c;
      opt.textContent = (CAT_EMOJI[c] || '🍽️') + ' ' + c;
      if (activeFoodCat === c) opt.selected = true;
      grp.appendChild(opt);
    });
    sel.appendChild(grp);
  });

  const ungrouped = allCats.filter(c => !grouped_flat.includes(c));
  if (ungrouped.length) {
    const grp = document.createElement('optgroup');
    grp.label = '📂 Other';
    ungrouped.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c;
      opt.textContent = (CAT_EMOJI[c] || '🍽️') + ' ' + c;
      if (activeFoodCat === c) opt.selected = true;
      grp.appendChild(opt);
    });
    sel.appendChild(grp);
  }
}

function filterFoodCat(cat) {
  activeFoodCat = cat;
  const sel = document.getElementById('food-cat-select');
  if (sel) sel.value = cat;
  const badge = document.getElementById('food-cat-active-badge');
  const badgeText = document.getElementById('food-cat-active-text');
  if (badge && badgeText) {
    if (cat) {
      badgeText.textContent = (CAT_EMOJI[cat] || '🍽️') + ' ' + cat;
      badge.style.display = 'inline-flex';
    } else {
      badge.style.display = 'none';
    }
  }
  const si = document.getElementById('food-search-input');
  if (si && cat) { si.value = ''; toggleSearchClear(''); }
  searchFoodDB(si?.value || '');
}

function clearFoodSearch() {
  const el = document.getElementById('food-search-input');
  if (el) { el.value = ''; el.focus(); }
  toggleSearchClear('');
  searchFoodDB('');
}

function toggleSearchClear(val) {
  const btn = document.getElementById('food-search-clear');
  if (btn) btn.style.display = val.length > 0 ? 'flex' : 'none';
}

async function searchFoodDB(query) {
  clearTimeout(foodSearchTimer);
  toggleSearchClear(query);
  foodSearchTimer = setTimeout(async () => {
    const params = new URLSearchParams({ q: query, limit: 80 });
    if (activeFoodCat) params.set('category', activeFoodCat);
    const r = await fetch(`/api/food/db?${params}`).then(res => res.json()).catch(() => ({foods:[],custom:[]}));
    const all = [
      ...(r.foods || []),
      ...(r.custom || []).map(c => ({...c, cal:c.calories}))
    ];
    const el = document.getElementById('food-search-results');
    const countEl = document.getElementById('food-results-count');
    if (!el) return;
    const label = activeFoodCat || 'all foods';
    if (countEl) countEl.textContent = all.length === 0 ? 'No results' : `${all.length} item${all.length !== 1 ? 's' : ''} in ${label}`;
    if (all.length === 0) {
      el.innerHTML = `<div class="food-empty-state" style="padding:28px 0;text-align:center">
        <div style="font-size:28px;margin-bottom:8px">🔍</div>
        <div style="font-size:13px;font-weight:600;color:var(--gray-600);margin-bottom:4px">Nothing found</div>
        <div style="font-size:12px;color:var(--gray-400)">Try a different name or pick another category</div>
      </div>`;
      return;
    }
    el.innerHTML = all.map(f => {
      const json = JSON.stringify(f).replace(/"/g, '&quot;');
      return `<div class="food-result-row" onclick="selectFoodItem(${json})">
        <div class="food-result-emoji">${f.emoji || '🍽️'}</div>
        <div class="food-result-info">
          <div class="food-result-name">${escHtml(f.name)}</div>
          <div style="display:flex;align-items:center;gap:6px;margin-top:2px;flex-wrap:wrap">
            <span class="food-result-category-tag">${f.category}</span>
            <span class="food-result-meta">${f.serving_g}g serving</span>
          </div>
        </div>
        <div style="text-align:right;flex-shrink:0">
          <div class="food-result-cal">${f.cal} kcal</div>
          <div style="font-size:10.5px;color:var(--gray-400)">${f.protein}g P</div>
        </div>
      </div>`;
    }).join('');
  }, 150);
}

function selectFoodItem(food) {
  selectedFoodItem = food;
  const col = document.getElementById('food-add-col');
  if (!col) return;

  const scale = (food.serving_g || 100) / 100;
  const cal   = Math.round(food.cal  * scale);
  const prot  = Math.round(food.protein * scale * 10)/10;
  const carbs = Math.round(food.carbs * scale * 10)/10;
  const fat   = Math.round(food.fat  * scale * 10)/10;
  const fiber = Math.round((food.fiber||0) * scale * 10)/10;

  const macros = [
    { label:'Protein', val:prot,  max:40, color:'#2563EB' },
    { label:'Carbs',   val:carbs, max:80, color:'#D97706' },
    { label:'Fat',     val:fat,   max:40, color:'#7C3AED' },
    { label:'Fiber',   val:fiber, max:15, color:'#16A34A' },
  ];

  const mealBtns = MEAL_TYPES.map(m => `
    <button type="button" class="meal-type-btn ${selectedMealType===m.id?'selected':''}"
      onclick="selectMealType('${m.id}')">${m.icon} ${m.label}</button>`).join('');

  col.innerHTML = `<div class="food-add-form">
    <div class="food-add-header">
      <div class="food-add-emoji">${food.emoji || '🍽️'}</div>
      <div>
        <div class="food-add-name">${escHtml(food.name)}</div>
        <div class="food-add-cat">${food.category}</div>
      </div>
    </div>
    <div class="nutrient-preview">
      <div style="font-size:20px;font-weight:700;font-family:'DM Serif Display',serif;color:var(--gray-900);margin-bottom:10px" id="fp-cal-preview">${cal} kcal</div>
      ${macros.map(m => `
        <div class="nutprev-row">
          <div class="nutprev-label">${m.label}</div>
          <div class="nutprev-bar"><div class="nutprev-fill" id="fp-bar-${m.label.toLowerCase()}" style="width:${Math.min(m.val/m.max*100,100).toFixed(0)}%;background:${m.color}"></div></div>
          <div class="nutprev-val" id="fp-val-${m.label.toLowerCase()}">${m.val}g</div>
        </div>`).join('')}
    </div>
    <div class="form-group" style="margin-bottom:12px">
      <label class="form-label">Quantity (grams)</label>
      <input type="number" class="form-input" id="food-qty-input" value="${food.serving_g||100}" min="1" step="1"
        oninput="updateFoodPreview(this.value)">
    </div>
    <div class="form-group" style="margin-bottom:14px">
      <label class="form-label">Meal</label>
      <div class="meal-type-picker">${mealBtns}</div>
    </div>
    <button class="btn-primary" style="width:100%" onclick="logSelectedFood()">
      Add to ${MEAL_TYPES.find(m=>m.id===selectedMealType)?.label || 'Meal'}
    </button>
  </div>`;
}

function selectMealType(mt) {
  selectedMealType = mt;
  document.querySelectorAll('.meal-type-btn').forEach(b => {
    b.classList.toggle('selected', b.textContent.trim().includes(MEAL_TYPES.find(m=>m.id===mt)?.label||''));
  });
  const addBtn = document.querySelector('#food-add-col button.btn-primary');
  if (addBtn) addBtn.textContent = 'Add to ' + (MEAL_TYPES.find(m=>m.id===mt)?.label||'Meal');
}

function updateFoodPreview(qty) {
  if (!selectedFoodItem) return;
  const q = parseFloat(qty) || 100;
  const scale = q / 100;
  const cal   = Math.round(selectedFoodItem.cal     * scale);
  const prot  = Math.round(selectedFoodItem.protein * scale * 10)/10;
  const carbs = Math.round(selectedFoodItem.carbs   * scale * 10)/10;
  const fat   = Math.round(selectedFoodItem.fat     * scale * 10)/10;
  const fiber = Math.round((selectedFoodItem.fiber||0) * scale * 10)/10;
  setText('fp-cal-preview', `${cal} kcal`);
  [['protein',prot,40,'#2563EB'],['carbs',carbs,80,'#D97706'],['fat',fat,40,'#7C3AED'],['fiber',fiber,15,'#16A34A']].forEach(([name,val,max]) => {
    const bar = document.getElementById(`fp-bar-${name}`);
    const valEl = document.getElementById(`fp-val-${name}`);
    if (bar) bar.style.width = Math.min(val/max*100,100).toFixed(0)+'%';
    if (valEl) valEl.textContent = val+'g';
  });
}

async function logSelectedFood() {
  if (!selectedFoodItem) return;
  const qty = parseFloat(document.getElementById('food-qty-input')?.value) || 100;
  const r = await fetch('/api/food/log', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      food_id:    selectedFoodItem.id,
      food_name:  selectedFoodItem.name,
      meal_type:  selectedMealType,
      date_key:   foodDate,
      quantity_g: qty
    })
  });
  const d = await r.json();
  if (d.success) {
    showToast(`${selectedFoodItem.emoji||'🍽️'} ${selectedFoodItem.name} added!`, 'success');
    closeModal('add-food-overlay');
    selectedFoodItem = null;
    document.getElementById('food-add-col').innerHTML = `<div class="food-add-placeholder"><div style="font-size:36px">🔍</div><div style="font-size:13px;color:var(--gray-400);margin-top:8px">Select a food item to add</div></div>`;
    loadFoodTracker();
    loadDashboard();
  } else {
    showToast('Failed to log food', 'error');
  }
}

async function removeFoodLog(id) {
  await fetch(`/api/food/log/${id}`, { method: 'DELETE' });
  showToast('Removed from log');
  loadFoodTracker();
  loadDashboard();
}

// ── User Profile Modal ────────────────────────────────────────────────────────
async function openProfileModal() {
  const r = await fetch('/api/food/profile').then(res => res.json()).catch(() => null);
  if (!r) return;
  const p = r.profile;
  const form = document.getElementById('profile-form');
  if (!form) return;
  ['name','age'].forEach(k => { if (form[k]) form[k].value = p[k] || ''; });
  if (form.gender)         form.gender.value         = p.gender         || 'male';
  if (form.activity_level) form.activity_level.value = p.activity_level || 'moderate';
  const goalRadio = form.querySelector(`input[name=goal][value="${p.goal||'maintain'}"]`);
  if (goalRadio) goalRadio.checked = true;

  // Populate unit-aware weight/height fields
  window._weightKg = parseFloat(p.weight_kg) || 70;
  window._heightCm = parseFloat(p.height_cm) || 170;
  setWeightUnit(window._weightUnit || 'kg', true);
  setHeightUnit(window._heightUnit || 'cm', true);

  updateTDEEPreview(r.targets);
  document.getElementById('profile-modal-overlay').style.display = 'flex';
}

function updateTDEEPreview(t) {
  const prev = document.getElementById('tdee-preview');
  if (prev && t) {
    prev.style.display = 'block';
    setText('prev-bmr',    `${t.bmr} kcal/day`);
    setText('prev-tdee',   `${t.tdee} kcal/day`);
    setText('prev-target', `${t.target_calories} kcal/day`);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  // ── Unit state for profile form ──
  window._weightUnit = 'kg';
  window._heightUnit = 'cm';
  window._weightKg   = 70;
  window._heightCm   = 170;

  document.getElementById('profile-form')?.addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.target;
    const data = {
      name:           form.name?.value,
      age:            parseInt(form.age?.value),
      weight_kg:      window._weightKg || parseFloat(form.weight_kg?.value) || 70,
      height_cm:      window._heightCm || parseFloat(form.height_cm?.value) || 170,
      gender:         form.gender?.value,
      activity_level: form.activity_level?.value,
      goal:           form.querySelector('input[name=goal]:checked')?.value || 'maintain'
    };
    const r = await fetch('/api/food/profile', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) });
    const d = await r.json();
    if (d.success) {
      showToast('Profile saved! Calorie targets updated.', 'success');
      updateTDEEPreview(d.targets);
      foodTargets = d.targets;
      closeModal('profile-modal-overlay');
      updateSidebarUser();
      // Refresh all pages that show calorie data
      loadDashboard();
      loadFoodTracker();
      if (document.getElementById('view-fitness')?.classList.contains('active')) loadFitness();
    }
  });

  // Profile form live TDEE update
  document.querySelectorAll('#profile-form input, #profile-form select').forEach(el => {
    el.addEventListener('change', async () => {
      const form = document.getElementById('profile-form');
      if (!form) return;
      const data = {
        name: form.name?.value || 'User',
        age: parseInt(form.age?.value) || 25,
        weight_kg: parseFloat(form.weight_kg?.value) || 70,
        height_cm: parseFloat(form.height_cm?.value) || 170,
        gender: form.gender?.value || 'male',
        activity_level: form.activity_level?.value || 'moderate',
        goal: form.querySelector('input[name=goal]:checked')?.value || 'maintain'
      };
      // Preview without saving
      const r = await fetch('/api/food/profile').then(res => res.json()).catch(() => null);
      if (r) {
        // Quick local estimate using the TDEE formula
        const w=data.weight_kg, h=data.height_cm, a=data.age;
        const bmr = data.gender==='male' ? 88.362+(13.397*w)+(4.799*h)-(5.677*a) : 447.593+(9.247*w)+(3.098*h)-(4.330*a);
        const mult = {sedentary:1.2,light:1.375,moderate:1.55,active:1.725,very_active:1.9}[data.activity_level]||1.55;
        const tdee = bmr*mult;
        const adj  = {lose_fast:-500,lose:-250,maintain:0,gain:250,gain_fast:500}[data.goal]||0;
        updateTDEEPreview({ bmr:Math.round(bmr), tdee:Math.round(tdee), target_calories:Math.round(tdee+adj) });
      }
    });
  });

  // Init food date picker
  const fp = document.getElementById('food-date-picker');
  if (fp) fp.value = new Date().toISOString().split('T')[0];
});

// ── Helpers ───────────────────────────────────────────────────────────────────
const FOOD_EMOJI_CACHE = {};
function getFoodEmoji(foodId) {
  if (FOOD_EMOJI_CACHE[foodId]) return FOOD_EMOJI_CACHE[foodId];
  return '🍽️';
}

// Pre-populate cache from food DB on load
fetch('/api/food/db?limit=100').then(r => r.json()).then(d => {
  (d.foods||[]).forEach(f => { FOOD_EMOJI_CACHE[f.id] = f.emoji || '🍽️'; });
}).catch(()=>{});

// ════════════════════════════════════════════════════════════
// PROFILE UNIT TOGGLES — kg/lbs, cm/ft-in
// ════════════════════════════════════════════════════════════

function setWeightUnit(unit, suppressLiveTDEE) {
  window._weightUnit = unit;
  // Toggle button states
  document.querySelectorAll('#weight-unit-toggle .unit-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.unit === unit);
  });
  const input = document.getElementById('weight-display-input');
  const hint  = document.getElementById('weight-unit-hint');
  if (!input) return;
  if (unit === 'kg') {
    input.step = '0.1';
    input.placeholder = '70';
    input.value = window._weightKg ? window._weightKg.toFixed(1) : '';
    if (hint) hint.textContent = `= ${window._weightKg ? (window._weightKg * 2.20462).toFixed(1) : '—'} lbs`;
  } else {
    const lbs = window._weightKg ? (window._weightKg * 2.20462) : 154;
    input.step = '0.5';
    input.placeholder = '154';
    input.value = lbs.toFixed(1);
    if (hint) hint.textContent = `= ${window._weightKg ? window._weightKg.toFixed(1) : '—'} kg`;
  }
  // Update hidden kg field
  const hidden = document.getElementById('weight-kg-hidden');
  if (hidden) hidden.value = window._weightKg || 70;
  if (!suppressLiveTDEE) triggerLiveTDEEUpdate();
}

function syncWeightInput(val) {
  const v = parseFloat(val);
  if (!v || isNaN(v)) return;
  if (window._weightUnit === 'kg') {
    window._weightKg = v;
    const hint = document.getElementById('weight-unit-hint');
    if (hint) hint.textContent = `= ${(v * 2.20462).toFixed(1)} lbs`;
  } else {
    window._weightKg = v / 2.20462;
    const hint = document.getElementById('weight-unit-hint');
    if (hint) hint.textContent = `= ${window._weightKg.toFixed(1)} kg`;
  }
  const hidden = document.getElementById('weight-kg-hidden');
  if (hidden) hidden.value = window._weightKg.toFixed(2);
  triggerLiveTDEEUpdate();
}

function setHeightUnit(unit, suppressLiveTDEE) {
  window._heightUnit = unit;
  document.querySelectorAll('#height-unit-toggle .unit-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.unit === unit);
  });
  const cmInput   = document.getElementById('height-cm-input');
  const ftinWrap  = document.getElementById('height-ftin-inputs');
  const ftInput   = document.getElementById('height-ft-input');
  const inInput   = document.getElementById('height-in-input');
  const hint      = document.getElementById('height-unit-hint');
  const cm        = window._heightCm || 170;

  if (unit === 'cm') {
    if (cmInput)  { cmInput.style.display = ''; cmInput.value = cm.toFixed(0); }
    if (ftinWrap) ftinWrap.style.display = 'none';
    if (hint)     hint.textContent = `= ${cmToFtIn(cm)}`;
  } else {
    if (cmInput)  cmInput.style.display = 'none';
    if (ftinWrap) ftinWrap.style.display = 'flex';
    const totalIn = cm / 2.54;
    const ft = Math.floor(totalIn / 12);
    const inches = Math.round(totalIn % 12);
    if (ftInput)  ftInput.value = ft;
    if (inInput)  inInput.value = inches;
    if (hint)     hint.textContent = `= ${cm.toFixed(0)} cm`;
  }
  const hidden = document.getElementById('height-cm-hidden');
  if (hidden) hidden.value = cm.toFixed(1);
  if (!suppressLiveTDEE) triggerLiveTDEEUpdate();
}

function syncHeightInput() {
  const unit = window._heightUnit || 'cm';
  if (unit === 'cm') {
    const v = parseFloat(document.getElementById('height-cm-input')?.value);
    if (v && !isNaN(v)) {
      window._heightCm = v;
      const hint = document.getElementById('height-unit-hint');
      if (hint) hint.textContent = `= ${cmToFtIn(v)}`;
    }
  } else {
    const ft = parseFloat(document.getElementById('height-ft-input')?.value) || 0;
    const inches = parseFloat(document.getElementById('height-in-input')?.value) || 0;
    window._heightCm = (ft * 12 + inches) * 2.54;
    const hint = document.getElementById('height-unit-hint');
    if (hint) hint.textContent = `= ${window._heightCm.toFixed(0)} cm`;
  }
  const hidden = document.getElementById('height-cm-hidden');
  if (hidden) hidden.value = (window._heightCm || 170).toFixed(1);
  triggerLiveTDEEUpdate();
}

function cmToFtIn(cm) {
  const totalIn = cm / 2.54;
  const ft = Math.floor(totalIn / 12);
  const inches = Math.round(totalIn % 12);
  return `${ft}′${inches}″`;
}

function triggerLiveTDEEUpdate() {
  const form = document.getElementById('profile-form');
  if (!form) return;
  const w = window._weightKg || 70;
  const h = window._heightCm || 170;
  const a = parseInt(form.age?.value) || 25;
  const g = form.gender?.value || 'male';
  const act = form.activity_level?.value || 'moderate';
  const goal = form.querySelector('input[name=goal]:checked')?.value || 'maintain';
  const bmr = g === 'male'
    ? 88.362 + (13.397*w) + (4.799*h) - (5.677*a)
    : 447.593 + (9.247*w) + (3.098*h) - (4.330*a);
  const mult = {sedentary:1.2,light:1.375,moderate:1.55,active:1.725,very_active:1.9}[act]||1.55;
  const tdee = bmr * mult;
  const adj  = {lose_fast:-500,lose:-250,maintain:0,gain:250,gain_fast:500}[goal]||0;
  updateTDEEPreview({ bmr:Math.round(bmr), tdee:Math.round(tdee), target_calories:Math.round(tdee+adj) });
}

// ════════════════════════════════════════════════════════════
// THOUGHTS — Daily Journal
// ════════════════════════════════════════════════════════════

const MOOD_EMOJI = {
  neutral:'😐', happy:'😊', excited:'🤩', calm:'😌',
  anxious:'😰', tired:'😴', sad:'😞', angry:'😤'
};
const MOOD_COLOR = {
  neutral:'#0E8F7E', happy:'#22C55E', excited:'#F59E0B', calm:'#06B6D4',
  anxious:'#8B5CF6', tired:'#9CA3AF', sad:'#3B82F6', angry:'#EF4444'
};

let currentThoughtsDate = new Date().toISOString().split('T')[0];
let selectedMood = 'neutral';
let editingThoughtId = null;

async function loadThoughts(dateStr) {
  if (dateStr) currentThoughtsDate = dateStr;
  const picker = document.getElementById('thoughts-date-picker');
  if (picker && !picker.value) picker.value = currentThoughtsDate;

  const r = await fetch(`/api/thoughts/${currentThoughtsDate}`).then(r => r.json()).catch(() => null);
  if (!r) return;

  // Update quota
  const quotaEl = document.getElementById('thoughts-quota');
  const usedEl  = document.getElementById('thoughts-used');
  if (quotaEl && usedEl) {
    usedEl.textContent = r.count;
    quotaEl.classList.toggle('full', r.remaining === 0);
  }

  // Update title
  const titleEl = document.getElementById('thoughts-feed-title');
  if (titleEl) {
    const d = new Date(currentThoughtsDate + 'T12:00:00');
    const today = new Date().toISOString().split('T')[0];
    titleEl.textContent = currentThoughtsDate === today
      ? "Today's thoughts"
      : d.toLocaleDateString('en-US', { weekday:'long', month:'long', day:'numeric' });
  }

  // Disable textarea if limit reached
  const ta  = document.getElementById('thought-textarea');
  const btn = document.getElementById('thought-submit-btn');
  if (ta)  ta.disabled = r.remaining === 0;
  if (ta && r.remaining === 0) ta.placeholder = "You've reached today's limit of 10 thoughts.";

  // Render thoughts
  renderThoughtsList(r.thoughts);

  // Week mood dots
  loadWeekMoods();
}

function renderThoughtsList(thoughts) {
  const el = document.getElementById('thoughts-list');
  if (!el) return;
  if (!thoughts || thoughts.length === 0) {
    el.innerHTML = `<div class="thoughts-empty">
      <div class="thoughts-empty-icon">💭</div>
      <div class="thoughts-empty-text">No thoughts yet</div>
      <div class="thoughts-empty-sub">Write your first one on the left</div>
    </div>`;
    return;
  }
  el.innerHTML = thoughts.map(t => {
    const time = new Date(t.created_at).toLocaleTimeString('en-US', { hour:'numeric', minute:'2-digit' });
    const mood = t.mood || 'neutral';
    return `<div class="thought-card" data-mood="${mood}" data-id="${t.id}">
      <div class="thought-card-header">
        <div class="thought-meta">
          <span class="thought-mood-badge">${MOOD_EMOJI[mood] || '😐'}</span>
          <span class="thought-time">${time}</span>
        </div>
        <div class="thought-card-actions">
          <button class="thought-action-btn" onclick="startEditThought('${t.id}')" title="Edit">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
          <button class="thought-action-btn del" onclick="deleteThought('${t.id}')" title="Delete">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
          </button>
        </div>
      </div>
      <div class="thought-content" id="tc-${t.id}">${escHtml(t.content)}</div>
      <div class="thought-edit-wrap" id="te-${t.id}" style="display:none">
        <textarea class="thought-edit-area" id="tea-${t.id}">${escHtml(t.content)}</textarea>
        <div class="thought-edit-actions">
          <button class="btn-outline" style="padding:5px 12px;font-size:12px" onclick="cancelEditThought('${t.id}')">Cancel</button>
          <button class="btn-primary" style="padding:5px 12px;font-size:12px" onclick="saveEditThought('${t.id}','${mood}')">Save</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function loadWeekMoods() {
  const r = await fetch('/api/thoughts/range/week').then(r => r.json()).catch(() => []);
  const el = document.getElementById('thoughts-week-moods');
  if (!el || !r.length) return;
  // Get one mood per day (most recent)
  const byDay = {};
  r.forEach(t => { if (!byDay[t.date_key]) byDay[t.date_key] = t.mood; });
  const days = ['M','T','W','T','F','S','S'];
  const today = new Date();
  el.innerHTML = Array.from({length:7}, (_,i) => {
    const d = new Date(today);
    d.setDate(d.getDate() - (6-i));
    const key = d.toISOString().split('T')[0];
    const mood = byDay[key];
    return mood
      ? `<div class="week-mood-dot" title="${key}"><div class="week-mood-emoji">${MOOD_EMOJI[mood]}</div><div class="week-mood-day">${days[i]}</div></div>`
      : `<div class="week-mood-dot"><div class="week-mood-emoji" style="opacity:.18">○</div><div class="week-mood-day" style="opacity:.3">${days[i]}</div></div>`;
  }).join('');
}

function selectMood(mood) {
  selectedMood = mood;
  document.querySelectorAll('.mood-btn').forEach(b => {
    b.classList.toggle('selected', b.dataset.mood === mood);
  });
}

function updateThoughtCounter(ta) {
  const len = ta.value.length;
  const el  = document.getElementById('thought-char-count');
  const btn = document.getElementById('thought-submit-btn');
  if (el) {
    el.textContent = `${len} / 1000`;
    el.classList.toggle('near', len > 800);
    el.classList.toggle('full', len >= 1000);
  }
  if (btn) btn.disabled = len === 0;
}

async function submitThought() {
  const ta = document.getElementById('thought-textarea');
  const content = ta?.value?.trim();
  if (!content) return;
  const btn = document.getElementById('thought-submit-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

  const r = await fetch('/api/thoughts', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ content, mood: selectedMood, date_key: currentThoughtsDate })
  }).then(r => r.json()).catch(() => null);

  if (r?.success) {
    ta.value = '';
    updateThoughtCounter(ta);
    showToast(`Thought saved ${MOOD_EMOJI[selectedMood]}`, 'success');
    loadThoughts();
  } else {
    showToast(r?.error || 'Failed to save', 'error');
  }
  if (btn) { btn.textContent = 'Save thought'; }
}

function startEditThought(id) {
  document.getElementById(`tc-${id}`)?.classList.add('editing');
  const wrap = document.getElementById(`te-${id}`);
  if (wrap) wrap.style.display = 'block';
  document.getElementById(`tea-${id}`)?.focus();
}

function cancelEditThought(id) {
  document.getElementById(`tc-${id}`)?.classList.remove('editing');
  const wrap = document.getElementById(`te-${id}`);
  if (wrap) wrap.style.display = 'none';
}

async function saveEditThought(id, mood) {
  const ta = document.getElementById(`tea-${id}`);
  const content = ta?.value?.trim();
  if (!content) return;
  const r = await fetch(`/api/thoughts/${id}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ content, mood })
  }).then(r => r.json()).catch(() => null);
  if (r?.success) { showToast('Thought updated', 'success'); loadThoughts(); }
}

async function deleteThought(id) {
  if (!confirm('Delete this thought?')) return;
  await fetch(`/api/thoughts/${id}`, { method: 'DELETE' });
  showToast('Thought deleted');
  loadThoughts();
}

function thoughtsDateShift(delta) {
  const d = new Date(currentThoughtsDate + 'T12:00:00');
  d.setDate(d.getDate() + delta);
  const today = new Date();
  if (d > today) return;
  currentThoughtsDate = d.toISOString().split('T')[0];
  const picker = document.getElementById('thoughts-date-picker');
  if (picker) picker.value = currentThoughtsDate;
  loadThoughts();
}

// ════════════════════════════════════════════════════════════
// TO-DO LIST
// ════════════════════════════════════════════════════════════

let allTodos = [];
let todoFilter = 'all';
let selectedTodoPriority = 'medium';
let editingTodoId = null;

async function loadTodos() {
  const r = await fetch('/api/todos').then(r => r.json()).catch(() => null);
  if (!r) return;
  allTodos = r.todos || [];

  // Stats
  const pending = allTodos.filter(t => t.status === 'pending');
  const done    = allTodos.filter(t => t.status === 'done');
  const today   = new Date().toISOString().split('T')[0];
  const overdue = pending.filter(t => t.due_date && t.due_date < today);
  const total   = allTodos.length;
  const donePct = total > 0 ? Math.round((done.length / total) * 100) : 0;

  setText('td-pending-count', pending.length);
  setText('td-done-count',    done.length);
  setText('td-overdue-count', overdue.length);
  setText('td-progress-label', `${donePct}% done`);
  const fill = document.getElementById('td-progress-fill');
  if (fill) fill.style.width = donePct + '%';

  // Nav badge
  const badge = document.getElementById('nav-todo-badge');
  if (badge) {
    if (pending.length > 0) { badge.textContent = pending.length; badge.style.display = 'inline-block'; }
    else badge.style.display = 'none';
  }

  renderTodos();
}

function renderTodos() {
  const today = new Date().toISOString().split('T')[0];
  const sort  = document.getElementById('todo-sort')?.value || 'priority';
  const PORD  = { high: 0, medium: 1, low: 2 };

  let items = [...allTodos];

  // Apply filter
  if (todoFilter !== 'all') items = items.filter(t => t.status === todoFilter);

  // Sort
  items.sort((a, b) => {
    if (sort === 'priority') return (PORD[a.priority]||1) - (PORD[b.priority]||1);
    if (sort === 'due_date') return (a.due_date||'9999') < (b.due_date||'9999') ? -1 : 1;
    return a.created_at < b.created_at ? 1 : -1;
  });

  const pending = items.filter(t => t.status === 'pending');
  const done    = items.filter(t => t.status === 'done');

  const pendSec = document.getElementById('todo-pending-section');
  const doneSec = document.getElementById('todo-done-section');
  const pendList= document.getElementById('todo-pending-list');
  const doneList= document.getElementById('todo-done-list');

  setText('td-pend-count-label', pending.length);
  setText('td-done-count-label', done.length);

  // Show/hide sections based on filter
  if (pendSec) pendSec.style.display = (todoFilter === 'done') ? 'none' : '';
  if (doneSec) doneSec.style.display = (todoFilter === 'pending') ? 'none' : '';

  if (pendList) {
    if (pending.length === 0) {
      pendList.innerHTML = `<div class="todo-empty">
        <div class="todo-empty-icon">🎉</div>
        <div class="todo-empty-text">All clear!</div>
        <div class="todo-empty-sub">No pending tasks. Great work!</div>
      </div>`;
    } else {
      pendList.innerHTML = pending.map(t => renderTodoCard(t, today)).join('');
    }
  }

  if (doneList) {
    if (done.length === 0) {
      doneList.innerHTML = `<div class="todo-empty"><div class="todo-empty-icon">📋</div><div class="todo-empty-text">Nothing completed yet</div></div>`;
    } else {
      doneList.innerHTML = done.map(t => renderTodoCard(t, today)).join('');
    }
  }
}

function renderTodoCard(t, today) {
  const isDone    = t.status === 'done';
  const isOverdue = !isDone && t.due_date && t.due_date < today;
  const PLABEL    = { high:'🔴 High', medium:'🟡 Medium', low:'🟢 Low' };

  let metaHtml = `<span class="todo-badge pri-${t.priority}">${PLABEL[t.priority]||'Medium'}</span>`;
  if (t.due_date) {
    const dueLbl = t.due_date === today ? 'Due today' : t.due_date < today ? `Overdue (${t.due_date})` : `Due ${t.due_date}`;
    metaHtml += `<span class="todo-badge ${isOverdue?'overdue':'due'}">📅 ${dueLbl}</span>`;
  }
  if (t.reminder_at) {
    const rt = new Date(t.reminder_at).toLocaleString('en-US', {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
    metaHtml += `<span class="todo-badge reminder">🔔 ${rt}</span>`;
  }

  return `<div class="todo-card pri-${t.priority} ${isDone?'done':''}" data-id="${t.id}">
    <div class="todo-checkbox ${isDone?'checked':''}" onclick="toggleTodo('${t.id}')"></div>
    <div class="todo-content">
      <div class="todo-title">${escHtml(t.title)}</div>
      ${t.notes ? `<div class="todo-notes">${escHtml(t.notes)}</div>` : ''}
      <div class="todo-meta-row">${metaHtml}</div>
    </div>
    <div class="todo-card-actions">
      ${!isDone ? `<button class="todo-act-btn" onclick="openEditTodo('${t.id}')" title="Edit">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
      </button>` : ''}
      <button class="todo-act-btn del" onclick="deleteTodo('${t.id}')" title="Delete">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
      </button>
    </div>
  </div>`;
}

function setTodoFilter(f) {
  todoFilter = f;
  document.querySelectorAll('.todo-filter-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.filter === f);
  });
  renderTodos();
}

function openTodoModal(editId) {
  editingTodoId = editId || null;
  selectedTodoPriority = 'medium';

  const title = document.getElementById('todo-modal-title');
  const titleInput = document.getElementById('todo-title-input');
  const notesInput = document.getElementById('todo-notes-input');
  const dueInput   = document.getElementById('todo-due-input');
  const reminderToggle = document.getElementById('todo-reminder-toggle');
  const reminderInput  = document.getElementById('todo-reminder-input');
  const reminderPicker = document.getElementById('todo-reminder-picker');
  const editIdEl = document.getElementById('todo-edit-id');

  if (editId) {
    const todo = allTodos.find(t => t.id === editId);
    if (!todo) return;
    if (title) title.textContent = 'Edit Task';
    if (titleInput) titleInput.value = todo.title;
    if (notesInput) notesInput.value = todo.notes || '';
    if (dueInput)   dueInput.value   = todo.due_date || '';
    selectedTodoPriority = todo.priority || 'medium';
    if (editIdEl) editIdEl.value = editId;
    if (todo.reminder_at && reminderToggle && reminderInput && reminderPicker) {
      reminderToggle.checked = true;
      reminderPicker.style.display = 'block';
      reminderInput.value = todo.reminder_at.slice(0,16);
    }
  } else {
    if (title) title.textContent = 'Add Task';
    if (titleInput) titleInput.value = '';
    if (notesInput) notesInput.value = '';
    if (dueInput)   dueInput.value   = '';
    if (editIdEl)   editIdEl.value   = '';
    if (reminderToggle) reminderToggle.checked = false;
    if (reminderPicker) reminderPicker.style.display = 'none';
    if (reminderInput)  reminderInput.value = '';
  }

  // Reset priority picker
  document.querySelectorAll('.todo-pri-btn').forEach(b => {
    b.classList.toggle('selected', b.dataset.p === selectedTodoPriority);
  });

  document.getElementById('todo-modal-overlay').style.display = 'flex';
  titleInput?.focus();
}

function openEditTodo(id) { openTodoModal(id); }

function selectTodoPriority(p) {
  selectedTodoPriority = p;
  document.querySelectorAll('.todo-pri-btn').forEach(b => {
    b.classList.toggle('selected', b.dataset.p === p);
  });
}

function toggleReminderPicker(show) {
  const picker = document.getElementById('todo-reminder-picker');
  if (picker) picker.style.display = show ? 'block' : 'none';
  if (show) {
    const inp = document.getElementById('todo-reminder-input');
    if (inp && !inp.value) {
      // Default to 1 hour from now
      const d = new Date();
      d.setHours(d.getHours() + 1, 0, 0, 0);
      inp.value = d.toISOString().slice(0,16);
    }
  }
}

async function saveTodo() {
  const titleInput = document.getElementById('todo-title-input');
  const title = titleInput?.value?.trim();
  if (!title) { titleInput?.focus(); showToast('Please enter a title', 'error'); return; }

  const editId = document.getElementById('todo-edit-id')?.value;
  const reminderOn = document.getElementById('todo-reminder-toggle')?.checked;
  const data = {
    title,
    notes:       document.getElementById('todo-notes-input')?.value || '',
    priority:    selectedTodoPriority,
    due_date:    document.getElementById('todo-due-input')?.value || null,
    reminder_at: reminderOn ? (document.getElementById('todo-reminder-input')?.value || null) : null,
    tags: []
  };

  const url    = editId ? `/api/todos/${editId}` : '/api/todos';
  const method = editId ? 'PUT' : 'POST';
  const r = await fetch(url, {
    method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(data)
  }).then(r => r.json()).catch(() => null);

  if (r?.success) {
    showToast(editId ? 'Task updated!' : 'Task added!', 'success');
    closeModal('todo-modal-overlay');
    loadTodos();
    // Schedule browser notification if reminder set
    if (data.reminder_at && reminderOn) {
      scheduleTodoBrowserNotif(r.todo, data.reminder_at);
    }
  } else {
    showToast('Failed to save task', 'error');
  }
}

async function toggleTodo(id) {
  const r = await fetch(`/api/todos/${id}/toggle`, { method:'POST' }).then(r => r.json());
  if (r.success) {
    const todo = allTodos.find(t => t.id === id);
    if (todo) {
      const msg = r.todo.status === 'done' ? `✅ "${todo.title}" completed!` : `↩️ Moved back to pending`;
      showToast(msg, r.todo.status === 'done' ? 'success' : 'info');
    }
    loadTodos();
  }
}

async function deleteTodo(id) {
  const todo = allTodos.find(t => t.id === id);
  if (!confirm(`Delete "${todo?.title || 'this task'}"?`)) return;
  await fetch(`/api/todos/${id}`, { method:'DELETE' });
  showToast('Task deleted');
  loadTodos();
}

// ── Reminder notifications ──────────────────────────────────────────────────

function scheduleTodoBrowserNotif(todo, reminderAt) {
  if (Notification.permission !== 'granted') return;
  const ms = new Date(reminderAt) - Date.now();
  if (ms <= 0 || ms > 86400000) return; // only schedule within 24h
  setTimeout(() => {
    new Notification('📋 MediScan Reminder', {
      body: todo.title,
      icon: '/static/favicon.ico',
      tag:  `todo-${todo.id}`
    });
  }, ms);
}

function scheduleTodoReminderChecks() {
  // Poll the server every 60 seconds for due reminders
  setInterval(async () => {
    if (Notification.permission !== 'granted') return;
    const r = await fetch('/api/todos/reminders/due').then(r => r.json()).catch(() => null);
    if (!r?.reminders?.length) return;
    r.reminders.forEach(todo => {
      new Notification('📋 MediScan Reminder', {
        body: todo.title + (todo.notes ? `\n${todo.notes}` : ''),
        icon: '/static/favicon.ico',
        tag:  `todo-${todo.id}`
      });
    });
    // Refresh badge
    loadTodos();
  }, 60000);
}

// ════════════════════════════════════════════════════════════
// WELLNESS SYNC — updates dashboard strip from all sources
// ════════════════════════════════════════════════════════════