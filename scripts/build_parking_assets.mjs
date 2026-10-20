import fs from 'node:fs/promises';
import path from 'node:path';
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';

// GLTFExporter uses the browser FileReader API, including for buffer-only models.
globalThis.FileReader ??= class {
  result = null;
  onloadend = null;
  async readAsArrayBuffer(blob) {
    this.result = await blob.arrayBuffer();
    this.onloadend?.();
  }
  async readAsDataURL(blob) {
    const data = Buffer.from(await blob.arrayBuffer()).toString('base64');
    this.result = `data:${blob.type};base64,${data}`;
    this.onloadend?.();
  }
};

const material = (name, color, metalness = 0, roughness = .8, options = {}) => {
  const value = new THREE.MeshStandardMaterial({ color, metalness, roughness, ...options });
  value.name = name;
  return value;
};
const concrete = material('Warm concrete', 0x9ba9a5, 0, .92);
const asphalt = material('Asphalt', 0x303d42, 0, 1);
const asphaltLight = material('Parking bay asphalt', 0x3b4b4e, 0, 1);
const marking = material('Ivory road paint', 0xe3ead9, 0, .9);
const lime = material('Lime guidance paint', 0xbce36d, 0, .9);
const steel = material('Brushed steel', 0xa7b9b4, .65, .35);
const charcoal = material('Powder coated charcoal', 0x24343a, .35, .62);
const brick = material('Sandstone', 0x6d877b, 0, .93);
const foliage = [material('Leaf deep', 0x326f55, 0, 1), material('Leaf light', 0x65a27d, 0, 1), material('Leaf highlight', 0x80ae87, 0, 1)];
const wood = material('Tree bark', 0x6c6451, 0, 1);
const lampGlow = material('Lamp diffuser', 0xfff1c3, 0, .4, { emissive: 0xffdeb0, emissiveIntensity: .7 });

function mesh(parent, name, geometry, surface, x = 0, y = 0, z = 0) {
  const item = new THREE.Mesh(geometry, surface);
  item.name = name;
  item.position.set(x, y, z);
  item.castShadow = true;
  item.receiveShadow = true;
  parent.add(item);
  return item;
}
function box(parent, name, size, at, surface, radius = 0) {
  const geometry = radius ? new RoundedBoxGeometry(...size, 3, radius) : new THREE.BoxGeometry(...size);
  return mesh(parent, name, geometry, surface, ...at);
}
function cylinder(parent, name, radius, height, at, surface, sides = 20) {
  return mesh(parent, name, new THREE.CylinderGeometry(radius, radius, height, sides), surface, ...at);
}
function pane(parent, name, points, surface) {
  const shape = new THREE.BufferGeometry();
  const [a, b, c, d] = points;
  shape.setAttribute('position', new THREE.Float32BufferAttribute([...a, ...b, ...c, ...a, ...c, ...d], 3));
  shape.computeVertexNormals();
  return mesh(parent, name, shape, surface);
}

