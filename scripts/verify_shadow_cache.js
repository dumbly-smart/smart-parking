(async (page) => {
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto(new URL('/health',page.url()).href);
  const result=await page.evaluate(async()=>{
    const map=document.createElement('script');map.type='importmap';map.textContent=JSON.stringify({imports:{three:'/static/three.module.js'}});document.head.append(map);
    const layout=await(await fetch('/api/sumo/map')).json();delete layout.city;layout.floors=layout.floors.map(f=>({...f,bays:f.bays.slice(0,8)}));
    const container=document.createElement('div');Object.assign(container.style,{width:'640px',height:'400px'});document.body.append(container);
    const {createParkingScene}=await import('/static/multi-floor-scene.js?v=shadow-regression');const api=await createParkingScene(container,()=>{});api.setMapData(layout);
    const wait=ms=>new Promise(r=>setTimeout(r,ms));const frames=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    const diag=()=>container.__garageDiagnostics();await wait(900);
    api.setTrafficSnapshot({vehicle_count:1,vehicles:[{id:'shadow-cache-car',x:-50,y:-20,elevation:0,floor:3,angle:90,speed_mps:0,in_city:false}]});await frames();const before=diag().shadowUpdates;
    api.setTrafficSnapshot({vehicle_count:0,vehicles:[]});await frames();if(diag().shadowUpdates<=before)throw Error('Removed traffic must invalidate the cached shadow map');
    const empty=Array.from({length:5},(_,i)=>({id:i+1,occupied:false}));await api.syncSlots(empty,{animate:false});await frames();const parkedBefore=diag().shadowUpdates;
    await api.syncSlots(empty.map(s=>({...s,occupied:s.id===1})));await frames();if(diag().shadowUpdates<=parkedBefore)throw Error('Reduced-motion arrivals must invalidate cached shadows');
    const exitBefore=diag().shadowUpdates;await api.syncSlots(empty);await frames();if(diag().shadowUpdates<=exitBefore)throw Error('Reduced-motion departures must invalidate cached shadows');
    return {passed:3,checks:['Removed traffic invalidates cached shadows','Reduced-motion arrivals invalidate shadows','Reduced-motion departures invalidate shadows']};
  });
  await page.emulateMedia({reducedMotion:'no-preference'});return result;
})
