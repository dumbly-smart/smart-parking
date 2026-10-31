import * as THREE from '/static/three.module.js';
import { mergeGeometries, mergeVertices } from '/static/vendor/utils/BufferGeometryUtils.js';

export const VEHICLE_COLORS = [0xe5484d,0x3387ed,0xf4b740,0x20b6a3,0x8e67d6,0xf3f0e8,0xe27635,0x2e414f,0xd8649a,0x8ac45c,0x39bbd6,0xb5bdc8];
export const VEHICLE_TYPES = ['Sedan', 'SUV', 'Hatchback'];
const geometries = {
  box: new THREE.BoxGeometry(1,1,1),
  cylinder: new THREE.CylinderGeometry(1,1,1,16),
  sphere: new THREE.SphereGeometry(1,12,8),
  torus: new THREE.TorusGeometry(1,.12,6,20),
  arch: new THREE.TorusGeometry(.39,.045,5,16,Math.PI),
  contact: new THREE.PlaneGeometry(1,1).rotateX(-Math.PI/2),
};
geometries.roundbox=new THREE.BoxGeometry(1,1,1,4,4,4);
for(let i=0;i<geometries.roundbox.attributes.position.count;i++){
  const p=new THREE.Vector3().fromBufferAttribute(geometries.roundbox.attributes.position,i),inner=p.clone().clampScalar(-.4,.4),normal=p.clone().sub(inner).normalize();p.copy(inner).addScaledVector(normal,.1);geometries.roundbox.attributes.position.setXYZ(i,p.x,p.y,p.z);
}geometries.roundbox.computeVertexNormals();
const materials = new Map(), templates = new Map();
const matrix = new THREE.Matrix4(), quaternion = new THREE.Quaternion(), axis = new THREE.Vector3(0,1,0);
export const hashModelId = id => [...String(id)].reduce((value,char)=>(value*31+char.charCodeAt(0))>>>0,7);
const smooth = t => {t=THREE.MathUtils.clamp(t,0,1);return t*t*(3-2*t);};

function mat(key, color, options={}) {
  if(!materials.has(key)){const {roughness,metalness,...surface}=options;const m=new THREE.MeshLambertMaterial({color,...surface});m.userData.shared=true;materials.set(key,m);}
  return materials.get(key);
}
const M = {
  paint: mat('parked-paint',0xffffff,{roughness:.27,metalness:.35}),
  glass: mat('glass',0x1d3549,{roughness:.16,metalness:.55,side:THREE.DoubleSide}),
  chrome: mat('chrome',0xc2d1d9,{metalness:.88,roughness:.22}),
  trim: mat('trim',0x18242c,{roughness:.62}),
  rubber: mat('rubber',0x14191e,{roughness:.95,metalness:0}),
  interior: mat('interior',0x755b49,{roughness:.92}),
  head: mat('head',0xe5f6ff,{emissive:0xb9e3ff,emissiveIntensity:.65}),
  tail: mat('tail',0xb92132,{emissive:0xa01525,emissiveIntensity:.5}),
  steel: mat('steel',0x91a6b4,{metalness:.65,roughness:.36}),
  concrete: mat('concrete',0x849899,{roughness:.96,metalness:0}),
  yellow: mat('yellow',0xf8c64f), white: mat('white',0xe8eee9), red: mat('red',0xdb4354),
  blue: mat('blue',0x338bc4), cyan: mat('cyan',0x32c2c5), dark: mat('dark',0x25333e),
  green: mat('green',0x47b785), amber: mat('amber',0xf5aa39,{emissive:0xe88913,emissiveIntensity:.3}),
};

class Parts {
  constructor(){this.parts=new Map();this.count=0;}
  add(kind,material,position,scale,rotation=[0,0,0]){
    const geometry=geometries[kind].clone().toNonIndexed();
    quaternion.setFromEuler(new THREE.Euler(...rotation));matrix.compose(new THREE.Vector3(...position),quaternion,new THREE.Vector3(...scale));geometry.applyMatrix4(matrix);
    if(!this.parts.has(material))this.parts.set(material,[]);this.parts.get(material).push(geometry);this.count++;return this;
  }
  box(m,x,y,z,w,h,d,rotation){return this.add('box',m,[x,y,z],[w,h,d],rotation);}
  cyl(m,x,y,z,r,h,rotation){return this.add('cylinder',m,[x,y,z],[r,h,r],rotation);}
  tube(m,points,r=.035){
    const curve=new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p)));
    const g=new THREE.TubeGeometry(curve,12,r,6,false).toNonIndexed();if(!this.parts.has(m))this.parts.set(m,[]);this.parts.get(m).push(g);this.count++;return this;
  }
  quad(m,a,b,c,d){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute([...a,...b,...c,...a,...c,...d],3));g.setAttribute('uv',new THREE.Float32BufferAttribute([0,0,1,0,1,1,0,0,1,1,0,1],2));g.computeVertexNormals();if(!this.parts.has(m))this.parts.set(m,[]);this.parts.get(m).push(g);this.count++;return this;}
  finish(){const result=[];for(const [material,pieces] of this.parts){const combined=mergeGeometries(pieces,false);pieces.forEach(p=>p.dispose());const geometry=mergeVertices(combined,1e-6);combined.dispose();geometry.computeBoundingSphere();result.push({geometry,material});}return result;}
  mount(parent){for(const {geometry,material} of this.finish()){const mesh=new THREE.Mesh(geometry,material);mesh.castShadow=true;mesh.receiveShadow=true;mesh.userData.staticArchitectural=true;parent.add(mesh);}return parent;}
}

