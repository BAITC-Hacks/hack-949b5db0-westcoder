import { initFeatures, profileActions, preferenceDetails, updateCalendar, markCalendarDirty } from './features.js';
const $ = (selector) => document.querySelector(selector);
const form = $('#event-form');
const output = $('#results');
const dialog = $('#detail-dialog');
const money = (value) => new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 2}).format(value) + ' ₸';
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dateLabel = (value) => new Date(value + 'T12:00:00').toLocaleDateString('ru-RU', {day:'numeric',month:'long'});
const capitalize = (value) => value.charAt(0).toUpperCase() + value.slice(1);
const labels = {wrong_city:'другой город',wrong_category:'другая категория',busy:'заняты на дату',availability_unknown:'нет достоверного календаря',wrong_format:'не поддерживают формат',over_budget:'выше бюджета',price_unknown:'нет цены',too_short:'не хватает часов',duration_unknown:'не указана длительность',duration_invalid:'ошибка в данных длительности',wrong_language:'нет нужного языка'};
const scoreLabels = {budget:'Запас бюджета',semantic:'Соответствие пожеланиям / описанию'};
const stageLabels = {initial:'В каталоге',city:'Город',category:'Категория',available:'Дата',format:'Формат',budget:'Бюджет',duration:'Часы',language:'Язык',recommended:'Топ-3'};
let metadata;
let result;
let pending = false;

function populate(id, values, optional=false) {
  $(id).innerHTML = (optional ? '<option value="">Любой</option>' : '') + values.map(value => `<option value="${esc(value)}">${esc(capitalize(value))}</option>`).join('');
}

function fill(request) {
  for (const [key, value] of Object.entries(request)) {
    if (form.elements[key]) form.elements[key].value = value ?? '';
  }
  validateDuration();
}

function validateDuration() {
  const input = $('#duration_hours');
  input.setCustomValidity(input.value !== '' && Number(input.value) <= 0 ? 'Укажите положительное число часов.' : '');
}

async function fetchJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {...options, signal: AbortSignal.timeout(20000)});
  } catch (error) {
    throw new Error(error.name === 'TimeoutError' ? 'Сервер отвечает слишком долго. Попробуйте ещё раз.' : 'Нет связи с сервером. Проверьте подключение и повторите запрос.');
  }
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error('Сервер вернул некорректный ответ. Попробуйте ещё раз.');
  }
  if (!response.ok) throw new Error(body.fields ? Object.values(body.fields).join(' ') : body.error || 'Не удалось выполнить запрос.');
  return body;
}

function readForm() {
  const values = Object.fromEntries([...form.elements].filter(el => el.name).map(el => [el.name, el.value]));
  values.budget_kzt = Number(values.budget_kzt);
  values.duration_hours = values.duration_hours === '' ? null : Number(values.duration_hours);
  values.language ||= null;
  return values;
}

function setBusy(busy) {
  pending = busy;
  form.querySelectorAll('input,select,textarea,button').forEach(el => el.disabled = busy);
  document.querySelectorAll('.demo-button,.suggestion button').forEach(el => el.disabled = busy);
  output.setAttribute('aria-busy', String(busy));
  document.querySelectorAll('[data-calendar-date]').forEach(el => el.disabled = busy);
  $('#submit-button').innerHTML = busy ? '<span>◌</span> Подбираем команду…' : '<span>✦</span> Подобрать подрядчиков <span>→</span>';
}

