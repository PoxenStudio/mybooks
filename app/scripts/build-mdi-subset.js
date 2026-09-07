// 生成只含项目实际用到的图标的 MDI 字体子集。
//
// 背景：@mdi/font 的完整 woff2 有 370+KB，但本项目模板里只用了约 250 个图标名
// （`<v-icon>mdi-xxx</v-icon>` 这类写法）。字体是按 CSS content 字符渲染的，
// 所以浏览器一旦遇到任意一个 mdi- 图标类名就要整份下载完整字体。
// 本脚本扫描 src 下所有用到的 mdi-xxx 图标名，用 harfbuzz（subset-font，纯
// WASM，无需装 python/fonttools）从官方 ttf 里抠出对应字形，生成一份小得多的
// 子集 woff2 + 对应的精简 CSS。
//
// 通过 nuxt.config.js 的 build:before 钩子在每次 `nuxt dev`/`build`/`generate`
// 启动时自动执行一遍（见 nuxt.config.js），不需要手动记得跑；也可以单独执行：
//     npm run icons:subset
//
// 产物（会被覆盖，不要手改）：
//     src/assets/fonts/materialdesignicons-subset.woff2
//     src/assets/css/mdi-subset.css
//
// 新增图标后如果没跑 build/dev，字体里就不会有对应字形——但 hook 会在下次
// build/dev 启动时自动补上，无需手工干预。

const fs = require('fs')
const path = require('path')
const subsetFont = require('subset-font')

const APP_DIR = path.resolve(__dirname, '..')
const SRC_DIR = path.join(APP_DIR, 'src')

const ICON_NAME_RE = /\bmdi-[a-zA-Z0-9-]+\b/g
// CSS 转义 "\F01C9" 里 F 是十六进制码点的一部分（不是分隔符），要整段一起捕获。
const CSS_RULE_RE = /\.mdi-([a-z0-9-]+)::before\s*\{\s*content:\s*"\\(F[0-9A-Fa-f]+)"/g

// Vuetify 内置组件（v-select 展开箭头、v-checkbox/v-radio、v-rating、v-pagination、
// v-data-table 排序箭头、v-alert/v-snackbar 关闭按钮等）在没有被业务代码显式覆盖时，
// 会用它自带的 mdi 预设图标（vuetify/lib/services/icons/presets/mdi.js）。
// 这些名字不会出现在我们自己的 .vue 源码里，必须手动补进子集，否则组件内置图标会消失。
const VUETIFY_BUILTIN_ICONS = [
  'check', 'close-circle', 'close', 'check-circle', 'information',
  'exclamation', 'alert', 'chevron-left', 'chevron-right',
  'checkbox-marked', 'checkbox-blank-outline', 'minus-box', 'circle',
  'arrow-up', 'chevron-down', 'menu', 'menu-down', 'radiobox-marked',
  'radiobox-blank', 'pencil', 'star-outline', 'star', 'star-half-full',
  'cached', 'page-first', 'page-last', 'unfold-more-horizontal',
  'paperclip', 'plus', 'minus',
]

function resolveMdiFontPaths() {
  const pnpmDirs = fs.existsSync(path.join(APP_DIR, 'node_modules/.pnpm')) ? fs.readdirSync(path.join(APP_DIR, 'node_modules/.pnpm')) : []
  const mdiFontDir = pnpmDirs.find((name) => name.startsWith('@mdi+font@'))
  const base = mdiFontDir
    ? path.join(APP_DIR, 'node_modules/.pnpm', mdiFontDir, 'node_modules/@mdi/font')
    : path.join(APP_DIR, 'node_modules/@mdi/font')
  const cssPath = path.join(base, 'css/materialdesignicons.css')
  const ttfPath = path.join(base, 'fonts/materialdesignicons-webfont.ttf')
  if (!fs.existsSync(cssPath) || !fs.existsSync(ttfPath)) {
    throw new Error('找不到 @mdi/font，请先 npm/pnpm install')
  }
  return { cssPath, ttfPath }
}

function findUsedIconNames() {
  const names = new Set()
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        walk(full)
      } else if (/\.(vue|js)$/.test(entry.name)) {
        const text = fs.readFileSync(full, 'utf8')
        for (const m of text.matchAll(ICON_NAME_RE)) {
          names.add(m[0].slice('mdi-'.length))
        }
      }
    }
  }
  walk(SRC_DIR)
  return names
}