function wheelTemplate(){
  if(templates.has('wheel'))return templates.get('wheel');
  const p=new Parts();
  p.cyl(M.rubber,0,0,0,.35,.25,[0,0,Math.PI/2]);
  for(const side of [-1,1]){
    p.cyl(M.chrome,side*.133,0,0,.245,.018,[0,0,Math.PI/2]);
    p.cyl(M.trim,side*.15,0,0,.192,.012,[0,0,Math.PI/2]);
    p.cyl(M.chrome,side*.16,0,0,.073,.024,[0,0,Math.PI/2]);
    for(let i=0;i<6;i++){
      const a=i*Math.PI/3;p.box(M.chrome,side*.17,Math.cos(a)*.13,Math.sin(a)*.13,.024,.19,.035,[a,0,0]);
      p.cyl(M.trim,side*.185,Math.cos(a)*.05,Math.sin(a)*.05,.012,.012,[0,0,Math.PI/2]);
    }
  }
  const t=p.finish();t.componentCount=p.count;templates.set('wheel',t);return t;
}

function batchStaticParts(parts){
  // Material consolidation keeps all triangles and their original colors/emission.
  const accessories=parts.filter(p=>p.material!==M.paint && p.material!==M.glass).map(part=>{
    const g=part.geometry.clone(),count=g.attributes.position.count,colors=new Float32Array(count*3),emission=new Float32Array(count*3),m=part.material,e=m.emissive.clone().multiplyScalar(m.emissiveIntensity);
    for(let i=0;i<count;i++){m.color.toArray(colors,i*3);e.toArray(emission,i*3);}g.setAttribute('color',new THREE.BufferAttribute(colors,3));g.setAttribute('staticEmission',new THREE.BufferAttribute(emission,3));return g;
  });
  const accessoryMaterial=mat('batched-accessories',0xffffff,{vertexColors:true});
  accessoryMaterial.onBeforeCompile=shader=>{shader.vertexShader='attribute vec3 staticEmission; varying vec3 vStaticEmission;\n'+shader.vertexShader;shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\nvStaticEmission=staticEmission;');shader.fragmentShader='varying vec3 vStaticEmission;\n'+shader.fragmentShader;shader.fragmentShader=shader.fragmentShader.replace('#include <emissivemap_fragment>','#include <emissivemap_fragment>\ntotalEmissiveRadiance+=vStaticEmission;');};
  accessoryMaterial.customProgramCacheKey=()=> 'static-color-emission-v1';
  const geometry=mergeGeometries(accessories,false);accessories.forEach(g=>g.dispose());geometry.computeBoundingSphere();
  return [...parts.filter(p=>p.material===M.paint || p.material===M.glass),{geometry,material:accessoryMaterial}];
}

function vehicleTemplate(type=0){
  if(templates.has(type))return templates.get(type);
  const suv=type===1,hatch=type===2,length=suv?4.65:hatch?3.85:4.35,width=suv?1.93:1.8,height=suv?1.72:1.46;
  const half=length/2,bodyY=suv?.77:.66,roofY=height-.08;
  const p=new Parts();
  p.box(M.trim,0,.37,0,width*.9,.18,length*.91);
  p.add('roundbox',M.paint,[0,bodyY,0],[width,.52,length*.92]);
  p.add('roundbox',M.paint,[0,bodyY+.25,half*.62],[width*.94,.16,length*.25],[.05,0,0]);
  p.add('roundbox',M.paint,[0,bodyY+.24,-half*.71],[width*.95,.16,length*(hatch?.14:.24)]);
  p.add('roundbox',M.paint,[0,roofY,-.18],[width*.76,.13,suv?2.5:hatch?1.75:2.0]);
  p.box(M.glass,0,(roofY+bodyY+.2)/2,.83,width*.77,height*.34,.055,[-.36,0,0]);
  p.box(M.glass,0,(roofY+bodyY+.2)/2,-1.08,width*.76,height*.29,.05,[.4,0,0]);
  p.box(M.chrome,0,bodyY-.05,half*.95,width*.66,.22,.06);
  for(let i=0;i<9;i++)p.box(M.trim,-.55+i*.137,bodyY-.05,half*.974,.035,.16,.02);
  p.box(M.chrome,0,bodyY-.05,half*.986,.15,.11,.025);
  for(const side of [-1,1]){
    p.box(M.trim,side*(width/2+.01),.4,0,.045,.13,length*.84);
    p.box(M.chrome,side*(width/2+.02),.77,0,.028,.028,length*.75);
    p.box(M.head,side*.66,bodyY+.13,half*.95,.45,.12,.055);
    p.box(M.tail,side*.67,bodyY+.1,-half*.96,.4,.13,.04);
    p.box(M.chrome,side*(width/2+.13),height*.68,.88,.23,.13,.23);
    p.box(M.glass,side*(width/2+.145),height*.68,.87,.014,.09,.17);
    // Rear side windows, quarter panels, shut lines and roof pillars.
    p.box(M.glass,side*(width/2-.08),height*.78,-.73,.028,height*.25,.65);
    for(const z of [-1.09,-.35,.83])p.box(M.paint,side*(width/2-.1),height*.77,z,.075,height*.38,.07,[z>.5?-.36:z<-.8?.4:0,0,side*.24]);
    p.box(M.trim,side*(width/2+.007),bodyY+.1,-.5,.02,.42,.015);
    for(const z of [-1.3,1.3])p.add('arch',M.trim,[side*(width/2+.015),.36,z],[1,1,1],[0,Math.PI/2,0]);
    p.box(M.chrome,side*.7,.31,-half*.9,.14,.07,.17);
  }
  p.box(M.white,0,.53,half*.981,.46,.12,.017);
  p.box(M.white,0,.56,-half*.982,.46,.12,.017);
  p.box(M.trim,0,.68,half*.997,.34,.016,.02);
  p.box(M.trim,0,.7,-half*.998,.3,.018,.02);
  // Seats, headrests, dashboard and console are separate interior parts.
  for(const x of [-.4,.4]){
    p.box(M.interior,x,.78,-.12,.52,.18,.65);p.box(M.interior,x,1.02,-.43,.52,.59,.15,[.1,0,0]);p.box(M.interior,x,1.32,-.45,.27,.18,.13);
  }
  p.box(M.interior,0,.85,-1.1,1.38,.2,.55);p.box(M.dark,0,.99,.68,1.52,.19,.33);p.box(M.steel,0,1.1,.63,.32,.18,.025);
  p.add('torus',M.trim,[-.43,1.12,.47],[.17,.17,.17],[-.4,0,0]);p.box(M.cyan,0,1.11,.64,.25,.12,.015);
  for(const x of [-.35,.35])p.box(M.trim,x,1.06,.88,.46,.017,.018,[0,0,x*.3]);
  if(suv){for(const x of [-.65,.65])p.box(M.trim,x,height+.08,-.2,.045,.06,2.8);p.box(M.steel,0,bodyY-.23,-half*.99,.9,.07,.08);}
  if(hatch)p.box(M.trim,0,height-.03,-1.26,1.55,.07,.19);
  const body=p.finish();
  const doorParts=[];
  for(const side of [-1,1]){
    const d=new Parts();d.box(M.paint,0,0,-.57,.055,.47,1.19);const top=roofY-(bodyY+.05)-.035;
    d.quad(M.glass,[-side*.025,.235,-.02],[-side*.025,.235,-1.1],[-side*.2,top,-.99],[-side*.2,top,-.18]);
    d.box(M.chrome,side*.033,.11,-.94,.025,.045,.18);d.box(M.trim,side*.027,-.19,-.57,.02,.045,1.17);const parts=d.finish();parts.componentCount=d.count;doorParts.push(parts);
  }
  const wheel=wheelTemplate(),parked=new Parts();
  // Closed doors and complete wheels are merged for the instanced parked cars.
  const parkedParts=[...body.map(p=>({...p}))];
  for(let i=0;i<2;i++)for(const part of doorParts[i]){
    const g=part.geometry.clone();g.translate((i===0?-1:1)*(width/2+.025),bodyY+.05,.64);parkedParts.push({geometry:g,material:part.material});
  }
  for(const side of [-1,1])for(const z of [-1.3,1.3])for(const part of wheel){const g=part.geometry.clone();g.translate(side*(width/2-.03),.36,z);parkedParts.push({geometry:g,material:part.material});}
  const byMaterial=new Map();for(const part of parkedParts){if(!byMaterial.has(part.material))byMaterial.set(part.material,[]);byMaterial.get(part.material).push(part.geometry);}
  const staticParts=[...byMaterial].map(([material,pieces])=>({material,geometry:mergeGeometries(pieces,false)}));
  const batchedParts=batchStaticParts(staticParts);
  const batchMetrics={sourceTriangles:staticParts.reduce((n,p)=>n+p.geometry.index.count/3,0),triangles:batchedParts.reduce((n,p)=>n+p.geometry.index.count/3,0),vertices:batchedParts.reduce((n,p)=>n+p.geometry.attributes.position.count,0),materialBatches:batchedParts.length};
  const result={body,doors:doorParts,wheel,staticParts,batchedParts,batchMetrics,width,length,height,bodyY,partCount:p.count+wheel.componentCount*4+doorParts.reduce((sum,parts)=>sum+parts.componentCount,0)+9};templates.set(type,result);return result;
}

function meshParts(parent,parts,paint){for(const part of parts){const mesh=new THREE.Mesh(part.geometry,part.material===M.paint?paint:part.material);mesh.castShadow=true;mesh.receiveShadow=true;parent.add(mesh);}}
function painted(color){const key=`vehicle-paint-${color}`;if(!materials.has(key)){const m=new THREE.MeshPhysicalMaterial({color,metalness:.38,roughness:.25,clearcoat:1,clearcoatRoughness:.15});m.userData.shared=true;materials.set(key,m);}return materials.get(key);}

export function createVehicle(seed=0,{batchedDistant=false,lazyDetailed=batchedDistant}={}){
  const index=typeof seed==='number'?seed:hashModelId(seed),type=index%3,color=VEHICLE_COLORS[index%VEHICLE_COLORS.length],t=vehicleTemplate(type);
  const root=new THREE.Group();root.name=`${VEHICLE_TYPES[type]} · detailed vehicle`;
  const lod=new THREE.LOD();root.add(lod);const near=new THREE.Group(),bodyRig=new THREE.Group();near.add(bodyRig);
  const doors=[],wheels=[];
  const stopMaterial=new THREE.MeshStandardMaterial({color:0xe62e49,emissive:0xff1435,emissiveIntensity:.25,toneMapped:false});
  const reverseMaterial=new THREE.MeshStandardMaterial({color:0xf8fcff,emissive:0xe3f4ff,emissiveIntensity:.05,toneMapped:false});
  const indicatorMaterials=[-1,1].map(()=>new THREE.MeshStandardMaterial({color:0xffb53c,emissive:0xff970d,emissiveIntensity:.02,toneMapped:false}));
  function ensureDetail(){if(near.userData.built)return;near.userData.built=true;
meshParts(bodyRig,t.body,painted(color));
  const contact=new THREE.Mesh(geometries.contact,mat('contact-shadow',0x08111a,{transparent:true,opacity:.23,depthWrite:false,roughness:1}));contact.scale.set(t.width*1.12,1,t.length*.98);contact.position.y=.015;near.add(contact);

  for(const [i,side] of [[0,-1],[1,1]]){const hinge=new THREE.Group();hinge.name=side<0?'Driver door hinge':'Passenger door hinge';hinge.position.set(side*(t.width/2+.025),t.bodyY+.05,.64);meshParts(hinge,t.doors[i],painted(color));bodyRig.add(hinge);doors.push(hinge);}

  for(const side of [-1,1])for(const z of [-1.3,1.3]){
    const steer=new THREE.Group();steer.position.set(side*(t.width/2-.03),.36,z);const spin=new THREE.Group();spin.name=`Wheel ${side<0?'left':'right'} ${z>0?'front':'rear'}`;meshParts(spin,t.wheel,painted(color));steer.add(spin);near.add(steer);wheels.push({steer,spin,front:z>0});
  }
  for(const side of [-1,1]){
    for(const [material,x,y,z,w,h,d] of [[stopMaterial,side*.65,t.bodyY+.12,-t.length*.49,.38,.09,.025],[reverseMaterial,side*.43,t.bodyY+.12,-t.length*.49,.14,.07,.025],[indicatorMaterials[side<0?0:1],side*.83,t.bodyY+.15,t.length*.485,.12,.09,.03],[indicatorMaterials[side<0?0:1],side*.84,t.bodyY+.15,-t.length*.49,.09,.09,.03]]){
      const mesh=new THREE.Mesh(geometries.box,material);mesh.position.set(x,y,z);mesh.scale.set(w,h,d);near.add(mesh);
    }
  }
  }
  if(!lazyDetailed)ensureDetail();
  const medium=new THREE.Group();meshParts(medium,t.batchedParts,painted(color));
  const distant=new THREE.Group();if(!batchedDistant)meshParts(distant,t.batchedParts,painted(color));
  lod.addLevel(near,0);lod.addLevel(medium,46);lod.addLevel(distant,125);
  root.userData.vehicle={type:VEHICLE_TYPES[type],typeIndex:type,color,width:t.width,length:t.length,height:t.height,partCount:t.partCount,batchMetrics:t.batchMetrics,ensureDetail,lod,bodyRig,doors,wheels,stopMaterial,reverseMaterial,indicatorMaterials,roll:0,steering:0,doorAngle:0,phase:0};
  return root;
}

export function animateVehicle(model,{distance=0,speed=0,steering=0,braking=false,reversing=false,door=0,time=0,dt=.016,decorative=true,updateJoints=true}={}){
  const rig=model.userData.vehicle;if(!rig)return;
  rig.roll+=distance/.35;rig.phase+=Math.abs(distance);
  const blend=1-Math.exp(-12*dt);rig.steering=THREE.MathUtils.lerp(rig.steering,THREE.MathUtils.clamp(steering,-.62,.62),blend);rig.doorAngle=THREE.MathUtils.lerp(rig.doorAngle,decorative?door:0,blend);
  if(!updateJoints)return;rig.ensureDetail?.();
  for(const wheel of rig.wheels){wheel.spin.rotation.x=rig.roll;if(wheel.front)wheel.steer.rotation.y=rig.steering;}
  rig.doors.forEach((hinge,i)=>{hinge.rotation.y=(i===0?1:-1)*rig.doorAngle;});
  rig.bodyRig.position.y=decorative && Math.abs(distance)>.001?Math.sin(rig.phase*3)*.012:0;
  rig.bodyRig.rotation.z=-rig.steering*Math.min(speed/18,.035);
  rig.stopMaterial.emissiveIntensity=braking?3.5:.35;
  rig.reverseMaterial.emissiveIntensity=reversing?2.5:.02;
  const flashing=Math.floor(time/380)%2===0;
  rig.indicatorMaterials.forEach((m,i)=>{m.emissiveIntensity=flashing && (i===0?rig.steering<-.07:rig.steering>.07)?3:.02;});
}
export function disposeVehicle(model){const rig=model.userData.vehicle;if(rig)for(const m of [rig.stopMaterial,rig.reverseMaterial,...rig.indicatorMaterials])m.dispose();}

export function createDistantTraffic(parent,capacity=1200){
  const group=new THREE.Group();group.name='retained-detail-traffic';parent.add(group);
  const batches=[0,1,2].map(type=>{const t=vehicleTemplate(type),batch=new THREE.Group();batch.userData.componentCount=t.partCount;group.add(batch);const meshes=t.batchedParts.map(part=>{const mesh=new THREE.InstancedMesh(part.geometry,part.material,capacity);mesh.userData.paint=part.material===M.paint;mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);mesh.count=0;mesh.frustumCulled=false;mesh.receiveShadow=true;batch.add(mesh);return mesh;});return {meshes,count:0,components:t.partCount};});
  const shadow=new THREE.InstancedMesh(geometries.box,new THREE.MeshBasicMaterial({colorWrite:false,depthWrite:false}),capacity),transform=new THREE.Matrix4(),q=new THREE.Quaternion(),unitScale=new THREE.Vector3(1,1,1),shadowPosition=new THREE.Vector3(),shadowScale=new THREE.Vector3(),color=new THREE.Color();shadow.count=0;shadow.castShadow=true;shadow.frustumCulled=false;group.add(shadow);
  return {update(states,camera){batches.forEach(b=>b.count=0);let total=0;for(const state of states){const car=state.model;if(!car.visible || car.position.distanceToSquared(camera.position)<15625 || total>=capacity)continue;const rig=car.userData.vehicle,batch=batches[rig.typeIndex];q.setFromEuler(car.rotation);transform.compose(car.position,q,unitScale);for(const mesh of batch.meshes){mesh.setMatrixAt(batch.count,transform);if(mesh.userData.paint)mesh.setColorAt(batch.count,color.set(rig.color));}batch.count++;
      transform.compose(shadowPosition.copy(car.position).addScaledVector(axis,.85),q,shadowScale.set(rig.width,1.3,rig.length));shadow.setMatrixAt(total++,transform);
    }for(const b of batches)for(const mesh of b.meshes){mesh.count=b.count;if(b.count){mesh.instanceMatrix.clearUpdateRanges();mesh.instanceMatrix.addUpdateRange(0,b.count*16);mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor){mesh.instanceColor.clearUpdateRanges();mesh.instanceColor.addUpdateRange(0,b.count*3);mesh.instanceColor.needsUpdate=true;}}}shadow.count=total;if(total){shadow.instanceMatrix.clearUpdateRanges();shadow.instanceMatrix.addUpdateRange(0,total*16);shadow.instanceMatrix.needsUpdate=true;}},diagnostics:()=>({materialBatches:batches.reduce((n,b)=>n+b.meshes.length,0),retainedComponents:batches.map(b=>b.components),cars:batches.reduce((n,b)=>n+b.count,0)})};
}

