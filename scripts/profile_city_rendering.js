(async (page) => {
  const source=await(await page.request.get('http://127.0.0.1:8000/api/sumo/status')).json();
  const vehicles=source.vehicles.slice(0,100),snapshot={...source,vehicles,vehicle_count:vehicles.length};
  await page.goto(new URL('/health',page.url()).href);
  await page.evaluate(async snapshot=>{
    const map=document.createElement('script');map.type='importmap';map.textContent=JSON.stringify({imports:{three:'/static/three.module.js'}});document.head.append(map);document.body.style.margin='0';document.body.innerHTML='<select id="scene-quality"><option value="auto">Auto</option><option value="high">High</option><option value="balanced">Balanced</option></select><div id="garage-scene" style="width:776px;height:650px;position:relative"></div>';
    const layout=await(await fetch('/api/sumo/map')).json(),{createParkingScene}=await import('/static/multi-floor-scene.js?v=performance-profile');window.__perfScene=await createParkingScene(document.querySelector('#garage-scene'),()=>{});window.__perfScene.setMapData(layout);window.__perfScene.setTrafficSnapshot(snapshot);
  },snapshot);
  const wait=ms=>new Promise(r=>setTimeout(r,ms));await wait(11000);
  const sample=()=>page.evaluate(async()=>{const intervals=[];let previous=performance.now(),end=previous+5000;await new Promise(resolve=>{function frame(now){intervals.push(now-previous);previous=now;if(now<end)requestAnimationFrame(frame);else resolve();}requestAnimationFrame(frame);});intervals.sort((a,b)=>a-b);const d=document.querySelector('#garage-scene').__garageDiagnostics();return {fps:Math.round(1000/(intervals.reduce((a,b)=>a+b,0)/intervals.length)),p95_frame_ms:Math.round(intervals[Math.floor(intervals.length*.95)]),draw_calls:d.drawCalls,triangles:d.triangles,renderer_cpu_ms:d.renderMs,update_cpu_ms:d.updateMs,pixel_ratio:d.pixelRatio,occluded_parked_cars:d.occludedParkedCars,shadow_map_size:d.shadowMapSize,mode:d.qualityMode,retained_components:d.retainedTraffic.retainedComponents,traffic_models:d.trafficModels};});
  const auto=await sample();await page.locator('#scene-quality').selectOption('high');await wait(2500);const high=await sample();return {viewport:{width:776,height:650},snapshot_vehicle_count:vehicles.length,auto,high};
})