async function search({refreshSemantic = false} = {}) {
  validateDuration();
  if (pending || !form.reportValidity()) return;
  const payload = readForm();
  if (refreshSemantic) payload.refresh_semantic = true;
  markCalendarDirty();
  setBusy(true);
  $('#form-error').hidden = true;
  $('#dirty-notice').hidden = true;
  output.innerHTML = '<div class="loading-card panel"><span class="loader"></span><h2>Ищем совпадения</h2><p>Проверяем условия и сравниваем подходящие профили.</p></div>';
  try {
    const body = await fetchJson('/api/recommend', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    result = body;
    render(body);
    updateCalendar(body.request);
  } catch (error) {
    result = null;
    const message = error.name === 'TimeoutError' ? 'Сервер отвечает слишком долго. Попробуйте ещё раз.' : error.message;
    $('#form-error').textContent = message;
    $('#form-error').hidden = false;
    output.innerHTML = `<div class="empty-state panel"><div class="empty-icon">↻</div><h3>Не удалось завершить подбор</h3><p>${esc(message)}</p><button class="retry-button" id="retry-search">Повторить</button></div>`;
    $('#retry-search').addEventListener('click', search);
  } finally {
    setBusy(false);
  }
}

function warningTags(candidate) {
  return `<div class="warning-tags">${candidate.synthetic ? '<span class="warning-tag">Синтетический профиль</span>' : ''}${candidate.city_imputed ? '<span class="warning-tag">Город проставлен</span>' : ''}${candidate.price_imputed ? '<span class="warning-tag">Цена проставлена</span>' : ''}</div>`;
}

function card(candidate, index, request) {
  const initials = candidate.name.split(/\s+/).slice(0,2).map(x => x[0]).join('');
  const explanation = candidate.explanation;
  const hours = !candidate.duration_data_valid ? 'Ошибка в данных длительности' : candidate.max_hours !== null ? 'До ' + candidate.max_hours + ' ч' : ['Флорист','Декоратор','Подарки и сувениры'].includes(request.category) ? 'Без почасового присутствия' : 'Длительность не указана';
  return `<article class="candidate-card panel">
    <div class="card-top"><div class="avatar tone-${index}">${esc(initials)}</div><div class="candidate-name"><h3>${esc(candidate.name)}</h3><div class="candidate-meta">${esc(candidate.category)} <span>·</span> ${esc(candidate.city)}</div></div><div class="score"><strong>${candidate.score.toLocaleString('ru-RU')}<span>/100</span></strong><small>балл подбора</small></div></div>
    <div class="match-row"><div class="price"><small>от</small> ${money(candidate.price_from_kzt)}${candidate.price_imputed ? '<small>*</small>' : ''}</div><span class="available">✓ ${esc(dateLabel(request.date))} · нет занятости</span></div>
    <div class="attribute-row"><span class="attribute">${esc(candidate.languages.map(capitalize).join(' · ') || 'Языки не указаны')}</span><span class="attribute">${esc(capitalize(request.event_format))}</span><span class="attribute">${esc(hours)}</span></div>
    ${warningTags(candidate)}
    <div class="explanation-box"><h4><span>✦</span> Почему рекомендуем</h4><p>${esc(explanation)}</p></div>
    ${preferenceDetails(candidate)}
    ${profileActions(candidate, request)}
    <div class="card-bottom"><span>${index === 0 ? 'Первый по оценке совпадения' : `№ ${index + 1} в вашей подборке`}</span><button class="detail-button" data-detail="${index}">Подробнее о совпадении <span>↗</span></button></div>
  </article>`;
}

function funnel(data) {
  const visibleStages = Object.entries(data.filter_stats).filter(([key]) => !(key === 'duration' && data.request.duration_hours === null) && !(key === 'language' && !data.request.language));
  const reasons = Object.entries(data.excluded_reasons).filter(([key]) => !['wrong_city','wrong_category'].includes(key));
  const lowerRank = data.eligible_candidates - data.recommendations.length;
  return `<section class="funnel-panel panel"><div class="section-top"><span>◎</span><h3>Как мы выбрали?</h3><small>ПРОЗРАЧНЫЙ ПОДБОР</small></div><p class="section-caption">Каждый шаг — проверка вашего условия. Занятые на дату исключаются.</p>
    <div class="funnel">${visibleStages.map(([key,count]) => `<div class="funnel-step"><strong>${count}</strong><span>${stageLabels[key]}</span></div>`).join('')}</div>
    <div class="exclusions">${reasons.map(([key,count]) => `<span><b>${count}</b> — ${labels[key]}</span>`).join('')}${lowerRank > 0 ? `<span><b>${lowerRank}</b> — ниже в рейтинге</span>` : ''}${!reasons.length && lowerRank <= 0 ? `<span>${data.total_candidates ? 'Все кандидаты выбранной категории, прошедшие условия, показаны.' : 'В выбранном городе нет профилей этой категории.'}</span>` : ''}</div>
    <details class="audit-details"><summary>Причина исключения каждого профиля (${data.excluded_candidates.length})</summary><p>В воронке профиль учитывается один раз — на первом непройденном условии.</p><ul>${data.excluded_candidates.map(c => `<li>${esc(c.name)} <small>${esc(c.id)}</small> — ${c.all_reasons.map(r => esc(labels[r] || r)).join('; ')}</li>`).join('')}</ul></details>
  </section>`;
}

function render(data) {
  const request = data.request;
  const empty = !data.recommendations.length;
  const title = data.status === 'category_not_found' ? 'В этом городе категории пока нет' : empty ? 'По этим условиям совпадений нет' : 'Ваша короткая подборка';
  const chips = [request.city,dateLabel(request.date),capitalize(request.event_format),request.category,'до ' + money(request.budget_kzt)];
  if (request.duration_hours) chips.push(request.duration_hours + ' ч');
  if (request.language) chips.push(capitalize(request.language));
  output.innerHTML = `<div class="results-heading"><h2>${empty ? 'Результат подбора' : title} ${!empty ? `<span class="count-badge">${data.recommendations.length}</span>` : ''}</h2><span class="ranking-label">${request.sort_by === 'price' ? 'По стартовой цене ↑' : 'По баллу подбора ↓'}</span></div>
    <p class="result-subtitle">${esc(data.message)}</p><div class="query-chips">${chips.map(c => `<span>${esc(c)}</span>`).join('')}</div>
    ${empty ? `<div class="empty-state panel"><div class="empty-icon">⌕</div><h3>${title}</h3><p>${data.status === 'category_not_found' ? 'Попробуйте другой город или категорию. В каталоге нет профилей с этим сочетанием.' : 'Кандидаты есть в каталоге, но не проходят ваши условия. Ниже — конкретные причины и доступные изменения.'}</p><div class="empty-reasons">${Object.entries(data.excluded_reasons).filter(([key]) => !['wrong_city','wrong_category'].includes(key)).map(([key,count]) => `<span>${count} — ${labels[key]}</span>`).join('')}</div></div>` : `<div class="cards">${data.recommendations.map((c,i) => card(c,i,request)).join('')}</div>`}
    ${!empty && data.recommendations.length < 3 ? '<p class="notice">Подходящих профилей меньше трёх. Остальные исключены по причинам ниже.</p>' : ''}
    ${funnel(data)}
    ${data.suggestions.length ? `<section class="suggestions-panel"><h3>✧ Что изменить, чтобы получить больше вариантов?</h3><p>Условия изменятся только после нажатия на кнопку.</p>${data.suggestions.map((s,i) => `<div class="suggestion"><span>${esc(s.text)}</span><button data-suggestion="${i}">Применить и подобрать ↗</button></div>`).join('')}</section>` : ''}
    <p class="semantic-note">${data.preference_mode === 'embeddings' ? 'Используется смысловое сходство описания с запросом.' : data.preference_mode === 'keywords' ? 'Пожелания проверены локально по ключевым словам. Совпадения подтверждаются цитатами; отсутствие слов не доказывает отсутствие услуги.' : 'Без пожеланий и семантического анализа порядок определяется стартовой ценой.'} ${request.sort_by === 'price' ? 'Выбрана сортировка по цене.' : ''} Балл не является вероятностью или оценкой качества. Цена «от» и доступность требуют подтверждения.</p>
    ${data.semantic_retry_allowed ? '<div class="notice">Можно повторить AI-анализ после сбоя. При успехе оценка и порядок карточек могут измениться.<br><button type="button" class="retry-button" id="retry-semantic">Повторить AI-анализ</button></div>' : ''}`;
  $('#retry-semantic')?.addEventListener('click', () => {
    fill(data.request);
    search({refreshSemantic: true});
  });
  output.querySelectorAll('[data-detail]').forEach(button => button.addEventListener('click', () => showProfile(data.recommendations[Number(button.dataset.detail)])));
  output.querySelectorAll('[data-suggestion]').forEach(button => button.addEventListener('click', () => {
    const suggestion = data.suggestions[Number(button.dataset.suggestion)];
    fill({...data.request,...suggestion.changes});
    document.querySelectorAll('.demo-button').forEach(el => el.classList.remove('selected'));
    search();
  }));
}

function openDialog(label, html) {
  $('#dialog-label').textContent = label;
  $('#dialog-content').innerHTML = html;
  dialog.showModal();
}

function showProfile(candidate) {
  const breakdown = candidate.score_breakdown ? `<h3>Балл подбора: ${esc(candidate.score)} / 100</h3><p>Обязательные условия проверяются до оценки. При поиске по пожеланиям: соответствие описанию — 80, запас бюджета — 20. Без анализа пожеланий или в режиме цены учитывается только запас бюджета. Это не рейтинг качества.</p><table><thead><tr><th>Фактор</th><th>Балл / 100</th><th>Вес</th></tr></thead><tbody>${Object.entries(candidate.score_breakdown).map(([key,s]) => `<tr><td>${esc(scoreLabels[key] || key)}</td><td>${Number(s.value).toFixed(2)}</td><td>${Number(s.weight).toFixed(2)}%</td></tr>`).join('')}</tbody></table>` : '';
  openDialog(candidate.id, `<h2>${esc(candidate.name)}</h2><p>${esc(candidate.categories.join(' · '))} · ${esc(candidate.city)} · от ${money(candidate.price_from_kzt)}</p>${warningTags(candidate)}<h3>Условия на момент подбора</h3><ul>${candidate.reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul>${preferenceDetails(candidate)}<h3>Описание из датасета</h3><p class="profile-description">${esc(candidate.description || 'Описание не указано.')}</p><p>Форматы: ${esc(candidate.event_formats.join(', '))}.<br>Языки: ${esc(candidate.languages.join(', ') || 'не указаны')}.</p>${breakdown}${candidate.warnings.length ? `<h3>Особенности данных</h3><ul>${candidate.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}<p>Наличие в подборке не означает бронирование. Отсутствие записи о занятости в календаре требует подтверждения.</p>`);
}

$('#about-method').addEventListener('click', () => openDialog('КАК ЭТО РАБОТАЕТ', '<h2>Каждое совпадение объяснимо.</h2><ol><li>Берём профили из приложенного каталога. Проверяем город, категорию, календарь, формат, бюджет, часы подрядчика и язык.</li><li>По пожеланиям: сходство описания — вес 80, запас бюджета — 20. Без внешнего анализа используется проверка ключевых слов с цитатами. Неподтверждённые пожелания показываем отдельно.</li><li>В режиме цены сортируем по стартовой цене. Без пожеланий и внешнего анализа этот же порядок действует по умолчанию. При равном балле — по ID.</li><li>Календарь пересчитывает все обязательные условия на каждый день. Подсказки могут менять до трёх параметров только после вашего нажатия.</li><li>Команда: отдельный подрядчик на каждую роль, одна дата, отдельные часы. Выбираем минимальную сумму стартовых цен в общем бюджете.</li></ol><p>Балл не является вероятностью или рейтингом качества. Все суммы — цены «от». Доступность и состав услуг требуют подтверждения. Избранное хранится только в этом браузере.</p>'));
$('#about-data').addEventListener('click', () => {
  if (!metadata) return;
  openDialog('ВАШ КАТАЛОГ', `<h2>${esc(metadata.total)} профилей для ваших событий.</h2><div class="data-stats"><div><strong>${metadata.total}</strong><small>профилей</small></div><div><strong>${metadata.categories.length}</strong><small>категорий</small></div><div><strong>${metadata.cities.length}</strong><small>локации</small></div></div><p>Источник — загруженный каталог. Новые профили не добавлялись. В исходном каталоге хакатона имена анонимизированы.</p><p>Локации: ${esc(metadata.cities.join(', '))}.<br>Календарь: ${esc(metadata.calendar_start)} — ${esc(metadata.calendar_end)}.</p><p>Синтетических профилей: ${metadata.synthetic}. Город проставлен: ${metadata.city_imputed}. Цена проставлена: ${metadata.price_imputed}.</p><p>Для флористов, декораторов и сувениров пустой лимит часов означает работу без почасового присутствия. В других категориях неизвестный лимит не подтверждает длительность.</p>`);
});
$('#close-dialog').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => { if (event.target === dialog && (event.offsetX < 0 || event.offsetY < 0 || event.offsetX > dialog.clientWidth || event.offsetY > dialog.clientHeight)) dialog.close(); });
form.addEventListener('submit', event => {event.preventDefault();search();});
form.addEventListener('input', () => {validateDuration(); if (result) $('#dirty-notice').hidden = false; markCalendarDirty(); document.querySelectorAll('.demo-button').forEach(el => el.classList.remove('selected'));});

async function init() {
  if (pending) return;
  setBusy(true);
  try {
    metadata = await fetchJson('/api/meta');
    if (!metadata.cities.length || !metadata.categories.length || !metadata.event_formats.length) {
      throw new Error('В каталоге не хватает городов, категорий или форматов для подбора.');
    }
    populate('#city',metadata.cities);
    populate('#category',metadata.categories);
    populate('#event_format',metadata.event_formats);
    populate('#language',metadata.languages,true);
    $('#date').min = metadata.calendar_start;
    $('#date').max = metadata.calendar_end;
    $('#catalog-count').textContent = metadata.total + ' профилей в каталоге';
    $('#calendar-note').textContent = `${dateLabel(metadata.calendar_start)} — ${dateLabel(metadata.calendar_end)} ${metadata.calendar_end.slice(0,4)}`;
    $('#demo-buttons').innerHTML = metadata.demos.map((demo,i) => `<button class="demo-button ${i === 0 ? 'selected' : ''}" data-demo="${i}">${esc(demo.title)}</button>`).join('');
    document.querySelectorAll('[data-demo]').forEach(button => button.addEventListener('click', () => {
      fill(metadata.demos[Number(button.dataset.demo)].request);
      document.querySelectorAll('.demo-button').forEach(el => el.classList.toggle('selected',el === button));
      search();
    }));
    fill(metadata.demos[0]?.request || {city:metadata.cities[0],category:metadata.categories[0],event_format:metadata.event_formats[0],date:metadata.calendar_start,budget_kzt:600000,duration_hours:null,language:null,preferences:'',sort_by:'style'});
    setBusy(false);
    initFeatures(metadata, {openDialog, showProfile, applyRequest: request => {if (pending) return; fill(request); document.querySelectorAll('.demo-button').forEach(el => el.classList.remove('selected')); search(); form.scrollIntoView({behavior:'smooth',block:'start'});}, readForm});
    await search();
  } catch (error) {
    pending = false;
    output.setAttribute('aria-busy','false');
    $('#catalog-count').textContent = 'Каталог недоступен';
    output.innerHTML = `<div class="empty-state panel"><h3>Не удалось загрузить каталог</h3><p>${esc(error.message)} Убедитесь, что backend запущен.</p><button class="retry-button" id="retry-init">Повторить</button></div>`;
    $('#retry-init').addEventListener('click', init);
  }
}
init();
