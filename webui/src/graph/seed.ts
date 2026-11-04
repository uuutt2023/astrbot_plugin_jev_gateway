/**
 * 拓扑种子位置。
 *
 * 参考 astrbot_plugin_livingmemory 的 graph-topology.js：那边是社区发现后
 * 用黄金角螺旋摆放，这里拓扑是已知的（接入对象 → 网关 → API 入口），
 * 直接按层摆：网关居中，接入对象在左列，API 入口在右列。
 */
import type { GraphEdge, GraphNode } from './types'

export interface Seed {
  positions: Record<string, { x: number; y: number }>
  /** 每个节点的层：0 接入对象 / 1 网关 / 2 API */
  layers: Record<string, number>
}

const COLUMN_X = 178
const ROW_GAP = 94

export function buildSeed(nodes: GraphNode[], _edges: GraphEdge[]): Seed {
  const positions: Record<string, { x: number; y: number }> = {}
  const layers: Record<string, number> = {}

  const clients = nodes.filter((n) => n.kind === 'client')
  const apis = nodes.filter((n) => n.kind === 'api')
  const hubs = nodes.filter((n) => n.kind === 'gateway')

  hubs.forEach((hub) => {
    positions[hub.id] = { x: 0, y: 0 }
    layers[hub.id] = 1
  })

  const place = (list: GraphNode[], x: number, layer: number) => {
    const mid = (list.length - 1) / 2
    list.forEach((node, index) => {
      positions[node.id] = { x, y: (index - mid) * ROW_GAP }
      layers[node.id] = layer
    })
  }

  place(clients, -COLUMN_X, 0)
  place(apis, COLUMN_X, 2)

  // 没被归类的节点（比如将来加的新类型）放到网关下方
  const known = new Set([...clients, ...apis, ...hubs].map((n) => n.id))
  const rest = nodes.filter((n) => !known.has(n.id))
  place(rest, 0, 3)

  return { positions, layers }
}
