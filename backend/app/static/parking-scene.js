import * as THREE from "/static/three.module.js";
import { GLTFLoader } from "/static/vendor/loaders/GLTFLoader.js";

const mat = (color, options = {}) => new THREE.MeshStandardMaterial({ color, roughness: .8, metalness: .12, ...options });
const palette = { asphalt: 0x263943, ground: 0x142b31, border: 0x758e83, line: 0xd1e9ca, lime: 0xc9f46e, orange: 0xff9b6e, teal: 0x4cb7be, white: 0xeaf4ee };
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function box(parent, width, height, depth, color, x, y, z, materialOptions = {}) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, height, depth), mat(color, materialOptions));
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}
function quad(parent, corners, material) {
  const geometry = new THREE.BufferGeometry();
  const [a, b, c, d] = corners;
  geometry.setAttribute("position", new THREE.Float32BufferAttribute([...a, ...b, ...c, ...a, ...c, ...d], 3));
  geometry.computeVertexNormals();
  const mesh = new THREE.Mesh(geometry, material);
  parent.add(mesh);
  return mesh;
}
function disc(parent, radius, height, color, x, y, z) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, height, 12), mat(color));
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  parent.add(mesh);
  return mesh;
}
function asphaltTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 512;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#39484b";
  ctx.fillRect(0, 0, 512, 512);
  let seed = 1197;
  for (let i = 0; i < 9000; i++) {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    const x = seed % 512;
    seed = (seed * 1664525 + 1013904223) >>> 0;
    const y = seed % 512;
    const shade = 42 + seed % 45;
    ctx.fillStyle = `rgba(${shade},${shade + 7},${shade + 7},${.12 + seed % 7 / 50})`;
    ctx.fillRect(x, y, 1 + seed % 3, 1 + seed % 3);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(4, 2);
  texture.anisotropy = 4;
  return texture;
}
function label(text, { color = "#e9f5e9", background = "#20343c", width = 256, height = 82, size = 37 } = {}) {
  const canvas = document.createElement("canvas"); canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = background; ctx.beginPath(); ctx.roundRect(2, 2, width - 4, height - 4, 18); ctx.fill();
  ctx.strokeStyle = "#618479"; ctx.lineWidth = 3; ctx.stroke();
  ctx.fillStyle = color; ctx.font = `800 ${size}px system-ui, sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, width / 2, height / 2 + 2);
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
  sprite.scale.set(width / 85, height / 85, 1);
  return sprite;
}
function car(color = 0x71c7dd) {
  const group = new THREE.Group();
  const body = new THREE.Shape();
  body.moveTo(-1.3, .36);
  body.lineTo(-1.27, .69);
  body.lineTo(-1.06, .79);
  body.lineTo(-.62, .81);
  body.lineTo(-.38, 1.14);
  body.lineTo(.47, 1.14);
  body.lineTo(.74, .81);
  body.lineTo(1.13, .76);
  body.lineTo(1.3, .66);
  body.lineTo(1.3, .39);
  body.closePath();
  const shell = new THREE.Mesh(new THREE.ExtrudeGeometry(body, { depth: 1.22, bevelEnabled: true, bevelThickness: .07, bevelSize: .07, bevelSegments: 3, steps: 1 }), mat(color, { metalness: .57, roughness: .25 }));
  shell.position.z = -.61;
  shell.castShadow = true;
  group.add(shell);
  box(group, 2.35, .07, 1.12, 0x1c2c32, 0, .37, 0);
  const glass = mat(0x183c4c, { metalness: .28, roughness: .12, transparent: true, opacity: .94, side: THREE.DoubleSide });
  quad(group, [[.45, 1.28, -.57], [.45, 1.28, .57], [.76, .94, .57], [.76, .94, -.57]], glass);
  quad(group, [[-.65, .94, -.57], [-.65, .94, .57], [-.39, 1.28, .57], [-.39, 1.28, -.57]], glass);
  box(group, .48, .025, .91, 0x254b56, .04, 1.215, 0, { metalness: .45, roughness: .16 });
  box(group, .08, .032, 1.13, color, .47, 1.2, 0);
  box(group, .08, .032, 1.13, color, -.4, 1.2, 0);
  box(group, .46, .016, .025, 0x62797b, .98, .812, 0);
  for (const z of [-.27, .27]) box(group, .025, .016, .33, 0x516b72, 1.02, .816, z);
  for (const side of [-1, 1]) {
    for (const points of [
      [[-.53, .84], [-.31, 1.07], [.02, 1.07], [.02, .84]],
      [[.12, .84], [.12, 1.07], [.42, 1.07], [.61, .84]],
    ]) {
      const shape = new THREE.Shape();
      shape.moveTo(points[0][0], points[0][1]);
      for (const [x, y] of points.slice(1)) shape.lineTo(x, y);
      shape.closePath();
      const windowMesh = new THREE.Mesh(new THREE.ShapeGeometry(shape), glass);
      windowMesh.position.z = side * .69;
      group.add(windowMesh);
    }
    box(group, .18, .1, .28, color, .12, .83, side * .78);
    box(group, .05, .19, .34, 0x27383b, .27, .69, side * .75);
    box(group, 1.83, .025, .025, 0x9db6ae, 0, .62, side * .694);
    for (const x of [-.79, .8]) {
      const tire = new THREE.Mesh(new THREE.CylinderGeometry(.29, .29, .2, 24), mat(0x11191d, { roughness: .96 }));
      tire.rotation.x = Math.PI / 2;
      tire.position.set(x, .3, side * .69);
      tire.castShadow = true;
      group.add(tire);
      const rim = new THREE.Mesh(new THREE.CylinderGeometry(.16, .16, .205, 12), mat(0xb5c3c3, { metalness: .72, roughness: .3 }));
      rim.rotation.x = Math.PI / 2;
      rim.position.set(x, .3, side * .69);
      group.add(rim);
      const hub = new THREE.Mesh(new THREE.CylinderGeometry(.065, .065, .21, 12), mat(0x465c63, { metalness: .65 }));
      hub.rotation.x = Math.PI / 2;
      hub.position.set(x, .3, side * .69);
      group.add(hub);
    }
    box(group, .055, .13, .28, 0xfff0be, 1.33, .59, side * .39, { emissive: 0xffdf8c, emissiveIntensity: 1.1 });
    box(group, .055, .14, .25, 0xf2604f, -1.33, .56, side * .42, { emissive: 0xbb261d, emissiveIntensity: .7 });
  }
  box(group, .035, .2, .48, 0x11222a, 1.35, .5, 0);
  box(group, .04, .16, .42, 0xbfd1ca, -1.35, .5, 0);
  box(group, .42, .07, .06, 0xdce7de, -1.36, .53, 0);
  return group;
}
function tree(parent, x, z) {
  disc(parent, .48, .09, 0x536a54, x, .17, z);
  box(parent, .12, .64, .12, 0x6b6050, x, .5, z);
  const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(.57, 1), mat(0x5c9270, { roughness: 1 }));
  crown.position.set(x, 1.17, z); crown.castShadow = true; parent.add(crown);
  const crown2 = new THREE.Mesh(new THREE.IcosahedronGeometry(.38, 1), mat(0x83b888, { roughness: 1 }));
  crown2.position.set(x + .22, 1.4, z - .09); crown2.castShadow = true; parent.add(crown2);
}
function lamp(parent, x, z) {
  disc(parent, .16, .14, 0x879a9a, x, .27, z);
  box(parent, .095, 2.8, .095, 0x8ca09b, x, 1.65, z);
  box(parent, .65, .13, .28, 0xd5e7d2, x + .26, 3.04, z, { emissive: 0x7a8f5b, emissiveIntensity: .6 });
  const light = new THREE.PointLight(0xcff8b2, 8, 8); light.position.set(x + .2, 2.9, z); parent.add(light);
}
function smooth(t) { return t * t * (3 - 2 * t); }

export async function createParkingScene(container, onSelect, sceneConfig = {}) {
  const loader = new GLTFLoader();
  const [lotResult, carResult] = await Promise.allSettled([
    loader.loadAsync("/static/models/parking-lot.glb"),
    loader.loadAsync("/static/models/sedan.glb"),
  ]);
  const lotTemplate = lotResult.status === "fulfilled" ? lotResult.value.scene : null;
  const carTemplate = carResult.status === "fulfilled" ? carResult.value.scene : null;
  if (lotTemplate) lotTemplate.traverse((item) => { if (item.isMesh) { item.castShadow = true; item.receiveShadow = true; } });
  function createCar(color) {
    if (!carTemplate) return car(color);
    const model = carTemplate.clone(true);
    model.traverse((item) => {
      if (!item.isMesh) return;
      item.castShadow = true;
      item.receiveShadow = true;
      if (item.material?.name === "Vehicle paint") {
        item.material = item.material.clone();
        item.material.color.setHex(color);
      }
    });
    return model;
  }
  const scene = new THREE.Scene(); scene.background = new THREE.Color(0x172a34); scene.fog = new THREE.Fog(0x172a34, 29, 65);
  const camera = new THREE.PerspectiveCamera(38, 1, .1, 100);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.prepend(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xd9f6ea, 0x1a3039, 2.4));
  const sun = new THREE.DirectionalLight(0xfff7d8, 3.1); sun.position.set(-6, 15, 10); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048); sun.shadow.camera.left = -25; sun.shadow.camera.right = 25; sun.shadow.camera.top = 20; sun.shadow.camera.bottom = -20; sun.shadow.bias = -.0005; scene.add(sun);
  const world = new THREE.Group(); scene.add(world);
  let slots = [], signature = "", positions = new Map(), pads = new Map(), labels = new Map(), edges = new Map(), cars = new Map(), barriers = new Map(), motions = new Map(), selectedId = null, cameraMotion = null;
  let width = sceneConfig.width || 17, orbit = .38, distance = 22, height = 14;
  const hardwareGate = new Map();
  const target = new THREE.Vector3();
  const raycaster = new THREE.Raycaster(); const pointer = new THREE.Vector2();

  function cameraPosition() { camera.position.set(target.x + Math.sin(orbit) * distance, height, target.z + Math.cos(orbit) * distance); camera.lookAt(target.x, .3, target.z); }
  function moveCamera(x, z, nextDistance, nextHeight, nextOrbit = orbit) {
    cameraMotion = { start: performance.now(), from: { x: target.x, z: target.z, distance, height, orbit }, to: { x, z, distance: nextDistance, height: nextHeight, orbit: nextOrbit } };
  }
  function resetView() { moveCamera(0, 0, Math.max(23.5, width * 1.3), Math.max(15, width * .8), .38); }
  function focusSlot(slotId) {
    const pos = positions.get(slotId);
    if (!pos) return;
    moveCamera(pos.x, pos.z, 11.5, 8.5);
  }
  function layout(slotList) {
    while (world.children.length) world.remove(world.children[0]);
    for (const motion of motions.values()) motion.resolve();
    pads = new Map(); labels = new Map(); edges = new Map(); positions = new Map(); cars = new Map(); barriers = new Map(); motions = new Map();
    slots = slotList;
    const cols = Math.ceil(slotList.length / 2);
    width = sceneConfig.width || Math.max(17, cols * 3.85 + 6.8);
    const half = width / 2;
    const bayX = (column) => (column - (cols - 1) / 2) * 3.85;
    const modelSlotIds = sceneConfig.asset_slot_ids || [];
    const useAssetLot = Boolean(lotTemplate && sceneConfig.asset === "parking-lot.glb" && modelSlotIds.length === slotList.length && slotList.every((slot) => modelSlotIds.includes(slot.id) && sceneConfig.slots?.[slot.id]));
    if (useAssetLot) world.add(lotTemplate.clone(true));
    else {
      box(world, width + 3, .48, 13.8, palette.ground, 0, -.37, 0);
      box(world, width + 1.2, .12, 10.65, 0xffffff, 0, -.065, 0, { map: asphaltTexture(), roughness: 1, metalness: 0 });
      box(world, width + .8, .025, 3.4, 0x2b434e, 0, .011, 0, { roughness: 1 });
      for (let x = -half + 1; x < half; x += 2.8) box(world, 1.15, .012, .045, 0xe5e8bf, x, .03, 0);
      for (const z of [-5.12, 5.12]) box(world, width + 1.1, .13, .15, palette.border, 0, .035, z);
      for (const z of [-5.65, 5.65]) box(world, width + 1.2, .08, .92, 0x60776d, 0, -.005, z);
      for (const x of [-half + 2.15, half - 2.15]) {
        for (let stripe = -3; stripe <= 3; stripe++) box(world, .13, .014, .28, 0xe0e5d5, x + stripe * .31, .04, 0);
      }
    }
    for (let i = 0; i < slotList.length; i++) {
      const slot = slotList[i], configured = sceneConfig.slots?.[slot.id], row = configured ? Math.sign(configured.position.z) || 1 : i % 2 === 0 ? -1 : 1, column = Math.floor(i / 2), x = configured?.position.x ?? bayX(column), z = configured?.position.z ?? row * 3.48;
      positions.set(slot.id, { x, z, row, heading: configured?.heading ?? (row === -1 ? Math.PI / 2 : -Math.PI / 2), entryRoute: configured?.entry_route, exitRoute: configured?.exit_route });
      const pad = box(world, 3.35, .018, 2.68, slot.occupied ? 0x46505a : 0x3a594c, x, .041, z);
      pad.userData.slotId = slot.id; pads.set(slot.id, pad);
      const edgeColor = slot.occupied ? palette.orange : palette.lime;
      const edge = box(world, 3.4, .045, .065, edgeColor, x, .08, z + row * 1.35); edges.set(slot.id, edge);
      if (!useAssetLot) {
        for (const offset of [-1.68, 1.68]) box(world, .06, .046, 2.75, 0xa9cdb1, x + offset, .08, z);
        box(world, .92, .22, .16, 0x9aac9b, x, .19, z + row * 1.12);
      }
      box(world, .76, .017, .32, 0x6e8d72, x, .076, z - row * .94);
      const marker = label(slot.name, { color: slot.occupied ? "#ffb28a" : "#d7fb9a" }); marker.position.set(x, .75, z - row * 1.76); marker.scale.set(2.3, .73, 1); world.add(marker); labels.set(slot.id, marker);
      const slotNumber = label(String(slot.id).padStart(2, "0"), { width: 112, height: 64, size: 34, color: "#a3c5b1", background: "#29433d" }); slotNumber.position.set(x, .13, z); slotNumber.scale.set(1.15, .65, 1); world.add(slotNumber);
    }
    if (!useAssetLot) {
      for (let x = -half + 1.1; x < half; x += 3.85) { tree(world, x, -6.05); tree(world, x + 1.5, 6.05); }
      lamp(world, -half + 2, -5.9); lamp(world, half - 2, 5.9);
      for (const x of [-half + 1.6, half - 1.6]) for (const z of [-4.9, 4.9]) {
        disc(world, .09, .55, 0xc7dbbb, x, .34, z);
        disc(world, .095, .065, 0xd8e999, x, .64, z);
      }
    }
    // Entry and exit portals sit at the ends of the central driving lane.
    for (const [x, name, color] of [[-half + .55, "ENTRY", palette.lime], [half - .55, "EXIT", palette.orange]]) {
      if (!useAssetLot) {
        box(world, .16, 2.2, .16, color, x, 1.12, -1.8); box(world, .16, 2.2, .16, color, x, 1.12, 1.8);
        box(world, .18, .16, 3.7, color, x, 2.2, 0);
        box(world, .12, .8, .12, 0x718d86, x, .46, -2.3);
        box(world, 1.4, .06, .12, 0xf2f5e6, x + (name === "ENTRY" ? .68 : -.68), .84, -2.3);
      }
      const sign = label(name, { color: name === "ENTRY" ? "#d5fa83" : "#ffb28d", width: 290, height: 80, size: 35 }); sign.position.set(x, 2.85, 0); world.add(sign);
    }
    if (useAssetLot) for (const operation of ["entry", "exit"]) {
      const pivot = world.getObjectByName(`${operation === "entry" ? "Entry" : "Exit"} barrier pivot`);
      if (pivot) barriers.set(operation, pivot);
    }
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(100, 100), mat(0x10242d)); ground.rotation.x = -Math.PI / 2; ground.position.y = -.58; ground.receiveShadow = true; world.add(ground);
    resetView(); syncSlots(slotList);
  }
  function paintSlot(slot) {
    const pad = pads.get(slot.id), marker = labels.get(slot.id), edge = edges.get(slot.id);
    if (!pad) return;
    pad.material.color.setHex(selectedId === slot.id ? 0x768b57 : slot.occupied ? 0x46505a : 0x3a594c);
    if (marker) marker.material.color.setHex(selectedId === slot.id ? 0xffffff : 0xe4f4e7);
    if (edge) edge.material.color.setHex(slot.occupied ? palette.orange : palette.lime);
  }
  function buildRoute(operation, pos, start) {
    const half = width / 2;
    const configured = operation === "entry" ? pos.entryRoute : pos.exitRoute;
    const points = configured ? configured.map((point) => [point.x, point.z]) : operation === "entry"
      ? [[-half + .5, 0], [-half + 1.6, 0], [pos.x - 1.35, 0], [pos.x - .35, pos.row * .55], [pos.x, pos.row * 1.7], [pos.x, pos.z]]
      : [[start?.x ?? pos.x, start?.z ?? pos.z], [pos.x, pos.row * 1.9], [pos.x + .35, pos.row * .8], [pos.x + 1.5, 0], [half - 2, 0], [half - .5, 0]];
    if (start && operation === "exit") points[0] = [start.x, start.z];
    return new THREE.CatmullRomCurve3(points.map(([x, z]) => new THREE.Vector3(x, .08, z)), false, "catmullrom", .45);
  }
  function startMotion(operation, slotId) {
    const pos = positions.get(slotId); if (!pos) return Promise.resolve();
    const interrupted = motions.get(slotId);
    if (interrupted) { motions.delete(slotId); interrupted.resolve(); }
    let model = cars.get(slotId);
    if (operation === "entry" && model) { world.remove(model); cars.delete(slotId); model = null; }
    if (!model) { model = createCar([0x7ac9db, 0xf4a976, 0xc7d6e4, 0xc5e881, 0xbaacd8][slotId % 5]); world.add(model); cars.set(slotId, model); }
    const route = buildRoute(operation, pos, interrupted && operation === "exit" ? model.position : null);
    const parkedYaw = pos.heading;
    const wheels = [];
    model.traverse((item) => { if (item.isGroup && item.name.startsWith("Wheel ")) wheels.push(item); });
    const place = (progress) => {
      const point = route.getPointAt(progress);
      const turn = smooth(THREE.MathUtils.clamp(Math.abs(point.z) / 2.8, 0, 1));
      model.position.copy(point);
      model.rotation.y = parkedYaw * turn;
      return point;
    };
    if (reducedMotion) {
      if (operation === "exit") { world.remove(model); cars.delete(slotId); }
      else place(1);
      return Promise.resolve();
    }
    resetView();
    const first = place(0);
    return new Promise((resolve) => {
      motions.set(slotId, { operation, slotId, model, route, wheels, place, previous: first.clone(), start: performance.now() + 450, duration: THREE.MathUtils.clamp(route.getLength() / 4.2 * 1000, 1900, 4300), resolve });
    });
  }
  function syncSlots(slotList, { animate = true } = {}) {
    if (!slotList?.length) return Promise.resolve();
    const nextSignature = slotList.map((s) => `${s.id}:${s.name}`).join("|");
    if (nextSignature !== signature) { signature = nextSignature; layout(slotList); return Promise.resolve(); }
    const previous = new Map(slots.map((slot) => [slot.id, slot]));
    slots = slotList;
    const started = [];
    for (const slot of slotList) {
      paintSlot(slot);
      const old = previous.get(slot.id);
      const changed = old && (old.occupied !== slot.occupied || (slot.occupied && old.active_session_id !== slot.active_session_id));
      if (animate && changed) {
        started.push(startMotion(slot.occupied ? "entry" : "exit", slot.id));
        continue;
      }
      if (motions.has(slot.id)) continue;
      const existing = cars.get(slot.id);
      if (slot.occupied && !existing) {
        const model = createCar([0x7ac9db, 0xf4a976, 0xc7d6e4, 0xc5e881, 0xbaacd8][slot.id % 5]);
        const pos = positions.get(slot.id); model.position.set(pos.x, .08, pos.z); model.rotation.y = pos.heading;
        world.add(model); cars.set(slot.id, model);
      } else if (!slot.occupied && existing) { world.remove(existing); cars.delete(slot.id); }
    }
    return Promise.all(started);
  }
  function selectSlot(slotId) { selectedId = slotId; for (const slot of slots) paintSlot(slot); }
  function tick(now) {
    requestAnimationFrame(tick);
    if (cameraMotion) {
      const t = smooth(Math.min(1, (now - cameraMotion.start) / 850));
      target.x = THREE.MathUtils.lerp(cameraMotion.from.x, cameraMotion.to.x, t);
      target.z = THREE.MathUtils.lerp(cameraMotion.from.z, cameraMotion.to.z, t);
      distance = THREE.MathUtils.lerp(cameraMotion.from.distance, cameraMotion.to.distance, t);
      height = THREE.MathUtils.lerp(cameraMotion.from.height, cameraMotion.to.height, t);
      orbit = THREE.MathUtils.lerp(cameraMotion.from.orbit, cameraMotion.to.orbit, t);
      cameraPosition();
      if (t === 1) cameraMotion = null;
    }
    for (const [operation, barrier] of barriers) {
      let openness = 0;
      for (const motion of motions.values()) {
        if (motion.operation !== operation) continue;
        const elapsed = now - motion.start;
        const progress = THREE.MathUtils.clamp(elapsed / motion.duration, 0, 1);
        const amount = operation === "entry"
          ? (elapsed < 0 ? smooth(THREE.MathUtils.clamp((elapsed + 450) / 350, 0, 1)) : 1 - smooth(THREE.MathUtils.clamp((progress - .18) / .16, 0, 1)))
          : smooth(THREE.MathUtils.clamp((progress - .68) / .14, 0, 1));
        openness = Math.max(openness, amount);
      }
      if (hardwareGate.has(operation)) openness = hardwareGate.get(operation) ? 1 : 0;
      barrier.rotation.x += (-openness * 1.12 - barrier.rotation.x) * .14;
    }
    for (const [slotId, motion] of motions) {
      const progress = THREE.MathUtils.clamp((now - motion.start) / motion.duration, 0, 1);
      const point = motion.place(smooth(progress));
      const travelled = point.distanceTo(motion.previous);
      const direction = motion.operation === "exit" && Math.abs(point.z) > 1.4 ? -1 : 1;
      for (const wheel of motion.wheels) wheel.rotation.z -= direction * travelled / .28;
      motion.previous.copy(point);
      const pad = pads.get(slotId);
      if (pad) { pad.material.emissive.setHex(motion.operation === "entry" ? palette.lime : palette.orange); pad.material.emissiveIntensity = .12 + .35 * Math.sin(progress * Math.PI); }
      if (progress === 1) {
        if (motion.operation === "exit") { world.remove(motion.model); cars.delete(slotId); }
        if (pad) pad.material.emissiveIntensity = 0;
        motions.delete(slotId);
        syncSlots(slots, { animate: false });
        motion.resolve();
      }
    }
    renderer.render(scene, camera);
  }
  const resize = new ResizeObserver(() => { const rect = container.getBoundingClientRect(); if (!rect.width || !rect.height) return; camera.aspect = rect.width / rect.height; camera.updateProjectionMatrix(); renderer.setSize(rect.width, rect.height, false); }); resize.observe(container);
  let drag = null;
  renderer.domElement.addEventListener("pointerdown", (event) => { drag = { x: event.clientX, y: event.clientY, orbit, moved: false }; renderer.domElement.setPointerCapture(event.pointerId); });
  renderer.domElement.addEventListener("pointermove", (event) => { if (!drag) return; const dx = event.clientX - drag.x, dy = event.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true; if (drag.moved) { cameraMotion = null; orbit = drag.orbit - dx * .006; height = THREE.MathUtils.clamp(height + dy * .03, 8, 27); cameraPosition(); } });
  renderer.domElement.addEventListener("pointerup", (event) => {
    if (!drag) return;
    if (!drag.moved) { const rect = renderer.domElement.getBoundingClientRect(); pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1); raycaster.setFromCamera(pointer, camera); const hits = raycaster.intersectObjects([...pads.values()]); if (hits.length) onSelect(hits[0].object.userData.slotId); }
    drag = null;
  });
  renderer.domElement.addEventListener("wheel", (event) => { event.preventDefault(); cameraMotion = null; distance = THREE.MathUtils.clamp(distance + Math.sign(event.deltaY) * 1.2, 12, 45); cameraPosition(); }, { passive: false });
  resetView(); requestAnimationFrame(tick);
  function animateEvent(operation, slotId) { return startMotion(operation, slotId); }
  function setGate(operation, opened) { if (opened === null) hardwareGate.delete(operation); else hardwareGate.set(operation, opened); }
  return { syncSlots, selectSlot, resetView, focusSlot, animateEvent, setGate };
}
