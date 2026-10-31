import * as THREE from '/static/three.module.js';

const clamp=THREE.MathUtils.clamp;
const ease=t=>{t=clamp(t,0,1);return t*t*(3-2*t);};
export const wrapAngle=angle=>THREE.MathUtils.euclideanModulo(angle+Math.PI,Math.PI*2)-Math.PI;

export function buildParkingManeuver(operation,bay,configured,start=null){
  if(!configured && bay.floor){
    const maneuver=buildParkingManeuver(operation,{x:0,y:26.5},null);
    const yaw=bay.heading || 0, matrix=new THREE.Matrix4().makeRotationY(yaw);
    matrix.setPosition(bay.x,0,-bay.y);
    for(const curve of [maneuver.forward,maneuver.reverse].filter(Boolean)){
      if(curve.points)for(const point of curve.points)point.z+=26.5,point.applyMatrix4(matrix);
      else for(const key of ['v0','v1','v2','v3'])curve[key].z+=26.5,curve[key].applyMatrix4(matrix);
      curve.updateArcLengths();
    }
    return maneuver;
  }
  const fallback=operation==='entry'?[{x:bay.x+18,z:-20},{x:bay.x,z:-bay.y}]:[{x:bay.x,z:-bay.y},{x:bay.x,z:-20},{x:bay.x+18,z:-20}];
  let points=(configured || fallback).map(p=>({...p}));
  const lane=-20+(operation==='entry'?-1.6:1.6);
  points=points.map(p=>({...p,z:Math.abs(p.z+20)<.25?lane:p.z}));
  if(operation==='entry'){
    const approach=points.filter(p=>Math.abs(p.z-lane)<.25);
    if(approach.length<2)approach.unshift({x:bay.x+18,z:lane});
    const direction=approach.length>1?Math.sign(approach[approach.length-1].x-approach[0].x)||-1:-1;
    const overshoot=new THREE.Vector3(bay.x+direction*3.4,.12,lane);
    if(approach.length)approach[approach.length-1]={x:overshoot.x,z:overshoot.z};
    else approach.push({x:bay.x+18,z:lane},{x:overshoot.x,z:overshoot.z});
    const forward=new THREE.CatmullRomCurve3(approach.map(p=>new THREE.Vector3(p.x,.12,p.z)),false,'catmullrom',.2);
    const reverse=new THREE.CubicBezierCurve3(overshoot,new THREE.Vector3(bay.x+direction*.7,.12,lane),new THREE.Vector3(bay.x,.12,-bay.y+2.8),new THREE.Vector3(bay.x,.12,-bay.y));
    const approachDuration=clamp(forward.getLength()/6.5*1000,2200,15000),reverseDuration=clamp(reverse.getLength()/1.6*1000,3200,6500);
    return {operation,forward,reverse,approachDuration,shiftDuration:450,reverseDuration,duration:approachDuration+450+reverseDuration};
  }
  if(start)points[0]={x:start.x,z:start.z};
  const forward=new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(p.x,.12,p.z)),false,'catmullrom',.2);
  return {operation,forward,duration:clamp(forward.getLength()/6.5*1000,3000,16000)};
}

export function sampleParkingManeuver(maneuver,elapsed){
  let curve=maneuver.forward,progress=clamp(elapsed/(maneuver.approachDuration || maneuver.duration),0,1),reversing=false,stopped=elapsed<0;
  if(maneuver.operation==='entry' && elapsed>=maneuver.approachDuration){
    const reverseTime=elapsed-maneuver.approachDuration-maneuver.shiftDuration;
    if(reverseTime<0){progress=1;stopped=true;}
    else{curve=maneuver.reverse;progress=clamp(reverseTime/maneuver.reverseDuration,0,1);reversing=true;}
  }
  const t=maneuver.worldSpace && curve===maneuver.forward?progress:ease(progress),position=curve.getPointAt(t),direction=curve.getTangentAt(t);
  if(reversing)direction.negate();
  return {position,heading:Math.atan2(direction.x,direction.z),pitch:Math.atan2(direction.y,Math.hypot(direction.x,direction.z)),reversing,braking:stopped || progress>.88,done:elapsed>=maneuver.duration,progress:clamp(elapsed/maneuver.duration,0,1)};
}

