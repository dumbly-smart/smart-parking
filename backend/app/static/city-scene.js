import * as THREE from '/static/three.module.js';
import { createUrbanMaterial, inferSurface, createContactMaterial, addBuildingShadowProxies, addVegetationShadowProxies, groundHeight } from '/static/city-environment.js?v=1';
import { mergeGeometries } from '/static/vendor/utils/BufferGeometryUtils.js';

const box=new THREE.BoxGeometry(1,1,1),cylinder=new THREE.CylinderGeometry(1,1,1,10),sphere=new THREE.SphereGeometry(1,16,12),cone=new THREE.ConeGeometry(1,1,12),contact=new THREE.PlaneGeometry(1,1).rotateX(-Math.PI/2);
const palette={road:0x303e49,curb:0xc5ceca,walk:0xb8bab2,steel:0x42515f,glass:0x447184,glassLight:0x87b1bd,window:0x355969,wood:0xa77c50,grass:0x688d67,leaf:0x42745e,white:0xe4e5d6,amber:0xe6c874};
class CityParts {
  constructor(){this.groups=new Map();this.count=0;this.lightAnchors=[];this.shadowCanopies=[];}
  add(kind,color,x,y,z,w,h,d,ry=0,emission=0,rx=0,rz=0){const key=`${kind}:${color}:${emission}`;if(!this.groups.has(key))this.groups.set(key,{kind,color,emission,items:[]});this.groups.get(key).items.push({x,y,z,w,h,d,ry,rx,rz});this.count++;}
  box(color,x,y,z,w,h,d,ry=0){this.add('box',color,x,y,z,w,h,d,ry);}
  cyl(color,x,y,z,r,h){this.add('cylinder',color,x,y,z,r,h,r);}
  ball(color,x,y,z,r,h=r){this.add('sphere',color,x,y,z,r,h,r);}
  mount(parent){const m=new THREE.Matrix4(),q=new THREE.Quaternion(),scale=new THREE.Vector3(),pos=new THREE.Vector3();for(const g of this.groups.values()){const material=g.kind==='contact'?createContactMaterial():createUrbanMaterial(g.color,{surface:inferSurface(g.color,g.kind),emission:g.emission,glass:[0x447184,0x87b1bd,0x355969,0x3e929f,0x61a6b5].includes(g.color),foliage:g.kind==='sphere' && inferSurface(g.color,'box')==='grass'});const mesh=new THREE.InstancedMesh({box,cylinder,sphere,cone,contact}[g.kind],material,g.items.length);g.items.forEach((p,i)=>{pos.set(p.x,p.y,p.z);scale.set(p.w,p.h,p.d);q.setFromEuler(new THREE.Euler(p.rx,p.ry,p.rz));m.compose(pos,q,scale);mesh.setMatrixAt(i,m);});mesh.computeBoundingSphere();mesh.receiveShadow=g.kind!=='contact';mesh.castShadow=false;parent.add(mesh);}return this.count;}
}
const seeded=n=>{let a=(n*1664525+1013904223)>>>0;return()=>{a=(a*1664525+1013904223)>>>0;return a/4294967296;};};

