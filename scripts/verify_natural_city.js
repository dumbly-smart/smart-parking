// Run using playwright-cli run-code --filename=scripts/verify_natural_city.js.
(async (page) => {
  const checks=[],check=(ok,name)=>{if(!ok)throw Error(name);checks.push(name);};
  const diagnostics=()=>page.evaluate(()=>document.querySelector('#garage-scene').__garageDiagnostics());
  await page.setViewportSize({width:1536,height:1100});await page.locator('#scene-quality').selectOption('high');await page.locator('#city-view').click();await page.waitForTimeout(1100);
  let d=await diagnostics();
  check(d.shadowsEnabled && d.shadowMapReady && d.shadowMapSize>=2048 && d.shadowSpan>=800,'City shadows are enabled, rendered and cover the district');
  check(d.city.shadowMasses===101 && d.city.streetLightAnchors>100,'Building shadow masses and street-light positions exist');
  check(d.environment.visible && d.environment.clouds===18 && d.environment.terrainVertices>10000,'Continuous terrain and atmospheric clouds exist');
  check(d.environment.textures>=6 && d.environment.anisotropy>=4,'Textured surfaces retain filtered detail');
  check(d.retainedTraffic.retainedComponents.every(count=>count>=200),'Full vehicle geometry is retained in distant batches');
  check(d.pixelRatio>=1.5,'High detail uses supersampled rendering');
  const terrainCheck=await page.evaluate(async()=>{const THREE=await import('/static/three.module.js'),module=await import('/static/city-environment.js?v=1'),scene=new THREE.Scene(),e=module.createNaturalEnvironment(scene,{}, {capabilities:{getMaxAnisotropy:()=>8}}),mesh=e.root.children.find(c=>c.geometry?.attributes.color),p=mesh.geometry.attributes.position,index=mesh.geometry.index;let clear=true,finite=true;
    for(let i=0;i<index.count;i+=3){const indices=[index.getX(i),index.getX(i+1),index.getX(i+2)],x=indices.reduce((s,j)=>s+p.getX(j),0)/3,z=indices.reduce((s,j)=>s+p.getZ(j),0)/3;if(x>-130&&x<130&&z>-70&&z<70)clear=false;}
    for(let i=0;i<p.count;i++)finite&&=Number.isFinite(p.getY(i));return {clear,finite,flat:Math.abs(module.groundHeight(-560,540)+.55)<.001};});
  check(terrainCheck.clear && terrainCheck.finite,'Terrain has a finite, unobstructed basement opening');
  check(terrainCheck.flat,'SUMO street network remains on flat terrain');
  await page.locator('#scene-quality').selectOption('balanced');check((await diagnostics()).pixelRatio<=1.25,'Balanced quality lowers resolution without dropping model geometry');await page.locator('#scene-quality').selectOption('high');
  await page.locator('[data-floor="1"]').click();d=await diagnostics();check(!d.environment.visible && !d.city.visible && d.floorElevations[0].visible,'Basement inspection hides surrounding terrain and city');
  await page.locator('#city-view').click();await page.locator('#scene-lighting').selectOption('golden');await page.locator('#mechanical-animations').uncheck();
  let status=await page.evaluate(async()=>await(await fetch('/api/sumo/status')).json());const wasRunning=status.state==='running';if(wasRunning)await page.locator('#sumo-pause').click();
  await page.waitForTimeout(1000);d=await diagnostics();check(d.lightingMode==='golden','Golden hour changes the lighting state');
  const scene=page.locator('#garage-scene'),on=await scene.screenshot({path:'output/playwright/natural-city-golden.png'});
  await page.locator('#soft-shadows').uncheck();await page.waitForTimeout(900);const off=await scene.screenshot({path:'output/playwright/natural-city-no-shadow.png'});
  const difference=await page.evaluate(async({a,b})=>{async function read(data){const img=new Image();img.src='data:image/png;base64,'+data;await img.decode();const c=document.createElement('canvas');c.width=img.width;c.height=img.height;const ctx=c.getContext('2d');ctx.drawImage(img,0,0);return ctx.getImageData(0,0,c.width,c.height).data;}const x=await read(a),y=await read(b);let total=0;for(let i=0;i<x.length;i++)if(i%4!==3)total+=Math.abs(x[i]-y[i]);return total/(x.length*.75);},{a:on.toString('base64'),b:off.toString('base64')});
  check(difference>.3,'Enabled shadows visibly change the rendered city');
  await page.locator('#soft-shadows').check();await page.locator('#mechanical-animations').check();await page.locator('#scene-lighting').selectOption('day');await page.waitForTimeout(900);await scene.screenshot({path:'output/playwright/natural-city-day.png'});
  if(wasRunning)await page.locator('#sumo-resume').click();
  await page.locator('#scene-quality').selectOption('auto');
  return {passed:checks.length,checks,shadowPixelDifference:difference,retainedVehicleComponents:d.retainedTraffic.retainedComponents,environment:d.environment};
})