export function mergeArchitecturalBoxes(parent){
  const groups=new Map();for(const mesh of [...parent.children]){
    if(!mesh.userData.staticArchitectural)continue;const m=mesh.material,key=[m.color.getHex(),m.roughness,m.metalness,m.emissive?.getHex(),m.emissiveIntensity,m.opacity,m.side].join('/');
    mesh.updateMatrix();const g=mesh.geometry.clone().applyMatrix4(mesh.matrix);if(!groups.has(key))groups.set(key,{material:m,geometries:[],objects:[]});const group=groups.get(key);group.geometries.push(g);group.objects.push(mesh);
  }
  for(const {material,geometries:parts,objects} of groups.values()){
    const geometry=mergeGeometries(parts,false);parts.forEach(g=>g.dispose());objects.forEach(o=>{parent.remove(o);if(o.material!==material && !o.material.userData.shared)o.material.dispose();});const mesh=new THREE.Mesh(geometry,material);mesh.receiveShadow=true;mesh.castShadow=true;parent.add(mesh);
  }
}

export function addParkedVehicles(parent,bays,level){
  const selected=bays.filter((b,i)=>b.live_slot_id===null && (i*17+level*7)%19<4).map((b,i)=>{const type=i%3,t=vehicleTemplate(type),ew=b.orientation==='east-west';quaternion.setFromAxisAngle(axis,ew?Math.PI/2:0);return {...b,type,color:new THREE.Color(VEHICLE_COLORS[(i*5+level*3)%VEHICLE_COLORS.length]),matrix:new THREE.Matrix4().compose(new THREE.Vector3(b.x,.08,-b.y),quaternion,new THREE.Vector3(1,1,1)),halfX:(ew?t.length/2:t.width/2)+.3,halfZ:(ew?t.width/2:t.length/2)+.3,height:t.height+.4,hidden:false};}),root=new THREE.Group();root.name='parked-vehicle-batches';parent.add(root);
  root.userData.retainedComponents=[];root.userData.models=selected.length;root.userData.visibleModels=selected.length;const batches=[];
  for(let type=0;type<3;type++){
    const items=selected.filter(b=>b.type===type),t=vehicleTemplate(type);if(!items.length)continue;root.userData.retainedComponents.push(t.partCount);
    const meshes=t.batchedParts.map(part=>{const mesh=new THREE.InstancedMesh(part.geometry,part.material,items.length);mesh.receiveShadow=true;mesh.userData.paint=part.material===M.paint;items.forEach((b,i)=>{mesh.setMatrixAt(i,b.matrix);if(mesh.userData.paint)mesh.setColorAt(i,b.color);});mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;mesh.computeBoundingSphere();root.add(mesh);return mesh;});batches.push({items,meshes});
  }
  const proxy=new THREE.InstancedMesh(geometries.box,mat('parked-shadow-proxy',0,{colorWrite:false,depthWrite:false}),selected.length);
  selected.forEach((b,i)=>{const t=vehicleTemplate(b.type);quaternion.setFromAxisAngle(axis,b.orientation==='east-west'?Math.PI/2:0);matrix.compose(new THREE.Vector3(b.x,.85,-b.y),quaternion,new THREE.Vector3(t.width,1.35,t.length));proxy.setMatrixAt(i,matrix);});proxy.castShadow=true;proxy.computeBoundingSphere();root.add(proxy);
  let lastX=Infinity,lastY=Infinity,lastZ=Infinity,lastCeiling=undefined,lastDeck=undefined;
  root.userData.updateVisibility=(camera,ceiling=null)=>{
    const deck=parent.position.y;if(lastX===camera.x && lastY===camera.y && lastZ===camera.z && lastCeiling===ceiling && lastDeck===deck)return;
    lastX=camera.x;lastY=camera.y;lastZ=camera.z;lastCeiling=ceiling;lastDeck=deck;let changed=false,visible=0;
    for(const b of selected){let hidden=ceiling!==null && camera.y>ceiling && deck+b.height<ceiling;
      if(hidden)for(const sx of [-1,1])for(const sy of [0,b.height])for(const sz of [-1,1]){const x=b.x+sx*b.halfX,y=deck+.08+sy,z=-b.y+sz*b.halfZ,t=(ceiling-y)/(camera.y-y),ix=x+(camera.x-x)*t,iz=z+(camera.z-z)*t;if(t<=0 || t>=1 || Math.abs(ix)>94.9 || Math.abs(iz)>31.9)hidden=false;}
      if(b.hidden!==hidden){b.hidden=hidden;changed=true;}if(!hidden)visible++;
    }
    root.userData.visibleModels=visible;if(!changed)return;
    for(const {items,meshes} of batches){let count=0;for(const b of items)if(!b.hidden){for(const mesh of meshes){mesh.setMatrixAt(count,b.matrix);if(mesh.userData.paint)mesh.setColorAt(count,b.color);}count++;}
      for(const mesh of meshes){mesh.count=count;if(count){mesh.instanceMatrix.clearUpdateRanges();mesh.instanceMatrix.addUpdateRange(0,count*16);mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor){mesh.instanceColor.clearUpdateRanges();mesh.instanceColor.addUpdateRange(0,count*3);mesh.instanceColor.needsUpdate=true;}}}
    }
  };
  return selected.length;
}