function building(p,b){
  const {x,width:w,depth:d,height:h,style}=b,z=-b.y,color=new THREE.Color(b.color).getHex(),accent=new THREE.Color(b.accent).getHex(),random=seeded(b.seed+33);
  p.add('contact',0x162b24,x,.075,z,w+9,1,d+9);
  p.box(palette.curb,x,.24,z,w+3,.48,d+3);
  p.box(color,x,h/2+.5,z,w,h,d);
  const glass=style==='tower'||style==='office';
  if(glass){
    p.box(palette.glass,x,h*.51,z,w+.08,h*.91,d+.08);
    for(let yy=4;yy<h;yy+=3.6){p.box(color,x,yy,z,(w+.35),.35,d+.35);for(let xx=-w/2+3;xx<w/2;xx+=4.5)if(random()>.7)for(const side of [-1,1])p.add('box',0xe2c98f,x+xx,yy+1.5,z+side*(d/2+.12),3.8,2.5,.06,0,.5);}
    for(let xx=-w/2+2;xx<w/2;xx+=4.5)for(const side of [-1,1])p.box(palette.steel,x+xx,h/2,z+side*(d/2+.09),.16,h,.12);
    for(let zz=-d/2+2;zz<d/2;zz+=4.5)for(const side of [-1,1])p.box(palette.steel,x+side*(w/2+.09),h/2,z+zz,.12,h,.16);
  }else{
    for(let yy=4.1;yy<h-1;yy+=3.5){
      for(let xx=-w/2+3;xx<w/2-1;xx+=4.7)for(const side of [-1,1]){
        const lit=random()>.79,c=lit?0xe2c98f:palette.window;
        p.box(palette.curb,x+xx,yy,z+side*(d/2+.12),2.65,2.45,.22);p.add('box',c,x+xx,yy+.05,z+side*(d/2+.26),2.2,1.95,.05,0,lit?.5:0);
        if(style==='apartment' && yy<Math.min(h,25)){
          p.box(palette.curb,x+xx,yy-1.22,z+side*(d/2+1),3.6,.16,2);p.box(accent,x+xx,yy-.73,z+side*(d/2+1.85),3.6,.62,.12);
        }
      }
      for(let zz=-d/2+3;zz<d/2-1;zz+=4.7)for(const side of [-1,1]){p.box(palette.curb,x+side*(w/2+.11),yy,z+zz,.2,2.4,2.5);p.box(palette.window,x+side*(w/2+.23),yy+.05,z+zz,.05,1.95,2.1);}
      if(style==='brick')p.box(0x9d6b59,x,yy-1.5,z,w+.1,.22,d+.1);
    }
  }
  // Shopfront glazing, entrance vestibules and colored projecting awnings.
  for(let xx=-w/2+4;xx<w/2-2;xx+=7){p.box(palette.glassLight,x+xx,1.9,z+d/2+.17,5.8,2.7,.15);p.box(palette.steel,x+xx,1.8,z+d/2+.3,.12,3,.18);p.box(accent,x+xx,3.7,z+d/2+1.2,6.3,.18,2.6);}
  p.box(palette.steel,x,1.8,z+d/2+.4,2.5,3.2,.22);p.box(palette.glassLight,x,1.9,z+d/2+.55,1.9,2.6,.08);
  p.box(accent,x,h+.7,z,w+1.2,.6,d+1.2);p.box(0x65777b,x,h+1.05,z,w-1,.2,d-1);
  // Roof parapets, mechanical units, condenser grilles and service ladders.
  for(const side of [-1,1]){p.box(color,x,h+1.35,z+side*d/2,w,.7,.35);p.box(color,x+side*w/2,h+1.35,z,.35,.7,d);}
  for(let i=0;i<3;i++){const ax=x-w*.25+i*w*.24,az=z-d*.22;p.box(palette.curb,ax,h+1.8,az,3,1.5,2.4);p.cyl(palette.steel,ax,h+2.6,az,.8,.1);for(let k=0;k<5;k++)p.box(palette.steel,ax-1+k*.5,h+1.9,az+1.22,.12,.8,.04);}
  if(style==='tower'){
    p.box(color,x,h+4,z,w*.62,7,d*.62);p.box(palette.glass,x,h+7.6,z,w*.55,.6,d*.55);p.cyl(palette.steel,x,h+12,z,.2,13);
    for(const side of [-1,1])p.box(accent,x+side*w*.45,h/2,z,.65,h+3,d+1);
  }
  roofGarden(p,b);
  if(style==='hotel')p.box(accent,x-w*.32,h*.5,z+d/2+.5,2,h*.8,1);
  if(style==='retail')for(let k=0;k<4;k++)p.box(palette.glassLight,x-w*.32+k*w*.21,h+1.8,z,3,.35,d*.5);
  if(style==='mall'){
    p.box(palette.glassLight,x,h+2,z,w*.67,3,d*.55);p.box(palette.steel,x,h+3.6,z,w*.7,.15,d*.6);
    for(let k=0;k<13;k++)p.box(palette.white,x-w*.46+k*w*.077,h*.5,z+d/2+.5,.6,h,1);
    p.box(accent,x,5.2,z+d/2+3,w*.93,.4,6);p.box(palette.glassLight,x,5.45,z+d/2+3,w*.9,.12,5.5);
  }
}

