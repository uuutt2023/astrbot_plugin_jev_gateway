/**
 * Canvas 渲染器。
 *
 * 移植自 astrbot_plugin_livingmemory 的 pages/dashboard/graph-renderer.js：
 * 圆形节点带呼吸光晕、贝塞尔曲线边、边上流动的粒子、悬停/选中高亮，
 * 其余节点淡出。
 */
import { CFG, clamp, hexToRgba, lerp, nodeColor } from './shared'
import type { GraphEdge, GraphNode, Point } from './types'

export interface RenderState {
  hoverId: string | null
  selectedId: string | null
}

interface Viewport {
  scale: number
  ox: number
  oy: number
}

interface ScreenNode {
  node: GraphNode
  sx: number
  sy: number
  sr: number
  color: string
  sublabel: string
  isHub: boolean
  isHovered: boolean
  isSelected: boolean
  isMuted: boolean
}

interface ScreenEdge {
  edge: GraphEdge
  sx: number
  sy: number
  tx: number
  ty: number
  cx: number
  cy: number
  color: string
  isActive: boolean
  isMuted: boolean
}

export class GraphRenderer {
  private ctx: CanvasRenderingContext2D
  private width = 0
  private height = 0
  private dpr = 1
  private viewport: Viewport = { scale: 1, ox: 0, oy: 0 }
  private nodes: GraphNode[] = []
  private edges: GraphEdge[] = []
  private screenNodes: ScreenNode[] = []
  private screenEdges: ScreenEdge[] = []
  private adjacency: Record<string, string[]> = {}
  private particleOffsets: Record<string, number> = {}
  private labelWidthCache: Record<string, number> = {}

  constructor(private canvas: HTMLCanvasElement) {
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('拿不到 2D 画布上下文')
    this.ctx = ctx
    this.resize()
  }

  resize(): void {
    const rect = this.canvas.getBoundingClientRect()
    this.dpr = Math.min(window.devicePixelRatio || 1, CFG.DPR_MAX)
    this.width = rect.width
    this.height = rect.height
    this.canvas.width = Math.max(1, Math.round(rect.width * this.dpr))
    this.canvas.height = Math.max(1, Math.round(rect.height * this.dpr))
  }

  configure(nodes: GraphNode[], edges: GraphEdge[]): void {
    this.nodes = nodes
    this.edges = edges
    this.adjacency = {}
    edges.forEach((edge) => {
      if (!this.adjacency[edge.source]) this.adjacency[edge.source] = []
      if (!this.adjacency[edge.target]) this.adjacency[edge.target] = []
      this.adjacency[edge.source].push(edge.target)
      this.adjacency[edge.target].push(edge.source)
    })
  }

  /** 设置节点在画面上的位置（世界坐标）。 */
  setPositions(positions: Record<string, Point>): void {
    this.positions = positions
  }

  private positions: Record<string, Point> = {}

  worldToScreen(wx: number, wy: number): Point {
    return {
      x: (wx + this.viewport.ox) * this.viewport.scale + this.width / 2,
      y: (wy + this.viewport.oy) * this.viewport.scale + this.height / 2,
    }
  }

  screenToWorld(sx: number, sy: number): Point {
    return {
      x: (sx - this.width / 2) / this.viewport.scale - this.viewport.ox,
      y: (sy - this.height / 2) / this.viewport.scale - this.viewport.oy,
    }
  }

  zoomBy(factor: number, anchor?: Point): void {
    const next = clamp(this.viewport.scale * factor, CFG.ZOOM_MIN, CFG.ZOOM_MAX)
    if (anchor) {
      // 以鼠标位置为锚点缩放
      const before = this.screenToWorld(anchor.x, anchor.y)
      this.viewport.scale = next
      const after = this.screenToWorld(anchor.x, anchor.y)
      this.viewport.ox += before.x - after.x
      this.viewport.oy += before.y - after.y
    } else {
      this.viewport.scale = next
    }
  }

  panBy(dx: number, dy: number): void {
    this.viewport.ox += dx / this.viewport.scale
    this.viewport.oy += dy / this.viewport.scale
  }

  resetView(): void {
    this.viewport = { scale: 1, ox: 0, oy: 0 }
  }

  get scale(): number {
    return this.viewport.scale
  }

  render(state: RenderState): void {
    const ctx = this.ctx
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0)
    ctx.clearRect(0, 0, this.width, this.height)

    const hubId = this.nodes.find((n) => n.kind === 'gateway')?.id ?? null
    const focusId = state.selectedId ?? state.hoverId
    const highlight = new Set<string>()
    if (focusId) {
      highlight.add(focusId)
      ;(this.adjacency[focusId] || []).forEach((id) => highlight.add(id))
    }
    const hasFocus = highlight.size > 0

    // 屏幕坐标
    const screenPositions: Record<string, Point> = {}
    this.nodes.forEach((node) => {
      const pos = this.positions[node.id] || { x: 0, y: 0 }
      screenPositions[node.id] = this.worldToScreen(pos.x, pos.y)
    })

