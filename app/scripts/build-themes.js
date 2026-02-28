#!/usr/bin/env node
/**
 * build-themes.js
 * 将 public/themes/*.yaml 转换为 src/assets/css/themes.css
 *
 * 用法：
 *   node scripts/build-themes.js
 *
 * Token 命名规则：
 *   YAML 路径  tokens.nav.bg          → CSS 变量  --tb-nav-bg
 *   YAML 路径  tokens.component.tab_bg → CSS 变量  --tb-component-tab-bg
 *   规则：前缀 --tb，层级用 - 分隔，下划线转连字符
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const yaml = require('js-yaml');

const ROOT       = path.resolve(__dirname, '..');
const THEMES_DIR = path.join(ROOT, 'public', 'themes');
const OUTPUT_CSS = path.join(ROOT, 'src', 'assets', 'css', 'themes.css');
const OUTPUT_IDX = path.join(THEMES_DIR, 'index.json');

/**
 * 将嵌套 tokens 对象展平为 { '--tb-nav-bg': '#003153', ... }
 */
function flattenTokens(obj, prefix = '--tb') {
  const result = {};
  for (const [key, value] of Object.entries(obj)) {
    const cssKey = `${prefix}-${key.replace(/_/g, '-')}`;
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      Object.assign(result, flattenTokens(value, cssKey));
    } else {
      result[cssKey] = value;
    }
  }
  return result;
}

/**
 * 生成单个主题的 :root[data-theme="x"] { ... } CSS 块
 */
function buildThemeBlock(themeName, tokens) {
  const flat = flattenTokens(tokens);
  const decls = Object.entries(flat)
    .map(([k, v]) => `  ${k}: ${v};`)
    .join('\n');
  return `:root[data-theme="${themeName}"] {\n${decls}\n}`;
}

function main() {
  const files = fs.readdirSync(THEMES_DIR)
    .filter(f => /\.ya?ml$/.test(f))
    .sort(); // 保持稳定顺序

  if (files.length === 0) {
    console.error('[build-themes] ERROR: No YAML theme files found in', THEMES_DIR);
    process.exit(1);
  }

  const cssBlocks = [];
  const themeIndex = [];

  for (const file of files) {
    const filePath = path.join(THEMES_DIR, file);
    let theme;
    try {
      theme = yaml.load(fs.readFileSync(filePath, 'utf8'));
    } catch (err) {
      console.error(`[build-themes] ERROR parsing ${file}:`, err.message);
      process.exit(1);
    }

    if (!theme || !theme.name || !theme.tokens) {
      console.warn(`[build-themes] WARN: Skipping ${file} (missing 'name' or 'tokens')`);
      continue;
    }

    cssBlocks.push(`/* ── Theme: ${theme.label || theme.name} ── */`);
    cssBlocks.push(buildThemeBlock(theme.name, theme.tokens));
    cssBlocks.push('');

    themeIndex.push({
      name:         theme.name,
      label:        theme.label || theme.name,
      vuetify_dark: !!theme.vuetify_dark,
    });

    console.log(`[build-themes] ✓  ${file}  →  theme "${theme.name}"`);
  }

  // ── 输出 themes.css ──────────────────────────────────────────────────────
  const header = [
    '/**',
    ' * themes.css — AUTO-GENERATED, DO NOT EDIT MANUALLY',
    ' * Source:  public/themes/*.yaml',
    ' * Rebuild: npm run build-themes',
    ` * Generated: ${new Date().toISOString()}`,
    ' */',
    '',
    '',
  ].join('\n');

  fs.mkdirSync(path.dirname(OUTPUT_CSS), { recursive: true });
  fs.writeFileSync(OUTPUT_CSS, header + cssBlocks.join('\n'));
  console.log(`[build-themes] CSS  → ${OUTPUT_CSS}`);

  // ── 输出 index.json ──────────────────────────────────────────────────────
  fs.writeFileSync(OUTPUT_IDX, JSON.stringify(themeIndex, null, 2) + '\n');
  console.log(`[build-themes] JSON → ${OUTPUT_IDX}`);
}

main();