function ribbon(points,width,y=.04){
  const positions=[];
  for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i],dx=b[0]-a[0],dz=-(b[1]-a[1]),len=Math.hypot(dx,dz);if(len<.01)continue;
    const sx=-dz/len*width/2,sz=dx/len*width/2,az=-a[1],bz=-b[1];
    positions.push(a[0]+sx,y,az+sz,a[0]-sx,y,az-sz,b[0]-sx,y,bz-sz,a[0]+sx,y,az+sz,b[0]-sx,y,bz-sz,b[0]+sx,y,bz+sz);
  }
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));g.computeVertexNormals();return g;
}
function roadGeometry(parent,city){
  const pieces=[];
  for(const road of city.roads)for(const lane of road.lanes)pieces.push(ribbon(lane.shape,lane.width+.06));
  for(const j of city.junctions){const pts=j.shape.map(p=>new THREE.Vector2(p[0],-p[1]));if(pts.length<3)continue;const faces=THREE.ShapeUtils.triangulateShape(pts,[]),g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(faces.flatMap(f=>f.flatMap(i=>[pts[i].x,.045,pts[i].y])),3));g.computeVertexNormals();pieces.push(g);}
  const geometry=mergeGeometries(pieces,false);pieces.forEach(g=>g.dispose());const road=new THREE.Mesh(geometry,createUrbanMaterial(palette.road,{surface:'asphalt'}));road.material.side=THREE.DoubleSide;road.receiveShadow=true;parent.add(road);
}
function tree(p,x,z,seed=0){
  const random=seeded(Math.round(seed*37+x*11+z*7)),height=(Math.abs(x)>620 || Math.abs(z)>600)?10+random()*7:5+random()*4.5,base=(Math.abs(x)>620 || Math.abs(z)>600)?groundHeight(x,z):.06,greens=[0x427152,0x547d55,0x6d8b59,0x3f6c51,0x7e945f];
  p.shadowCanopies.push([x,base+height*.78,z,height*.42,height*.4,height*.42]);
  p.cyl(0x806a4e,x,base+height*.35,z,.2+random()*.15,height*.7);
  for(let k=0;k<3;k++){const a=k*2.1+random(),r=height*.2;p.add('cylinder',0x806a4e,x+Math.cos(a)*r*.5,base+height*.58,z+Math.sin(a)*r*.5,.08,height*.4,.08,-a,0,0,.6);}
  for(let k=0;k<7;k++){const a=k*2.4+random()*.7,r=k===6?0:height*(.11+random()*.17);p.add('sphere',greens[Math.floor(random()*greens.length)],x+Math.cos(a)*r,base+height*(.65+random()*.26),z+Math.sin(a)*r,height*(.18+random()*.09),height*(.19+random()*.12),height*(.18+random()*.09),random()*3);}
}
function roofGarden(p,b){
  const {x,width:w,depth:d,height:h,seed}=b,z=-b.y,y=h+1.3,random=seeded(seed+981);
  if(seed%3===0){
    p.box(0x8c9c7a,x+w*.21,y,z+d*.19,w*.38,.18,d*.36);
    for(let i=0;i<5;i++){const ax=x+w*.04+i*w*.075;p.box(0xb4a58a,ax,y+.3,z+d*.31,1.1,.65,1.4);p.ball(0x547d55,ax,y+.9,z+d*.31,.72,.6);}
    for(const side of [-1,1])p.box(palette.steel,x+w*.21+side*w*.17,y+1.6,z+d*.18,.12,3.1,.12);
    p.box(palette.wood,x+w*.21,y+3.2,z+d*.18,w*.36,.12,d*.34);
    for(let i=0;i<7;i++)p.box(0xceb48a,x+w*.21,y+3.3,z+d*.03+i*d*.045,w*.38,.08,.23);
  }else if(seed%3===1){
    for(let i=0;i<3;i++)for(let k=0;k<3;k++){const ax=x-w*.25+i*w*.14,az=z+d*.1+k*d*.1;p.box(palette.steel,ax,y+.5,az,w*.125,.18,d*.085);p.add('box',0x264859,ax,y+.66,az,w*.12,.1,d*.08,0,0,-.12);for(let line=0;line<3;line++)p.box(0x6c91a3,ax-w*.045+line*w*.045,y+.73,az,.04,.015,d*.07);}
  }else if(b.style==='hotel'){
    p.box(0xd9d7bc,x,y+.1,z+d*.17,w*.45,.25,d*.38);p.box(0x61a6b5,x,y+.26,z+d*.17,w*.39,.06,d*.31);
    for(let i=0;i<3;i++){p.box(palette.white,x+w*.3,y+.6,z-d*.04+i*d*.13,1.3,.25,2.6);p.cyl(palette.steel,x+w*.39,y+1.5,z-d*.04+i*d*.13,.03,2.8);p.add('cone',0xe8d2a6,x+w*.39,y+3,z-d*.04+i*d*.13,1.65,.45,1.65);}
  }
  if(b.style==='brick'||b.style==='retail')for(const side of [-1,1])p.add('box',side===1?0x9a6954:0xae8067,x,y+1.9,z+side*d*.13,w*.82,.18,d*.31,0,0,side*.27);
  if(random()>.5)p.box(0x82938b,x+w*.34,y+1.3,z-d*.25,2.4,2.5,2.1);
}
function naturalLandscaping(p,city){
  const random=seeded(8831);
  for(const block of city.blocks){if(block.central||block.park)continue;
    for(const side of [-1,1])for(const end of [-1,1]){const x=block.x+side*(block.width/2-12),z=-block.y+end*(block.depth/2-12);p.box(0x718760,x,.1,z,9,.12,11);tree(p,x+(random()-.5)*2,z+(random()-.5)*2,x+z);for(let k=0;k<4;k++)p.add('sphere',[0x557c52,0x839461,0xb1aa73][k%3],x-3+random()*6,.5+random()*.5,z-4+random()*8,.6,.55,.6);}
  }
  for(let grove=0;grove<36;grove++){const angle=random()*Math.PI*2,radius=760+random()*1050,cx=Math.cos(angle)*radius,cz=Math.sin(angle)*radius;for(let i=0;i<12;i++){const a=random()*Math.PI*2,r=Math.sqrt(random())*55,x=cx+Math.cos(a)*r,z=cz+Math.sin(a)*r;tree(p,x,z,grove*109+i*29);}}
  const parkBlock=city.blocks.find(b=>b.park);if(parkBlock){const x=parkBlock.x,z=-parkBlock.y;
    for(let i=0;i<30;i++){const a=random()*Math.PI*2,r=28+random()*38,px=x+Math.cos(a)*r,pz=z+Math.sin(a)*r;p.ball([0x74895b,0x8b9b69,0x5f7e54][i%3],px,.55,pz,1.1+random(),.6);for(let j=0;j<3;j++)p.ball([0xc0b16e,0xb896ad,0xe6d6ac][i%3],px+(random()-.5)*2,.95,pz+(random()-.5)*2,.12,.18);}
  }
}
function lamp(p,x,z,ry=0){p.lightAnchors.push([x+Math.sin(ry)*2.3,7.35,z+Math.cos(ry)*2.3]);p.cyl(palette.steel,x,3.8,z,.13,7.6);p.box(palette.steel,x+Math.sin(ry)*1.2,7.7,z+Math.cos(ry)*1.2,.18,.14,2.6,ry);p.box(palette.steel,x+Math.sin(ry)*2.3,7.65,z+Math.cos(ry)*2.3,.8,.18,1.1,ry);p.add('box',0xffe5ae,x+Math.sin(ry)*2.3,7.53,z+Math.cos(ry)*2.3,.55,.04,.8,ry,.65);}
function shelter(p,x,z,ry=0){
  // Glass side/back panels, structural frames, bench slats and a route display.
  const at=(a,b)=>[x+Math.cos(ry)*a+Math.sin(ry)*b,z-Math.sin(ry)*a+Math.cos(ry)*b];
  const part=(c,a,y,b,w,h,d)=>{const [xx,zz]=at(a,b);p.box(c,xx,y,zz,w,h,d,ry);};
  part(palette.curb,0,.15,0,10,.3,4.5);part(palette.steel,0,3.2,0,10.5,.18,4.8);part(palette.glassLight,0,3.35,0,10,.12,4.3);part(palette.glassLight,0,1.7,-1.9,9,2.7,.1);
  for(const a of [-4.4,4.4]){part(palette.steel,a,1.65,-1.8,.15,3.3,.15);part(palette.glassLight,a,1.6,0,.1,2.8,3.8);}
  for(let k=0;k<4;k++)part(palette.wood,0,.7,-.65+k*.25,6,.12,.18);part(palette.steel,0,1.15,-1,6,.65,.1);part(palette.steel,5.7,2,0,.17,4,.17);part(0x559f9e,5.7,3.1,0,1.5,1.1,.1);part(palette.white,3.7,1.9,-1.77,1,1.5,.06);
}
function pavement(p,city){
  // Leave a true central opening for the underground garage cutaway.
  // The continuous terrain comes from city-environment; keep road geometry unchanged.
  for(const b of city.blocks){if(b.central)continue;p.box(b.park?palette.grass:palette.walk,b.x,-.08,-b.y,b.width,.25,b.depth);p.box(palette.curb,b.x,-.18,-b.y,b.width+1,.25,b.depth+1);}
  // Central block plaza behind the garage and a landscaped front approach.
  for(const plaza of city.plazas || [])p.box(plaza.surface==='grass'?palette.grass:palette.walk,plaza.x,-.1,-plaza.y,plaza.width,.3,plaza.depth);
  for(const x of city.grid_x)for(let y=-520;y<530;y+=40)if(city.grid_y.every(c=>Math.abs(c-y)>20)){tree(p,x-15+Math.sin(y*.13)*1.2,-y+Math.sin(y*.11)*3,Math.floor(y));lamp(p,x+12,-y,Math.PI/2);}
  for(const y of city.grid_y)for(let x=-540;x<550;x+=45)if(city.grid_x.every(c=>Math.abs(c-x)>22)){tree(p,x+Math.sin(x*.1)*3,-y-15+Math.cos(x*.13),Math.floor(x));lamp(p,x,-y+12,Math.PI);}
  // Road lane dividers and zebra crossings terminate before the native junctions.
  for(const x of city.grid_x)for(let y=-520;y<530;y+=9)if(city.grid_y.every(j=>Math.abs(j-y)>15)&&!(x===-160&&Math.abs(y+20)<16))for(const offset of [-3.2,3.2])p.box(palette.white,x+offset,.065,-y,.12,.018,3.2);
  for(const y of city.grid_y)for(let x=-540;x<550;x+=9)if(city.grid_x.every(j=>Math.abs(j-x)>15))for(const offset of [-3.2,3.2])p.box(palette.white,x,.065,-y+offset,3.2,.018,.12);
  for(const x of city.grid_x)for(const y of city.grid_y){
    for(let k=-5;k<=5;k++)for(const sign of [-1,1]){p.box(palette.white,x+k*.95,.075,-y+sign*12,.45,.018,3);p.box(palette.white,x+sign*12,.075,-y+k*.95,3,.018,.45);}
    for(const sx of [-1,1])for(const sz of [-1,1])p.cyl(palette.steel,x+sx*10,.5,-y+sz*10,.09,1);
  }
  for(const [x,z,ry] of [[-146,68,0],[146,-65,Math.PI],[274,128,0],[-374,-210,Math.PI/2],[414,-354,0]])shelter(p,x,z,ry);
}
function park(p,block){
  const x=block.x,z=-block.y,w=block.width,d=block.depth;
  p.box(0xd7ceb4,x,.09,z,w*.88,.15,5);p.box(0xd7ceb4,x,.1,z,5,.15,d*.88);
  p.cyl(palette.curb,x,.4,z,14,.8);p.cyl(0x3e929f,x,.86,z,12.5,.18);p.cyl(0xc6d3cb,x,1.6,z,2.7,2);
  for(let i=0;i<16;i++){const a=i*Math.PI/8;tree(p,x+Math.cos(a)*(w*.38),z+Math.sin(a)*(d*.38),i);}
  for(const a of [-1,1])for(const b of [-1,1]){p.box(palette.wood,x+a*22,.7,z+b*14,7,.15,1.2);p.box(palette.steel,x+a*22,1.2,z+b*14+.6,7,.8,.1);p.cyl(palette.steel,x+a*28,.7,z+b*14,.5,1.4);}
  p.box(0x9bba90,x+w*.25,.1,z+d*.25,22,.2,15);p.box(0xceb980,x+w*.25,.25,z+d*.25,19,.15,12);
  for(const side of [-1,1])p.cyl(palette.amber,x+w*.25+side*4,2,z+d*.25,.15,4);
  return {x,z,w,d};
}
function pedestrians(root,parkData){
  if(!parkData)return[];const list=[];
  for(let i=0;i<14;i++){
    const group=new THREE.Group(),shirt=new THREE.MeshLambertMaterial({color:[0xe6ac68,0x73b7c5,0xb2789d,0xd7dbcc,0x728db7][i%5]}),skin=new THREE.MeshLambertMaterial({color:[0xbd896b,0xe1b497,0x8f6652][i%3]}),pants=new THREE.MeshLambertMaterial({color:0x324452});
    const body=new THREE.Mesh(box,shirt);body.scale.set(.43,.62,.27);body.position.y=1.12;group.add(body);const head=new THREE.Mesh(sphere,skin);head.scale.set(.19,.23,.19);head.position.y=1.68;group.add(head);
    const limbs=[];for(const side of [-1,1])for(const leg of [true,false]){const joint=new THREE.Group();joint.position.set(side*(leg?.14:.3),leg?.87:1.35,0);const mesh=new THREE.Mesh(box,leg?pants:shirt);mesh.scale.set(leg?.16:.12,leg?.75:.55,.15);mesh.position.y=leg?-.37:-.25;joint.add(mesh);group.add(joint);limbs.push({joint,phase:side*(leg?1:-1)});}root.add(group);list.push({group,limbs,phase:i/14,park:parkData});
  }return list;
}
function signals(root,city,p){
  const count=city.signals.length,lamps=[];
  const lensMeshes=[0xff4949,0xffc557,0x68eb9d].map(()=>{const mesh=new THREE.InstancedMesh(sphere,new THREE.MeshBasicMaterial({color:0xffffff,toneMapped:false}),count);root.add(mesh);return mesh;});
  const m=new THREE.Matrix4(),q=new THREE.Quaternion(),size=new THREE.Vector3(.13,.13,.13),off=[0x3d2228,0x403523,0x203b30];
  city.signals.forEach((s,i)=>{
    const points=s.lane.shape,a=points.at(-2),b=points.at(-1),dx=b[0]-a[0],dz=-(b[1]-a[1]),length=Math.hypot(dx,dz)||1,fx=dx/length,fz=dz/length,rx=-fz,rz=fx;
    const px=b[0]+rx*3.5,pz=-b[1]+rz*3.5,hx=px-rx*2.3,hz=pz-rz*2.3,ry=Math.atan2(fx,fz);
    p.cyl(palette.steel,px,2.4,pz,.11,4.8);p.box(palette.steel,px-rx*1.15,4.7,pz-rz*1.15,2.5,.12,.12,Math.atan2(-rz,rx));p.box(0x192833,hx,4.25,hz,.5,1.2,.3,ry);
    for(let k=0;k<3;k++){m.compose(new THREE.Vector3(hx-fx*.19,4.58-k*.33,hz-fz*.19),q,size);lensMeshes[k].setMatrixAt(i,m);lensMeshes[k].setColorAt(i,new THREE.Color(off[k]));}
    lamps.push({...s,index:i,state:'o'});
  });lensMeshes.forEach(m=>m.computeBoundingSphere());
  return {lamps,lensMeshes,update(states){for(const s of lamps){const chars=s.indices.map(i=>states?.[s.controller]?.[i]||'o'),state=chars.some(c=>'Gg'.includes(c))?'g':chars.some(c=>'yY'.includes(c))?'y':chars.some(c=>'rR'.includes(c))?'r':'o';s.state=state;for(let k=0;k<3;k++)lensMeshes[k].setColorAt(s.index,new THREE.Color(state===['r','y','g'][k]?[0xff4949,0xffc557,0x68eb9d][k]:off[k]));}lensMeshes.forEach(m=>{if(m.instanceColor)m.instanceColor.needsUpdate=true;});}};
}

