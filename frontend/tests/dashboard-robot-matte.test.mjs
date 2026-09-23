import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

// Carga un módulo sin dependencias y sin requerir type:module en package.json.
const code = await readFile(new URL('../src/renderer/dashboard-robot-matte.js', import.meta.url), 'utf8');
const { removeRobotBackdrop } = await import(`data:text/javascript,${encodeURIComponent(code)}`);
const width = 116;
const height = 122;
const at = (x, y) => (y * width + x) * 4;
function fixture() {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < data.length; i += 4) data.set([5, 28, 41, 255], i);
  return { width, height, data };
}

test('el fondo plano y los cuatro bordes son transparentes', () => {
  const source = fixture();
  const output = removeRobotBackdrop(source, new Uint8ClampedArray(source.data.length));
  assert.ok(output.every((value) => value === 0));
});

test('el visor negro y los píxeles protegidos no cambian', () => {
  const source = fixture();
  const coverage = new Uint8ClampedArray(source.data.length);
  for (const [x, y, rgba] of [[50, 50, [1, 7, 12, 255]], [56, 9, [79, 147, 155, 255]], [43, 59, [255, 90, 170, 255]]]) {
    const offset = at(x, y);
    source.data.set(rgba, offset);
    coverage[offset + 3] = 255;
  }
  const output = removeRobotBackdrop(source, coverage);
  for (const [x, y] of [[50, 50], [56, 9], [43, 59]]) {
    assert.deepEqual(output.slice(at(x, y), at(x, y) + 4), source.data.slice(at(x, y), at(x, y) + 4));
  }
});

test('el halo permanece semitransparente sin conservar el rectángulo azul', () => {
  const source = fixture();
  source.data.set([25, 170, 185, 255], at(10, 30));
  const output = removeRobotBackdrop(source, new Uint8ClampedArray(source.data.length));
  assert.ok(output[at(10, 30) + 3] > 0);
  assert.ok(output[at(10, 30) + 3] < 255);
  for (const [x, y] of [[0, 0], [115, 0], [0, 121], [115, 121], [0, 60], [115, 60]]) {
    assert.equal(output[at(x, y) + 3], 0);
  }
});

test('no modifica el buffer de origen', () => {
  const source = fixture();
  const before = source.data.slice();
  removeRobotBackdrop(source, new Uint8ClampedArray(source.data.length));
  assert.deepEqual(source.data, before);
});

test('rechaza una máscara que no corresponde a la imagen', () => {
  assert.throws(() => removeRobotBackdrop(fixture(), new Uint8ClampedArray(4)), TypeError);
});