export function vehicleNearBarrier(position,crossing,speed=0){
  return Math.abs(position.z-crossing.z)<1.4 && Math.abs(position.x-crossing.x)<clamp(Math.abs(speed)*1.4,7,16);
}

// Join the entrance, native garage aisles and ramps, then reverse into the bay.
export function buildEntryJourney(layout,bay){
  const elevation=layout.floors.find(f=>f.number===bay.floor).elevation;
  const z=-bay.y,ew=bay.orientation==='east-west';
  const aisleX=[-83,-68,-53,-38,-23,-8,48,63,78].reduce((a,b)=>Math.abs(a-bay.x)<Math.abs(b-bay.x)?a:b);
  const laneZ=z<0?-20:20;
  const start=ew?new THREE.Vector3(aisleX,elevation+.12,z<0?-20:20):new THREE.Vector3(bay.x>0?78:-83,elevation+.12,laneZ);
  const overshoot=ew?new THREE.Vector3(aisleX,elevation+.12,clamp(z+(z<0?3.4:-3.4),-18,18)):new THREE.Vector3(bay.x+(start.x<bay.x?3.4:-3.4),elevation+.12,laneZ);
  const goal=new THREE.Vector3(bay.x,elevation+.12,z);
  const approachNodes=layout.network.nodes.filter(n=>n.id.startsWith(`L${bay.floor}_`) && /_[abcdef]$/.test(n.id));
  const endpoint=approachNodes.reduce((a,b)=>Math.hypot(a.x-start.x,-a.y-start.z)<Math.hypot(b.x-start.x,-b.y-start.z)?a:b);
  const adjacency=new Map();for(const edge of layout.network.edges){if(edge.kind==='city')continue;if(!adjacency.has(edge.from))adjacency.set(edge.from,[]);adjacency.get(edge.from).push(edge);}
  const queue=[['street_entry',[]]],seen=new Set(['street_entry']);let edges=[];
  while(queue.length){const [id,path]=queue.shift();if(id===endpoint.id){edges=path;break;}for(const edge of adjacency.get(id)||[])if(!seen.has(edge.to)){seen.add(edge.to);queue.push([edge.to,[...path,edge]]);}}
  if(!edges.length)throw new Error(`No entrance route to floor ${bay.floor}`);
  const points=[new THREE.Vector3(-140,.12,20)];
  for(const edge of edges)for(const [x,y,h] of edge.shape){const point=new THREE.Vector3(x,h+.12,-y);if(point.distanceTo(points.at(-1))>.01)points.push(point);}
  for(const point of [start,overshoot])if(point.distanceTo(points.at(-1))>.01)points.push(point);
  const forward=new THREE.CurvePath();let previous=points[0];
  for(let i=1;i<points.length-1;i++){
    const p=points[i],before=points[i-1],after=points[i+1],r=Math.min(1.8,p.distanceTo(before)*.2,p.distanceTo(after)*.2);
    const a=p.clone().addScaledVector(before.clone().sub(p).normalize(),r),b=p.clone().addScaledVector(after.clone().sub(p).normalize(),r);
    forward.add(new THREE.LineCurve3(previous,a));forward.add(new THREE.QuadraticBezierCurve3(a,p,b));previous=b;
  }
  forward.add(new THREE.LineCurve3(previous,overshoot));
  const control=ew?new THREE.Vector3(aisleX,elevation+.12,z):new THREE.Vector3(bay.x,elevation+.12,laneZ);
  const toward=goal.clone().lerp(control,.6);
  const reverse=new THREE.CubicBezierCurve3(overshoot,control,toward,goal);
  const approachDuration=forward.getLength()/5.5*1000,reverseDuration=Math.max(4000,reverse.getLength()/1.3*1000);
  return {operation:'entry',forward,reverse,approachDuration,reverseDuration,shiftDuration:650,duration:approachDuration+650+reverseDuration,worldSpace:true,fromEntrance:true};
}