function rect(parent,color,x,y,z,w,h,d){const mesh=new THREE.Mesh(geometries.box,mat(`fixture-${color}`,color));mesh.position.set(x,y,z);mesh.scale.set(w,h,d);mesh.castShadow=true;mesh.receiveShadow=true;parent.add(mesh);return mesh;}
function led(parent,color,x,y,z,r){const mesh=new THREE.Mesh(geometries.sphere,new THREE.MeshStandardMaterial({color,emissive:color,emissiveIntensity:.65,toneMapped:false}));mesh.position.set(x,y,z);mesh.scale.setScalar(r);parent.add(mesh);return mesh;}

export function createBarrier(parent,x,z,along='z',length=3.6){
  const p=new Parts();p.box(M.dark,x,.6,z,.5,1.2,.55);p.box(M.white,x,.94,z,.52,.28,.58);p.box(M.blue,x,1.17,z,.52,.15,.58);p.box(M.dark,x-.32,.6,z,.15,.9,.22);p.box(M.cyan,x-.405,.84,z,.014,.25,.16);p.mount(parent);
  const pivot=new THREE.Group();pivot.position.set(x,1.17,z);pivot.name='Motorized barrier pivot';if(along==='x')pivot.rotation.y=Math.PI/2;parent.add(pivot);
  const arm=new Parts();arm.box(M.white,0,0,length/2,.11,.14,length);for(let k=0;k<6;k++)arm.box(k%2?M.red:M.white,0,0,(k+.5)*length/6,.13,.17,length/9);arm.box(M.dark,0,-.14,length-.1,.14,.22,.13);arm.mount(pivot);
  const signal=led(parent,0xe34950,x,1.36,z,.09);
  const state={pivot,signal,open:0,target:false,crossing:new THREE.Vector3(x+(along==='x'?length/2:0),0,z+(along==='z'?length/2:0))};return state;
}
export function animateBarrier(state,open,dt){state.target=Boolean(open);state.open=THREE.MathUtils.lerp(state.open,open?1:0,1-Math.exp(-4.5*dt));state.pivot.rotation.x=-state.open*Math.PI*.47;state.signal.material.color.setHex(open?0x55ec9d:0xee4352);state.signal.material.emissive.setHex(open?0x55ec9d:0xee4352);}

