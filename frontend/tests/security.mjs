import {chromium} from 'playwright';
import assert from 'node:assert/strict';

const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext();
const page=await context.newPage();
const errors=[];
page.on('pageerror',e=>errors.push(e.message));
try{
  // Authenticate through the loopback-only development front door, then reuse the
  // localhost session for the separately running production frontend on port 3001.
  await page.goto('http://localhost:3000');
  await page.getByRole('button',{name:'Открыть локальную версию'}).click();
  await page.getByRole('heading',{name:'Твои подписки.'}).waitFor();
  // Inject into the HTML response so Chrome's HTML parser (not DevTools' trusted
  // evaluation context) evaluates the attempted script under the response CSP.
  await page.route('http://localhost:3001/',async route=>{
    const original=await route.fetch();const html=await original.text();
    await route.fulfill({response:original,body:html.replace('</body>','<script>window.__untrustedScriptExecuted=true</script></body>')});
  });
  const response=await page.goto('http://localhost:3001');
  await page.getByRole('heading',{name:'Твои подписки.'}).waitFor();
  const policy=response.headers()['content-security-policy'];
  assert.ok(policy.includes('strict-dynamic'));
  assert.ok(!policy.includes('unsafe-eval'));
  assert.ok(!/script-src[^;]*unsafe-inline/.test(policy));
  assert.ok(policy.includes("frame-ancestors 'none'"));
  assert.ok(response.headers()['permissions-policy'].includes('camera=()'));
  const scriptNonces=await page.locator('script').evaluateAll(nodes=>nodes.filter(n=>n.textContent.trim()).map(n=>n.nonce));
  assert.ok(scriptNonces.filter(Boolean).length>0);
  assert.equal(scriptNonces.filter(n=>!n).length,1);
  assert.equal(await page.evaluate(()=>window.__untrustedScriptExecuted),undefined);
  const again=await context.request.get('http://localhost:3001');
  assert.notEqual(again.headers()['content-security-policy'],policy);
  const anon=await browser.newContext();
  const denied=await anon.request.get('http://localhost:3001/api/members/');
  assert.equal(denied.status(),403);
  assert.ok(denied.headers()['cache-control'].includes('no-store'));
  await anon.close();
  assert.deepEqual(errors,[]);
  console.log('Production browser security passed: nonces on framework scripts, fresh policy per request, injected script blocked, no unsafe-eval/inline scripts, private API denied and not cached.');
}finally{await browser.close();}
