import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const root = new URL('../src/modules/bot_leads_deploy/', import.meta.url);
const js = await readFile(new URL('visual.js', root), 'utf8');
const css = await readFile(new URL('visual.css', root), 'utf8');
const bootstrap = await readFile(new URL('../src/renderer/gooey-buttons.js', import.meta.url), 'utf8');

test('Leads Deploy has its own presentation entry and stylesheet', () => {
  assert.match(js, /export function initializeLeadsDeployVisuals/);
  assert.match(js, /leads-deploy-visual-style/);
  assert.match(js, /new URL\("\.\/visual\.css\?v=reference-1", import\.meta\.url\)/);
  assert.doesNotMatch(js + css, /bot_nuevos_productos|#view-bot\b|--np-|\.np-/);
});

test('All CSS rules are scoped to Leads Deploy or its own hidden calendar', () => {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const headers = [...clean.matchAll(/([^{}]+)\{/g)].map(m => m[1].trim());
  for (const header of headers) {
    if (header.startsWith('@media')) continue;
    // Ignore commas inside :is/:has arguments and quoted SVG data URLs.
    const selectors = header.split(/,(?![^()]*\))/).map(s => s.trim());
    for (const selector of selectors) {
      assert.ok(
        selector.startsWith('#view-leads-deploy') ||
        selector.startsWith('body:has(#view-leads-deploy.active)') ||
        selector === '.ldv-header-date',
        `Unscoped selector: ${selector}`,
      );
    }
  }
  assert.match(css, /\.ldv-header-date\s*\{\s*display:\s*none/);
});

test('Presentation has no network, storage, timers or bot configuration changes', () => {
  assert.doesNotMatch(js, /\b(?:fetch|XMLHttpRequest|WebSocket|localStorage|sessionStorage|setInterval|setTimeout)\b/);
  assert.doesNotMatch(js, /\.config\b|\.value\s*=|\.checked\s*=|\.disabled\s*=|\.hidden\s*=|\.files\s*=/);
  assert.doesNotMatch(js, /dispatchEvent|\.click\(|submit\(|runUtel|leadsDeployApi/);
});

test('The original guide is moved, never cloned or rebound', () => {
  assert.match(js, /view\.querySelector\("#leads-deploy-guide"\)/);
  assert.match(js, /guideRow\.append\(guide\)/);
  assert.match(js, /insertBefore\(guideHome\.node, next\)/);
  assert.doesNotMatch(js, /cloneNode|addEventListener/);
});

test('Repeated mount is idempotent and destroy releases observers', () => {
  assert.match(js, /activePresentation\?\.view === view && view\?\.isConnected/);
  assert.match(js, /mountObserver\.disconnect\(\)/);
  assert.match(js, /dateObserver\?\.disconnect\(\)/);
  assert.match(js, /if \(activePresentation === presentation\) activePresentation = null/);
  assert.match(js, /if \(ownsStylesheet\) stylesheet\.remove\(\)/);
});

test('Mutation observer watches mount only, not operational logs', () => {
  assert.match(js, /mountObserver\.observe\(view, \{ childList: true \}\)/);
  assert.doesNotMatch(js, /querySelector\("#leads-deploy-(terminal|error-terminal|run-status|validation|column-mapping)"\)/);
  assert.match(js, /node\.textContent === edit\.replacement/);
});

test('Hidden/disabled controls remain controlled by the existing module', () => {
  assert.match(css, /#view-leads-deploy \[hidden\]\s*\{\s*display: none !important/);
  assert.match(css, /#view-leads-deploy \.bot-internal-field/);
  assert.match(css, /#view-leads-deploy button:disabled/);
  assert.doesNotMatch(css, /#leads-deploy-(?:stop|retry-errors|batch-run)\s*\{[^}]*display:\s*none/);
});

test('Batch actions and long diagnostics retain a responsive layout', () => {
  assert.match(css, /grid-template-areas: "config flow" "diagnostic flow"/);
  assert.match(css, /grid-template-areas: "config" "flow" "diagnostic"/);
  assert.match(css, /\.bot-flow-actions[^{}]*\{[^}]*flex-wrap: wrap/);
  assert.match(css, /overflow-wrap: anywhere/);
  assert.match(css, /prefers-reduced-motion: reduce/);
});

test('Visual startup is independent and failure-tolerant; previous theme remains', () => {
  assert.match(bootstrap, /import\("\.\.\/modules\/bot_leads_deploy\/visual\.js\?v=reference-1"\)[\s\S]*?\.catch/);
  assert.match(bootstrap, /initializeLeadsDeployVisuals\(\)/);
  assert.match(bootstrap, /import\("\.\.\/modules\/bot_nuevos_productos\/visual\.js\?v=reference-1"\)/);
});