export function addDeckDetails(parent,floor,sign){
  const p=new Parts(),accent=mat(`floor-${floor.number}`,floor.color),state={floor:floor.number,fans:[],lifts:[],cameras:[],leds:[]};
  const columns=[-90,-60,-30,0,30,60,90].flatMap(x=>[-29,29].map(z=>[x,z]));
  for(const [x,z] of columns){
    p.box(M.dark,x,.14,z,.92,.27,.92);p.box(M.yellow,x,.52,z,.78,.65,.78);p.box(accent,x,1.45,z,.68,.25,.68);
    for(let i=0;i<4;i++)p.box(M.trim,x,.29+i*.15,z+.399,.7,.075,.012,[0,0,-.35]);
    for(const dx of [-.33,.33])for(const dz of [-.33,.33])p.cyl(M.chrome,x+dx,.29,z+dz,.045,.035);
  }
  // Layered handrails and repeated balusters around each concrete deck edge.
  for(const z of [-31.3,31.3])for(let x=-93;x<94;x+=4.6){
    if(z>0 && (Math.abs(x-35)<4 || Math.abs(x+35)<4))continue;
    p.box(M.steel,x,.65,z,.055,1.15,.055);
    for(const y of [.32,.65,1.17])p.box(y===1.17?accent:M.steel,x+2.25,y,z,4.6,.05,.045);
  }
  for(const x of [-94.2,94.2])for(let z=-30;z<31;z+=4.5){p.box(M.steel,x,.65,z,.055,1.15,.055);for(const y of [.32,.65,1.17])p.box(M.steel,x,y,z+2.2,.045,.05,4.5);}
  // Ceiling structure, sprinkler pipes, cable trays and segmented ventilation ducts.
  if(floor.number<6){
    for(const x of [-75,-45,-15,15,45,75]){p.box(M.concrete,x,3.53,0,.4,.42,60);p.box(M.steel,x,3.12,0,.11,.11,56);}
    for(const z of [-24,24]){p.cyl(M.red,0,3.2,z,.045,184,[0,0,Math.PI/2]);for(let x=-86;x<90;x+=11){p.cyl(M.steel,x,3.15,z,.07,.08);p.box(M.chrome,x,3.09,z,.22,.04,.22);}}
    p.box(M.steel,-5,3.24,7,175,.37,1.1);
    for(let x=-85;x<83;x+=3.5)p.box(M.dark,x,3.24,7, .035,.4,1.13);
    p.box(M.dark,0,3.48,-7,174,.13,.35);
    for(let x=-84;x<88;x+=5)p.box(M.chrome,x,3.57,-7,.04,.24,.5);
  }else{
    for(const x of [-48,37]){
      for(const dx of [-12,12])for(const dz of [-3,3])p.box(M.steel,x+dx,2.2,-24+dz,.13,4.4,.13);
      p.box(M.steel,x,4.35,-24,28,.16,9,[.07,0,0]);
      for(let col=0;col<12;col++)for(let row=0;row<4;row++)p.box(M.blue,x-12.5+col*2.25,4.48+row*.11,-27+row*2,2.1,.07,1.8,[.07,0,0]);
    }
  }
  // Wheel stops, numbered-zone colors, crosswalks and direction chevrons.
  for(const b of floor.bays){const ew=b.orientation==='east-west',x=b.x+(ew?1.9:0),z=-b.y+(ew?0:1.9);p.box(M.yellow,x,.18,z,ew?.18:1.6,.17,ew?1.6:.18);}
  for(const x of [-89,89])for(let i=0;i<7;i++)p.box(M.white,x,.13,17+i*.85,2.8,.015,.45);
  for(const z of [-20,20])for(let x=-70;x<75;x+=24){const d=z<0?-1:1;p.box(M.white,x,.14,z,1.8,.012,.1);p.box(M.white,x+d*.7,.14,z-.3,.8,.012,.1,[0,d*.65,0]);p.box(M.white,x+d*.7,.14,z+.3,.8,.012,.1,[0,-d*.65,0]);}
  for(const [index,x] of [-78,-10,72].entries()){
    // EV dispenser: plinth, cabinet, touchscreen, connector and hanging cable.
    p.box(M.dark,x,.15,-30.3,.8,.3,.65);p.box(M.white,x,.88,-30.3,.55,1.3,.32);p.box(M.green,x,1.58,-30.3,.59,.11,.36);p.box(M.dark,x,1.17,-30.115,.4,.38,.014);p.box(M.cyan,x,1.2,-30.102,.31,.17,.012);p.box(M.dark,x+.29,.94,-30.08,.06,.23,.1);
    p.tube(M.rubber,[[x+.28,1.42,-30.15],[x+.56,.85,-30.08],[x+.51,.3,-30.02],[x+.15,.34,-29.99],[x+.2,.91,-30.05]],.035);
    state.leds.push(led(parent,0x51e0a7,x,1.56,-30.1,.045));
    if(index===0)sign(parent,'EV CHARGING',x,2,-30.3,5,'#95efc1');
  }
  for(const x of [-89,89]){
    // Fire equipment and a service cabinet with vented doors and hardware.
    p.box(M.red,x,1.25,25,.95,1.25,.25);p.box(M.glass,x,1.28,25.14,.72,.94,.02);p.cyl(M.red,x,.79,25.35,.16,.57);p.box(M.chrome,x,1.15,25.35,.27,.07,.1);p.tube(M.trim,[[x+.12,1.12,25.35],[x+.27,1.02,25.38],[x+.27,.77,25.4]],.025);
    p.box(M.white,x,1.24,-13,1,1.9,.38);p.box(M.dark,x,1.24,-12.795,.012,1.85,.016);for(let y=.55;y<1.5;y+=.12)p.box(M.steel,x+.24,y,-12.79,.29,.03,.018);p.box(M.yellow,x,1.85,-12.78,.25,.23,.016);
  }
  p.mount(parent);
  // Detailed sliding elevator doors and an illuminated floor indicator.
  for(const x of [-93,93]){
    const frame=new Parts();frame.box(M.dark,x,1.45,31.02,3.1,2.9,.18);frame.box(M.steel,x,2.87,30.85,3.4,.18,.3);frame.box(M.dark,x+1.43,1.3,30.8,.21,.6,.18);frame.box(M.cyan,x+1.43,1.45,30.69,.13,.15,.01);frame.mount(parent);
    const left=rect(parent,0xa6bcc9,x-.63,1.37,30.84,1.23,2.6,.12),right=rect(parent,0xa6bcc9,x+.63,1.37,30.84,1.23,2.6,.12);
    sign(parent,`${floor.name} ↕`,x,3.16,30.8,2.8,floor.color);state.lifts.push({left,right,x});
  }
  // Fan blades turn inside protective housings; camera heads pan on brackets.
  for(const x of [-91,91]){
    const fan=new THREE.Group();fan.position.set(x,2.5,0);fan.rotation.y=Math.PI/2;parent.add(fan);
    const housing=new Parts();housing.add('torus',M.steel,[0,0,0],[.65,.65,.65]);housing.add('torus',M.trim,[0,0,.03],[.49,.49,.49]);for(let k=0;k<8;k++)housing.box(M.steel,0,0,.13,.035,1.2,.03,[0,0,k*Math.PI/4]);housing.mount(fan);
    const rotor=new THREE.Group();fan.add(rotor);const blades=new Parts();for(let k=0;k<4;k++){const a=k*Math.PI/2;blades.box(M.dark,Math.cos(a)*.25,Math.sin(a)*.25,.03,.52,.17,.045,[0,0,a+.3]);}blades.mount(rotor);state.fans.push(rotor);
    const cam=new THREE.Group();cam.position.set(x,3,-23);parent.add(cam);const shell=new Parts();shell.box(M.steel,0,0,0,.06,.34,.06);shell.box(M.white,0,-.2,.15,.26,.2,.44);shell.cyl(M.trim,0,-.2,.38,.07,.035,[Math.PI/2,0,0]);shell.mount(cam);state.cameras.push(cam);
  }
  return state;
}

