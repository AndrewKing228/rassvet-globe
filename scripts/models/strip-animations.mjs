// Убирает анимации из glTF: трекер показывает модель статично, а анимации исходника мешают ScenegraphLayer.
// Запуск: node strip-animations.mjs <вход.glb> <выход.glb>
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { prune } from '@gltf-transform/functions';

const [, , input, output] = process.argv;
if (!input || !output) { console.error('Использование: node strip-animations.mjs <вход.glb> <выход.glb>'); process.exit(2); }
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(input);
const anims = doc.getRoot().listAnimations();
for (const a of anims) a.dispose();
await doc.transform(prune());
await io.write(output, doc);
console.log(`анимаций удалено: ${anims.length}; ${output}`);
