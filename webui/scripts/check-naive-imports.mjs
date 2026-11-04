/**
 * 检查 .vue 里用到的 naive-ui 组件是否都导入了。
 *
 * 漏导入不会报错——Vue 会把 <n-input> 当成原生自定义标签渲染，
 * 页面上元素消失但一片安静。所以在这儿拦一道。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const ROOT = new URL('../src', import.meta.url).pathname

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) out.push(...walk(full))
    else if (full.endsWith('.vue')) out.push(full)
  }
  return out
}

function camel(tag) {
  return 'N' + tag.slice(2).split('-').map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join('')
}

const problems = []
for (const file of walk(ROOT)) {
  const source = readFileSync(file, 'utf-8')
  const script = source.split('</script>')[0]
  const used = [...source.matchAll(/<(n-[a-z-]+)/g)].map((m) => m[1])
  const imported = new Set(script.match(/\b(N[A-Z][A-Za-z0-9]*)\b/g) || [])
  const missing = [...new Set(used)].filter((tag) => !imported.has(camel(tag)))
  if (missing.length) {
    problems.push(`${relative(ROOT, file)} 缺少导入：${missing.join(', ')}`)
  }
}

if (problems.length) {
  console.error('naive-ui 组件导入不完整：')
  for (const item of problems) console.error('  - ' + item)
  process.exit(1)
}
console.log('✅ 所有 .vue 的 naive-ui 组件都已导入')
