/**
 * 力导向布局核心（纯计算，无 DOM）。
 *
 * 移植自 astrbot_plugin_livingmemory 的 pages/dashboard/graph-layout-core.js：
 * 斥力 + 连边引力 + 重力 + 阻尼，每步都把节点往种子位置拉一点，
 * 所以布局会稳定在「左列 / 中间 / 右列」的层次上。
 */
import { CFG, clamp, nodeRadius } from './shared'
import type { GraphEdge, GraphNode, SimNode } from './types'

interface SimEdge {
  source: number
  target: number
  weight: number
  jitter: number
}

function hashUnit(value: string, salt: number): number {
  const str = `${value}:${salt}`
  let h = 2166136261
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return ((h >>> 0) % 100000) / 100000
}

export class ForceLayout {
  private sim: SimNode[] = []
  private simEdges: SimEdge[] = []
  private indexById: Record<string, number> = {}

  compute(
    nodes: GraphNode[],
    edges: GraphEdge[],
    seed: Record<string, { x: number; y: number }>,
    hubId: string | null,
  ): void {
    this.sim = []
    this.simEdges = []
    this.indexById = {}

    if (!nodes.length) return

    nodes.forEach((node) => {
      const seeded = seed[node.id] || { x: 0, y: 0 }
      this.indexById[node.id] = this.sim.length
      this.sim.push({
        id: node.id,
        node,
        x: seeded.x,
        y: seeded.y,
        vx: 0,
        vy: 0,
        radius: nodeRadius(node, node.id === hubId),
        tx: seeded.x,
        ty: seeded.y,
      })
    })

    edges.forEach((edge) => {
      const si = this.indexById[edge.source]
      const ti = this.indexById[edge.target]
      if (si == null || ti == null) return
      this.simEdges.push({
        source: si,
        target: ti,
        weight: clamp(Number(edge.weight || 1), 0.4, 12),
        jitter: hashUnit(`${edge.id}:${edge.source}:${edge.target}`, 61),
      })
    })

    this.run(CFG.FORCE_ITERATIONS)
  }

  private run(iterations: number): void {
    const sim = this.sim
    const n = sim.length
    if (!n) return
    const effectiveRange = 300 + Math.min(140, n * 2)

    for (let step = 0; step < iterations; step++) {
      const alpha = 1 - step / iterations
      const cooled = 0.3 + alpha * 0.7

      // 斥力
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const a = sim[i]
          const b = sim[j]
          let dx = a.x - b.x
          let dy = a.y - b.y
          let distSq = dx * dx + dy * dy
          if (distSq < 0.01) {
            const kick = hashUnit(`${a.id}:${b.id}`, 43) * Math.PI * 2
            dx = Math.cos(kick) * 0.1
            dy = Math.sin(kick) * 0.1
            distSq = dx * dx + dy * dy
          }
          const dist = Math.sqrt(distSq)
          const minSep = (a.radius + b.radius) * 2.2 + 18
          let repulse = (CFG.FORCE_REPULSION * cooled) / Math.max(distSq, minSep * minSep * 0.25)
          if (dist < effectiveRange) {
            const falloff = 1 - dist / effectiveRange
            repulse *= falloff * falloff
          } else {
            repulse *= 0.05
          }
          if (dist < minSep) repulse += (minSep - dist) * 0.35
          const fx = (dx / dist) * repulse
          const fy = (dy / dist) * repulse
          a.vx += fx
          a.vy += fy
          b.vx -= fx
          b.vy -= fy
        }
      }

      // 连边引力
      this.simEdges.forEach((edge) => {
        const s = sim[edge.source]
        const t = sim[edge.target]
        const dx = t.x - s.x
        const dy = t.y - s.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 0.001
        const baseDistance = CFG.FORCE_LINK_DISTANCE + edge.jitter * 30
        const weightFactor = Math.min(1.5, Math.sqrt(edge.weight) * 0.3)
        const desired = baseDistance - weightFactor * 15
        let strength = CFG.FORCE_LINK_STRENGTH * cooled
        if (dist / desired > 2) strength *= 0.5
        const force = (dist - desired) * strength
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force
        s.vx += fx
        s.vy += fy
        t.vx -= fx
        t.vy -= fy
      })

      // 重力 + 回拉种子位置
      sim.forEach((sn) => {
        const gravity = CFG.FORCE_GRAVITY * cooled
        sn.vx -= (sn.x - sn.tx) * CFG.ANCHOR_STRENGTH * cooled
        sn.vy -= (sn.y - sn.ty) * CFG.ANCHOR_STRENGTH * cooled
        sn.vx -= sn.x * gravity * 0.12
        sn.vy -= sn.y * gravity * 0.12
      })

      // 阻尼与限速
      sim.forEach((sn) => {
        sn.vx *= CFG.FORCE_DAMPING
        sn.vy *= CFG.FORCE_DAMPING
        const speed = Math.sqrt(sn.vx * sn.vx + sn.vy * sn.vy)
        if (speed > CFG.FORCE_MAX_SPEED) {
          sn.vx = (sn.vx / speed) * CFG.FORCE_MAX_SPEED
          sn.vy = (sn.vy / speed) * CFG.FORCE_MAX_SPEED
        }
        sn.x += sn.vx
        sn.y += sn.vy
      })
    }
  }

  positions(): Record<string, { x: number; y: number }> {
    const out: Record<string, { x: number; y: number }> = {}
    this.sim.forEach((sn) => {
      out[sn.id] = { x: sn.x, y: sn.y }
    })
    return out
  }

  radiusOf(nodeId: string): number {
    const sn = this.sim.find((item) => item.id === nodeId)
    return sn ? sn.radius : CFG.NODE_RADIUS_BASE
  }
}