    // 边
    this.screenEdges = []
    this.edges.forEach((edge) => {
      const s = screenPositions[edge.source]
      const t = screenPositions[edge.target]
      if (!s || !t) return
      const dx = t.x - s.x
      const dy = t.y - s.y
      const length = Math.sqrt(dx * dx + dy * dy) || 1
      const bend = Math.min(26, length * 0.07)
      const isActive = !hasFocus || (highlight.has(edge.source) && highlight.has(edge.target))
      const sourceNode = this.nodes.find((n) => n.id === edge.source)
      this.screenEdges.push({
        edge,
        sx: s.x,
        sy: s.y,
        tx: t.x,
        ty: t.y,
        cx: (s.x + t.x) / 2 - (dy / length) * bend,
        cy: (s.y + t.y) / 2 + (dx / length) * bend,
        color: sourceNode ? nodeColor(sourceNode) : '#8a93a0',
        isActive,
        isMuted: hasFocus && !isActive,
      })
    })

    // 节点
    this.screenNodes = this.nodes.map((node) => {
      const p = screenPositions[node.id]
      const isHub = node.id === hubId
      const base = node.kind === 'gateway' ? CFG.NODE_RADIUS_MAX * 0.62 : 7
      const weight = clamp(Number(node.weight || 0), 0, 200)
      let sr = base + Math.sqrt(weight) * 0.9 * this.viewport.scale
      if (isHub) sr = Math.min(CFG.NODE_RADIUS_MAX * 1.5, sr * 1.5)
      if (node.id === state.selectedId) sr += 1.5
      return {
        node,
        sx: p.x,
        sy: p.y,
        sr: Math.max(1.6, sr),
        color: nodeColor(node),
        sublabel: node.sublabel || '',
        isHub,
        isHovered: node.id === state.hoverId,
        isSelected: node.id === state.selectedId,
        isMuted: hasFocus && !highlight.has(node.id),
      }
    })

