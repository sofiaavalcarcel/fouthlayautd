// Matte del recorte original (116 x 122): conserva el casco y el visor opacos.
// Solo el fondo exterior y el halo se componen con transparencia; no se redibuja
// la ilustración ni se cambia su resolución. Sin librerías ni peticiones de red.

export function removeRobotBackdrop(source, coverage) {
  const { width, height, data } = source;
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 8 || height < 8
      || data.length !== width * height * 4 || coverage.length !== data.length) {
    throw new TypeError("Dimensiones de imagen/máscara de robot inválidas.");
  }
  const output = new Uint8ClampedArray(data.length);
  const clamp = (value) => Math.max(0, Math.min(1, value));
  const smooth = (value) => { const t = clamp(value); return t * t * (3 - 2 * t); };

  for (let y = 0; y < height; y += 1) {
    // Los márgenes no contienen cuerpo; estiman el azul del fondo en cada fila.
    const backdrop = [0, 0, 0];
    let samples = 0;
    for (let sy = Math.max(0, y - 2); sy <= Math.min(height - 1, y + 2); sy += 1) {
      for (const sx of [0, 1, width - 2, width - 1]) {
        const offset = (sy * width + sx) * 4;
        for (let c = 0; c < 3; c += 1) backdrop[c] += data[offset + c];
        samples += 1;
      }
    }
    for (let c = 0; c < 3; c += 1) backdrop[c] /= samples;

    for (let x = 0; x < width; x += 1) {
      const offset = (y * width + x) * 4;
      const protectedAlpha = coverage[offset + 3] / 255;
      // Conserva literalmente cada píxel protegido (incluidos los negros).
      if (protectedAlpha === 1) {
        output.set(data.subarray(offset, offset + 4), offset);
        continue;
      }
      let haloAlpha = 0;
      for (let c = 0; c < 3; c += 1) {
        haloAlpha = Math.max(haloAlpha, (data[offset + c] - backdrop[c]) / (255 - backdrop[c] || 1));
      }
      // Elimina ruido oscuro y desvanece el borde: nunca queda un recuadro.
      haloAlpha = clamp((haloAlpha - 0.018) / 0.982);
      const edge = smooth(Math.min(x, y, width - 1 - x, height - 1 - y) / 3);
      const alpha = protectedAlpha + (1 - protectedAlpha) * haloAlpha * edge;
      output[offset + 3] = Math.round(alpha * data[offset + 3]);
      if (output[offset + 3] === 0) continue;
      for (let c = 0; c < 3; c += 1) {
        output[offset + c] = (data[offset + c] - backdrop[c] * (1 - alpha)) / alpha;
      }
    }
  }
  return output;
}

export function createTransparentRobotArtwork(image) {
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  if (width !== 116 || height !== 122) {
    throw new Error("Este matte corresponde al recorte original de 116 × 122.");
  }
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("Canvas 2D no disponible para el robot.");
  context.drawImage(image, 0, 0);
  const source = context.getImageData(0, 0, width, height);
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#fff";

  // Silueta protegida: casco, interior del visor, orejas y antena originales.
  context.beginPath();
  context.moveTo(17.5, 53);
  context.bezierCurveTo(17.5, 35, 30, 28, 49, 28);
  context.lineTo(66, 28);
  context.bezierCurveTo(85, 28, 95, 38, 95, 54);
  context.lineTo(95, 70);
  context.bezierCurveTo(95, 87, 81, 92, 63, 92);
  context.lineTo(47, 92);
  context.bezierCurveTo(29, 92, 17.5, 82, 17.5, 67);
  context.closePath();
  context.fill();
  for (const [x, y, rx, ry] of [[14, 60, 5.6, 13.8], [98, 60, 5.2, 13.8], [56, 9, 5.4, 5.4]]) {
    context.beginPath();
    context.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
    context.fill();
  }
  context.fillRect(54, 12, 4, 19);
  const coverage = context.getImageData(0, 0, width, height).data;
  const pixels = removeRobotBackdrop(source, coverage);
  context.putImageData(new ImageData(pixels, width, height), 0, 0);
  return canvas.toDataURL("image/png");
}
