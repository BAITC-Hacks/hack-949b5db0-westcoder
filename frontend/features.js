const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = n => new Intl.NumberFormat('ru-RU').format(n) + ' ₸';
const dateLabel = d => new Date(d + 'T12:00:00').toLocaleDateString('ru-RU');
const key = 'eventmatch.favorites.v1';
let meta, hooks, initialized = false, saved = {}, selected = new Set(), profiles = new Map();
let calendarRequest, calendarData, month, calendarController, calendarVersion = 0;
let teamPending = false, teamHasResult = false;

function notice(text) {
  $('#storage-notice').textContent = text;
  $('#storage-notice').hidden = !text;
}

function validEntry(entry) {
  const c = entry?.candidate;
  return c && typeof c.id === 'string' && typeof c.name === 'string' && typeof c.city === 'string'
    && typeof c.description === 'string' && Number.isFinite(c.price_from_kzt)
    && ['languages','categories','event_formats','busy_dates','reasons','warnings'].every(k => Array.isArray(c[k]) && c[k].every(v => typeof v === 'string'))
    && entry.request && /^\d{4}-\d{2}-\d{2}$/.test(entry.request.date);
}

function saveStorage() {
  try { localStorage.setItem(key, JSON.stringify(saved)); notice(''); }
  catch { notice('Браузер не разрешил сохранение. Избранное доступно до закрытия страницы.'); }
}

function syncButtons() {
  document.querySelectorAll('[data-save]').forEach(b => {
    const active = Object.hasOwn(saved, b.dataset.save);
    b.textContent = active ? '♥ В избранном' : '♡ Сохранить';
    b.setAttribute('aria-pressed', String(active));
  });
  document.querySelectorAll('[data-compare]').forEach(b => {
    b.checked = selected.has(b.dataset.compare);
    b.disabled = selected.size >= 4 && !b.checked;
  });
  $('#saved-count').textContent = Object.keys(saved).length;
  $('#compare-button').textContent = `Сравнить (${selected.size}/4)`;
  $('#compare-button').disabled = selected.size < 2;
  $('#comparison-bar').hidden = selected.size === 0;
  $('#comparison-status').textContent = `Для сравнения: ${selected.size} из 4`;
  $('#open-comparison').disabled = selected.size < 2;
}

export function profileActions(candidate, request) {
  profiles.set(candidate.id, {candidate, request});
  return `<div class="profile-actions"><button type="button" class="secondary-button" data-save="${esc(candidate.id)}" aria-pressed="${Object.hasOwn(saved,candidate.id)}">${Object.hasOwn(saved,candidate.id) ? '♥ В избранном' : '♡ Сохранить'}</button><label class="compare-choice"><input type="checkbox" data-compare="${esc(candidate.id)}" ${selected.has(candidate.id) ? 'checked' : ''} ${selected.size >= 4 && !selected.has(candidate.id) ? 'disabled' : ''}> Сравнить</label></div>`;
}

export function preferenceDetails(candidate) {
  const evidence = candidate.preference_evidence || [];
  const conflicts = candidate.preference_conflicts || [];
  const unverified = candidate.preference_unverified || [];
  if (!evidence.length && !conflicts.length && !unverified.length) return '';
  return `<details class="preference-details"><summary>Пожелания: ${evidence.length} подтверждено в описании</summary>${evidence.map(e => `<p><strong>${esc(e.label)}</strong><br>«${esc(e.excerpt)}»</p>`).join('')}${conflicts.length ? `<p class="conflict-text">Возможное противоречие: ${conflicts.map(esc).join(', ')}.</p>` : ''}${unverified.length ? `<p>Не подтверждено описанием: ${unverified.map(esc).join(', ')}. Уточните у подрядчика.</p>` : ''}</details>`;
}

function renderSaved() {
  const entries = Object.values(saved);
  $('#saved-profiles').innerHTML = entries.length ? `<div class="saved-grid">${entries.map(({candidate:c,request}) => `<article class="saved-card"><h3>${esc(c.name)}</h3><p>${esc(c.categories.join(' · '))} · ${esc(c.city)}</p><strong>от ${money(c.price_from_kzt)}</strong><p>Сохранено для ${esc(dateLabel(request.date))}</p>${c.synthetic || c.price_imputed || c.city_imputed ? '<p class="data-warning">Есть синтетические или проставленные данные.</p>' : ''}${profileActions(c, request)}<div class="saved-card-buttons"><button class="text-button" data-saved-detail="${esc(c.id)}">Описание</button><button class="text-button" data-recheck="${esc(c.id)}">Перепроверить подбор →</button></div></article>`).join('')}</div>` : '<p class="section-description">Здесь появятся сохранённые подрядчики. Нажмите «Сохранить» на карточке результата.</p>';
  syncButtons();
}

