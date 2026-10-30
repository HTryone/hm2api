/** 纯展示用的格式化工具（无副作用、无请求）。 */

export function text(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

export function number(value: unknown): number | null {
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

export function metric(value: unknown): string {
  const n = number(value)
  if (n === null) return '—'
  return n.toLocaleString('zh-CN')
}

export function bytes(value: unknown): string {
  const n = number(value)
  if (n === null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KiB`
  return `${(n / 1048576).toFixed(1)} MiB`
}

export function when(value: unknown): string {
  const n = number(value)
  if (n === null || n <= 0) return '—'
  return new Date(n * 1000).toLocaleString('zh-CN')
}

export function seconds(value: unknown): string {
  const n = number(value)
  if (n === null) return '—'
  if (n < 120) return `${n} 秒后`
  if (n < 7200) return `${Math.round(n / 60)} 分钟后`
  return `${(n / 3600).toFixed(1)} 小时后`
}

export function percent(value: unknown): string {
  const n = number(value)
  return n === null ? '未知' : `${(n * 100).toFixed(1)}%`
}

export function platformLabel(key: string): string {
  if (key === 'qwenwork') return '千问办公'
  if (key === 'loomy') return '讯飞 Loomy'
  return key
}
