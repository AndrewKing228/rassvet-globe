// Модель NASA → части для окна 3D по названиям материалов исходника: каждая часть — узел part:<id> с одним цветом.
// Текстуры, анимации и нормали убраны (страница считает затенение по граням), сетка упрощена, квантование, без Draco.
// Запуск: node parts-by-material.mjs <исходник.glb> <выход.glb> "<id>=<регулярка>;<id>=<регулярка>…" [бюджет треугольников]
// Материалы, не попавшие ни в одно правило, идут в часть body.
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { prune, weld, join, quantize, flatten, dedup, simplifyPrimitive } from '@gltf-transform/functions';
import { MeshoptSimplifier } from 'meshoptimizer';
import draco3d from 'draco3dgltf';
import fs from 'fs';

const [, , input, output, spec = '', budgetArg] = process.argv;
if (!input || !output) { console.error('Использование: node parts-by-material.mjs <исходник.glb> <выход.glb> "<id>=<регулярка>;…" [бюджет]'); process.exit(2); }
const BUDGET = +budgetArg || 40000;
const RULES = spec.split(';').filter(Boolean).map(x => { const i = x.indexOf('='); return [x.slice(0, i), new RegExp(x.slice(i + 1), 'i')]; });
const PALETTE = { body: [0.86, 0.7, 0.36], solar: [0.25, 0.36, 0.66], dish: [0.9, 0.9, 0.9], telescopes: [0.82, 0.83, 0.86], radiator: [0.93, 0.93, 0.9] };

await MeshoptSimplifier.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'draco3d.decoder': await draco3d.createDecoderModule() });
const doc = await io.read(input), root = doc.getRoot();
await doc.transform(flatten());
const scene = root.listScenes()[0];
const partOf = mat => { const name = mat ? mat.getName() : ''; const r = RULES.find(([, re]) => re.test(name)); return r ? r[0] : 'body'; };

// примитивы по частям: каждый примитив — в свой узел внутри part:<id> (с мировой матрицей исходного узла)
const parts = new Map(), colors = new Map();
const nodes = root.listNodes().filter(n => n.getMesh());
for (const n of nodes) {
  const M = n.getWorldMatrix();
  for (const prim of n.getMesh().listPrimitives()) {
    const id = partOf(prim.getMaterial());
    if (!parts.has(id)) { const pn = doc.createNode('part:' + id); scene.addChild(pn); parts.set(id, pn); colors.set(id, []); }
    const m = prim.getMaterial(); if (m && !m.getBaseColorTexture()) colors.get(id).push(m.getBaseColorFactor().slice(0, 3));
    const mesh = doc.createMesh(id).addPrimitive(prim.clone());
    parts.get(id).addChild(doc.createNode().setMesh(mesh).setMatrix(M));
  }
}
for (const n of nodes) n.dispose();
for (const [id, pn] of parts) {
  const cs = colors.get(id), avg = cs.length ? [0, 1, 2].map(k => cs.reduce((s, c) => s + c[k], 0) / cs.length) : null;
  const col = PALETTE[id] || avg || [0.8, 0.8, 0.8];
  const mat = doc.createMaterial(id).setBaseColorFactor([...col, 1]).setMetallicFactor(0).setRoughnessFactor(0.75);
  for (const c of pn.listChildren()) for (const prim of c.getMesh().listPrimitives()) {
    prim.setMaterial(mat);
    for (const sem of prim.listSemantics()) if (sem !== 'POSITION') prim.setAttribute(sem, null);   // нормали и UV не нужны
  }
}
for (const t of root.listTextures()) t.dispose();
for (const a of root.listAnimations()) a.dispose();
await doc.transform(prune(), dedup(), join({ keepNamed: false }), weld());
const prims = root.listMeshes().flatMap(m => m.listPrimitives());
const tris = () => prims.reduce((s, p) => s + (p.getIndices() ? p.getIndices().getCount() : p.getAttribute('POSITION').getCount()) / 3, 0);
const before = tris();
let ratio = Math.min(1, BUDGET / before);
for (let k = 0; k < 6 && tris() > BUDGET; k++) {
  for (const p of prims) simplifyPrimitive(p, { simplifier: MeshoptSimplifier, ratio, error: 0.01 * 2 ** k, lockBorder: false });
  ratio = Math.min(1, BUDGET / tris()) * 0.95;
}
await doc.transform(prune(), weld(), quantize());
for (const e of root.listExtensionsUsed()) if (e.extensionName !== 'KHR_mesh_quantization') e.dispose();
await io.write(output, doc);
console.log(`части: ${[...parts.keys()].join(', ')}; треугольников ${Math.round(before)} → ${Math.round(tris())}; ${fs.statSync(output).size} байт; ${output}`);