function compare() {
  const entries = [...selected].map(id => profiles.get(id) || saved[id]).filter(Boolean);
  if (entries.length < 2) return;
  const fields = [
    ['Цена от', e => money(e.candidate.price_from_kzt)],
    ['Категории', e => e.candidate.categories.join(', ')],
    ['Город', e => e.candidate.city],
    ['Языки', e => e.candidate.languages.join(', ') || 'Не указаны'],
    ['Часы на площадке', e => e.candidate.max_hours == null ? 'Не указаны / не применимо' : e.candidate.max_hours],
    ['Форматы', e => e.candidate.event_formats.join(', ')],
    ['Дата запроса', e => dateLabel(e.request.date)],
    ['Особенности данных', e => [e.candidate.synthetic ? 'Синтетический профиль' : '',e.candidate.city_imputed ? 'Город проставлен' : '',e.candidate.price_imputed ? 'Цена проставлена' : ''].filter(Boolean).join('; ') || 'Без этих пометок'],
    ['Описание', e => e.candidate.description],
  ];
  hooks.openDialog('СРАВНЕНИЕ', `<h2>Сравните выбранные профили</h2><p>Факты каталога. Запросы могут относиться к разным датам; перед выбором повторите подбор. Стартовые цены требуют подтверждения.</p><div class="comparison-scroll"><table class="comparison-table"><thead><tr><th>Параметр</th>${entries.map(e => `<th>${esc(e.candidate.name)}</th>`).join('')}</tr></thead><tbody>${fields.map(([name,get]) => `<tr><th>${name}</th>${entries.map(e => `<td>${esc(get(e))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
}

async function post(path, payload, signal) {
  const response = await fetch(path, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:signal || AbortSignal.timeout(20000)});
  const body = await response.json();
  if (!response.ok) throw new Error(body.fields ? Object.values(body.fields).join(' ') : body.error || 'Не удалось выполнить запрос.');
  return body;
}

export function markCalendarDirty() {
  calendarVersion++;
  calendarController?.abort();
  calendarData = null;
  if (calendarRequest) $('#calendar-content').innerHTML = '<p>Параметры изменены. Обновите подбор, чтобы пересчитать календарь.</p>';
}

export async function updateCalendar(request) {
  calendarController?.abort();
  const controller = new AbortController();
  calendarController = controller;
  const version = ++calendarVersion;
  const timer = setTimeout(() => controller.abort(), 12000);
  calendarRequest = request;
  calendarData = null;
  month = request.date.slice(0,7);
  $('#calendar-panel').hidden = false;
  $('#calendar-content').innerHTML = '<p role="status">Считаем подходящие профили на каждую дату…</p>';
  try {
    const body = await post('/api/calendar', request, controller.signal);
    if (version !== calendarVersion) return;
    calendarData = body;
    renderCalendar();
  } catch (error) {
    if (version !== calendarVersion) return;
    $('#calendar-content').innerHTML = `<p>${controller.signal.aborted ? 'Календарь не успел загрузиться.' : esc(error.message)}</p><button class="secondary-button" id="retry-calendar">Повторить</button>`;
    $('#retry-calendar').onclick = () => updateCalendar(request);
  } finally { clearTimeout(timer); }
}

function renderCalendar() {
  if (!calendarData) return;
  const months = [...new Set(calendarData.days.map(d => d.date.slice(0,7)))];
  const days = calendarData.days.filter(d => d.date.startsWith(month));
  const firstDay = new Date(month + '-01T12:00:00');
  const padding = (firstDay.getDay() + 6) % 7;
  const dayCount = new Date(firstDay.getFullYear(),firstDay.getMonth()+1,0).getDate();
  const byDate = new Map(days.map(d => [d.date,d.count]));
  const max = Math.max(...days.map(d => d.count),0);
  const cells = Array.from({length:dayCount}, (_,i) => {
    const date = month + '-' + String(i+1).padStart(2,'0');
    const count = byDate.get(date);
    if (count === undefined) return `<span class="calendar-outside">${i+1}</span>`;
    return `<button type="button" data-calendar-date="${date}" class="calendar-day ${count ? 'has-matches' : 'no-matches'} ${count === max && count > 0 ? 'best-day' : ''}" aria-label="${esc(dateLabel(date))}: ${count} подходящих профилей" aria-pressed="${date === calendarRequest.date}" ${$('#submit-button').disabled ? 'disabled' : ''}><span>${i+1}</span><small>${count} проф.</small></button>`;
  }).join('');
  $('#calendar-content').innerHTML = `<p>Число профилей, проходящих все обязательные условия. Нажмите на дату, чтобы выполнить подбор.</p><div class="calendar-controls"><button class="secondary-button" id="previous-month" aria-label="Предыдущий месяц" ${months.indexOf(month) === 0 ? 'disabled' : ''}>←</button><strong>${firstDay.toLocaleDateString('ru-RU',{month:'long',year:'numeric'})}</strong><button class="secondary-button" id="next-month" aria-label="Следующий месяц" ${months.indexOf(month) === months.length-1 ? 'disabled' : ''}>→</button></div><div class="calendar-grid">${['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(d => `<span class="weekday">${d}</span>`).join('')}${'<span></span>'.repeat(padding)}${cells}</div><p class="calendar-legend">Зелёные даты — есть варианты. Контур отмечает дни с наибольшим выбором в этом месяце. Отсутствие записи о занятости требует подтверждения.</p>`;
  $('#previous-month').onclick = () => {month=months[months.indexOf(month)-1];renderCalendar();};
  $('#next-month').onclick = () => {month=months[months.indexOf(month)+1];renderCalendar();};
  document.querySelectorAll('[data-calendar-date]').forEach(b => b.onclick = () => hooks.applyRequest({...calendarRequest,date:b.dataset.calendarDate}));
}

export function initFeatures(metadata, callbacks) {
  meta = metadata;
  hooks = callbacks;
  if (initialized) return;
  initialized = true;
  window.addEventListener('pagehide', () => {calendarVersion++;calendarController?.abort();});
  try {
    const data = JSON.parse(localStorage.getItem(key) || '{}');
    saved = Object.fromEntries(Object.values(data || {}).filter(validEntry).slice(0,100).map(e => [e.candidate.id,e]));
  } catch { saved = {}; notice('Сохранённый список недоступен. Можно создать новый.'); }
  Object.entries(saved).forEach(([id, entry]) => profiles.set(id,entry));
  renderSaved();
  $('#compare-button').onclick = compare;
  $('#open-comparison').onclick = compare;
  $('#clear-comparison').onclick = () => {selected.clear();syncButtons();};
  document.addEventListener('click', event => {
    const save = event.target.closest('[data-save]');
    if (save) {
      const id = save.dataset.save;
      if (Object.hasOwn(saved,id)) delete saved[id];
      else if (profiles.has(id)) saved[id] = profiles.get(id);
      saveStorage(); renderSaved();
    }
    const detail = event.target.closest('[data-saved-detail]');
    if (detail && saved[detail.dataset.savedDetail]) hooks.showProfile(saved[detail.dataset.savedDetail].candidate);
    const check = event.target.closest('[data-recheck]');
    if (check && saved[check.dataset.recheck]) hooks.applyRequest(saved[check.dataset.recheck].request);
  });
  document.addEventListener('change', event => {
    if (!event.target.matches('[data-compare]')) return;
    const id = event.target.dataset.compare;
    if (event.target.checked && selected.size < 4) selected.add(id);
    else selected.delete(id);
    syncButtons();
  });
  initTeam();
}

function options(values, selected, optional=false) {
  return (optional ? '<option value="">Любой</option>' : '') + values.map(value => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(value)}</option>`).join('');
}

function addRole(category, hours='') {
  if ($('#team-roles').children.length >= 5) return;
  const row = document.createElement('div');
  row.className = 'team-role';
  row.innerHTML = `<label>Категория<select class="role-category" required>${options(meta.categories,category)}</select></label><label>Часы подрядчика<input class="role-hours" type="number" min="0.5" step="any" placeholder="Любые" value="${esc(hours)}"></label><button type="button" class="secondary-button remove-role" aria-label="Удалить роль">×</button>`;
  row.querySelector('button').onclick = () => {row.remove(); updateRoleButtons(); dirtyTeam();};
  $('#team-roles').append(row);
  updateRoleButtons();
}

function updateRoleButtons() {
  const count = $('#team-roles').children.length;
  $('#add-role').disabled = count >= 5 || teamPending;
  document.querySelectorAll('.remove-role').forEach(b => b.disabled = count <= 1 || teamPending);
}

function dirtyTeam() {
  if (teamHasResult) $('#team-dirty').hidden = false;
}

function initTeam() {
  const request = hooks.readForm();
  $('#team-city').innerHTML = options(meta.cities,request.city);
  $('#team-format').innerHTML = options(meta.event_formats,request.event_format);
  $('#team-language').innerHTML = options(meta.languages,request.language,true);
  $('#team-date').min = meta.calendar_start;
  $('#team-date').max = meta.calendar_end;
  $('#team-date').value = request.date;
  const defaults = ['Фотограф','Ведущий'].filter(c => meta.categories.includes(c));
  (defaults.length ? defaults : meta.categories.slice(0,1)).forEach(c => addRole(c));
  $('#team-form').querySelectorAll('input,select,button').forEach(el => el.disabled = false);
  updateRoleButtons();
  $('#copy-event').disabled = false;
  $('#copy-event').onclick = () => {
    const event = hooks.readForm();
    $('#team-city').value = event.city; $('#team-date').value = event.date;
    $('#team-format').value = event.event_format; $('#team-language').value = event.language || '';
    dirtyTeam();
  };
  $('#add-role').onclick = () => {
    const used = [...document.querySelectorAll('.role-category')].map(s => s.value);
    addRole(meta.categories.find(c => !used.includes(c)) || meta.categories[0]); dirtyTeam();
  };
  $('#team-form').addEventListener('input', dirtyTeam);
  $('#team-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (teamPending || !$('#team-form').reportValidity()) return;
    const payload = {city:$('#team-city').value,date:$('#team-date').value,event_format:$('#team-format').value,
      budget_kzt:Number($('#team-budget').value),language:$('#team-language').value || null,
      roles:[...document.querySelectorAll('.team-role')].map(r => ({category:r.querySelector('.role-category').value,duration_hours:r.querySelector('.role-hours').value === '' ? null : Number(r.querySelector('.role-hours').value)}))};
    teamPending = true;
    $('#team-error').hidden = true; $('#team-dirty').hidden = true;
    $('#team-results').innerHTML = '<p role="status">Подбираем полную команду…</p>';
    $('#team-results').setAttribute('aria-busy','true');
    $('#team-form').querySelectorAll('input,select,button').forEach(el => el.disabled = true);
    $('#copy-event').disabled = true;
    try { const data = await post('/api/team',payload); renderTeam(data); teamHasResult = true; }
    catch (error) {$('#team-error').textContent = error.name === 'TimeoutError' ? 'Сервер отвечает слишком долго. Повторите подбор.' : error.message; $('#team-error').hidden = false; $('#team-results').innerHTML = '';}
    finally {teamPending=false; $('#team-form').querySelectorAll('input,select,button').forEach(el => el.disabled=false);$('#copy-event').disabled=false;$('#team-results').setAttribute('aria-busy','false');updateRoleButtons();}
  });
}

function renderTeam(data) {
  $('#team-results').innerHTML = `<div class="team-result-heading"><h3>${esc(data.message)}</h3><p>${esc(data.request.city)} · ${esc(dateLabel(data.request.date))} · бюджет ${money(data.request.budget_kzt)}</p></div>${data.status === 'matched' ? `<div class="team-total"><div><small>Сумма цен «от»</small><strong>${money(data.total_from_kzt)}</strong></div><div><small>Остаток бюджета</small><strong>${money(data.remaining_kzt)}</strong></div></div><div class="saved-grid">${data.members.map(c => `<article class="saved-card"><p class="role-name">${esc(c.category)}</p><h3>${esc(c.name)}</h3><strong>от ${money(c.price_from_kzt)}</strong><p>${c.duration_hours == null ? 'Часы не ограничены запросом' : 'Нужно часов: ' + c.duration_hours}</p><p>${esc(c.languages.join(' · '))}</p>${c.warnings.length ? `<p class="data-warning">${c.warnings.map(esc).join(' ')}</p>` : ''}<details><summary>Описание</summary><p>${esc(c.description)}</p></details>${profileActions(c,{...data.request,category:c.category,duration_hours:c.duration_hours,sort_by:'price'})}</article>`).join('')}</div>` : `<ul>${data.roles.map(r => `<li>${esc(r.category)}: ${r.eligible_candidates} профилей по дате и условиям роли (до проверки общего бюджета).</li>`).join('')}</ul>${data.minimum_required_kzt != null ? `<p>Минимальная сумма полной команды: <strong>${money(data.minimum_required_kzt)}</strong>. Не хватает ${money(data.minimum_required_kzt-data.request.budget_kzt)}.</p><button class="secondary-button" id="apply-team-budget">Установить этот бюджет и подобрать</button>` : '<p>Попробуйте изменить дату, часы роли или язык. Один профиль нельзя назначить на две роли одновременно.</p>'}`}<p class="semantic-note">${esc(data.note)}</p>`;
  if ($('#apply-team-budget')) $('#apply-team-budget').onclick = () => {$('#team-budget').value=data.minimum_required_kzt;$('#team-form').requestSubmit();};
  syncButtons();
}
