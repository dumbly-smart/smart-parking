import * as THREE from '/static/three.module.js';
import { createRenderBudget } from '/static/render-budget.js?v=1';
import { createNaturalEnvironment } from '/static/city-environment.js?v=1';
import { createCityDistrict } from '/static/city-scene.js?v=2';
import { createGarageSign } from '/static/parking-scene.js?v=18';
import { createVehicle, animateVehicle, addParkedVehicles, addDeckDetails, createBarrier, animateBarrier, animateArchitecture, addRampDetails, animateRamp, addSiteDetails, disposeVehicle, hashModelId, createDistantTraffic, mergeArchitecturalBoxes } from '/static/garage-models.js?v=10';
import { buildEntryJourney, buildParkingManeuver, sampleParkingManeuver, vehicleNearBarrier, wrapAngle } from '/static/garage-motion.js?v=4';

const material = (color, extra = {}) => {const {roughness,metalness,...surface}=extra;return new THREE.MeshLambertMaterial({color,...surface});};
const clamp = THREE.MathUtils.clamp;
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export async function createParkingScene(container, onSelect, sceneConfig = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.max(.75,Math.min(devicePixelRatio || 1,1.25)));
  let qualityMode='auto';const renderBudget=createRenderBudget({initialRatio:renderer.getPixelRatio(),maxRatio:Math.min(Math.max(devicePixelRatio || 1,1),1.5)});renderBudget.reset(performance.now(),renderer.getPixelRatio());
  let renderVisible=true;const sceneVisibility=new IntersectionObserver(entries=>{renderVisible=entries[0].isIntersecting;},{rootMargin:'100px'});sceneVisibility.observe(container);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.shadowMap.autoUpdate=false;renderer.shadowMap.needsUpdate=true;
  container.prepend(renderer.domElement);
  const scene = new THREE.Scene();scene.matrixAutoUpdate=false;
  scene.background = new THREE.Color('#152933');
  const hemisphere=new THREE.HemisphereLight(0xe9f6ff, 0x627262, 2.5);scene.add(hemisphere);
  const sunlight = new THREE.DirectionalLight(0xffedce, 2.8);
  sunlight.position.set(-100, 180, 90); scene.add(sunlight,sunlight.target);
  sunlight.castShadow=true;sunlight.shadow.mapSize.set(Math.min(2048,renderer.capabilities.maxTextureSize),Math.min(2048,renderer.capabilities.maxTextureSize));sunlight.shadow.camera.near=1;sunlight.shadow.camera.far=2300;sunlight.shadow.bias=-.00008;sunlight.shadow.normalBias=.16;
  const fill = new THREE.DirectionalLight(0xb9ddff, 1.3); fill.position.set(100, 70, -80); scene.add(fill);
  const camera = new THREE.PerspectiveCamera(42, 1, .1, 6500);
  const building = new THREE.Group(), ramps = new THREE.Group(), traffic = new THREE.Group(), site = new THREE.Group();
  scene.add(site, building, ramps, traffic);
  const distantTraffic=createDistantTraffic(traffic);
  const deckGroups = new Map(), trafficCars = new Map(), liveCars = new Map(), pads = new Map(), motions = new Map(), gateArms = new Map();
  const parkedBatches=[],frameBefore=new THREE.Vector3(),frameFocus=new THREE.Vector3(),markerPoint=new THREE.Vector3();
  const mechanisms=[],rampMechanisms=[],sensors=new Map();let entranceBarrier=null,exitBarrier=null,simulationRunning=false,activeRampIds=new Set(),mechanicalAnimations=!reducedMotion,followId=null,lastFrame=performance.now(),frameTime=16,renderTime=0,updateTime=0,suspendRendering=false;
  let renderedFrames=0;
  const unitBox = new THREE.BoxGeometry(1, 1, 1);
  const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
  let cityDistrict=null,naturalEnvironment=null,cityScope=true,cityEnabled=true,lightingMode='day';
  const streetLights=Array.from({length:4},()=>{const light=new THREE.PointLight(0xffdca0,90,28,2);light.visible=false;scene.add(light);return light;});
  let data = null, slots = [], selected = null, selectedLevel = null, viewMode = 'assembled';
  let orbit = .52, tilt = .48, radius = 245, target = new THREE.Vector3(-5, 33, 6), cameraTween = null;
  const palette = [0x80cad9, 0xf3ad83, 0xb8a0da, 0xf2ca78, 0xe793b7, 0xb6d889];

  function cube(parent, x, y, z, w, h, d, color, extra = {}) {
    const mesh = new THREE.Mesh(unitBox, material(color, extra));
    mesh.receiveShadow=true;mesh.castShadow=true;
    mesh.userData.staticArchitectural=true;
    mesh.position.set(x, y, z); mesh.scale.set(w, h, d); parent.add(mesh); return mesh;
  }
  function sign(parent, text, x, y, z, width = 9, color = '#dcecc9') {
    const mesh = createGarageSign(text, { color, background: '#1b333d', width: 420, height: 100, size: Math.min(64, 540 / text.length) });
    mesh.position.set(x, y, z); mesh.scale.set(width, width / 4.2, 1); parent.add(mesh); return mesh;
  }
  function lines(parent, vertices, color, opacity = 1) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    const mesh = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color, transparent: opacity < 1, opacity }));
    parent.add(mesh); return mesh;
  }
  function instanceBoxes(parent, positions, dimensions, color) {
    if (!positions.length) return;
    const mesh = new THREE.InstancedMesh(unitBox, material(color), positions.length), matrix = new THREE.Matrix4();
    positions.forEach((p, i) => { matrix.compose(new THREE.Vector3(...p), new THREE.Quaternion(), new THREE.Vector3(...dimensions)); mesh.setMatrixAt(i, matrix); });
    mesh.instanceMatrix.needsUpdate = true; parent.add(mesh); return mesh;
  }

  const floorHeight = () => data?.floor_height || 4.2;
  const floorElevation = level => data?.floors?.find(f=>f.number===level)?.elevation ?? (level-1)*floorHeight();
  const floorName = level => data?.floors?.find(f=>f.number===level)?.name || `${level}F`;
  let undergroundCutaway=true;
  const earth = new THREE.Group();site.add(earth);
  const displaySpacing = () => viewMode === 'exploded' && selectedLevel === null ? 14 : floorHeight();
  const elevationY = value => value / floorHeight() * displaySpacing();
  let drivenSlotId=null,driverView=true,navigationRoute=null;
  const navigation=new THREE.Group();navigation.name='Assigned bay navigation';scene.add(navigation);
  const navCanvas=document.querySelector('#parking-minimap'),navContext=navCanvas?.getContext('2d');
  const driverEye=new THREE.Vector3(),driverAhead=new THREE.Vector3();
  function clearNavigation(){
    if(drivenSlotId!==null){const model=liveCars.get(drivenSlotId);if(model)model.visible=true;}
    drivenSlotId=null;navigationRoute=null;
    for(const child of [...navigation.children]){navigation.remove(child);child.geometry?.dispose();child.material?.dispose();}
    const panel=document.querySelector('#parking-navigation');if(panel)panel.hidden=true;
  }
  function followParking(id){
    clearNavigation();const bay=trackedBays.get(id);if(!bay)return;
    drivenSlotId=id;driverView=true;followId=null;cityScope=false;selectedLevel=null;viewMode='assembled';cameraTween=null;radius=18;applyView();
    const panel=document.querySelector('#parking-navigation');if(panel)panel.hidden=false;
    const toggle=document.querySelector('#parking-camera-toggle');if(toggle){toggle.setAttribute('aria-pressed','true');toggle.textContent='Overhead view';}
    const marker=new THREE.Mesh(new THREE.ConeGeometry(.55,1.3,12),new THREE.MeshBasicMaterial({color:0xb7ff65,depthTest:false}));
    marker.rotation.z=Math.PI;marker.position.set(bay.x,elevationY(floorElevation(bay.floor))+2.3,-bay.y);marker.renderOrder=30;navigation.add(marker);
  }
  function updateParkingNavigation(now){
    if(drivenSlotId===null)return;
    const bay=trackedBays.get(drivenSlotId),model=liveCars.get(drivenSlotId),motion=motions.get(drivenSlotId);
    if(!bay)return;
    if(motion && navigationRoute!==motion.maneuver){
      navigationRoute=motion.maneuver;
      const old=navigation.children.find(child=>child.name==='Parking route');if(old){navigation.remove(old);old.geometry.dispose();old.material.dispose();}
      const points=[];for(const curve of [motion.maneuver.forward,motion.maneuver.reverse].filter(Boolean))for(const point of curve.getPoints(70)){point.y=motion.maneuver.worldSpace?point.y+.1:elevationY(floorElevation(bay.floor))+.22;points.push(point);}
      const route=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color:0x51dfff,depthTest:false}));route.name='Parking route';route.renderOrder=25;navigation.add(route);
    }
    const trackedSlot=slots.find(slot=>slot.id===drivenSlotId);
    if(!model && !motion && trackedSlot && !trackedSlot.occupied){clearNavigation();resetView();return;}
    const name=trackedSlot?.name || `Bay ${drivenSlotId}`;
    const distance=model?Math.hypot(model.position.x-bay.x,model.position.z+bay.y):0;
    const currentFloor=motion?.maneuver.worldSpace?clamp(Math.round((model?.position.y || 0)/floorHeight())+(data.ground_floor || 3),1,6):bay.floor;
    const status=document.querySelector('#parking-destination');if(status)status.textContent=`${name} · ${floorName(currentFloor)} → ${floorName(bay.floor)} · ${Math.round(distance)} m · ${motion?(motion.operation==='exit'?'Departing':sampleParkingManeuver(motion.maneuver,now-motion.start).reversing?'Reverse into bay':'Follow the route'):'Parked'}`;
    if(!navContext)return;
    const c=navContext,w=navCanvas.width,h=navCanvas.height,px=x=>(x+150)/250*w,pz=z=>(z+36)/72*h;
    c.fillStyle='#10212e';c.fillRect(0,0,w,h);c.strokeStyle='#52717c';c.lineWidth=.7;
    for(const b of data.floors.find(f=>f.number===bay.floor).bays){const ew=b.orientation==='east-west';c.strokeRect(px(b.x-(ew?2.5:1.25)),pz(-b.y-(ew?1.25:2.5)),(ew?5:2.5)/250*w,(ew?2.5:5)/72*h);}
    c.beginPath();c.moveTo(px(-149),pz(20));c.lineTo(px(-83),pz(20));c.moveTo(px(-149),pz(28));c.lineTo(px(-35),pz(28));c.stroke();
    if(navigationRoute){c.strokeStyle='#52ddff';c.lineWidth=2;c.beginPath();for(const curve of [navigationRoute.forward,navigationRoute.reverse].filter(Boolean))for(const p of curve.getPoints(45))c.lineTo(px(p.x),pz(p.z));c.stroke();}
    c.fillStyle='#b7ff65';c.fillRect(px(bay.x)-3,pz(-bay.y)-3,6,6);
    if(model){c.save();c.translate(px(model.position.x),pz(model.position.z));c.rotate(-model.rotation.y);c.fillStyle='#ffcd66';c.beginPath();c.moveTo(0,6);c.lineTo(-4,-4);c.lineTo(4,-4);c.closePath();c.fill();c.restore();}
  }
  let lastNearPlane=0;
  function cameraPosition() {
    if(drivenSlotId!==null && driverView){
      const model=liveCars.get(drivenSlotId);
      if(model){
        model.visible=false;model.updateWorldMatrix(true,false);
        driverEye.set(-.35,1.28,.35);driverAhead.set(-.35,1.23,9);model.localToWorld(driverEye);model.localToWorld(driverAhead);
        camera.position.copy(driverEye);camera.near=.08;camera.updateProjectionMatrix();lastNearPlane=.08;camera.lookAt(driverAhead);return;
      }
    }

    const nearPlane=Math.max(.08,Math.min(25,radius*.02));if(Math.abs(nearPlane-lastNearPlane)>.001){camera.near=nearPlane;camera.updateProjectionMatrix();lastNearPlane=nearPlane;}
    camera.position.set(target.x + Math.sin(orbit) * radius * Math.cos(tilt), target.y + Math.sin(tilt) * radius, target.z + Math.cos(orbit) * radius * Math.cos(tilt));
    camera.lookAt(target);
  }
  function moveCamera(nextTarget, nextRadius, nextTilt = tilt, nextOrbit = orbit) {
    cameraTween = { start: performance.now(), from: { target: target.clone(), radius, tilt, orbit }, to: { target: nextTarget, radius: nextRadius, tilt: nextTilt, orbit: nextOrbit } };
  }
  function fitRadius(span = 205) {
    const widthFit = span / (2 * Math.tan(camera.fov * Math.PI / 360) * Math.max(.65, camera.aspect));
    return Math.max(190, widthFit * 1.25);
  }
  function updateControls() {
    container.closest('.garage-map-card')?.querySelectorAll('[data-floor]').forEach(button => {
      const active = button.dataset.floor === String(selectedLevel ?? 'all'); button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
    });
    const control = document.querySelector('#garage-view-mode'); if (control) control.value = viewMode;
    container.closest('.garage-map-card')?.querySelectorAll('[data-floor]').forEach(button=>{if(button.dataset.floor!=='all' && data){const count=button.querySelector('small'),dot=button.querySelector('.floor-live-dot');button.replaceChildren(document.createTextNode(`${floorName(Number(button.dataset.floor))} `));if(dot)button.append(dot);if(count)button.append(count);}});
    document.querySelector('#city-view')?.setAttribute('aria-pressed',String(cityScope));
    const status = document.querySelector('#floor-view-status');
    if (status) status.textContent = cityScope && data?.city ? 'PARKFLOW CENTRAL · CITY DISTRICT' : selectedLevel ? `${floorName(selectedLevel)} · live tracked occupancy · 396 bays` : viewMode === 'exploded' ? 'ALL SIX FLOORS · EXPLODED VIEW' : 'ALL SIX FLOORS · ASSEMBLED BUILDING';
    const inspector=document.querySelector('#vehicle-inspection');if(inspector)inspector.hidden=!followId;
  }
  function resetView() {
    clearNavigation();
    followId=null;cityScope=false;
    selectedLevel = null; applyView();
    moveCamera(new THREE.Vector3(-5, elevationY((floorElevation(1)+floorElevation(6))/2), 8), fitRadius(camera.aspect<.85?210:205), .47, camera.aspect<.85?1:.52);
  }
  function selectFloor(level) {
    clearNavigation();
    followId=null;cityScope=false;
    selectedLevel = level === null ? null : Number(level);
    applyView();
    if (selectedLevel === null) return resetView();
    moveCamera(new THREE.Vector3(0, elevationY(floorElevation(selectedLevel)), 0), fitRadius(195), .68, .27);
  }
  function focusLiveBays() {
    clearNavigation();
    followId=null;cityScope=false;
    selectedLevel = 5; applyView();
    const values = data?.active_bays || [];
    const x = values.reduce((s, b) => s + b.x, 0) / (values.length || 1), z = -values.reduce((s, b) => s + b.y, 0) / (values.length || 1);
    moveCamera(new THREE.Vector3(x, elevationY(floorElevation(5)) + 1, z), 28, .65, .3);
  }
  function focusSlot(id) { const b=trackedBays.get(id);if(!b)return;selectFloor(b.floor);moveCamera(new THREE.Vector3(b.x,elevationY(floorElevation(b.floor))+.5,-b.y),19,.7,.3); }
  function cityView(){
    clearNavigation();
    if(!data?.city)return resetView();
    followId=null;selectedLevel=null;cityScope=true;viewMode='assembled';cityEnabled=true;
    const checkbox=document.querySelector('#city-scenery');if(checkbox)checkbox.checked=true;
    applyView();moveCamera(new THREE.Vector3(0,12,0),Math.max(1400,fitRadius(1280)*1.18),.78,.45);
  }
  function inspectVehicle(){
    clearNavigation();
    const available=[...trafficCars.keys()];if(!available.length)return;
    const previous=available.indexOf(followId);followId=available[(previous+1)%available.length];
    const state=trafficCars.get(followId);cityScope=false;selectedLevel=state.vehicle.in_city?null:(state.vehicle.floor || 1);applyView();
    moveCamera(new THREE.Vector3(state.vehicle.x,elevationY(state.vehicle.elevation || 0)+.9,-state.vehicle.y),9.5,.28,state.yaw+.7);
  }
  let shadowDirty=true,lastShadowUpdate=0,lastShadowFocus=new THREE.Vector3(Infinity,Infinity,Infinity),shadowUpdates=0;
  function setLighting(mode){
    shadowDirty=true;
    lightingMode=mode;const evening=mode==='evening',golden=mode==='golden';
    hemisphere.intensity=evening?.4:cityScope?1.0:1.3;sunlight.intensity=evening?.3:golden?3.2:3.0;fill.intensity=evening?.3:golden?.3:.45;
    sunlight.color.set(evening?0xc3d4ed:golden?0xffc17e:0xffe6be);hemisphere.color.set(evening?0x819bc4:0xc2dbef);hemisphere.groundColor.set(0x717f5f);
    scene.background=new THREE.Color(evening?0x0a1528:0xa8c4cf);cityDistrict?.setLighting(mode);naturalEnvironment?.setLighting(mode);renderer.toneMappingExposure=evening?1.12:1.05;
  }
  function updateLightingCoverage(now){
    const span=radius>650?900:Math.max(32,Math.min(420,radius*.9)),focus=target.clone();focus.y=Math.max(0,focus.y);const golden=lightingMode==='golden';
    sunlight.target.position.copy(focus);sunlight.position.copy(focus).add(new THREE.Vector3(-500,golden?380:720,340));
    const shadowCamera=sunlight.shadow.camera;if(shadowCamera.right!==span){shadowDirty=true;shadowCamera.left=-span;shadowCamera.right=span;shadowCamera.top=span;shadowCamera.bottom=-span;shadowCamera.updateProjectionMatrix();}
    if(lastShadowFocus.distanceToSquared(focus)>1){shadowDirty=true;lastShadowFocus.copy(focus);}
    let gateAnimating=false;for(const gate of gateArms.values())if(Math.abs(gate.open-(gate.target?1:0))>.01)gateAnimating=true;
    const dynamicShadows=trafficCars.size>0 || motions.size>0 || gateAnimating || mechanicalAnimations && radius<300;
    if(renderer.shadowMap.enabled && (shadowDirty || dynamicShadows && now-lastShadowUpdate>(radius<300?50:radius<650?125:1000))){renderer.shadowMap.needsUpdate=true;lastShadowUpdate=now;shadowDirty=false;shadowUpdates++;}
    const anchors=cityDistrict?.lightAnchors || [],nearby=lightingMode==='evening' && cityDistrict?.root.visible && radius<200 ? [...anchors].sort((a,b)=>Math.hypot(a[0]-target.x,a[2]-target.z)-Math.hypot(b[0]-target.x,b[2]-target.z)).slice(0,4):[];
    streetLights.forEach((light,i)=>{light.visible=Boolean(nearby[i]);if(nearby[i])light.position.set(...nearby[i]);});
  }

  function makeDeck(floor) {
    const group = new THREE.Group(); building.add(group); deckGroups.set(floor.number, group);
    const accent = new THREE.Color(floor.color);
    cube(group, 0, -.35, 0, 190, .65, 64, 0x8b9f9d);
    cube(group, 0, .005, 0, 188.7, .06, 62.8, floor.number % 2 ? 0x3e5155 : 0x46595c);
    // Perimeter circulation surfaces and the ramp bank access gaps.
    cube(group, -2.5, .05, -20, 172, .025, 7.2, 0x263c44);
    cube(group, -2.5, .05, 20, 172, .025, 7.2, 0x263c44);
    for (const x of [-83, -68, -53, -38, -23, -8, 48, 63, 78]) cube(group, x, .06, 0, 4.8, .025, 36, 0x2c4148);
    const markings = [], dash = [];
    for (const bay of floor.bays) {
      if (bay.live_slot_id !== null) continue;
      const w = bay.orientation === 'east-west' ? 5 : 2.5, d = bay.orientation === 'east-west' ? 2.5 : 5;
      const x = bay.x, z = -bay.y;
      for (const [ax, az, bx, bz] of [[x-w/2,z-d/2,x+w/2,z-d/2],[x-w/2,z+d/2,x+w/2,z+d/2],[x-w/2,z-d/2,x-w/2,z+d/2],[x+w/2,z-d/2,x+w/2,z+d/2]]) markings.push(ax,.1,az,bx,.1,bz);
    }
    lines(group, markings, 0xb8c7bf, .82);
    for (let x = -81; x < 79; x += 7) for (const z of [-20,20]) dash.push(x,.115,z,x+2.6,.115,z);
    lines(group, dash, 0xe8ce7a);
    // Instanced architectural columns and wheel stops keep the six-deck view light.
    instanceBoxes(group, [-90,-60,-30,0,30,60,90].flatMap(x => [-29,29].map(z => [x,1.85,z])), [.65,3.7,.65], 0xa5b9b8);
    cube(group, 0, .75, -31.3, 189, .18, .16, accent);
    for (const x of [-94.2,94.2]) cube(group, x, .75, 0, .16, .18, 62, accent);
    // Leave southern access gaps at x=-35 and x=35 for the two ramp lanes.
    for (const [x,w] of [[-65,58],[0,62],[65,58]]) cube(group,x,.75,31.3,w,.18,.16,accent);
    for (const x of [-93,93]) {
      cube(group,x,1.5,34,4.3,3,5.8,0x64818b); cube(group,x,1.3,30.99,1.8,2.5,.08,0xb8d2d5);
    }
    sign(group, `${floor.name}${floor.number===5?' · LIVE BAYS':''}`, -86, 2.5, 32.8, 14, floor.color);
    sign(group, floor.number===data.ground_floor?'GROUND · ENTRY / EXIT':`${floor.name} · PARKING DECK`, 68, 1.6, 31.6, 16, floor.color);
    const zoneLetters = floor.number % 2 ? ['R','N','M','L','K','J','B','C','D'] : ['N','M','L','K','J','H','B','C','D'];
    [-83,-68,-53,-38,-23,-8,48,63,78].forEach((x,i) => sign(group,zoneLetters[i],x,2.2,15.8,2.8,floor.color));
    // Parked cars come exclusively from durable tracked occupancy records.
    mechanisms.push(addDeckDetails(group,floor,sign));
    for (const x of [-70,-10,50]) cube(group,x,3.55,0,12,.08,.2,0xe5f2da,{emissive:0xc8e9e5,emissiveIntensity:.35});
    if (floor.number === 5) buildLiveBays(group);
    mergeArchitecturalBoxes(group);
  }

  function buildLiveBays(group) {
    // Keep tracked bays on the same 2.5 m × 5 m grid as the modeled
    // reference spaces. The largest modeled SUV (including mirrors) is
    // about 2.22 m wide × 4.65 m long, leaving clearance on every side.
    const bayWidth = 2.5, bayLength = 5, padInset = .05;
    for (const bay of data.active_bays) {
      const pad = cube(group,bay.x,.13,-bay.y,bayWidth-padInset*2,.05,bayLength-padInset*2,0x709650,{emissive:0xa7da62,emissiveIntensity:.12});
      pad.userData.slotId = bay.id; pads.set(bay.id,pad);
      pad.userData.staticArchitectural=false;
      const sensorMaterial=material(0x63e7a0,{emissive:0x32cc77,emissiveIntensity:1.3});const sensor=new THREE.Mesh(new THREE.SphereGeometry(.095,10,6),sensorMaterial);sensor.position.set(bay.x,2.9,-bay.y);group.add(sensor);sensors.set(bay.id,sensor);
      cube(group,bay.x,3.04,-bay.y,.23,.12,.2,0xf0f3e8);cube(group,bay.x,3.25,-bay.y,.035,.35,.035,0x81959b);
      const vertices = [], x=bay.x,z=-bay.y;
      for(const [ax,az,bx,bz] of [[x-bayWidth/2,z-bayLength/2,x+bayWidth/2,z-bayLength/2],[x-bayWidth/2,z+bayLength/2,x+bayWidth/2,z+bayLength/2],[x-bayWidth/2,z-bayLength/2,x-bayWidth/2,z+bayLength/2],[x+bayWidth/2,z-bayLength/2,x+bayWidth/2,z+bayLength/2]])vertices.push(ax,.19,az,bx,.19,bz);
      lines(group,vertices,0xd4fb8a);
      sign(group,bay.name,bay.x,.65,z+2.6,2.9,'#e4ffa2');
    }
    sign(group,'LIVE SENSOR ZONE · 2F',-79,3,-31,11,'#d9fc9d');
    for(const [operation,z,length] of [['entry',-23.5,3.8],['exit',-20,3.2]]) {
      gateArms.set(operation,createBarrier(group,-70,z,'z',length));
    }
  }
  function buildSite() {
    // A real opening in the terrain exposes the two basement decks.
    for(const [x,z,w,d] of [[-110,-10,28,130],[110,-10,28,130],[0,-55,192,40]])cube(site,x,-.42,z,w,.65,d,0x364d49);
    cube(earth,0,-10,0,240,.7,120,0x68736c);
    // Layered soil, foundation waterproofing and retaining-wall anchors.
    for(const [y,h,color] of [[-1.3,1.8,0x70513d],[-3.8,3.2,0x9c7653],[-7.1,3.4,0x5f544a]]){
      cube(earth,-119,y,0,2,h,120,color);cube(earth,119,y,0,2,h,120,color);cube(earth,0,y,-59,236,h,2,color);
      for(const x of [-107,107])cube(earth,x,y,55,22,h,1.3,color);
    }
    for(const x of [-115,115]){cube(earth,x,-4.7,-2,.7,9,112,0x81908d);for(let z=-53;z<52;z+=8){cube(earth,x+(x<0?.4:-.4),-3,z,.12,.3,.3,0xc4c9bd);cube(earth,x+(x<0?.4:-.4),-7,z,.12,.3,.3,0xc4c9bd);}}
    for(let x=-112;x<114;x+=8)cube(earth,x,-4.7,-55,.3,9,.8,0x8b9995);
    sign(earth,'B2 · BASEMENT · −8.4 m',-65,-7.2,56,27,'#76c8d4');
    sign(earth,'B1 · BASEMENT · −4.2 m',-65,-3.1,56,27,'#f0a377');
    sign(site,'GROUND LEVEL · STREET ACCESS',42,.5,58,34,'#d5efb6');
    mergeArchitecturalBoxes(earth);
    cube(site,-104,-.7,20,12,.09,105,0x1c3039);
    for(let z=-30;z<70;z+=10)cube(site,-104,-.62,z,.18,.03,4,0xb7c7b6);
    addSiteDetails(site,sign,{barrier:false});
    buildAccessGates();
    sign(site,'P2 · SIX LEVELS',-101,5,6,10);
    sign(site,'UP RAMPS',-3,.4,41,14,'#f4cf85'); sign(site,'DOWN RAMPS',-3,.4,51,14,'#e9ad88');
    mergeArchitecturalBoxes(site);
  }
  function clearRamps() { rampMechanisms.length=0;while(ramps.children.length){const item=ramps.children[0];ramps.remove(item);item.traverse(node=>{if(node.geometry && node.geometry!==unitBox)node.geometry.dispose();if(node.material){for(const m of Array.isArray(node.material)?node.material:[node.material])if(!m.userData.shared)m.dispose();}});} }
  function buildAccessGates() {
    const plaza=new THREE.Group();plaza.name='Separate entry and exit plaza';site.add(plaza);
    for(const [z,color] of [[20,0x477c70],[28,0x846142]]){
      cube(plaza,-128,.04,z,46,.07,3.2,0x24343d);
      for(const side of [-1,1])cube(plaza,-128,.09,z+side*1.7,46,.09,.16,0xd5d5bf);
      for(const x of [-142,-131,-115]){
        const direction=z===20?1:-1;
        cube(plaza,x,.095,z,3.2,.035,.18,color);
        lines(plaza,[x+direction*1.6,.13,z,x+direction*.3,.13,z-.8,x+direction*1.6,.13,z,x+direction*.3,.13,z+.8],0xffefc0);
      }
      cube(plaza,-126,.1,z,.22,.04,3,0xf3efe0);
      cube(plaza,-130,.105,z,2,.015,2.5,0x608795,{transparent:true,opacity:.25});
    }
    cube(plaza,-124,.18,24,14,.36,4.3,0xd3c9a6);
    for(const x of [-130,-118])for(const z of [22.2,25.8]){cube(plaza,x,.65,z,.18,1.3,.18,0xf2ba48);cube(plaza,x,.9,z,.2,.12,.2,0x242c30);}
    cube(plaza,-124,1.65,24,4.6,2.9,2.7,0xe4ded0);
    cube(plaza,-124,2.1,22.63,3.8,1.45,.035,0x79b6c8,{transparent:true,opacity:.5});
    cube(plaza,-124,2.1,25.37,3.8,1.45,.035,0x79b6c8,{transparent:true,opacity:.5});
    for(const x of [-126.32,-121.68])cube(plaza,x,2.1,24,.04,1.45,2.1,0x79b6c8,{transparent:true,opacity:.5});
    cube(plaza,-124,3.2,24,5.3,.2,3.4,0x325e6e);
    for(const z of [17,31])cube(plaza,-124,2.7,z,.24,5.4,.24,0x6f8794);
    cube(plaza,-124,5.45,24,8,.22,15.5,0x547b87,{transparent:true,opacity:.3,depthWrite:false});
    for(const z of [18.2,29.8])cube(plaza,-124,5.27,z,6,.08,.2,0xdbeff2,{emissive:0xa8dce5,emissiveIntensity:.8});
    entranceBarrier=createBarrier(plaza,-123,18.4,'z',3.2);
    exitBarrier=createBarrier(plaza,-123,26.4,'z',3.2);
    for(const [x,z,label,color] of [[-129,17,'ENTRY →','#99f4c8'],[-119,32,'← EXIT','#ffd59b']]){
      cube(plaza,x,2,z,.16,4,.16,0x879ba0);sign(plaza,label,x,3.7,z,6,color);
      cube(plaza,x,1.1,z,.4,.6,.35,0x172e3a);cube(plaza,x-.22,1.2,z,.035,.26,.22,0x7ce4e9,{emissive:0x56c8df,emissiveIntensity:.7});
    }
    for(const [x,z,direction] of [[-127,20,-1],[-121,28,1]]){
      cube(plaza,x,4.9,z,.08,.8,.08,0x5d727f);
      cube(plaza,x,4.5,z,.65,.27,.32,0xd9e4e1);
      cube(plaza,x+direction*.34,4.5,z,.035,.19,.22,0x17242b);
      cube(plaza,x+direction*.365,4.5,z,.025,.1,.1,0x456fa0,{emissive:0x1d527b,emissiveIntensity:.5});
    }
    for(const [x,z] of [[-126,22.05],[-120,25.95]]){
      cube(plaza,x,.8,z,.35,1.6,.32,0x264653);
      cube(plaza,x,1.35,z,.4,.42,.35,0xc9d9df);
      cube(plaza,x-.22,1.4,z,.025,.22,.24,0x65cce4,{emissive:0x318bb9,emissiveIntensity:.7});
      cube(plaza,x-.23,1.12,z,.025,.035,.18,0x101e29);
    }
    sign(plaza,'P2 · ENTRY / EXIT',-124,7.8,24,9,'#ecf3e1');
    sign(plaza,'TICKET · RFID · PLATE READER',-124,3.65,25.8,7,'#accbda');
  }

  function buildRamps() {
    clearRamps();
    for(const ramp of data?.inter_floor_ramps || []) {
      const rampGroup=new THREE.Group();rampGroup.userData.floors=[ramp.from_floor,ramp.to_floor];ramps.add(rampGroup);
      const points=ramp.points.map(p=>new THREE.Vector3(p[0],elevationY(p[2]),-p[1]));
      for(let i=1;i<points.length;i++) {
        const a=points[i-1],b=points[i],side=new THREE.Vector3(b.z-a.z,0,-(b.x-a.x)).normalize().multiplyScalar(ramp.width/2);
        const vertices=[a.clone().add(side),a.clone().sub(side),b.clone().sub(side),b.clone().add(side)];
        const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute([...vertices[0],...vertices[1],...vertices[2],...vertices[0],...vertices[2],...vertices[3]],3));g.computeVertexNormals();
        rampGroup.add(new THREE.Mesh(g,material(0x50616a,{side:THREE.DoubleSide})));
        const rails=[];
        for(const s of [-1,1]){const aa=a.clone().addScaledVector(side,s),bb=b.clone().addScaledVector(side,s);rails.push(aa.x,aa.y+.65,aa.z,bb.x,bb.y+.65,bb.z);}
        lines(rampGroup,rails,ramp.direction==='up'?0xf1cc7d:0xf2a78c);
        const center=[];for(let k=0;k<10;k+=2){const aa=a.clone().lerp(b,k/10),bb=a.clone().lerp(b,(k+1)/10);center.push(aa.x,aa.y+.06,aa.z,bb.x,bb.y+.06,bb.z);}lines(rampGroup,center,0xf4e6b9);
      }
      rampMechanisms.push(addRampDetails(rampGroup,ramp,points));rampGroup.traverse(node=>{if(node.isMesh){node.castShadow=true;node.receiveShadow=true;}});
    }
    // Short level connectors join the ramp banks to the south drive aisle.
    for(const floor of data?.floors || []) {
      const y=elevationY(floor.elevation);
      if(floor.number<6) for(const [x,end] of [[-35,40],[-35,47]])cube(ramps,x,y-.08,(20+end)/2,3.8,.16,end-20,0x4d6067).userData.floors=[floor.number];
      if(floor.number>1) for(const [x,end] of [[35,40],[35,47]])cube(ramps,x,y-.08,(20+end)/2,3.8,.16,end-20,0x4d6067).userData.floors=[floor.number];
    }
  }
  function applyView() {
    shadowDirty=true;sunlight.castShadow=renderer.shadowMap.enabled;
    for(const [level,group] of deckGroups){group.position.y=elevationY(floorElevation(level));group.visible=(selectedLevel===null || selectedLevel===level) && (undergroundCutaway || selectedLevel!==null || floorElevation(level)>=0);}
    if(cityDistrict)cityDistrict.root.visible=cityEnabled && selectedLevel===null;
    naturalEnvironment?.setVisible(cityEnabled && selectedLevel===null);
    const lighting=document.querySelector('#scene-lighting')?.value || 'day';setLighting(lighting);
    if(data)buildRamps();earth.visible=undergroundCutaway && viewMode!=='exploded';ramps.children.forEach(child=>{const levels=child.userData.floors;child.visible=undergroundCutaway || !levels || levels.every(level=>floorElevation(level)>=0);});ramps.visible=selectedLevel===null || Boolean(followId);site.visible=selectedLevel===null;
    if(followId)ramps.children.forEach(child=>{child.visible=child.userData.floors?.includes(selectedLevel) ?? false;});
    for(const state of trafficCars.values())updateVehicleTarget(state);
    updateControls();
  }
  const trackedBays = new Map();
  function setMapData(layout) {
    data=layout;
    let nextId=6;
    for(const floor of data.floors || [])for(const bay of floor.bays){
      const id=bay.live_slot_id ?? nextId++;
      trackedBays.set(id,{...bay,id,floor:floor.number,heading:bay.orientation==='east-west' ? (bay.x<[-83,-68,-53,-38,-23,-8,48,63,78].reduce((a,b)=>Math.abs(a-bay.x)<Math.abs(b-bay.x)?a:b)?Math.PI/2:-Math.PI/2) : ((bay.y>0?-20:20)+bay.y>0?0:Math.PI)});
    }
    for(const floor of data.floors || [])makeDeck(floor);
    buildSite();if(data.city?.buildings?.length){naturalEnvironment=createNaturalEnvironment(scene,data.city,renderer);cityDistrict=createCityDistrict(scene,data.city,sign);}applyView();syncSlots(slots,{animate:false});if(cityDistrict)cityView();else resetView();
  }
  function colorPad(slot) { const pad=pads.get(slot.id);if(pad)pad.material.color.setHex(selected===slot.id?0x94c66d:slot.occupied?0xb77552:0x709650);const sensor=sensors.get(slot.id);if(sensor){const color=slot.occupied?0xff5b62:0x53ed96;sensor.material.color.setHex(color);sensor.material.emissive.setHex(color);} }
  function selectSlot(id){selected=id;slots.forEach(colorPad);}
  function ensureLiveCar(id) {let model=liveCars.get(id);if(!model){shadowDirty=true;model=createVehicle(hashModelId((slots.find(slot=>slot.id===id)?.rfid_uid?.split(':').slice(2).join(':') || `live-${id}`).toLowerCase()),{lazyDetailed:true});deckGroups.get(trackedBays.get(id)?.floor || 5)?.add(model);liveCars.set(id,model);}return model;}
  function startMotion(operation,id) {
    if(!data)return Promise.resolve();
    const interrupted=motions.get(id);interrupted?.resolve();
    const bay=trackedBays.get(id);if(!bay)return Promise.resolve();
    const configured=sceneConfig.slots?.[id];
    const model=ensureLiveCar(id);
    const maneuver=operation==='entry'?buildEntryJourney(data,bay):buildParkingManeuver(operation,bay,configured?.exit_route,interrupted&&operation==='exit'?model.position:null);
    if(maneuver.worldSpace)scene.add(model);
    model.userData.arrivalAt=null;
    shadowDirty=true;
    if(reducedMotion){if(operation==='exit'){model.parent?.remove(model);disposeVehicle(model);liveCars.delete(id);}else {deckGroups.get(bay.floor)?.add(model);model.position.set(bay.x,.12,-bay.y);}return Promise.resolve();}
    const initial=sampleParkingManeuver(maneuver,0);model.position.copy(initial.position);model.rotation.y=initial.heading;
    return new Promise(resolve=>motions.set(id,{operation,maneuver,model,start:performance.now()+600,duration:maneuver.duration,previous:model.position.clone(),lastYaw:model.rotation.y,speed:0,resolve}));
  }
  function syncSlots(next,{animate=true}={}) {
    const previous=new Map(slots.map(s=>[s.id,s]));slots=next || [];const started=[];
    for(const slot of slots){colorPad(slot);if(!data)continue;const old=previous.get(slot.id);
      if(animate && old && old.occupied!==slot.occupied){started.push(startMotion(slot.occupied?'entry':'exit',slot.id));continue;}
      if(motions.has(slot.id))continue;
      const b=trackedBays.get(slot.id);if(!b)continue;
      if(slot.occupied){const model=ensureLiveCar(slot.id);if(model.position.x!==b.x || model.position.z!==-b.y)shadowDirty=true;model.position.set(b.x,.12,-b.y);model.rotation.x=0;model.rotation.y=sceneConfig.slots?.[slot.id]?.heading ?? b.heading;}
      else if(liveCars.has(slot.id)){shadowDirty=true;const model=liveCars.get(slot.id);model.parent?.remove(model);disposeVehicle(model);liveCars.delete(slot.id);}
    }return Promise.all(started);
  }
  function updateVehicleTarget(state) {
    const v=state.vehicle;
    state.target.set(v.x,elevationY(v.elevation || 0)+.1,-v.y);
    state.model.visible=v.in_city ? (String(v.id)===followId || selectedLevel===null && cityEnabled) : (String(v.id)===followId || selectedLevel===null || Math.abs((v.elevation || 0)-floorElevation(selectedLevel))<.45) && (undergroundCutaway || selectedLevel!==null || (v.elevation || 0)>=-.1);
  }
  function setTrafficSnapshot(snapshot) {
    const wasRunning=simulationRunning;simulationRunning=snapshot?.state==='running';
    if(wasRunning && snapshot?.state==='stopped'){
      for(const motion of motions.values())motion.resolve();
      motions.clear();syncSlots(slots,{animate:false});
    }
    const keep=new Set();const counts=new Map();let rampCount=0,cityCount=0;
    cityDistrict?.setSignals(snapshot?.traffic_lights || {});
    activeRampIds=new Set();
    for(const v of snapshot?.vehicles || []) {
      if(![v.x,v.y,v.elevation ?? 0,v.angle].every(Number.isFinite))continue;
      const id=String(v.id);keep.add(id);if(v.in_city)cityCount++;else counts.set(v.floor,(counts.get(v.floor)||0)+1);if(v.on_ramp){rampCount++;activeRampIds.add(v.road_id);}
      let state=trafficCars.get(id);
      if(!state){shadowDirty=true;const model=createVehicle(hashModelId(id.toLowerCase()),{batchedDistant:true});traffic.add(model);state={model,target:new THREE.Vector3(),vehicle:v,yaw:0,pitch:0,brakeUntil:0};trafficCars.set(id,state);updateVehicleTarget(state);model.position.copy(state.target);}
      const previous=state.vehicle,travel=Math.hypot(v.x-previous.x,v.y-previous.y);
      if(previous.speed_mps-v.speed_mps>.35)state.brakeUntil=performance.now()+1100;
      state.pitch=travel>.1?Math.atan2((v.elevation||0)-(previous.elevation||0),travel):state.pitch;
      state.vehicle=v;state.yaw=Math.atan2(Math.sin(v.angle*Math.PI/180),-Math.cos(v.angle*Math.PI/180));updateVehicleTarget(state);
    }
    for(const [id,state] of trafficCars)if(!keep.has(id)){shadowDirty=true;traffic.remove(state.model);disposeVehicle(state.model);trafficCars.delete(id);}
    if(followId && !trafficCars.has(followId)){followId=null;if(trafficCars.size)inspectVehicle();else resetView();}
    const inspectButton=document.querySelector('#inspect-vehicle');if(inspectButton)inspectButton.disabled=trafficCars.size===0;
    if(followId){const state=trafficCars.get(followId);const detail=document.querySelector('#vehicle-inspection-text');if(detail)detail.textContent=`${state.model.userData.vehicle.type} · ${followId} · ${(state.vehicle.speed_mps*3.6).toFixed(1)} km/h · ${state.vehicle.in_city?'city streets':state.vehicle.on_ramp?'on ramp':floorName(state.vehicle.floor)}`;}
    const summary=document.querySelector('#floor-traffic-summary');if(summary)summary.textContent=`${cityCount} city · ${(snapshot?.vehicle_count || 0)-cityCount} garage · ${rampCount} on ramps`;
    document.querySelectorAll('[data-floor-count]').forEach(el=>{el.textContent=counts.get(Number(el.dataset.floorCount)) || 0;});
  }
  function setGate(operation,opened){shadowDirty=true;const gate=gateArms.get(operation);if(gate)gate.hardware=opened;}
  function tick(now) {
    requestAnimationFrame(tick);
    if(suspendRendering){lastFrame=now;return;}
    const workStarted=performance.now();
    const frameDuration=now-lastFrame;frameTime=THREE.MathUtils.lerp(frameTime,frameDuration,.06);const dt=clamp((now-lastFrame)/1000,.001,.25);lastFrame=now;
    if(cameraTween){const t=clamp((now-cameraTween.start)/650,0,1),s=t*t*(3-2*t),a=cameraTween.from,b=cameraTween.to;target.copy(a.target).lerp(b.target,s);radius=THREE.MathUtils.lerp(a.radius,b.radius,s);tilt=THREE.MathUtils.lerp(a.tilt,b.tilt,s);orbit=THREE.MathUtils.lerp(a.orbit,b.orbit,s);if(t===1)cameraTween=null;}
    cameraPosition();
    for(const state of trafficCars.values()){
      const before=frameBefore.copy(state.model.position),oldYaw=state.model.rotation.y;
      state.model.position.lerp(state.target,1-Math.exp(-11*dt));const delta=THREE.MathUtils.euclideanModulo(state.yaw-oldYaw+Math.PI,2*Math.PI)-Math.PI;state.model.rotation.order='YXZ';state.model.rotation.y+=delta*(1-Math.exp(-10*dt));
      const pitch=Math.atan(Math.tan(state.pitch)*displaySpacing()/floorHeight());state.model.rotation.x=THREE.MathUtils.lerp(state.model.rotation.x,-pitch,1-Math.exp(-8*dt));
      const distance=state.model.position.distanceTo(before),turn=state.model.rotation.y-oldYaw,steering=Math.atan2(turn*2.6,Math.max(distance,.06));
      animateVehicle(state.model,{distance,speed:state.vehicle.speed_mps,steering,braking:now<state.brakeUntil || state.vehicle.speed_mps<.15,time:now,dt,decorative:mechanicalAnimations,updateJoints:state.model.position.distanceToSquared(camera.position)<2500 || state.model.name===followId});
    }
    for(const [id,motion] of motions){

      const sample=sampleParkingManeuver(motion.maneuver,now-motion.start);motion.model.position.copy(sample.position);motion.model.rotation.order='YXZ';motion.model.rotation.y=sample.heading;motion.model.rotation.x=-(sample.pitch || 0);
      const distance=motion.model.position.distanceTo(motion.previous),steering=Math.atan2(wrapAngle(sample.heading-motion.lastYaw)*2.6,Math.max(distance,.05))*(sample.reversing?-1:1);motion.speed=distance/dt;
      animateVehicle(motion.model,{distance:sample.reversing?-distance:distance,speed:motion.speed,steering,braking:sample.braking,reversing:sample.reversing,time:now,dt,decorative:mechanicalAnimations});motion.previous.copy(motion.model.position);motion.lastYaw=sample.heading;
      if(sample.done){shadowDirty=true;if(motion.operation==='exit'){motion.model.parent?.remove(motion.model);disposeVehicle(motion.model);liveCars.delete(id);}else {deckGroups.get(trackedBays.get(id)?.floor || 5)?.add(motion.model);motion.model.userData.arrivalAt=now;}motions.delete(id);syncSlots(slots,{animate:false});motion.resolve();}
    }
    for(const [id,model] of liveCars)if(!motions.has(id)){const age=model.userData.arrivalAt?(now-model.userData.arrivalAt)/1000:99,door=age>.4&&age<3.2?smoothStep((age-.4)/.6)*(1-smoothStep((age-2.3)/.7))*.85:0;animateVehicle(model,{door,time:now,dt,decorative:mechanicalAnimations});}
    for(const [op,arm] of gateArms){const motionNear=[...motions.values()].some(m=>m.operation===op && vehicleNearBarrier(m.model.position,arm.crossing,m.speed)),trafficNear=[...trafficCars.values()].some(s=>s.vehicle.floor===5 && vehicleNearBarrier(s.model.position,arm.crossing,s.vehicle.speed_mps));const open=arm.hardware ?? (motionNear || trafficNear);animateBarrier(arm,open,dt);}
    for(const [arm,z] of [[entranceBarrier,20],[exitBarrier,28]])if(arm)animateBarrier(arm,(simulationRunning && [...trafficCars.values()].some(s=>Math.abs(s.vehicle.elevation || 0)<.5 && Math.abs(s.vehicle.x+123)<12 && Math.abs(s.vehicle.y+z)<2)) || [...motions.values()].some(m=>m.maneuver.worldSpace && Math.abs(m.model.position.y)<.8 && Math.abs(m.model.position.x+123)<12 && Math.abs(m.model.position.z-z)<2),dt);
    mechanisms.forEach(state=>animateArchitecture(state,now,mechanicalAnimations,dt));
    if(mechanicalAnimations)rampMechanisms.forEach(state=>animateRamp(state,now,activeRampIds.has(state.id)));
    if(followId && trafficCars.has(followId)){
      const state=trafficCars.get(followId),level=state.vehicle.in_city?null:state.vehicle.floor;if(selectedLevel!==level){selectedLevel=level;applyView();}
      if(!cameraTween){target.lerp(frameFocus.copy(state.model.position).addScaledVector(THREE.Object3D.DEFAULT_UP,.85),1-Math.exp(-8*dt));const turn=THREE.MathUtils.euclideanModulo(state.yaw+.7-orbit+Math.PI,Math.PI*2)-Math.PI;orbit+=turn*(1-Math.exp(-2*dt));}
    }
    cityDistrict?.animate(now,mechanicalAnimations);
    const marker=document.querySelector('#city-garage-marker');if(marker){marker.hidden=!cityScope;const point=markerPoint.set(0,25,0).project(camera);marker.style.left=`${(point.x*.5+.5)*100}%`;marker.style.top=`${(-point.y*.5+.5)*100}%`;}
    updateParkingNavigation(now);
    cameraPosition();if(!renderVisible || document.hidden)return;
    for(const {level,root} of parkedBatches)if(root.parent.visible){const next=deckGroups.get(level+1);root.userData.updateVisibility(camera.position,next?.visible?next.position.y-.675:null);}
    updateLightingCoverage(now);naturalEnvironment?.update(now,camera,mechanicalAnimations);distantTraffic.update(trafficCars.values(),camera);const renderingStarted=performance.now();updateTime=renderingStarted-workStarted;renderer.render(scene,camera);renderedFrames++;renderTime=performance.now()-renderingStarted;
    if(qualityMode==='auto' && !cameraTween && !drag){const ratio=renderBudget.sample(now,frameDuration);if(ratio!==null){renderer.setPixelRatio(ratio);const r=container.getBoundingClientRect();renderer.setSize(r.width,r.height,false);}}

  }
  let drag=null;
  renderer.domElement.addEventListener('pointerdown',event=>{drag={x:event.clientX,y:event.clientY,orbit,tilt,target:target.clone(),pan:event.button===2||event.shiftKey,moved:false};renderer.domElement.setPointerCapture(event.pointerId);});
  renderer.domElement.addEventListener('pointermove',event=>{if(!drag)return;const dx=event.clientX-drag.x,dy=event.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>5)drag.moved=true;if(drag.moved){cameraTween=null;if(drag.pan){const scale=radius*.0015;target.copy(drag.target).add(new THREE.Vector3(-Math.cos(orbit)*dx-Math.sin(orbit)*dy,0,Math.sin(orbit)*dx-Math.cos(orbit)*dy).multiplyScalar(scale));}else{orbit=drag.orbit-dx*.005;tilt=clamp(drag.tilt+dy*.004,.12,1.35);}}});
  renderer.domElement.addEventListener('pointerup',event=>{if(drag && !drag.moved && deckGroups.get(5)?.visible){const rect=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);const hits=raycaster.intersectObjects([...pads.values()]);if(hits.length)onSelect(hits[0].object.userData.slotId);}drag=null;});
  renderer.domElement.addEventListener('contextmenu',event=>event.preventDefault());
  renderer.domElement.addEventListener('pointercancel',()=>{drag=null;});
  renderer.domElement.addEventListener('wheel',event=>{event.preventDefault();cameraTween=null;radius=clamp(radius*Math.exp(event.deltaY*.001),12,5000);},{passive:false});
  const resize=new ResizeObserver(()=>{const rect=container.getBoundingClientRect();if(!rect.width||!rect.height)return;camera.aspect=rect.width/rect.height;camera.updateProjectionMatrix();renderer.setSize(rect.width,rect.height,false);if(data&&selectedLevel===null){if(cityScope)cityView();else resetView();}});resize.observe(container);
  document.querySelectorAll('[data-floor]').forEach(button=>button.addEventListener('click',()=>selectFloor(button.dataset.floor==='all'?null:Number(button.dataset.floor))));
  document.querySelector('#garage-view-mode')?.addEventListener('change',event=>{viewMode=event.target.value;selectedLevel=null;resetView();});
  document.querySelector('#parking-camera-toggle')?.addEventListener('click',()=>{
    driverView=!driverView;const model=liveCars.get(drivenSlotId);if(model)model.visible=!driverView;
    if(!driverView){const b=trackedBays.get(drivenSlotId);target.set(b.x,elevationY(floorElevation(b.floor)), -b.y);radius=42;tilt=1.35;orbit=0;cameraTween=null;}
    document.querySelector('#parking-camera-toggle').textContent=driverView?'Overhead view':'Driver view';document.querySelector('#parking-camera-toggle').setAttribute('aria-pressed',String(driverView));
  });
  document.querySelector('#parking-navigation-close')?.addEventListener('click',()=>{clearNavigation();resetView();});
  document.querySelector('#city-view')?.addEventListener('click',cityView);
  document.querySelector('#access-view')?.addEventListener('click',()=>{followId=null;cityScope=false;selectedLevel=null;viewMode='assembled';applyView();moveCamera(new THREE.Vector3(-125,1.8,24),43,.6,-1.1);});
  document.querySelector('#city-garage-marker')?.addEventListener('click',resetView);
  document.querySelector('#city-scenery')?.addEventListener('change',event=>{cityEnabled=event.target.checked;if(!cityEnabled)cityScope=false;applyView();if(!cityEnabled)resetView();});
  document.querySelector('#inspect-vehicle')?.addEventListener('click',inspectVehicle);
  document.querySelector('#underground-cutaway')?.addEventListener('change',event=>{undergroundCutaway=event.target.checked;applyView();});
  document.querySelector('#scene-lighting')?.addEventListener('change',event=>setLighting(event.target.value));
  document.querySelector('#soft-shadows')?.addEventListener('change',event=>{renderer.shadowMap.enabled=event.target.checked;sunlight.castShadow=event.target.checked;shadowDirty=true;});
  document.querySelector('#scene-quality')?.addEventListener('change',event=>{qualityMode=event.target.value;const shadowSize=Math.min(qualityMode==='high'?4096:2048,renderer.capabilities.maxTextureSize);if(sunlight.shadow.mapSize.x!==shadowSize){sunlight.shadow.map?.dispose();sunlight.shadow.map=null;sunlight.shadow.mapSize.set(shadowSize,shadowSize);shadowDirty=true;}renderer.setPixelRatio(qualityMode==='high'?Math.min(Math.max(devicePixelRatio || 1,1.5),2):qualityMode==='auto'?Math.max(.75,Math.min(devicePixelRatio || 1,1.25)):Math.min(devicePixelRatio || 1,1.25));renderBudget.reset(performance.now(),renderer.getPixelRatio());const r=container.getBoundingClientRect();renderer.setSize(r.width,r.height,false);});
  const mechanicalControl=document.querySelector('#mechanical-animations');if(mechanicalControl){mechanicalControl.checked=mechanicalAnimations;mechanicalControl.addEventListener('change',event=>{mechanicalAnimations=event.target.checked;});}
  container.__garageDiagnostics=(options={})=>{if(typeof options.suspendRendering==='boolean')suspendRendering=options.suspendRendering;return {drawCalls:renderer.info.render.calls,triangles:renderer.info.render.triangles,fps:Math.round(1000/frameTime),renderMs:Math.round(renderTime),updateMs:Math.round(updateTime),trafficModels:trafficCars.size,nearVehicles:[...trafficCars.values()].filter(s=>s.model.userData.vehicle.lod.getCurrentLevel()===0).length,mechanicalAssemblies:mechanisms.length,drivenSlotId,driverView,navigationRoute:Boolean(navigationRoute),navigationMarkers:navigation.children.length,journeyFromEntrance:motions.get(drivenSlotId)?.maneuver.fromEntrance || false,drivenPosition:liveCars.get(drivenSlotId)?.position.toArray(),followId,cameraRadius:Math.round(radius),selectedLevel,cityScope,city:cityDistrict?.diagnostics(),environment:naturalEnvironment?.diagnostics(),retainedTraffic:distantTraffic.diagnostics(),shadowsEnabled:renderer.shadowMap.enabled,shadowMapReady:Boolean(sunlight.shadow.map),shadowUpdates,cameraNear:camera.near,depthMode:'adaptive-near',sunPosition:sunlight.position.toArray(),sunTarget:sunlight.target.position.toArray(),sunIntensity:sunlight.intensity,shadowSpan:sunlight.shadow.camera.right,shadowMapSize:sunlight.shadow.mapSize.x,pixelRatio:renderer.getPixelRatio(),qualityMode,renderedFrames,parkedVisibility:parkedBatches.map(b=>({floor:b.level,shown:b.root.parent.visible,total:b.root.userData.models,visible:b.root.userData.visibleModels})),renderVisible:renderVisible&&!document.hidden,occludedParkedCars:parkedBatches.filter(b=>b.root.parent.visible).reduce((n,b)=>n+b.root.userData.models-b.root.userData.visibleModels,0),lightingMode,streetLights:streetLights.filter(l=>l.visible).length,undergroundCutaway,earthVisible:earth.visible,viewMode,floorElevations:data?.floors.map(f=>({name:f.name,elevation:f.elevation,visible:deckGroups.get(f.number)?.visible}))};};
  const initialRect=container.getBoundingClientRect();camera.aspect=initialRect.width/Math.max(1,initialRect.height);camera.updateProjectionMatrix();renderer.setSize(initialRect.width,initialRect.height,false);
  cameraPosition();requestAnimationFrame(tick);
  return {followParking,syncSlots,selectSlot,focusSlot,focusLiveBays,resetView,setMapData,setTrafficSnapshot,setGate,selectFloor,inspectVehicle,cityView,animateEvent:startMotion};
}

function smoothStep(t){t=clamp(t,0,1);return t*t*(3-2*t);}
