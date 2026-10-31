// Run with playwright-cli run-code --filename=scripts/verify_garage_models.js.
(async (page) => {
  return await page.evaluate(async () => {
    const THREE = await import('/static/three.module.js');
    const models = await import('/static/garage-models.js?v=9');
    const motion = await import('/static/garage-motion.js?v=2');
    const checks = [];
    function check(condition, name) { if (!condition) throw new Error(name); checks.push(name); }
    const cars = [0, 1, 2].map(seed => models.createVehicle(seed));
    check(new Set(cars.map(car => car.userData.vehicle.type)).size === 3, 'Three distinct vehicle body types');
    check(new Set(cars.map(car => car.userData.vehicle.color)).size === 3, 'Distinct paint colors');
    check(cars.every(car => car.userData.vehicle.partCount >= 100), 'Detailed component templates');
    check(cars.every(car => car.userData.vehicle.lod.levels.length === 3), 'Three geometry detail levels');
    const car = cars[0], rig = car.userData.vehicle;
    check(rig.wheels.length === 4 && rig.doors.length === 2, 'Four wheel assemblies and two articulated doors');
    models.animateVehicle(car, { distance: .35, speed: 3, steering: .25, braking: true, reversing: true, door: .8, time: 0, dt: 1 });
    check(rig.wheels.every(w => Math.abs(w.spin.rotation.x - 1) < .001), 'Wheel spin matches distance and tire radius');
    check(rig.wheels.filter(w => w.front).every(w => w.steer.rotation.y > .24) && rig.wheels.filter(w => !w.front).every(w => w.steer.rotation.y === 0), 'Front axle steers independently');
    check(rig.doors[0].rotation.y > .79 && rig.doors[1].rotation.y < -.79, 'Opposed door hinge directions');
    check(rig.stopMaterial.emissiveIntensity > 3 && rig.reverseMaterial.emissiveIntensity > 2, 'Brake and reversing lamps respond');
    check(rig.indicatorMaterials[1].emissiveIntensity > 2 && rig.indicatorMaterials[0].emissiveIntensity < .1, 'Right indicator follows positive steering');
    const roll = rig.roll;
    models.animateVehicle(car, { distance: 0, speed: 0, steering: 0, door: 0, dt: 1, time: 500 });
    check(rig.roll === roll, 'Stopped cars do not spin wheels');
    check(rig.stopMaterial.emissiveIntensity < 1 && rig.reverseMaterial.emissiveIntensity < .1, 'Lamps clear when control state clears');
    check(Math.abs(rig.doors[0].rotation.y) < .001, 'Door closes after parking phase');
    const root = new THREE.Group(), gate = models.createBarrier(root, 0, 0);
    models.animateBarrier(gate, true, 1);
    check(gate.pivot.rotation.x < -1.4, 'Gate boom opens at motor pivot');
    models.animateBarrier(gate, false, 1);
    check(Math.abs(gate.pivot.rotation.x) < .03, 'Gate boom closes');
    const deck = models.addDeckDetails(new THREE.Group(), { number: 1, color: '#48b9d2', bays: [] }, () => {});
    models.animateArchitecture(deck, 1000, true, .1);
    check(deck.fans.every(fan => fan.rotation.z > 0), 'Ventilation rotors animate');
    check(deck.lifts.every(lift => lift.left.position.x < lift.x - 1 && lift.right.position.x > lift.x + 1), 'Lift doors slide away from the opening');
    const angle = deck.fans[0].rotation.z;
    models.animateArchitecture(deck, 2000, false, .1);
    check(deck.fans[0].rotation.z === angle, 'Mechanical animation switch pauses rotors');
    const ramp = models.addRampDetails(new THREE.Group(), { id: 'up_1_2', width: 3.8 }, [new THREE.Vector3(0,0,0), new THREE.Vector3(70,4.2,0)]);
    models.animateRamp(ramp, 0, false);
    check(ramp.leds.every(lamp => lamp.material.emissiveIntensity === .18), 'Inactive ramps retain steady marker lamps');
    models.animateRamp(ramp, 0, true);
    check(ramp.leds.filter(lamp => lamp.material.emissiveIntensity > 3).length === 1, 'Occupied ramp beacon sequence follows traffic state');
    const farRoot=new THREE.Group(),distant=models.createDistantTraffic(farRoot,10),camera=new THREE.PerspectiveCamera();
    car.position.set(300,0,0);distant.update([{model:car}],camera);
    check(distant.diagnostics().cars===1,'Distant traffic is batched');
    check(distant.diagnostics().retainedComponents.every(count=>count>=200),'Distant batches retain full multi-part vehicle geometry');
    car.visible=false;distant.update([{model:car}],camera);
    check(distant.diagnostics().cars===0,'Hidden floors are excluded from distant traffic');
    car.visible=true;car.position.set(5,0,0);distant.update([{model:car}],camera);
    check(distant.diagnostics().cars===0,'Nearby cars retain their articulated geometry');
    const context=new THREE.Group();models.addParkedVehicles(context,Array.from({length:20},(_,i)=>({x:-80+i*5,y:6,live_slot_id:null,orientation:'north-south'})),1);const parked=context.children.find(c=>c.name==='parked-vehicle-batches');
    check(parked && parked.children.length<=10 && parked.userData.retainedComponents.every(n=>n>=200),'Parked cars use consolidated full-geometry batches');
    check(cars.every(c=>c.userData.vehicle.batchMetrics.sourceTriangles===c.userData.vehicle.batchMetrics.triangles && c.userData.vehicle.batchMetrics.materialBatches<=3),'Material batching preserves every static vehicle triangle');
    check(cars.every(c=>c.userData.vehicle.batchMetrics.vertices<c.userData.vehicle.batchMetrics.triangles*3),'Indexed geometry eliminates duplicate vertex processing');
    const accessories=car.userData.vehicle.lod.levels[1].object.children.find(m=>m.geometry.attributes.staticEmission);
    check(accessories.geometry.attributes.color.count===accessories.geometry.attributes.position.count && accessories.geometry.attributes.staticEmission.array.some(n=>n>0),'Batched accessories retain per-vertex color and lamp emission');
    parked.userData.updateVisibility(new THREE.Vector3(0,1000,500),3.525);check(parked.userData.visibleModels===0,'Cars fully blocked by a concrete slab are culled');
    parked.userData.updateVisibility(new THREE.Vector3(0,1000,500),null);check(parked.userData.visibleModels===parked.userData.models,'Floor inspection restores all parked cars');
    parked.userData.updateVisibility(new THREE.Vector3(-150,2,80),3.525);check(parked.userData.visibleModels===parked.userData.models,'Open-side views conservatively retain parked cars');
    const lazy=models.createVehicle(1,{batchedDistant:true});models.animateVehicle(lazy,{distance:.35,updateJoints:false});check(lazy.userData.vehicle.wheels.length===0,'Distant traffic defers invisible articulated rigs');
    models.animateVehicle(lazy,{distance:0});check(lazy.userData.vehicle.wheels.length===4 && lazy.userData.vehicle.wheels.every(w=>Math.abs(w.spin.rotation.x-1)<.001),'Close-up inspection creates wheels with continuous rotation');models.disposeVehicle(lazy);
    const bootstrap=JSON.parse(document.querySelector('#dashboard-bootstrap').textContent),cfg=bootstrap.scene.slots['1'],bay={x:cfg.position.x,y:-cfg.position.z};
    const entry=motion.buildParkingManeuver('entry',bay,cfg.entry_route),exit=motion.buildParkingManeuver('exit',bay,cfg.exit_route);
    let aligned=true,reverseObserved=false;
    for(let t=0;t<entry.duration-5;t+=40){
      const a=motion.sampleParkingManeuver(entry,t),b=motion.sampleParkingManeuver(entry,t+1),d=b.position.clone().sub(a.position);if(d.length()<.000001)continue;
      const dot=d.normalize().dot(new THREE.Vector3(Math.sin(a.heading),0,Math.cos(a.heading)));aligned&&=a.reversing?dot<-.99:dot>.99;reverseObserved ||= a.reversing;
    }
    check(aligned && reverseObserved,'Reverse parking displacement agrees with vehicle facing throughout the maneuver');
    const beforeShift=motion.sampleParkingManeuver(entry,entry.approachDuration+100),afterShift=motion.sampleParkingManeuver(entry,entry.approachDuration+200);
    check(beforeShift.position.distanceTo(afterShift.position)<.0001,'Vehicle stops before selecting reverse gear');
    const final=motion.sampleParkingManeuver(entry,entry.duration);
    check(final.position.distanceTo(new THREE.Vector3(bay.x,.12,-bay.y))<.001 && Math.abs(final.heading)<.001,'Reverse maneuver finishes in the bay facing the aisle');
    for(const [operation,maneuver,z,length] of [['entry',entry,-23.5,3.8],['exit',exit,-20,3.2]]){
      const gate=models.createBarrier(new THREE.Group(),-70,z,'z',length);let previous=motion.sampleParkingManeuver(maneuver,0).position,crossed=false,clear=true;
      for(let t=10;t<maneuver.duration;t+=10){const position=motion.sampleParkingManeuver(maneuver,t).position,speed=position.distanceTo(previous)/.01;models.animateBarrier(gate,motion.vehicleNearBarrier(position,gate.crossing,speed),.01);if((previous.x+70)*(position.x+70)<=0 && Math.abs(position.z-gate.crossing.z)<1.4){crossed=true;clear&&=gate.open>.9;}previous=position;}
      check(crossed && clear,`${operation} boom opens before the car crosses its lane`);
    }
    const optionalExit=motion.buildParkingManeuver('exit',bay,null);
    check(motion.sampleParkingManeuver(optionalExit,0).position.distanceTo(new THREE.Vector3(bay.x,.12,-bay.y))<.001,'Optional exit route starts at the occupied bay');
    const widest=Math.max(...cars.map(c=>new THREE.Box3().setFromObject(c.userData.vehicle.lod.levels[0].object).getSize(new THREE.Vector3()).x));
    check(-21.6+widest/2 < -20-.29 && -21.6-widest/2 > -23.5+.29,'Entry cars including mirrors clear both barrier cabinets');
    check(-18.4-widest/2 > -20+.29,'Exit cars including mirrors clear the center cabinet');
    const result = { passed: checks.length, checks, vehicle_parts: cars.map(c => ({ type: c.userData.vehicle.type, components: c.userData.vehicle.partCount })) };
    cars.forEach(models.disposeVehicle);
    return result;
  });
})
