import * as THREE from '/static/three.module.js';

const textures=new Map();let anisotropy=4;const breeze={value:0};
const rng=seed=>{let s=seed>>>0;return()=>((s=(s*1664525+1013904223)>>>0)/4294967296);};
export function configureSurfaceFiltering(renderer){anisotropy=Math.min(16,renderer.capabilities.getMaxAnisotropy());for(const texture of textures.values()){texture.anisotropy=anisotropy;texture.needsUpdate=true;}}
function surfaceTexture(kind){
  if(textures.has(kind))return textures.get(kind);
  const canvas=document.createElement('canvas');canvas.width=canvas.height=512;const ctx=canvas.getContext('2d'),random=rng(kind.length*731+12);
  ctx.fillStyle=kind==='grass'?'#a3ac8b':kind==='asphalt'?'#b2b3b1':kind==='wood'?'#b4a58e':'#c8c5bd';ctx.fillRect(0,0,512,512);
  const image=ctx.getImageData(0,0,512,512);for(let i=0;i<image.data.length;i+=4){const value=(random()-.5)*(kind==='grass'?50:30);for(let k=0;k<3;k++)image.data[i+k]=Math.max(0,Math.min(255,image.data[i+k]+value));}ctx.putImageData(image,0,0);
  if(kind==='asphalt'){for(let i=0;i<1800;i++){const v=90+random()*90;ctx.fillStyle=`rgba(${v},${v},${v},.23)`;ctx.fillRect(random()*512,random()*512,1+random()*2,1+random()*2);}for(let i=0;i<4;i++){ctx.strokeStyle='#686e6b24';ctx.lineWidth=.7;ctx.beginPath();let x=random()*512,y=random()*512;ctx.moveTo(x,y);for(let n=0;n<6;n++){x+=random()*36-18;y+=random()*22;ctx.lineTo(x,y);}ctx.stroke();}}
  if(kind==='paving'){ctx.strokeStyle='#7f85813b';ctx.lineWidth=2;for(let y=0;y<=512;y+=64){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(512,y);ctx.stroke();for(let x=(y/64%2)*64;x<=512;x+=128){ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x,y+64);ctx.stroke();}}}
  if(kind==='grass'){for(let i=0;i<4500;i++){const x=random()*512,y=random()*512;ctx.strokeStyle=random()>.5?'#55674638':'#d4d1a432';ctx.lineWidth=.6;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+random()*3-1.5,y-2-random()*5);ctx.stroke();}}
  if(kind==='wood'){for(let y=0;y<512;y+=8){ctx.strokeStyle='#68584333';ctx.beginPath();ctx.moveTo(0,y);ctx.bezierCurveTo(160,y+9,340,y-7,512,y+2);ctx.stroke();}}
  const texture=new THREE.CanvasTexture(canvas);texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=anisotropy;texture.minFilter=THREE.LinearMipmapLinearFilter;texture.generateMipmaps=true;textures.set(kind,texture);return texture;
}
export function createUrbanMaterial(color,{surface='concrete',emission=0,glass=false,foliage=false}={}){
  const material=new THREE.MeshStandardMaterial({color,roughness:glass?.24:surface==='asphalt'?.94:.87,metalness:glass?.38:0,emissive:color,emissiveIntensity:emission,envMapIntensity:glass?.7:.18});
  material.userData.surface=surface;
  if(!glass && !emission){
    const texture=surfaceTexture(surface),tile=surface==='grass'?6:surface==='asphalt'?8:surface==='paving'?4:3;
    material.onBeforeCompile=shader=>{
      shader.uniforms.urbanBreeze=breeze;shader.uniforms.urbanSurface={value:texture};shader.uniforms.urbanTile={value:tile};
      shader.vertexShader='uniform float urbanBreeze; varying vec3 vUrbanPosition;\nvarying vec3 vUrbanNormal;\n'+shader.vertexShader;
      shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>',`#include <begin_vertex>
        vec4 urbanPosition = vec4(position,1.0); vec3 urbanNormal = normal;
        #ifdef USE_INSTANCING
          urbanPosition = instanceMatrix * urbanPosition; urbanNormal = mat3(instanceMatrix) * urbanNormal;
        #endif
        vUrbanPosition = (modelMatrix * urbanPosition).xyz; vUrbanNormal = normalize(mat3(modelMatrix) * urbanNormal);
        ${foliage?'transformed.x += sin(urbanBreeze+vUrbanPosition.x*.08+vUrbanPosition.z*.06)*.013*max(position.y+.5,0.0);':''}`);
      shader.fragmentShader='uniform sampler2D urbanSurface; uniform float urbanTile; varying vec3 vUrbanPosition; varying vec3 vUrbanNormal;\n'+shader.fragmentShader;
      shader.fragmentShader=shader.fragmentShader.replace('#include <color_fragment>',`#include <color_fragment>
        vec3 urbanBlend=abs(normalize(vUrbanNormal)); urbanBlend/=max(dot(urbanBlend,vec3(1.0)),.0001);
        vec3 urbanTex=texture2D(urbanSurface,vUrbanPosition.zy/urbanTile).rgb*urbanBlend.x+texture2D(urbanSurface,vUrbanPosition.xz/urbanTile).rgb*urbanBlend.y+texture2D(urbanSurface,vUrbanPosition.xy/urbanTile).rgb*urbanBlend.z;
        diffuseColor.rgb *= mix(vec3(.85),urbanTex*1.25,.38);`);
    };
    material.customProgramCacheKey=()=>`urban-${surface}-${foliage}-v2`;
  }
  return material;
}
export function inferSurface(color,kind){const c=new THREE.Color(color),hsl={};c.getHSL(hsl);return color===0x303e49?'asphalt':kind==='sphere'||(hsl.h>.17&&hsl.h<.46&&hsl.s>.14)?'grass':color===0xb8bab2||color===0xc5ceca?'paving':color===0xa77c50||color===0x806a4e?'wood':'concrete';}

export function createContactMaterial(){
  const canvas=document.createElement('canvas');canvas.width=canvas.height=128;const ctx=canvas.getContext('2d');
  const gradient=ctx.createRadialGradient(64,64,15,64,64,64);gradient.addColorStop(0,'rgba(18,30,24,.36)');gradient.addColorStop(.65,'rgba(18,30,24,.22)');gradient.addColorStop(1,'rgba(18,30,24,0)');ctx.fillStyle=gradient;ctx.fillRect(0,0,128,128);
  return new THREE.MeshBasicMaterial({map:new THREE.CanvasTexture(canvas),transparent:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-1,toneMapped:false});
}
function landHeight(x,z){const distance=Math.max(Math.abs(x)-620,Math.abs(z)-600,0),blend=THREE.MathUtils.smoothstep(distance,0,520);return -.55+blend*(12+Math.sin(x*.003)*17+Math.cos(z*.004)*15+Math.sin((x+z)*.006)*7);}
function terrain(parent){
  const count=104,size=8400,positions=[],colors=[],indices=[],c=new THREE.Color();
  const xs=[...new Set([...Array.from({length:count+1},(_,i)=>(i/count-.5)*size),-130,130])].sort((a,b)=>a-b),zs=[...new Set([...Array.from({length:count+1},(_,i)=>(i/count-.5)*size),-70,70])].sort((a,b)=>a-b);
  for(const z of zs)for(const x of xs){const y=landHeight(x,z),shade=.94+Math.sin(x*.014+z*.011)*.06+Math.cos(x*.036-z*.019)*.025;positions.push(x,y,z);c.set(0x64865d).multiplyScalar(shade);colors.push(c.r,c.g,c.b);}
  for(let row=0;row<zs.length-1;row++)for(let col=0;col<xs.length-1;col++){
    if(xs[col]>=-130 && xs[col+1]<=130 && zs[row]>=-70 && zs[row+1]<=70)continue;
    const a=row*xs.length+col,b=a+1,d=a+xs.length,e=d+1;indices.push(a,d,b,b,d,e);
  }
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));g.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));g.setIndex(indices);g.computeVertexNormals();const m=createUrbanMaterial(0xffffff,{surface:'grass'});m.vertexColors=true;const mesh=new THREE.Mesh(g,m);mesh.receiveShadow=true;parent.add(mesh);return mesh;
}
function skyTexture(evening=false){
  const key=evening?'eveningSky':'daySky';if(textures.has(key))return textures.get(key);const canvas=document.createElement('canvas');canvas.width=1024;canvas.height=512;const ctx=canvas.getContext('2d'),g=ctx.createLinearGradient(0,0,0,512);
  for(const [pos,color] of evening?[[0,'#111c36'],[.42,'#3b4d6a'],[.54,'#a37d6b'],[.7,'#4e5e68'],[1,'#202c35']]:[[0,'#4c83b4'],[.35,'#91b9d2'],[.52,'#dce2d9'],[.65,'#b3c1b0'],[1,'#798771']])g.addColorStop(pos,color);ctx.fillStyle=g;ctx.fillRect(0,0,1024,512);const t=new THREE.CanvasTexture(canvas);t.mapping=THREE.EquirectangularReflectionMapping;t.colorSpace=THREE.SRGBColorSpace;textures.set(key,t);return t;
}
function cloudTexture(){
  const canvas=document.createElement('canvas');canvas.width=512;canvas.height=256;const ctx=canvas.getContext('2d'),random=rng(419);for(let i=0;i<42;i++){const x=70+random()*370,y=95+random()*80,r=20+random()*65,g=ctx.createRadialGradient(x,y,0,x,y,r);g.addColorStop(0,'rgba(255,255,247,.16)');g.addColorStop(1,'rgba(255,255,255,0)');ctx.fillStyle=g;ctx.fillRect(x-r,y-r,r*2,r*2);}return new THREE.CanvasTexture(canvas);
}
export function createNaturalEnvironment(scene,city,renderer){
  configureSurfaceFiltering(renderer);const root=new THREE.Group();root.name='natural-landscape';scene.add(root);const ground=terrain(root);
  const clouds=[],random=rng(2192),cloudMap=cloudTexture();
  for(let i=0;i<18;i++){const m=new THREE.MeshBasicMaterial({map:cloudMap,transparent:true,opacity:.5,depthWrite:false,side:THREE.DoubleSide,toneMapped:false}),mesh=new THREE.Mesh(new THREE.PlaneGeometry(1,1),m);const angle=random()*Math.PI*2,radius=1400+random()*1300;mesh.position.set(Math.cos(angle)*radius,450+random()*300,Math.sin(angle)*radius);mesh.scale.set(350+random()*500,140+random()*170,1);root.add(mesh);clouds.push({mesh,start:mesh.position.x,speed:.45+random()*.7});}
  scene.environment=skyTexture(false);scene.environmentIntensity=.5;
  let mode='day',visible=true;
  return {root,
    setVisible(value){visible=value;root.visible=value;if(value){scene.background=skyTexture(mode==='evening');scene.fog=new THREE.Fog(mode==='evening'?0x526477:0xc0d2d7,2300,5500);}else{scene.background=new THREE.Color(mode==='evening'?0x101c30:0x9bb4be);scene.fog=null;}},
    setLighting(value){mode=value;scene.environment=skyTexture(value==='evening');if(visible){scene.background=skyTexture(value==='evening');scene.fog=new THREE.Fog(value==='evening'?0x526477:0xc0d2d7,2300,5500);}clouds.forEach(c=>c.mesh.material.opacity=value==='evening'?.22:.5);},
    update(time,camera,animated){if(animated)breeze.value=time/1000;for(const c of clouds){c.mesh.quaternion.copy(camera.quaternion);if(animated)c.mesh.position.x=c.start+Math.sin(time/1000000)*100*c.speed;}},
    diagnostics:()=>({visible:root.visible,clouds:clouds.length,terrainVertices:ground.geometry.attributes.position.count,terrainOpening:true,textures:textures.size,anisotropy,mode})};
}

export function addBuildingShadowProxies(parent,buildings){
  const geometry=new THREE.BoxGeometry(1,1,1),material=new THREE.MeshBasicMaterial({colorWrite:false,depthWrite:false}),mesh=new THREE.InstancedMesh(geometry,material,buildings.length),m=new THREE.Matrix4();
  buildings.forEach((b,i)=>{m.makeScale(b.width,b.height,b.depth);m.setPosition(b.x,b.height/2+.5,-b.y);mesh.setMatrixAt(i,m);});mesh.castShadow=true;mesh.frustumCulled=false;mesh.name='architectural-shadow-masses';parent.add(mesh);return mesh;
}
export function groundHeight(x,z){return landHeight(x,z);}

export function addVegetationShadowProxies(parent,canopies){
  const mesh=new THREE.InstancedMesh(new THREE.SphereGeometry(1,8,5),new THREE.MeshBasicMaterial({colorWrite:false,depthWrite:false}),canopies.length),m=new THREE.Matrix4();
  canopies.forEach((c,i)=>{m.makeScale(c[3],c[4],c[5]);m.setPosition(c[0],c[1],c[2]);mesh.setMatrixAt(i,m);});mesh.castShadow=true;mesh.frustumCulled=false;mesh.name='vegetation-shadow-masses';parent.add(mesh);return mesh;
}
