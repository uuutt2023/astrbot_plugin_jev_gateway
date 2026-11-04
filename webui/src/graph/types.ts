/** 拓扑图的数据形状。 */

export type NodeKind = 'gateway' | 'api' | 'client'

export interface GraphNode {
  id: string
  kind: NodeKind
  label: string
  detail?: string
  /** 流量权重，决定节点大小与边粗细 */
  weight?: number
  /** API 入口是否健康 */
  healthy?: boolean
  /** 接入对象最近是否还在调用 */
  active?: boolean
  requests?: number
  meta?: Record<string, unknown>
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  weight?: number
  label?: string
}

export interface GraphPayload {
  gateway?: Record<string, unknown>
  nodes: GraphNode[]
  edges: GraphEdge[]
  updated_at?: number
}

/** 布局里的一个节点。 */
export interface SimNode {
  id: string
  node: GraphNode
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  /** 种子位置：力导向会往回拉，避免节点飘走 */
  tx: number
  ty: number
}

export interface Point {
  x: number
  y: number
}