export function animateArchitecture(state,time,enabled,dt){
  if(!enabled)return;
  for(const fan of state.fans)fan.rotation.z=(fan.rotation.z+dt*7)%(Math.PI*2);
  state.cameras.forEach((camera,i)=>{camera.rotation.y=Math.sin(time/5000+i)*.3;});
  const loop=(time/1000)%24,stop=Math.floor(loop/4)+1,phase=loop%4;
  const open=stop===state.floor?smooth(phase/.75)*(1-smooth((phase-2.2)/.7)):0;
  state.lifts.forEach(lift=>{lift.left.position.x=lift.x-.63-open*.85;lift.right.position.x=lift.x+.63+open*.85;});
  state.leds.forEach((mesh,i)=>{mesh.material.emissiveIntensity=.7+Math.sin(time/800+i)*.35;});
}

export function addRampDetails(parent,ramp,points){
  const p=new Parts(),leds=[];
  for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i],direction=b.clone().sub(a),length=direction.length(),side=new THREE.Vector3(direction.z,0,-direction.x).normalize(),pitch=Math.atan2(direction.y,Math.hypot(direction.x,direction.z));
    const yaw=Math.atan2(-direction.z,direction.x),center=a.clone().lerp(b,.5);
    for(const s of [-1,1]){
      const c=center.clone().addScaledVector(side,s*(ramp.width/2+.08));p.box(M.steel,c.x,c.y-.28,c.z,length,.38,.14,[0,yaw,pitch]);
      for(let k=0;k<=12;k++){
        const pos=a.clone().lerp(b,k/12).addScaledVector(side,s*(ramp.width/2+.12));p.box(M.steel,pos.x,pos.y+.55,pos.z,.07,1.1,.07);p.box(k%2?M.white:M.yellow,pos.x,pos.y+.72,pos.z,.09,.15,.09);
        if(s===1 && k%2===0)leds.push(led(parent,0xffb34d,pos.x,pos.y+.96,pos.z,.08));
      }
    }
  }p.mount(parent);return {id:ramp.id,leds};
}
export function animateRamp(state,time,active){state.leds.forEach((lamp,i)=>{lamp.material.emissiveIntensity=active?(Math.floor(time/180)%state.leds.length===i?3.5:.65):.18;});}