export function createCityDistrict(parent,city,sign){
  const root=new THREE.Group();root.name='city-district';parent.add(root);const p=new CityParts();pavement(p,city);roadGeometry(root,city);
  city.buildings.forEach(b=>building(p,b));const parkBlock=city.blocks.find(b=>b.park),parkData=parkBlock?park(p,parkBlock):null;
  naturalLandscaping(p,city);const shadowMasses=addBuildingShadowProxies(root,city.buildings);
  if(parkData){
    const path=[];for(let k=0;k<=72;k++){const a=k/72*Math.PI*2,r=1+Math.sin(a*3)*.06;path.push([parkData.x+Math.cos(a)*parkData.w*.35*r,-(parkData.z+Math.sin(a)*parkData.d*.35*r)]);}
    const walk=new THREE.Mesh(ribbon(path,3,.21),createUrbanMaterial(0xc3b99d,{surface:'paving'}));walk.material.side=THREE.DoubleSide;walk.receiveShadow=true;root.add(walk);
    const shape=new THREE.Shape();for(let k=0;k<=48;k++){const a=k/48*Math.PI*2,r=1+Math.sin(a*3)*.13,x=Math.cos(a)*19*r,z=Math.sin(a)*10*r;if(!k)shape.moveTo(x,-z);else shape.lineTo(x,-z);}
    const pond=new THREE.Mesh(new THREE.ShapeGeometry(shape),new THREE.MeshPhysicalMaterial({color:0x548f91,roughness:.18,metalness:.18,clearcoat:.7,envMapIntensity:.6}));pond.rotation.x=-Math.PI/2;pond.position.set(parkData.x-42,.27,parkData.z+31);root.add(pond);
    for(let i=0;i<26;i++){const a=i/26*Math.PI*2,r=1+Math.sin(a*3)*.13;p.ball([0x9a9f8b,0x7b877c,0xb3b39b][i%3],parkData.x-42+Math.cos(a)*20*r,.38,parkData.z+31+Math.sin(a)*11*r,.7+(i%3)*.15,.45);}
  }
  const trafficSignals=signals(root,city,p);const vegetationShadows=addVegetationShadowProxies(root,p.shadowCanopies),componentCount=p.mount(root),walkers=pedestrians(root,parkData);
  const water=new THREE.Group();root.add(water);const jets=[];
  if(parkData)for(let i=0;i<9;i++){const a=i*Math.PI/4,r=i===8?0:7,mesh=new THREE.Mesh(cylinder,new THREE.MeshLambertMaterial({color:0x9cdee2,transparent:true,opacity:.7}));mesh.position.set(parkData.x+Math.cos(a)*r,2,parkData.z+Math.sin(a)*r);water.add(mesh);jets.push({mesh,phase:i});}
  const mall=city.buildings.find(b=>b.style==='mall');if(mall)sign(root,'CENTRAL GALLERIA',mall.x,10,-mall.y+mall.depth/2+.8,62,'#f7e2ad');
  sign(root,'PARKFLOW CENTRAL',-280,8,126,45,'#b3e1db');if(parkData)sign(root,'GARDEN SQUARE',parkData.x,2,parkData.z+parkData.d/2-6,25,'#dbe9b5');
  const state={root,componentCount,buildingCount:city.buildings.length,signalCount:trafficSignals.lamps.length,walkers:walkers.length,trafficSignals,
    setSignals:states=>trafficSignals.update(states),
    animate(time,enabled){if(!enabled||!root.visible)return;const t=time/1000;for(const w of walkers){const a=(t*.045+w.phase*Math.PI*2),r=Math.min(w.park.w,w.park.d)*.31;w.group.position.set(w.park.x+Math.cos(a)*r,.12,w.park.z+Math.sin(a)*r);w.group.rotation.y=-a;for(const limb of w.limbs)limb.joint.rotation.x=Math.sin(t*4.2+w.phase*10)*.48*limb.phase;}for(const j of jets){const h=2+Math.sin(t*1.7+j.phase)*.65+(j.phase===8?1.8:0);j.mesh.scale.set(.12,h,.12);j.mesh.position.y=.9+h/2;}},
    lightAnchors:p.lightAnchors,
    setLighting(mode){root.traverse(node=>{if(node.material?.emissiveIntensity>0)node.material.emissiveIntensity=mode==='evening'?1.7:.08;});},
    diagnostics:()=>({buildings:city.buildings.length,components:componentCount,shadowMasses:shadowMasses.count,vegetationShadowProxies:vegetationShadows.count,streetLightAnchors:p.lightAnchors.length,signalHeads:trafficSignals.lamps.length,walkers:walkers.length,visible:root.visible,pedestrianSample:walkers[0]?.group.position.toArray(),fountainSample:jets[0]?.mesh.scale.y,signalColorSample:trafficSignals.lensMeshes.map(mesh=>{const c=new THREE.Color();mesh.getColorAt(0,c);return c.getHexString();}),signalStates:trafficSignals.lamps.map(s=>({id:s.id,state:s.state,controller:s.controller,indices:s.indices}))})};
  return state;
}
