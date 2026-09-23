// Brief review and deterministic planning. Credentials never enter the browser.
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(value) + ' ₸';
const dateLabel = value => new Date(value+'T12:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'long'});
let metadata, initialized=false, briefBusy=false, briefVersion=0, planVersion=0, planController, latestTeam;

async function post(path, body, signal=AbortSignal.timeout(18000)) {
  let response;
  try { response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal}); }
  catch(error) { throw new Error(error.name==='TimeoutError' ? 'Ответ задерживается. Попробуйте ещё раз.' : 'Нет связи с сервером. Попробуйте ещё раз.'); }
  let result;
  try {result=await response.json();} catch {throw new Error('Сервер вернул некорректный ответ. Повторите запрос.');}
  if(!response.ok)throw new Error(result.fields ? Object.values(result.fields).join(' ') : result.error || 'Не удалось выполнить запрос.');
  return result;
}
function options(values, value, placeholder='Выберите') {
  return `<option value="">${placeholder}</option>`+values.map(v=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(v)}</option>`).join('');
}
function renderDraft(result) {
  const d=result.draft;
  $('#brief-result').innerHTML=`<div class="draft-heading"><h3>Черновик вашего события</h3><p>${esc(result.note)}</p></div><form id="draft-form"><div class="draft-grid">
    <label>Город<select id="draft-city" required>${options(metadata.cities,d.city)}</select></label>
    <label>Дата<input id="draft-date" type="date" min="${metadata.calendar_start}" max="${metadata.calendar_end}" value="${esc(d.date)}" required></label>
    <label>Формат<select id="draft-format" required>${options(metadata.event_formats,d.event_format)}</select></label>
    <label>Общий бюджет, ₸<input id="draft-budget" type="number" min="0" step="any" value="${d.budget_kzt ?? ''}" required></label>
    <label>Часы для каждой роли<input id="draft-hours" type="number" min="0" step="any" value="${d.duration_hours ?? ''}" placeholder="Любые"></label>
    <label>Язык<select id="draft-language">${options(metadata.languages,d.language,'Любой')}</select></label></div>
    <fieldset class="draft-roles"><legend>Кто нужен в команде? Выберите до 5 ролей.</legend><div class="draft-role-list">${metadata.categories.map(c=>`<label><input type="checkbox" name="draft-role" value="${esc(c)}" ${d.roles.includes(c)?'checked':''}>${esc(c)}</label>`).join('')}</div></fieldset>
    <label for="draft-preferences">Пожелания и детали</label><textarea id="draft-preferences" rows="2" maxlength="1500">${esc(d.preferences)}</textarea>
    <p class="draft-note">Заполните пропуски. Часы применятся ко всем выбранным ролям — их можно изменить отдельно в команде. Бюджет — на всю команду.</p>
    <p id="draft-error" class="notice" role="alert" hidden></p><button class="primary-button" id="apply-draft">Применить к команде →</button></form>`;
  const hours=$('#draft-hours');
  const validateHours=()=>hours.setCustomValidity(hours.value!=='' && Number(hours.value)<=0 ? 'Укажите положительное число часов.' : '');
  hours.addEventListener('input',validateHours);
  $('#draft-form').addEventListener('submit',event=>{
    event.preventDefault();validateHours();if(!event.currentTarget.reportValidity())return;
    const roles=[...document.querySelectorAll('[name="draft-role"]:checked')].map(c=>({category:c.value,duration_hours:hours.value===''?null:Number(hours.value)}));
    const error=$('#draft-error');
    if(!roles.length || roles.length>5) {error.textContent='Выберите от одной до пяти ролей.';error.hidden=false;return;}
    if($('#team-submit').disabled) {error.textContent='Дождитесь текущего подбора команды.';error.hidden=false;return;}
    const request={city:$('#draft-city').value,date:$('#draft-date').value,event_format:$('#draft-format').value,
      budget_kzt:Number($('#draft-budget').value),language:$('#draft-language').value||null,preferences:$('#draft-preferences').value,roles};
    document.dispatchEvent(new CustomEvent('eventmatch:apply-team',{detail:request}));
    error.hidden=true;$('#team-panel').scrollIntoView({behavior:'smooth',block:'start'});$('#team-submit').focus({preventScroll:true});
    $('#apply-draft').textContent='Параметры перенесены ✓';
  });
}
function readTeam() {
  return {city:$('#team-city').value,date:$('#team-date').value,event_format:$('#team-format').value,
    budget_kzt:Number($('#team-budget').value),language:$('#team-language').value||null,preferences:$('#team-preferences').value,
    roles:[...document.querySelectorAll('.team-role')].map(row=>({category:row.querySelector('.role-category').value,
      duration_hours:row.querySelector('.role-hours').value===''?null:Number(row.querySelector('.role-hours').value)}))};
}
function invalidatePlan() {
  planVersion++;planController?.abort();$('#plan-button').disabled=!metadata || $('#team-submit').disabled;
  if($('#plan-results').textContent)$('#plan-results').innerHTML='<p class="notice">Условия изменены. Проверьте план Б заново.</p>';
  latestTeam=null;$('#handoff').hidden=true;
}
async function compareDates() {
  if($('#team-submit').disabled || !$('#team-form').reportValidity())return;
  const request=readTeam(), reserve=Number($('#reserve-percent').value), version=++planVersion;
  planController?.abort();const controller=new AbortController();planController=controller;
  const timer=setTimeout(()=>controller.abort(),12000);
  $('#plan-button').disabled=true;$('#plan-results').innerHTML='<p role="status">Проверяем команды на соседние даты…</p>';
  try {
    const data=await post('/api/plan',{...request,reserve_percent:reserve},controller.signal);
    if(version!==planVersion)return;
    $('#plan-results').innerHTML=`<div class="plan-summary"><h3>${data.current.status==='matched'?'На вашу дату команда укладывается с резервом.':'На вашу дату команда с таким резервом не найдена.'}</h3><p>На подрядчиков: <strong>${money(data.spendable_kzt)}</strong>. Резерв: ${money(data.reserve_kzt)} (${data.reserve_percent}%). Проверено соседних дат: ${data.checked_dates}.</p></div>
      ${data.alternatives.length?`<div class="plan-grid">${data.alternatives.map((option,i)=>`<article class="plan-card"><small>${i===0?'МИНИМАЛЬНАЯ СУММА СРЕДИ СОСЕДНИХ ДАТ':'ЕЩЁ ОДИН ВАРИАНТ'}</small><h4>${esc(dateLabel(option.date))}</h4><strong>от ${money(option.total_from_kzt)}</strong><p>${option.members.map(c=>esc(c.category)).join(' · ')}</p><button class="secondary-button" data-plan-date="${i}">Выбрать дату →</button></article>`).join('')}</div>`:'<p class="notice">В пределах ±7 дней полная команда с резервом не найдена. Попробуйте уменьшить часы или пересмотреть роли.</p>'}<p class="semantic-note">${esc(data.note)} При выборе даты бюджет подбора станет ${money(data.spendable_kzt)}: резерв останется за его пределами.</p>`;
    document.querySelectorAll('[data-plan-date]').forEach(button=>button.onclick=()=>{
      if($('#team-submit').disabled)return;
      const date=data.alternatives[Number(button.dataset.planDate)].date;
      document.dispatchEvent(new CustomEvent('eventmatch:apply-team',{detail:{...request,date,budget_kzt:data.spendable_kzt}}));
      $('#reserve-percent').value='0'; // The reserve is already outside this budget.
      $('#team-form').requestSubmit();
    });
  } catch(error) {
    if(version===planVersion)$('#plan-results').innerHTML=`<p class="notice" role="alert">${esc(error.message)} Нажмите «Проверить план Б», чтобы повторить.</p>`;
  } finally {clearTimeout(timer);if(version===planVersion)$('#plan-button').disabled=$('#team-submit').disabled;}
}
function exportBrief() {
  if(!latestTeam)return;
  const d=latestTeam, r=d.request;
  const lines=['EVENTMATCH — БРИФ МЕРОПРИЯТИЯ','',`${r.city} · ${r.date} · ${r.event_format}`,
    `Бюджет команды: ${money(r.budget_kzt)}`,`Сумма стартовых цен: ${money(d.total_from_kzt)}`,`Остаток: ${money(d.remaining_kzt)}`,
    `Язык: ${r.language || 'не ограничен'}`,...(r.preferences ? ['Пожелания: '+r.preferences] : []),'','КОМАНДА',
    ...d.members.flatMap(c=>[`${c.category}: ${c.name} (${c.id}) — от ${money(c.price_from_kzt)}`,`Часы: ${c.duration_hours ?? 'уточнить'}. ${c.warnings.join(' ')}`]),'',
    'ВОПРОСЫ ПЕРЕД ПОДТВЕРЖДЕНИЕМ','1. Свободна ли дата? Кто именно приедет на событие?',
    '2. Что входит в стоимость? Как оплачиваются дорога, оборудование и дополнительные часы?',
    '3. Каковы условия предоплаты, отмены и замены исполнителя?',
    '4. Можно ли увидеть актуальное портфолио и подтвердить пожелания?',
    '5. Каковы время приезда, монтажа и контакты ответственного?', '',
    'Это предварительный подбор из демонстрационного каталога, не подтверждённое бронирование.',
    'Имена анонимизированы. Цена «от» и отсутствие записи о занятости требуют подтверждения.',
    'Источник каталога (SHA-256): '+d.dataset_sha256];
  const url=URL.createObjectURL(new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/plain;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download=`eventmatch-${r.date}.txt`;document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
document.addEventListener('eventmatch:ready',event=>{
  metadata=event.detail;
  $('#brief-mode').textContent=metadata.ai_brief_available?'AI-разбор · OpenAI':'Локальный разбор · без внешнего AI';
  $('#brief-privacy').textContent=metadata.ai_brief_available?'Описание будет отправлено в OpenAI для разбора. Не добавляйте личные данные.':'Описание разбирается локально. Проверьте черновик перед применением.';
  $('#brief-submit').disabled=false;$('#plan-button').disabled=false;
  if(initialized)return;initialized=true;
  const examples={wedding:'Свадьба в Алматы 26.09.2026. Бюджет 2 млн тенге. Нужны фотограф и ведущий на 6 часов. Русский язык. Живые эмоции, без громких конкурсов.',
    corporate:'Корпоратив в Астане 15.10.2026. Бюджет 3 млн тенге. Нужны фотограф и ведущий на 4 часа. Русский язык. Спокойная подача и репортаж.'};
  document.querySelectorAll('[data-brief-example]').forEach(button=>button.onclick=()=>{
    $('#brief-text').value=examples[button.dataset.briefExample];$('#brief-text').dispatchEvent(new Event('input'));$('#brief-text').focus();
  });
  $('#brief-text').addEventListener('input',()=>{briefVersion++;$('#brief-result').innerHTML='';});
  $('#brief-form').addEventListener('submit',async event=>{
    event.preventDefault();if(briefBusy || !event.currentTarget.reportValidity())return;
    const version=++briefVersion;briefBusy=true;$('#brief-submit').disabled=true;$('#brief-error').hidden=true;
    $('#brief-result').innerHTML='<p role="status">Разбираем описание события…</p>';
    try {const result=await post('/api/brief',{text:$('#brief-text').value});if(version===briefVersion)renderDraft(result);}
    catch(error) {if(version===briefVersion){$('#brief-result').innerHTML='';$('#brief-error').textContent=error.message;$('#brief-error').hidden=false;}}
    finally {briefBusy=false;$('#brief-submit').disabled=false;}
  });
  $('#plan-button').onclick=compareDates;$('#reserve-percent').addEventListener('change',invalidatePlan);$('#export-brief').onclick=exportBrief;
});
document.addEventListener('eventmatch:team-dirty',invalidatePlan);
document.addEventListener('eventmatch:team-busy',event=>{if(event.detail)invalidatePlan();$('#plan-button').disabled=event.detail;});
document.addEventListener('eventmatch:team-result',event=>{latestTeam=event.detail.status==='matched'?event.detail:null;$('#handoff').hidden=!latestTeam;});
window.addEventListener('pagehide',()=>{briefVersion++;planVersion++;planController?.abort();});
