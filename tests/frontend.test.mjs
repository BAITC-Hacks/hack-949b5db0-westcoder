// DOM integration tests. No browser/layout or external embeddings are involved.
// Setup: npm install jsdom --prefix .tools/ui-test --no-save --package-lock=false --ignore-scripts
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const require = createRequire(import.meta.url);
const {JSDOM} = require('../.tools/ui-test/node_modules/jsdom');
const root = fileURLToPath(new URL('../', import.meta.url));
const html = fs.readFileSync(new URL('../frontend/index.html', import.meta.url),'utf8');
const plannerSource = fs.readFileSync(new URL('../frontend/planner.js', import.meta.url),'utf8');
const featureSource = fs.readFileSync(new URL('../frontend/features.js', import.meta.url),'utf8').replaceAll('export function ','function ').replaceAll('export async function ','async function ');
const appSource = fs.readFileSync(new URL('../frontend/app.js', import.meta.url),'utf8').replace(/^import .*?;\r?\n/, 'const {initFeatures,profileActions,preferenceDetails,updateCalendar,markCalendarDirty}=window.__features;\n');

async function until(check, label, timeout=6000) {
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline) {if(check())return;await new Promise(r=>setTimeout(r,15));}
  assert.fail('Timed out: '+label);
}

test('single selection, wishes, calendar, favorites, comparison, compound suggestions and team', {timeout:30000}, async () => {
  const server=spawn(process.env.PYTHON || 'python',['-B','-m','backend.server','--port','0'],{cwd:root,env:{...process.env,ENABLE_EMBEDDINGS:'false'},windowsHide:true,stdio:['ignore','pipe','pipe']});
  let stdout='', stderr='', processError;
  server.stdout.on('data',b=>stdout+=b);
  server.stderr.on('data',b=>stderr+=b);
  server.on('error',e=>processError=e);
  const instances=[];
  try {
    await until(()=>processError || /http:\/\/127\.0\.0\.1:\d+/.test(stdout),'server startup');
    if(processError)throw processError;
    const base=stdout.match(/http:\/\/127\.0\.0\.1:\d+/)[0];
    const errors=[];
    function boot(storage, failure=null) {
      const dom=new JSDOM(html,{url:base,runScripts:'outside-only',pretendToBeVisual:true});
      instances.push(dom);
      const w=dom.window;
      w.AbortController=globalThis.AbortController;
      w.AbortSignal=globalThis.AbortSignal;
      w.__failure=failure;
      w.__requests=[];
      w.fetch=async (url,options)=>{
        const target=new URL(url,base);
        if(target.pathname==='/api/recommend')w.__requests.push(JSON.parse(options.body));
        if(target.pathname===w.__failure?.path) {
          if(w.__failure.mode==='offline')throw new TypeError('Failed to fetch');
          return new Response('<h1>Bad gateway</h1>',{status:502,headers:{'Content-Type':'text/html'}});
        }
        return fetch(target,options);
      };
      w.HTMLElement.prototype.scrollIntoView=function(){};
      w.HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
      w.HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
      w.addEventListener('error',e=>errors.push(e.error?.stack || e.message));
      if(storage)w.localStorage.setItem('eventmatch.favorites.v1',storage);
      w.eval('(()=>{'+plannerSource+'})();');
      w.eval('(()=>{'+featureSource+';window.__features={initFeatures,profileActions,preferenceDetails,updateCalendar,markCalendarDirty};})();');
      w.eval('(()=>{'+appSource+'})();');
      return w;
    }
    let w=boot();
    let doc=w.document;
    const q=s=>doc.querySelector(s);
    const all=s=>[...doc.querySelectorAll(s)];
    const input=(selector,value)=>{q(selector).value=value;q(selector).dispatchEvent(new w.Event('input',{bubbles:true}));};
    const settled=()=>!q('#submit-button').disabled && !q('#results .loading-card');
    await until(()=>all('.candidate-card').length===3 && settled(),'initial recommendations');
    await until(()=>all('[data-calendar-date]').length>0,'calendar');
    q('[data-detail="0"]').click();
    assert.equal(all('dialog table tbody tr').length,1,'Without preferences only the budget factor is active');
    q('#close-dialog').click();
    input('#budget_kzt','650123.45');
    input('#duration_hours','0.25');
    assert.equal(q('#event-form').checkValidity(),true,'Fractional inputs remain valid');
    q('#submit-button').click();
    await until(()=>settled() && all('.candidate-card').length===3,'fractional inputs');
    assert.equal(w.__requests.at(-1).budget_kzt,650123.45);
    assert.equal(w.__requests.at(-1).duration_hours,0.25);
    const beforeInvalid=w.__requests.length;
    input('#duration_hours','0');
    assert.equal(q('#duration_hours').checkValidity(),false,'Zero hours remain invalid');
    q('#submit-button').click();
    assert.equal(w.__requests.length,beforeInvalid,'Invalid duration does not submit a request');
    input('#duration_hours','6');
    input('#preferences','репортаж, естественные эмоции');
    assert.match(q('#calendar-content').textContent,/Параметры изменены/);
    q('#submit-button').click();
    q('#copy-event').click();
    assert.equal(q('#team-date').value,q('#date').value,'Copy also works while the main inputs are disabled');
    await until(()=>settled() && all('.preference-details').length===3,'style evidence');
    assert.match(q('#results').textContent,/ключевым словам/);
    const saveButtons=all('#results [data-save]');
    saveButtons[0].click();saveButtons[1].click();
    assert.equal(all('#saved-profiles .saved-card').length,2);
    assert.equal(Object.keys(JSON.parse(w.localStorage.getItem('eventmatch.favorites.v1'))).length,2);
    const compareBoxes=all('#results [data-compare]');
    compareBoxes[0].click();compareBoxes[1].click();
    assert.equal(q('#compare-button').disabled,false);
    q('#compare-button').click();
    assert.ok(q('dialog[open] .comparison-table'));
    assert.equal(all('.comparison-table thead th').length,3);
    q('#close-dialog').click();
    const storage=w.localStorage.getItem('eventmatch.favorites.v1');
    w.dispatchEvent(new w.Event('pagehide'));w.close();w=boot(storage);doc=w.document;
    await until(()=>settled() && all('.candidate-card').length===3,'reload');
    assert.equal(all('#saved-profiles .saved-card').length,2);
    all('[data-saved-detail]')[0].click();
    assert.ok(q('dialog[open] .profile-description'));
    q('#close-dialog').click();
    await until(()=>all('[data-calendar-date]').length>0,'calendar after reload');
    const nextDate=all('[data-calendar-date]').find(b=>b.dataset.calendarDate!==q('#date').value && b.classList.contains('has-matches'));
    const chosenDate=nextDate.dataset.calendarDate;
    nextDate.click();
    await until(()=>settled() && q('#date').value===chosenDate,'calendar applies date');
    all('.demo-button')[2].click();
    await until(()=>settled() && q('#budget_kzt').value==='50000','empty demo');
    input('#duration_hours','24');q('#submit-button').click();
    await until(()=>settled() && all('.suggestion button').length>0,'compound offers');
    assert.equal(all('.candidate-card').length,0);
    all('.suggestion button')[0].click();
    await until(()=>settled() && all('.candidate-card').length>0,'compound offer applied');
    assert.ok(Number(q('#budget_kzt').value)>50000);
    assert.ok(Number(q('#duration_hours').value)<24);
    input('#team-date','2026-09-23');q('#team-submit').click();
    await until(()=>!q('#team-submit').disabled && q('#team-results').getAttribute('aria-busy')==='false','complete team');
    assert.equal(all('#team-results .saved-card').length,2,q('#team-error').textContent+' '+q('#team-results').textContent);
    assert.ok(q('.team-total'));
    all('#team-results [data-save]')[1].click();
    const teamId=all('#team-results [data-save]')[1].dataset.save;
    q(`[data-saved-detail="${teamId}"]`).click();
    assert.ok(q('dialog[open]'));
    q('#close-dialog').click();
    input('#team-budget','1');q('#team-submit').click();
    await until(()=>!q('#team-submit').disabled && q('#apply-team-budget'),'over-budget team');
    assert.equal(all('#team-results .saved-card').length,0);
    q('#apply-team-budget').click();
    await until(()=>!q('#team-submit').disabled && all('#team-results .saved-card').length===2,'apply minimum budget');
    for(const mode of ['offline','invalid_json']) {
      w.__failure={path:'/api/recommend',mode};
      q('#submit-button').click();
      await until(()=>settled() && q('#retry-search'),'recommendation error: '+mode);
      assert.equal(q('#city').disabled,false);
      assert.equal(q('#preferences').disabled,false);
      w.__failure=null;
      q('#retry-search').click();
      await until(()=>settled() && all('.candidate-card').length>0,'recommendation retry: '+mode);
    }
    w.dispatchEvent(new w.Event('pagehide'));w.close();
    w=boot(storage,{path:'/api/meta',mode:'offline'});doc=w.document;
    await until(()=>q('#retry-init'),'startup failure');
    w.__failure=null;
    q('#retry-init').click();
    await until(()=>settled() && all('.candidate-card').length===3,'startup retry');
    await until(()=>all('[data-calendar-date]').length>0,'calendar after startup retry');
    assert.equal(q('#team-submit').disabled,false,'Team selection is initialized after retry');
    assert.equal(all('#saved-profiles .saved-card').length,2,'Favorites are restored after retry');
    assert.deepEqual(errors,[],'No runtime DOM errors');
    assert.doesNotMatch(stderr,/Traceback|ERROR/);
  } finally {
    instances.forEach(dom=>{if(dom.window.document)dom.window.dispatchEvent(new dom.window.Event('pagehide'));dom.window.close();});
    server.kill();
  }
});
