"use strict";
// Native ZIP extraction also works when Node's dependency extractor exits early.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { downloadArtifact } = require('@electron/get');
async function main() {
  const root = path.dirname(require.resolve('electron/package.json'));
  const { version } = require('electron/package.json');
  const zip = await downloadArtifact({ version, artifactName: 'electron', platform: 'win32', arch: process.arch,
    checksums: require(path.join(root, 'checksums.json')) });
  const destination = fs.mkdtempSync(path.join(root, 'extract-'));
  const result = spawnSync('powershell.exe', ['-NoProfile', '-Command',
    "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::ExtractToDirectory($env:UTEL_ELECTRON_ZIP, $env:UTEL_ELECTRON_DEST)"],
    { stdio: 'inherit', env: { ...process.env, UTEL_ELECTRON_ZIP: zip, UTEL_ELECTRON_DEST: destination } });
  if (result.error || result.status !== 0 || !fs.existsSync(path.join(destination, 'electron.exe'))) {
    throw new Error('No se pudo extraer Electron. Vuelva a ejecutar el instalador.');
  }
  const dist = path.join(root, 'dist');
  if (fs.existsSync(dist)) fs.renameSync(dist, path.join(root, `dist-incomplete-${Date.now()}`));
  fs.renameSync(destination, dist);
  fs.writeFileSync(path.join(root, 'path.txt'), 'electron.exe');
  console.log(`Electron ${version}: ejecutable instalado.`);
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