function buildVehicle() {
  const car = new THREE.Group(); car.name = 'Parkflow sedan · forward +X';
  const paint = material('Vehicle paint', 0xbfd8e1, .55, .24);
  const dark = material('Trim and grille', 0x17232b, .12, .72);
  const glass = material('Tinted glass', 0x234b5a, .34, .12, { side: THREE.DoubleSide });
  const tire = material('Rubber tires', 0x11191c, 0, .96);
  const rim = material('Machined wheels', 0xb5c8c8, .75, .28);
  const lamp = material('Headlights', 0xf4edce, .2, .3, { emissive: 0xffe5a3, emissiveIntensity: .8 });
  const brake = material('Tail lights', 0xd9443b, .1, .35, { emissive: 0x93231e, emissiveIntensity: .75 });
  box(car, 'Rounded lower body', [2.66, .43, 1.26], [0, .52, 0], paint, .1);
  box(car, 'Lower dark sill', [2.42, .13, 1.2], [0, .34, 0], dark, .035);
  const profile = new THREE.Shape();
  profile.moveTo(-1.23, .62);
  profile.lineTo(-1.04, .83);
  profile.lineTo(-.65, .85);
  profile.lineTo(-.36, 1.23);
  profile.quadraticCurveTo(-.29, 1.29, -.19, 1.3);
  profile.lineTo(.35, 1.3);
  profile.quadraticCurveTo(.45, 1.29, .5, 1.22);
  profile.lineTo(.79, .85);
  profile.lineTo(1.18, .8);
  profile.lineTo(1.3, .65);
  profile.closePath();
  const cabin = new THREE.ExtrudeGeometry(profile, { depth: 1.08, bevelEnabled: true, bevelThickness: .045, bevelSize: .045, bevelSegments: 4, curveSegments: 12 });
  mesh(car, 'Sculpted roof and hood', cabin, paint, 0, 0, -.54);
  pane(car, 'Front windshield', [[.5, 1.32, -.49], [.5, 1.32, .49], [.8, .91, .49], [.8, .91, -.49]], glass);
  pane(car, 'Rear windshield', [[-.68, .91, -.49], [-.68, .91, .49], [-.38, 1.32, .49], [-.38, 1.32, -.49]], glass);
  box(car, 'Panoramic roof glass', [.54, .018, .94], [.03, 1.34, 0], glass, .008);
  for (const side of [-1, 1]) {
    const z = side * .595;
    pane(car, `Rear side window ${side}`, [[-.57, .91, z], [-.29, 1.25, z], [-.01, 1.25, z], [-.01, .91, z]], glass);
    pane(car, `Front side window ${side}`, [[.07, .91, z], [.07, 1.25, z], [.39, 1.25, z], [.64, .91, z]], glass);
    box(car, `Side mirror ${side}`, [.23, .11, .24], [.38, .89, side * .7], paint, .03);
    box(car, `Door handle ${side}`, [.23, .025, .02], [-.12, .76, side * .648], steel, .008);
    box(car, `Lower side trim ${side}`, [1.98, .035, .025], [0, .49, side * .635], steel, .008);
    for (const x of [-.82, .82]) {
      const wheel = new THREE.Group(); wheel.name = `Wheel ${x} ${side}`;
      wheel.position.set(x, .3, side * .67);
      const rubber = cylinder(wheel, 'Tire', .28, .19, [0, 0, 0], tire, 32); rubber.rotation.x = Math.PI / 2;
      const alloy = cylinder(wheel, 'Alloy rim', .165, .205, [0, 0, side * .006], rim, 20); alloy.rotation.x = Math.PI / 2;
      for (let spoke = 0; spoke < 5; spoke++) {
        const angle = spoke * Math.PI * 2 / 5;
        const piece = box(wheel, `Spoke ${spoke}`, [.035, .12, .012], [Math.sin(angle) * .07, Math.cos(angle) * .07, side * .114], steel, .008);
        piece.rotation.z = -angle;
      }
      cylinder(wheel, 'Wheel hub', .045, .22, [0, 0, side * .006], dark, 16).rotation.x = Math.PI / 2;
      car.add(wheel);
    }
    box(car, `Headlight ${side}`, [.055, .16, .27], [1.335, .64, side * .43], lamp, .018);
    box(car, `Tail light ${side}`, [.055, .14, .28], [-1.335, .62, side * .43], brake, .018);
  }
  box(car, 'Front grille', [.03, .16, .52], [1.35, .53, 0], dark, .008);
  box(car, 'Rear license plate', [.035, .13, .42], [-1.35, .52, 0], marking, .008);
  box(car, 'Front plate', [.035, .11, .42], [1.36, .44, 0], marking, .008);
  return car;
}

