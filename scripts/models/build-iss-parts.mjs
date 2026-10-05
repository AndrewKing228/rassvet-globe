// МКС по частям для разбора в окне 3D: модель NASA IGOAL «International Space Station (ISS) (D)» →
//   <выход.glb> — общий вид: каждая часть (модуль, сегмент фермы, батареи, эксперимент…) — узел part:<id>
//                 с одним однотонным материалом, без мелких деталей, вся станция ≤ BUDGET треугольников;
//   <каталог>/<id>.glb — подробная версия одной части с деталями (≤ DETAIL_BUDGET), страница грузит её при выборе.
// Текстуры, анимации и нормали убраны (страница считает затенение по граням), сетка упрощена, квантование.
// Без Draco и meshopt — страница обходится без WebAssembly. Координаты у всех файлов общие.
// Запуск: node build-iss-parts.mjs <исходник.glb> <выход.glb> [<каталог подробных частей>]
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { prune, weld, join, quantize, flatten, dedup, simplifyPrimitive, cloneDocument } from '@gltf-transform/functions';
import { MeshoptSimplifier } from 'meshoptimizer';
import draco3d from 'draco3dgltf';
import fs from 'fs';
import path from 'path';

const [, , input, output, detailDir] = process.argv;
if (!input || !output) { console.error('Использование: node build-iss-parts.mjs <исходник.glb> <выход.glb> [<каталог подробных частей>]'); process.exit(2); }
const BUDGET = 48000;          // треугольников на всю станцию (лимит проверки каталога — 50 000)
const DETAIL_BUDGET = 7000;    // на подробную часть
// Мелкие детали (поручни, разъёмы, наклейки…) — тысячи отдельных кусочков; в общем виде их нет, в подробных частях есть.
const DETAIL = /_Details|Handrail|Handhold|Decal|Sticker|Connector|APFR|APRF|Logo|Struts|Trunnion/;

const MOD = [0.88, 0.88, 0.85], TRUSS = [0.7, 0.72, 0.76], SOLAR = [0.78, 0.52, 0.24], PAY = [0.82, 0.74, 0.58];
// Части: правило по имени узла исходника (проверяется сам узел и его предки, первое совпадение) и цвет.
// Порядок важен: эксперименты сидят на платформах и «Кибо», батареи и радиаторы — внутри сегментов фермы.
const PARTS = [
  ['solar-p6', /PORT_BETA_ROT_(2B|4B)/, SOLAR], ['solar-p4', /PORT_BETA_ROT_(2A|4A)/, SOLAR],
  ['solar-s4', /STBD_BETA_ROT_(1A|3A)/, SOLAR], ['solar-s6', /STBD_BETA_ROT_(1B|3B)/, SOLAR],
  ['radiators', /Radiator|TRRJ_GAMMA_ROT/, [0.93, 0.93, 0.9]],
  ['nicer', /NICER/, PAY], ['sage3', /^SAGE_/, PAY], ['tsis', /TSIS/, PAY],
  ['calet', /CALET/, PAY], ['maxi', /MAXI/, PAY], ['gedi', /GEDI/, PAY], ['ecostress', /ECOSTRESS/, PAY], ['oco3', /OCO3/, PAY],
  ['asim', /ASIM/, PAY], ['bartolomeo', /BARTOLOMEO/, PAY], ['ams', /^AMS$/, [0.8, 0.78, 0.7]],
  ['canadarm2', /^SSRMS_Base$/, [0.85, 0.85, 0.8]], ['dextre', /^SPDM_LEE_Base$/, [0.85, 0.85, 0.8]], ['mbs', /^MT_Location$/, [0.75, 0.75, 0.72]],
  ['elc', /^ELC_\d$/, [0.62, 0.66, 0.72]], ['esp', /^ESP\d$/, [0.62, 0.66, 0.72]],
  ['z1', /^Z1$/, TRUSS], ['s0', /^Truss_S0$/, TRUSS], ['s1', /^Truss_S1$/, TRUSS], ['p1', /^Truss_P1$/, TRUSS],
  ['s3', /^Truss_S3$/, TRUSS], ['p3', /^Truss_P3$/, TRUSS], ['s4', /^(Truss_S4|STBD_ALPHA_ROT)$/, TRUSS], ['p4', /^(Truss_P4|PORT_ALPHA_ROT)$/, TRUSS],
  ['s5', /^Truss_S5$/, TRUSS], ['p5', /^Truss_P5$/, TRUSS], ['s6', /^Truss_S6$/, TRUSS], ['p6', /^Truss_P6$/, TRUSS],
  ['zarya', /^Zarya_FGB$/, MOD], ['zvezda', /^Zvezda_SM$/, MOD], ['nauka', /^MLM$/, MOD],
  ['prichal', /^Russian_RSNode_DockingModule$/, MOD], ['rassvet', /^MRM1$/, MOD], ['poisk', /^MRM2$/, MOD],
  ['unity', /^Node1$/, MOD], ['harmony', /^Node2$/, MOD], ['tranquility', /^Node3$/, MOD], ['destiny', /^USLab$/, MOD],
  ['quest', /^Airlock$/, MOD], ['cupola', /^Cupola$/, [0.8, 0.82, 0.86]], ['pma', /^PMA\d$/, [0.84, 0.84, 0.86]],
  ['leonardo', /^PMM$/, MOD], ['beam', /^BEAM$/, [0.88, 0.86, 0.8]], ['bishop', /^Bishop_Airlock$/, MOD],
  ['columbus', /^Columbus$/, MOD], ['kibo-pm', /^JEM_PM$/, MOD], ['kibo-elm', /^JEM_PS$/, MOD], ['kibo-ef', /^JEM_EF$/, [0.75, 0.76, 0.78]],
];
const NO_DETAIL = new Set(['solar-p6', 'solar-p4', 'solar-s4', 'solar-s6', 'radiators']);   // простые формы — подробная версия не нужна