    this.drawBackground()
    this.screenEdges.forEach((de) => this.drawEdge(de))
    this.screenEdges.forEach((de) => this.drawParticles(de))
    this.screenNodes.forEach((sn) => this.drawNode(sn))
    this.screenNodes.forEach((sn) => this.drawLabel(sn))
  }

  private drawBackground(): void {
    const ctx = this.ctx
    ctx.save()
    ctx.strokeStyle = 'rgba(140,150,165,0.10)'
    ctx.lineWidth = 1
    const step = 46 * this.viewport.scale
    if (step > 14) {
      const offsetX = ((this.viewport.ox * this.viewport.scale + this.width / 2) % step + step) % step
      const offsetY = ((this.viewport.oy * this.viewport.scale + this.height / 2) % step + step) % step
      for (let x = offsetX; x < this.width; x += step) {
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, this.height)
        ctx.stroke()
      }
      for (let y = offsetY; y < this.height; y += step) {
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(this.width, y)
        ctx.stroke()
      }
    }
    ctx.restore()
  }

  private drawEdge(de: ScreenEdge): void {
    const ctx = this.ctx
    const opacity = de.isMuted
      ? CFG.EDGE_OPACITY_DEFAULT * 0.35
      : de.isActive
        ? CFG.EDGE_OPACITY_ACTIVE
        : CFG.EDGE_OPACITY_DEFAULT
    const width = de.isActive ? CFG.EDGE_WIDTH_ACTIVE : CFG.EDGE_WIDTH_DEFAULT
    const strength = clamp(Math.sqrt(Number(de.edge.weight || 1)) / 3.6, 0, 1)

    ctx.beginPath()
    ctx.moveTo(de.sx, de.sy)
    ctx.quadraticCurveTo(de.cx, de.cy, de.tx, de.ty)
    ctx.strokeStyle = hexToRgba(de.color, clamp(opacity + strength * 0.1, 0, 0.84))
    ctx.lineWidth = width + strength * 0.8
    ctx.lineCap = 'round'
    ctx.stroke()
  }

  private drawParticles(de: ScreenEdge): void {
    if (!de.isActive) return
    const ctx = this.ctx
    const key = de.edge.id
    if (!(key in this.particleOffsets)) this.particleOffsets[key] = Math.random()
    const now = performance.now() / 1000
    const count = de.isMuted ? CFG.PARTICLE_COUNT_DEFAULT : CFG.PARTICLE_COUNT_ACTIVE

    for (let i = 0; i < count; i++) {
      const t = (((now * CFG.PARTICLE_SPEED + this.particleOffsets[key] + i / count) % 1) + 1) % 1
      const inv = 1 - t
      const px = inv * inv * de.sx + 2 * inv * t * de.cx + t * t * de.tx
      const py = inv * inv * de.sy + 2 * inv * t * de.cy + t * t * de.ty
      ctx.beginPath()
      ctx.arc(px, py, CFG.PARTICLE_SIZE, 0, Math.PI * 2)
      ctx.fillStyle = hexToRgba(de.color, 0.5)
      ctx.fill()
    }
  }

  private drawNode(sn: ScreenNode): void {
    const ctx = this.ctx
    const r = sn.sr
    ctx.save()
    ctx.globalAlpha = sn.isMuted ? 0.26 : 1

    const pulse = 0.5 + Math.sin(Date.now() * 0.0024) * 0.5
    const haloBase = sn.isSelected ? 9 : sn.isHovered ? 7 : sn.isHub ? 6 : pulse * 2.2
    if (haloBase > 0 && !sn.isMuted) {
      ctx.beginPath()
      ctx.arc(sn.sx, sn.sy, r + haloBase * this.viewport.scale, 0, Math.PI * 2)
      ctx.fillStyle = hexToRgba(sn.color, sn.isSelected ? 0.2 : 0.06 + pulse * 0.04)
      ctx.fill()
    }

    ctx.beginPath()
    ctx.arc(sn.sx, sn.sy, r, 0, Math.PI * 2)
    ctx.fillStyle = sn.isMuted ? '#c7ccd4' : sn.color
    ctx.fill()
    ctx.lineWidth = sn.isSelected ? 2.4 : sn.isHovered || sn.isHub ? 1.6 : 1
    ctx.strokeStyle = sn.isSelected || sn.isHovered || sn.isHub ? sn.color : '#ffffff'
    ctx.stroke()
    ctx.restore()
  }

  private drawLabel(sn: ScreenNode): void {
    const ctx = this.ctx
    const scale = this.viewport.scale
    const fontSize = Math.round(clamp(CFG.NODE_FONT_SIZE * scale, 10, CFG.NODE_FONT_MAX_SIZE))
    ctx.save()
    ctx.fillStyle = sn.isMuted ? '#a9b0ba' : '#2f343a'
    ctx.font = `${sn.isSelected || sn.isHub ? '650 ' : '520 '}${fontSize}px "PingFang SC", "Microsoft YaHei", Arial, sans-serif`
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'

    const maxChars = 18
    const label = sn.node.label.length > maxChars ? `${sn.node.label.slice(0, maxChars - 1)}…` : sn.node.label
    const labelX = sn.sx + sn.sr + clamp(7 * scale, 5, 11)
    const widthKey = `${ctx.font}|${label}`
    let labelWidth = this.labelWidthCache[widthKey]
    if (labelWidth == null) {
      labelWidth = ctx.measureText(label).width
      if (Object.keys(this.labelWidthCache).length > 800) this.labelWidthCache = {}
      this.labelWidthCache[widthKey] = labelWidth
    }
    ctx.fillText(label, labelX, sn.sy)

    // 副标题常显（余额、调用次数），悬停时再补一行运行状态
    const metaFs = Math.round(clamp(CFG.NODE_META_SIZE * scale, 8, 12))
    let metaY = sn.sy + fontSize / 2 + 3
    if (sn.sublabel) {
      ctx.fillStyle = sn.isMuted ? '#a9b0ba' : '#6b7280'
      ctx.font = `${metaFs}px "SFMono-Regular", Consolas, monospace`
      ctx.textBaseline = 'top'
      ctx.fillText(sn.sublabel, labelX, metaY)
      metaY += metaFs + 2
    }
    if (sn.isHovered || sn.isSelected) {
      const meta = this.metaText(sn.node)
      if (meta) {
        ctx.fillStyle = '#6b7280'
        ctx.font = `${metaFs}px "SFMono-Regular", Consolas, monospace`
        ctx.textBaseline = 'top'
        ctx.fillText(meta, labelX, metaY)
      }
    }
    ctx.restore()
  }

  private metaText(node: GraphNode): string {
    if (node.kind === 'client') {
      const requests = Number(node.requests || 0)
      const active = node.active === false ? ' · 不活跃' : ''
      return `${requests} 次${active}`
    }
    if (node.kind === 'api') {
      const requests = Number(node.requests || 0)
      const healthy = node.healthy === false ? ' · 异常' : ''
      return `${requests} 次${healthy}`
    }
    return node.detail || ''
  }

  hitTestNode(sx: number, sy: number): GraphNode | null {
    let best: GraphNode | null = null
    let bestDist = Infinity
    this.screenNodes.forEach((sn) => {
      const dx = sx - sn.sx
      const dy = sy - sn.sy
      const dist = Math.sqrt(dx * dx + dy * dy)
      const reach = sn.sr + CFG.HOVER_RADIUS
      if (dist <= reach && dist < bestDist) {
        bestDist = dist
        best = sn.node
      }
    })
    return best
  }

  /** 拖动节点时改它的位置。 */
  moveNode(nodeId: string, worldX: number, worldY: number): void {
    const pos = this.positions[nodeId]
    if (!pos) return
    pos.x = worldX
    pos.y = worldY
  }
}

export { lerp }