function tree(parent, x, z, index) {
  const tree = new THREE.Group(); tree.name = `Landscape tree ${index}`; tree.position.set(x, 0, z); parent.add(tree);
  cylinder(tree, 'Circular planter', .49, .17, [0, .11, 0], concrete, 20);
  cylinder(tree, 'Soil', .42, .025, [0, .205, 0], brick, 20);
  cylinder(tree, 'Trunk', .1, .9, [0, .67, 0], wood, 12);
  for (const [offset, radius, shade] of [[[0, 1.48, 0], .63, 0], [[-.23, 1.73, .12], .44, 1], [[.29, 1.72, -.15], .47, 2]]) {
    const crown = mesh(tree, 'Leaf crown', new THREE.IcosahedronGeometry(radius, 2), foliage[shade], ...offset);
    crown.scale.y = 1.12;
  }
}
function postLight(parent, x, z) {
  cylinder(parent, 'Light pole footing', .18, .2, [x, .2, z], concrete);
  cylinder(parent, 'Street lamp pole', .065, 3.2, [x, 1.86, z], steel, 12);
  box(parent, 'Lamp arm', [.78, .08, .1], [x + .34, 3.43, z], steel, .025);
  box(parent, 'Lamp luminous panel', [.62, .04, .27], [x + .48, 3.37, z], lampGlow, .02);
}
function buildLot() {
  const lot = new THREE.Group(); lot.name = 'Parkflow five-space parking lot';
  const width = 18.35, half = width / 2;
  box(lot, 'Concrete site foundation', [width + 3, .42, 14], [0, -.37, 0], concrete, .12);
  box(lot, 'Asphalt driving surface', [width + 1.2, .11, 10.7], [0, -.06, 0], asphalt, .04);
  box(lot, 'Central driving lane', [width + .8, .018, 3.5], [0, .006, 0], asphaltLight);
  for (const z of [-5.7, 5.7]) {
    box(lot, `Raised pedestrian pavement ${z}`, [width + 1.3, .16, .98], [0, .045, z], concrete, .04);
    box(lot, `Pavement edge ${z}`, [width + 1.1, .16, .12], [0, .06, z - Math.sign(z) * .48], steel);
  }
  for (let x = -half + 1.1; x < half; x += 2.85) box(lot, `Lane dash ${x.toFixed(1)}`, [1.24, .013, .065], [x, .025, 0], marking);
  for (const gateX of [-half + 2.15, half - 2.15]) {
    for (let stripe = -3; stripe <= 3; stripe++) box(lot, `Crosswalk stripe ${gateX} ${stripe}`, [.18, .016, .34], [gateX + stripe * .31, .03, 0], marking);
  }
  const columns = 3;
  for (let i = 0; i < 5; i++) {
    const row = i % 2 === 0 ? -1 : 1;
    const column = Math.floor(i / 2);
    const x = (column - (columns - 1) / 2) * 3.85;
    const z = row * 3.48;
    box(lot, `Bay surface ${i + 1}`, [3.34, .015, 2.65], [x, .017, z], asphaltLight);
    for (const offset of [-1.68, 1.68]) box(lot, `Bay boundary ${i + 1}`, [.065, .019, 2.7], [x + offset, .035, z], marking);
    box(lot, `Bay back line ${i + 1}`, [3.42, .02, .07], [x, .036, z + row * 1.34], marking);
    box(lot, `Concrete wheel stop ${i + 1}`, [1, .23, .18], [x, .155, z + row * 1.1], concrete, .035);
  }
  for (let x = -half + 1.2, index = 0; x < half; x += 3.85, index++) {
    tree(lot, x, -6.08, index);
    tree(lot, x + 1.5, 6.08, index + 10);
  }
  postLight(lot, -half + 2, -5.85); postLight(lot, half - 2, 5.85);
  for (const [x, name, accent] of [[-half + .55, 'Entry', lime], [half - .55, 'Exit', material('Exit amber', 0xffa470, .1, .4)]]) {
    for (const z of [-1.82, 1.82]) {
      box(lot, `${name} portal post`, [.2, 2.3, .2], [x, 1.15, z], charcoal, .035);
      box(lot, `${name} portal accent`, [.04, 2.06, .07], [x + .105, 1.17, z], accent);
    }
    box(lot, `${name} portal beam`, [.2, .24, 3.84], [x, 2.3, 0], charcoal, .035);
    box(lot, `${name} portal light`, [.03, .07, 3.35], [x + .11, 2.34, 0], accent);
    cylinder(lot, `${name} barrier post`, .1, 1, [x, .53, -2.35], steel);
    const barrier = new THREE.Group(); barrier.name = `${name} barrier pivot`;
    barrier.position.set(x, 1.04, -2.35); lot.add(barrier);
    box(barrier, `${name} barrier arm`, [.12, .1, 3.7], [0, 0, 1.85], marking, .018);
    for (const offset of [.5, 1.4, 2.3, 3.2])
      box(barrier, `${name} barrier stripe`, [.125, .105, .28], [0, .004, offset], accent, .015);
  }
  // These structures make the model legible as a staffed parking facility.
  box(lot, 'Entry control kiosk', [1.18, 1.55, 1.3], [-half + 1.2, .77, -6.65], brick, .06);
  box(lot, 'Kiosk glazing', [.7, .56, .025], [-half + 1.2, 1.07, -5.98], material('Kiosk glass', 0x386473, .3, .22));
  box(lot, 'Kiosk roof', [1.42, .17, 1.52], [-half + 1.2, 1.61, -6.65], charcoal, .06);
  box(lot, 'EV charger', [.55, 1.36, .38], [3.85, .69, -6.08], charcoal, .08);
  box(lot, 'EV charger light', [.43, .26, .02], [3.85, 1.03, -5.86], lime, .02);
  for (const z of [-4.9, 4.9]) for (const x of [-half + 1.6, half - 1.6]) {
    cylinder(lot, 'Safety bollard', .1, .7, [x, .36, z], steel, 12);
    cylinder(lot, 'Bollard reflective cap', .102, .06, [x, .73, z], lime, 12);
  }
  return lot;
}

const destination = path.resolve('backend/app/static/models');
await fs.mkdir(destination, { recursive: true });
const exporter = new GLTFExporter();
for (const [name, object] of [['sedan', buildVehicle()], ['parking-lot', buildLot()]]) {
  const result = await exporter.parseAsync(object, { binary: true, onlyVisible: true, includeCustomExtensions: true });
  const file = path.join(destination, `${name}.glb`);
  await fs.writeFile(file, Buffer.from(result));
  console.log(`${file}: ${(result.byteLength / 1024).toFixed(1)} KiB`);
}
