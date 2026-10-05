// МКС по частям для разбора в окне 3D: модель NASA IGOAL «International Space Station (ISS) (D)» → models/iss.glb.
// Каждая часть (модуль, ферма, батареи…) — отдельный узел part:<id> с одним однотонным материалом; текстуры и анимации
// убраны, сетка упрощена до бюджета треугольников, квантование. Без Draco и meshopt — страница обходится без WebAssembly.
// Запуск: node build-iss-parts.mjs <исходник.glb> <выход.glb>
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { prune, weld, join, quantize, flatten, dedup, simplifyPrimitive } from '@gltf-transform/functions';
import { MeshoptSimplifier } from 'meshoptimizer';
import draco3d from 'draco3dgltf';

const [, , input, output] = process.argv;
if (!input || !output) { console.error('Использование: node build-iss-parts.mjs <исходник.glb> <выход.glb>'); process.exit(2); }
const BUDGET = 48000;   // треугольников на всю станцию (лимит проверки каталога — 50 000)
// Мелкие детали (поручни, разъёмы, наклейки…) — тысячи отдельных кусочков, которые упрощением не убрать; для разбора по модулям не нужны.
const DETAIL = /_Details|Handrail|Handhold|Decal|Sticker|Connector|APFR|APRF|Logo|Struts|Trunnion/;

// Части: правило по имени узла исходника (проверяется сам узел и его предки, первое совпадение) и цвет.
// Порядок важен: солнечные батареи и радиаторы сидят внутри сегментов фермы.
const PARTS = [
  ['solar', /BETA_ROT/, [0.78, 0.52, 0.24]],
  ['radiators', /Radiator|TRRJ_GAMMA_ROT/, [0.93, 0.93, 0.9]],
  ['mss', /^(SSRMS_Base|MT_Location|SPDM_LEE_Base)$/, [0.85, 0.85, 0.8]],
  ['carriers', /^(ELC_\d|ESP\d)$/, [0.62, 0.66, 0.72]],
  ['truss', /^(Truss_|Z1$|PORT_ALPHA_ROT|STBD_ALPHA_ROT)/, [0.7, 0.72, 0.76]],
  ['zarya', /^Zarya_FGB$/, [0.86, 0.86, 0.82]],
  ['zvezda', /^Zvezda_SM$/, [0.86, 0.86, 0.82]],
  ['nauka', /^MLM$/, [0.86, 0.86, 0.82]],
  ['prichal', /^Russian_RSNode_DockingModule$/, [0.86, 0.86, 0.82]],
  ['rassvet', /^MRM1$/, [0.86, 0.86, 0.82]],
  ['poisk', /^MRM2$/, [0.86, 0.86, 0.82]],
  ['unity', /^Node1$/, [0.9, 0.9, 0.88]],
  ['harmony', /^Node2$/, [0.9, 0.9, 0.88]],
  ['tranquility', /^Node3$/, [0.9, 0.9, 0.88]],
  ['destiny', /^USLab$/, [0.9, 0.9, 0.88]],
  ['quest', /^Airlock$/, [0.9, 0.9, 0.88]],
  ['cupola', /^Cupola$/, [0.8, 0.82, 0.86]],
  ['pma', /^PMA\d$/, [0.84, 0.84, 0.86]],
  ['leonardo', /^PMM$/, [0.9, 0.9, 0.88]],
  ['beam', /^BEAM$/, [0.88, 0.86, 0.8]],
  ['bishop', /^Bishop_Airlock$/, [0.88, 0.88, 0.9]],
  ['columbus', /^Columbus$/, [0.9, 0.9, 0.88]],
  ['kibo', /^JEM_(PM|PS|EF)$/, [0.9, 0.9, 0.88]],
  ['ams', /^AMS$/, [0.8, 0.78, 0.7]],
];

await MeshoptSimplifier.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'draco3d.decoder': await draco3d.createDecoderModule() });
const doc = await io.read(input);
const root = doc.getRoot();

// 1. часть для каждого узла с сеткой — по нему и его предкам
const parentOf = new Map();
for (const n of root.listNodes()) for (const c of n.listChildren()) parentOf.set(c, n);
const isDetail = n => { for (let x = n; x; x = parentOf.get(x)) if (DETAIL.test(x.getName())) return true; return false; };
const partOf = n => { for (let x = n; x; x = parentOf.get(x)) { const p = PARTS.find(([, re]) => re.test(x.getName())); if (p) return p[0]; } return null; };
const assign = new Map(), skipped = new Map();
let details = 0;
for (const n of root.listNodes()) if (n.getMesh()) {
  if (isDetail(n)) { details++; continue; }
  const p = partOf(n);
  if (p) assign.set(n, p); else { const top = (() => { let x = n; while (parentOf.get(x) && parentOf.get(parentOf.get(x))) x = parentOf.get(x); return x.getName(); })(); skipped.set(top, (skipped.get(top) || 0) + 1); }
}
console.log('мелких деталей удалено:', details);
if (skipped.size) console.log('без части (удаляются):', [...skipped].map(([k, v]) => `${k}×${v}`).join(', '));

// 2. мировые координаты, затем узлы частей
await doc.transform(flatten());
const scene = root.listScenes()[0];
const mats = new Map(), partNodes = new Map();
for (const [id, , rgb] of PARTS) {
  mats.set(id, doc.createMaterial(id).setBaseColorFactor([...rgb, 1]).setMetallicFactor(0).setRoughnessFactor(0.75));
  const pn = doc.createNode('part:' + id); scene.addChild(pn); partNodes.set(id, pn);
}
for (const n of root.listNodes()) {
  if (!n.getMesh() || n.getName().startsWith('part:')) continue;
  const id = assign.get(n);
  if (!id) { n.dispose(); continue; }
  for (const prim of n.getMesh().listPrimitives()) {
    prim.setMaterial(mats.get(id));
    // нормали не нужны: швы по нормалям мешают упрощению, а затенение страница считает по граням
    for (const sem of prim.listSemantics()) if (sem !== 'POSITION') prim.setAttribute(sem, null);
  }
  scene.removeChild(n); partNodes.get(id).addChild(n);
}
for (const t of root.listTextures()) t.dispose();
for (const m of root.listMaterials()) if (![...mats.values()].includes(m)) m.dispose();
for (const a of root.listAnimations()) a.dispose();
await doc.transform(prune(), dedup(), join({ keepNamed: false }), weld());

// 3. упрощение: общий коэффициент подбирается под бюджет
const prims = root.listMeshes().flatMap(m => m.listPrimitives());
const tris = () => prims.reduce((s, p) => s + (p.getIndices() ? p.getIndices().getCount() : p.getAttribute('POSITION').getCount()) / 3, 0);
const before = tris();
let ratio = Math.min(1, BUDGET / before);
for (let k = 0; k < 6 && tris() > BUDGET; k++) {
  for (const p of prims) simplifyPrimitive(p, { simplifier: MeshoptSimplifier, ratio, error: 0.01 * 2 ** k, lockBorder: false });
  ratio = Math.min(1, BUDGET / tris()) * 0.95;
}
// Без нормалей: страница рисует части с плоским затенением (SimpleMeshLayer считает нормали по граням) — файл в разы меньше
await doc.transform(prune(), weld(), quantize());
// расширения исходника (Draco, WebP-текстуры) в результате не нужны
for (const e of root.listExtensionsUsed()) if (e.extensionName !== 'KHR_mesh_quantization') e.dispose();

const after = tris();
await io.write(output, doc);
console.log(`частей: ${PARTS.length}; треугольников: ${Math.round(before)} → ${Math.round(after)}; ${output}`);