export function addSiteDetails(parent,sign,{barrier=true}={}){
  const p=new Parts();
  // Entrance booth, access terminal and planted furniture.
  p.box(M.concrete,-103,.15,12,5,.3,4);p.box(M.white,-103,1.6,12,3.2,2.9,2.5);p.box(M.glass,-103,1.9,13.27,2.7,1.4,.035);p.box(M.glass,-101.37,1.9,12,.035,1.4,1.9);p.box(M.blue,-103,3.1,12,3.9,.2,3.1);p.box(M.dark,-104.62,1.2,12,.025,2.2,.9);p.box(M.chrome,-104.65,1.2,11.7,.03,.2,.04);
  sign(parent,'P2 · ACCESS',-103,3.7,12,7,'#a9dcff');
  for(const x of [-110,102])for(const z of [-33,46]){
    p.cyl(M.steel,x,3,z,.075,6);p.box(M.dark,x+.5,6,z,1.3,.18,.4);p.box(M.white,x+.5,5.88,z,.9,.03,.25);
    p.box(M.concrete,x+3,.35,z,3,.7,2);p.box(M.green,x+3,.85,z,2.7,.5,1.7);
    for(const s of [-.7,0,.7])p.cyl(M.trim,x+3+s,.98,z,.035,1.2);
  }
  for(let x=-110;x<105;x+=6){p.box((Math.floor(x/6)%2)?M.white:M.trim,x,-.46,72,5.9,.3,.45);}
  for(let i=0;i<5;i++)p.box(M.white,-104,-.57,28+i*1.2,10,.025,.5);
  for(const [x,z] of [[-112,-34],[-112,46],[104,48],[104,-34]]){
    p.cyl(mat('bark',0x745c43),x,1.7,z,.19,4);
    for(let k=0;k<7;k++){const a=k*2.4,r=k%2?1.5:.7;p.add('sphere',mat(`foliage-${k%3}`,[0x4e956d,0x72af74,0x387c68][k%3]),[x+Math.cos(a)*r,4.4+(k%3)*.6,z+Math.sin(a)*r],[1.9,1.5,1.9]);}
    for(let k=0;k<5;k++)p.box(mat('wood',0xb4824d),x+5,.7,z-.65+k*.28,3,.12,.17);
    for(const dx of [4,6])p.box(M.steel,x+dx,.35,z,.12,.7,1.35);
  }
  p.mount(parent);
  return barrier?createBarrier(parent,-101,17.6,'z'):null;
}