function loadCodepoints(cssPath) {
  const css = fs.readFileSync(cssPath, 'utf8')
  const mapping = new Map()
  for (const m of css.matchAll(CSS_RULE_RE)) {
    mapping.set(m[1], m[2].toUpperCase())
  }
  return mapping
}

async function buildMdiSubset() {
  const { cssPath, ttfPath } = resolveMdiFontPaths()

  const used = new Set([...findUsedIconNames(), ...VUETIFY_BUILTIN_ICONS])
  if (used.size === 0) {
    throw new Error('没在 src 下扫到任何 mdi- 图标，检查 SRC_DIR 是否正确')
  }

  const codepoints = loadCodepoints(cssPath)
  const missing = [...used].filter((n) => !codepoints.has(n)).sort()
  if (missing.length > 0) {
    console.warn('[mdi-subset] 以下图标名在 @mdi/font 里找不到对应字形，已跳过（检查是否拼写错误）：')
    for (const n of missing) console.warn(`  mdi-${n}`)
  }

  const resolved = new Map([...used].filter((n) => codepoints.has(n)).map((n) => [n, codepoints.get(n)]))
  if (resolved.size === 0) {
    throw new Error('没有任何图标能解析到字形，中止')
  }

  const text = [...new Set(resolved.values())].map((cp) => String.fromCodePoint(parseInt(cp, 16))).join('')

  const ttfBuffer = fs.readFileSync(ttfPath)
  const subsetBuffer = await subsetFont(ttfBuffer, text, {
    targetFormat: 'woff2',
    noLayoutClosure: true,
  })

  const outFontDir = path.join(SRC_DIR, 'assets/fonts')
  const outCssDir = path.join(SRC_DIR, 'assets/css')
  fs.mkdirSync(outFontDir, { recursive: true })
  fs.mkdirSync(outCssDir, { recursive: true })

  const outFontPath = path.join(outFontDir, 'materialdesignicons-subset.woff2')
  fs.writeFileSync(outFontPath, subsetBuffer)

  const cssLines = [
    '/* 由 scripts/build-mdi-subset.js 自动生成，不要手改；nuxt dev/build 会自动重新生成 */',
    '@font-face {',
    '  font-family: "Material Design Icons";',
    '  src: url("~assets/fonts/materialdesignicons-subset.woff2") format("woff2");',
    '  font-weight: normal;',
    '  font-style: normal;',
    '  font-display: block;',
    '}',
    '',
    '.mdi:before,',
    '.mdi-set {',
    '  display: inline-block;',
    '  font: normal normal normal 24px/1 "Material Design Icons";',
    '  font-size: inherit;',
    '  text-rendering: auto;',
    '  line-height: inherit;',
    '  -webkit-font-smoothing: antialiased;',
    '  -moz-osx-font-smoothing: grayscale;',
    '}',
    '',
  ]
  for (const name of [...resolved.keys()].sort()) {
    cssLines.push(`.mdi-${name}::before {`)
    cssLines.push(`  content: "\\${resolved.get(name)}";`)
    cssLines.push('}')
    cssLines.push('')
  }
  const outCssPath = path.join(outCssDir, 'mdi-subset.css')
  fs.writeFileSync(outCssPath, cssLines.join('\n'))

  const stats = {
    used: used.size,
    resolved: resolved.size,
    fontSizeKb: subsetBuffer.length / 1024,
    outFontPath,
    outCssPath,
  }
  console.log(`[mdi-subset] 用到的图标：${stats.used} 个，解析成功：${stats.resolved} 个`)
  console.log(`[mdi-subset] 子集字体：${path.relative(APP_DIR, outFontPath)} (${stats.fontSizeKb.toFixed(1)} KB)`)
  return stats
}

module.exports = buildMdiSubset

if (require.main === module) {
  buildMdiSubset().catch((err) => {
    console.error(err)
    process.exit(1)
  })
}
