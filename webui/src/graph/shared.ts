/**
 * 图谱渲染的共享常量与工具。
 *
 * 数值取自 astrbot_plugin_livingmemory 的 pages/dashboard/graph-shared.js，
 * 按本图规模（节点少、层级固定）做了收敛。
 */
import type { GraphNode } from './types'

export const CFG = {
  NODE_RADIUS_MIN: 6,
  NODE_RADIUS_MAX: 17,
  NODE_RADIUS_BASE: 7,
  NODE_FONT_SIZE: 12,
  NODE_FONT_MAX_SIZE: 18,
  NODE_META_SIZE: 10,
  EDGE_WIDTH_DEFAULT: 0.9,
  EDGE_WIDTH_ACTIVE: 1.3,
  EDGE_WIDTH_HIGHLIGHT: 2,
  EDGE_OPACITY_DEFAULT: 0.26,
  EDGE_OPACITY_ACTIVE: 0.52,
  EDGE_OPACITY_HIGHLIGHT: 0.8,
  PARTICLE_COUNT_DEFAULT: 1,
  PARTICLE_COUNT_ACTIVE: 2,
  PARTICLE_COUNT_HIGHLIGHT: 3,
  PARTICLE_SPEED: 0.12,
  PARTICLE_SIZE: 1.7,
  /* 力导向布局 */
  FORCE_ITERATIONS: 260,
  FORCE_REPULSION: 2400,
  FORCE_LINK_DISTANCE: 152,
  FORCE_LINK_STRENGTH: 0.05,
  FORCE_GRAVITY: 0.014,
  FORCE_DAMPING: 0.84,
  FORCE_MAX_SPEED: 16,
  /* 往种子位置拉的力度，节点不会飘离自己的层 */
  ANCHOR_STRENGTH: 0.042,
  ZOOM_MIN: 0.25,
  ZOOM_MAX: 2.6,
  DPR_MAX: 2,
  HOVER_RADIUS: 12,
} as const

/** 节点配色：网关主色、接入对象青色、API 绿色。 */
export const KIND_COLORS = {
  gateway: '#5b6ef5',
  client: '#2a9e96',
  clientIdle: '#9aa3ad',
  api: '#78a94b',
  apiDown: '#df6d62',
} as const

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v))
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

export function hexToRgba(hex: string, alpha: number): string {
  let v = String(hex || '#000').replace('#', '').trim()
  v = v.length === 3
    ? v
        .split('')
        .map((c) => c + c)
        .join('')
    : v.padEnd(6, '0').slice(0, 6)
  const r = parseInt(v.slice(0, 2), 16)
  const g = parseInt(v.slice(2, 4), 16)
  const b = parseInt(v.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${clamp(alpha, 0, 1)})`
}

/** 节点颜色：不健康 / 不活跃的节点要能一眼看出来。 */
export function nodeColor(node: GraphNode): string {
  if (node.kind === 'gateway') return KIND_COLORS.gateway
  if (node.kind === 'client') {
    return node.active === false ? KIND_COLORS.clientIdle : KIND_COLORS.client
  }
  return node.healthy === false ? KIND_COLORS.apiDown : KIND_COLORS.api
}

/** 节点半径：流量越大越大。 */
export function nodeRadius(node: GraphNode, isHub: boolean): number {
  const weight = clamp(Number(node.weight || 0), 0, 200)
  let r = CFG.NODE_RADIUS_BASE + Math.sqrt(weight) * 0.9
  if (isHub) r = Math.min(CFG.NODE_RADIUS_MAX, r * 1.6)
  return clamp(r, CFG.NODE_RADIUS_MIN, isHub ? CFG.NODE_RADIUS_MAX : CFG.NODE_RADIUS_MAX)
}

export function getPos(e: MouseEvent, el: HTMLElement): { x: number; y: number } {
  const rect = el.getBoundingClientRect()
  return { x: e.clientX - rect.left, y: e.clientY - rect.top }
}