await MeshoptSimplifier.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'draco3d.decoder': await draco3d.createDecoderModule() });
const src = await io.read(input);

// 1. часть и признак «мелкая деталь» для каждого узла с сеткой — в extras, чтобы пережили flatten и клонирование
{
  const root = src.getRoot(), parentOf = new Map();
  for (const n of root.listNodes()) for (const c of n.listChildren()) parentOf.set(c, n);
  const up = n => { const out = []; for (let x = n; x; x = parentOf.get(x)) out.push(x); return out; };
  const skipped = new Map();
  for (const n of root.listNodes()) if (n.getMesh()) {
    const chain = up(n), detail = chain.some(x => DETAIL.test(x.getName()));
    let part = null; for (const x of chain) { const p = PARTS.find(([, re]) => re.test(x.getName())); if (p) { part = p[0]; break; } }
    if (!part) { const top = chain[Math.max(0, chain.length - 2)].getName(); skipped.set(top, (skipped.get(top) || 0) + 1); }
    n.setExtras({ ...n.getExtras(), part, detail });
  }
  if (skipped.size) console.log('без части (удаляются):', [...skipped].map(([k, v]) => `${k}×${v}`).join(', '));
  await src.transform(flatten());
  for (const t of root.listTextures()) t.dispose();
  for (const a of root.listAnimations()) a.dispose();
}

// 2. вариант модели: выбранные части, с деталями или без, упрощение под бюджет
async function variant(ids, withDetails, budget, out) {
  const doc = cloneDocument(src), root = doc.getRoot(), scene = root.listScenes()[0];
  const mats = new Map(), partNodes = new Map();
  for (const [id, , rgb] of PARTS) if (ids.has(id)) {
    mats.set(id, doc.createMaterial(id).setBaseColorFactor([...rgb, 1]).setMetallicFactor(0).setRoughnessFactor(0.75));
    const pn = doc.createNode('part:' + id); scene.addChild(pn); partNodes.set(id, pn);
  }
  for (const n of root.listNodes()) {
    if (!n.getMesh() || n.getName().startsWith('part:')) continue;
    const { part, detail } = n.getExtras() || {};
    if (!ids.has(part) || (detail && !withDetails)) { n.dispose(); continue; }
    for (const prim of n.getMesh().listPrimitives()) {
      prim.setMaterial(mats.get(part));
      // нормали не нужны: швы по нормалям мешают упрощению, а затенение страница считает по граням
      for (const sem of prim.listSemantics()) if (sem !== 'POSITION') prim.setAttribute(sem, null);
    }
    scene.removeChild(n); partNodes.get(part).addChild(n);
  }
  for (const m of root.listMaterials()) if (![...mats.values()].includes(m)) m.dispose();
  await doc.transform(prune(), dedup(), join({ keepNamed: false }), weld());
  const prims = root.listMeshes().flatMap(m => m.listPrimitives());
  const tris = () => prims.reduce((s, p) => s + (p.getIndices() ? p.getIndices().getCount() : p.getAttribute('POSITION').getCount()) / 3, 0);
  const before = tris();
  let ratio = Math.min(1, budget / Math.max(1, before));
  for (let k = 0; k < 6 && tris() > budget; k++) {
    for (const p of prims) simplifyPrimitive(p, { simplifier: MeshoptSimplifier, ratio, error: 0.01 * 2 ** k, lockBorder: false });
    ratio = Math.min(1, budget / tris()) * 0.95;
  }
  await doc.transform(prune(), weld(), quantize());
  // расширения исходника (Draco, WebP-текстуры) в результате не нужны
  for (const e of root.listExtensionsUsed()) if (e.extensionName !== 'KHR_mesh_quantization') e.dispose();
  await io.write(out, doc);
  return [Math.round(before), Math.round(tris()), fs.statSync(out).size];
}

const all = new Set(PARTS.map(p => p[0]));
const [b0, a0, s0] = await variant(all, false, BUDGET, output);
console.log(`общий вид: частей ${all.size}; треугольников ${b0} → ${a0}; ${s0} байт; ${output}`);
if (detailDir) {
  fs.mkdirSync(detailDir, { recursive: true });
  let total = 0;
  for (const id of all) {
    if (NO_DETAIL.has(id)) continue;
    const out = path.join(detailDir, id + '.glb');
    const [b, a, sz] = await variant(new Set([id]), true, DETAIL_BUDGET, out); total += sz;
    console.log(`  ${id}: ${b} → ${a} треугольников, ${sz} байт`);
  }
  console.log(`подробные части: ${total} байт в ${detailDir}`);
}
