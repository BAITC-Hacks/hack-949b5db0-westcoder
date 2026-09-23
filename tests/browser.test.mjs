// Optional real-browser integration: npm install playwright @axe-core/playwright jsdom --prefix .tools/ui-test --no-save --package-lock=false --ignore-scripts
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import fs from 'node:fs';
const require=createRequire(import.meta.url);
const {chromium}=require('../.tools/ui-test/node_modules/playwright');
const AxeBuilder=require('../.tools/ui-test/node_modules/@axe-core/playwright').default;
const root=fileURLToPath(new URL('../',import.meta.url));

test('Chrome: brief review, team, reserve alternatives, export, recovery and responsive layout',{timeout:90000},async()=>{
  // Set EVENTMATCH_TEST_URL to check an already running local server as well.
  const server=process.env.EVENTMATCH_TEST_URL ? null : spawn(process.env.PYTHON || 'python',['-B','-m','backend.server','--port','0'],{cwd:root,windowsHide:true,env:{...process.env,ENABLE_EMBEDDINGS:'false',ENABLE_AI_BRIEF:'false'},stdio:['ignore','pipe','pipe']});
  let stdout='',stderr='',browser;
  server?.stdout.on('data',data=>stdout+=data);server?.stderr.on('data',data=>stderr+=data);
  try {
    const base=process.env.EVENTMATCH_TEST_URL || await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('Server startup timed out: '+stderr)),8000);
      server.on('error',reject);
      server.stdout.on('data',()=>{const m=stdout.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});
    });
    fs.mkdirSync(new URL('../artifacts/',import.meta.url),{recursive:true});
    browser=await chromium.launch({channel:'chrome',headless:true});
    const context=await browser.newContext({viewport:{width:1440,height:1050},deviceScaleFactor:1});
    const page=await context.newPage();
    const errors=[],assetErrors=[];page.on('pageerror',error=>errors.push(error.message));
    page.on('response',response=>{
      if (['stylesheet','script'].includes(response.request().resourceType()) && !response.ok())
        assetErrors.push(`${response.status()} ${response.url()}`);
    });
    page.on('requestfailed',request=>{
      if (['stylesheet','script'].includes(request.resourceType())) assetErrors.push(request.url());
    });
    await page.goto(base,{waitUntil:'networkidle'});
    assert.deepEqual(assetErrors,[],'All stylesheets and scripts must load; restart the server after backend updates');
    const styles=await page.evaluate(()=>({
      studioLoaded:[...document.styleSheets].some(sheet=>new URL(sheet.href || location.href).pathname==='/studio.css'),
      briefDisplay:getComputedStyle(document.querySelector('#brief-panel')).display,
      scripts:[...document.querySelectorAll('script[src]')].map(script=>script.src),
    }));
    assert.equal(styles.studioLoaded,true,'Studio stylesheet is attached');
    assert.equal(styles.briefDisplay,'grid','The planning workspace must have its layout styles applied');
    assert.equal(new Set(styles.scripts).size,styles.scripts.length,'Modules must be included only once');
    await page.locator('.candidate-card').first().waitFor();
    assert.equal(await page.locator('.candidate-card').count(),3);
    await page.screenshot({path:root+'artifacts/studio-desktop.png'});
    const checkOverflow=async()=>{
      const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,
        outside:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,cls:e.className,id:e.id,right:e.getBoundingClientRect().right})).slice(0,15)}));
      assert.ok(layout.scroll<=layout.width,'No horizontal overflow: '+JSON.stringify(layout));
    };
    await checkOverflow();
    await page.locator('[data-brief-example="wedding"]').click();
    await page.locator('#brief-submit').click();
    await page.locator('#draft-form').waitFor();
    assert.equal(await page.locator('#draft-budget').inputValue(),'2000000');
    assert.equal(await page.locator('#draft-city').inputValue(),'Алматы');
    assert.equal(await page.locator('[name="draft-role"]:checked').count(),2);
    // Review really controls the request; it is not submitted just by parsing.
    assert.equal(await page.locator('#team-results .saved-card').count(),0);
    await page.locator('#draft-date').fill('2026-09-23');
    await page.locator('#draft-hours').fill('');
    await page.locator('#apply-draft').click();
    assert.equal(await page.locator('#team-date').inputValue(),'2026-09-23');
    await page.locator('#team-submit').click();
    await page.locator('#handoff:not([hidden])').waitFor();
    assert.equal(await page.locator('#team-results .saved-card').count(),2);
    const downloadPromise=page.waitForEvent('download');await page.locator('#export-brief').click();
    const download=await downloadPromise;
    assert.equal(download.suggestedFilename(),'eventmatch-2026-09-23.txt');
    const exported=fs.readFileSync(await download.path(),'utf8');
    assert.match(exported,/ВОПРОСЫ ПЕРЕД ПОДТВЕРЖДЕНИЕМ/);
    assert.match(exported,/Фотограф/);
    await page.locator('#plan-button').click();
    await page.locator('[data-plan-date]').first().waitFor();
    assert.match(await page.locator('.plan-summary').innerText(),/200\s?000/);
    await page.locator('[data-plan-date="0"]').click();
    await page.locator('#handoff:not([hidden])').waitFor();
    assert.equal(await page.locator('#team-budget').inputValue(),'1800000');
    assert.equal(await page.locator('#reserve-percent').inputValue(),'0');
    await page.locator('#team-budget').fill('1500000');
    assert.equal(await page.locator('#handoff').isVisible(),false,'Do not export a stale team');
    await page.locator('#team-submit').click();
    await page.locator('#handoff:not([hidden])').waitFor();
    // New endpoints retain a visible, usable failure path.
    await page.route('**/api/brief',route=>route.abort());
    await page.locator('#brief-submit').click();
    await page.locator('#brief-error:not([hidden])').waitFor();
    assert.equal(await page.locator('#brief-submit').isEnabled(),true);
    await page.unroute('**/api/brief');
    await page.locator('#brief-submit').click();await page.locator('#draft-form').waitFor();
    for(const width of [360,390,768,1024,1440]) {
      await page.setViewportSize({width,height:1000});await checkOverflow();
    }
    await page.setViewportSize({width:390,height:844});await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:root+'artifacts/studio-mobile.png'});
    await page.screenshot({path:root+'artifacts/studio-mobile-full.png',fullPage:true});
    await page.setViewportSize({width:1440,height:1050});
    const audit=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
    fs.writeFileSync(root+'artifacts/accessibility.json',JSON.stringify(audit.violations,null,2));
    assert.deepEqual(audit.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)})),[],'Accessibility audit');
    await page.locator('[data-detail="0"]').click();
    assert.equal(await page.locator('dialog[open]').count(),1);
    const dialogAudit=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
    assert.deepEqual(dialogAudit.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})),[],'Profile dialog accessibility');
    await page.keyboard.press('Escape');
    assert.deepEqual(errors,[],'No browser runtime errors');
    assert.doesNotMatch(stderr,/Traceback/);
  } finally {await browser?.close();server?.kill();}
});
