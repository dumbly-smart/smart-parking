(async (page) => {
  const checks=[],check=(ok,name)=>{if(!ok)throw Error(name);checks.push(name);};const diag=()=>page.evaluate(()=>document.querySelector('#garage-scene').__garageDiagnostics());
  await page.setViewportSize({width:1280,height:900});await page.locator('#scene-quality').selectOption('auto');await page.locator('#city-view').click();await page.waitForTimeout(950);let d=await diag();
  check(d.qualityMode==='auto' && d.pixelRatio<=1.5,'Auto uses a bounded frame-budget resolution');
  check(d.retainedTraffic.materialBatches<=9 && d.retainedTraffic.retainedComponents.every(n=>n>=200),'Distant traffic batches retain detailed geometry with at most nine material submissions');
  check(d.drawCalls<1100,'City draw submissions stay below the original two-thousand-call workload');
  check(d.occludedParkedCars>200,'Fully occluded cars are skipped behind solid garage slabs');
  check(d.depthMode==='adaptive-near' && d.cameraNear>=10,'Overview uses precise depth without logarithmic fragment writes');
  await page.locator('[data-floor="1"]').click();await page.waitForTimeout(800);d=await diag();check(d.parkedVisibility.filter(f=>f.shown).every(f=>f.visible===f.total),'Selecting a floor restores every parked model on that floor');
  await page.locator('#city-view').click();await page.waitForTimeout(900);await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));await page.waitForTimeout(300);d=await diag();check(!d.renderVisible,'Offscreen city canvas is detected');const before=d.renderedFrames;await page.waitForTimeout(400);check((await diag()).renderedFrames===before,'GPU rendering stops while the city is offscreen');
  await page.locator('#city-view').click();await page.waitForTimeout(600);check((await diag()).renderedFrames>before,'Rendering resumes when city returns onscreen');
  await page.locator('#scene-quality').selectOption('high');await page.waitForTimeout(350);d=await diag();check(d.pixelRatio>=1.5 && d.shadowMapSize>=2048,'Manual high detail remains available');await page.locator('#scene-quality').selectOption('auto');
  return {passed:checks.length,checks};
})
