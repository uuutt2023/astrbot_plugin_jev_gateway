/**
 * 鼠标 / 触摸交互：拖拽节点、平移、滚轮缩放、双指捏合、悬停命中。
 *
 * 移植自 astrbot_plugin_livingmemory 的 pages/dashboard/graph-interaction.js。
 */
import { CFG, getPos } from './shared'
import type { GraphNode, Point } from './types'
import type { GraphRenderer } from './renderer'

export interface InteractionCallbacks {
  onHover(node: GraphNode | null): void
  onSelect(node: GraphNode | null): void
  onRender(): void
  onNodeMoved(nodeId: string, world: Point): void
}

export class GraphInteraction {
  private listeners: Array<{
    target: EventTarget
    name: string
    callback: EventListener
    options?: boolean | AddEventListenerOptions
  }> = []
  private dragging = false
  private panning = false
  private dragNode: GraphNode | null = null
  private dragStart: Point = { x: 0, y: 0 }
  private dragOffset: Point = { x: 0, y: 0 }
  private panStart = { ox: 0, oy: 0, mx: 0, my: 0 }
  private hoverId: string | null = null
  private pinchDist = 0
  private pinchScale = 1
  private pinching = false
  private moveFrame: number | null = null
  /** 指针位置：跟 MouseEvent 一样存 clientX/clientY */
  private pendingMove: { clientX: number; clientY: number } | null = null

  constructor(
    private canvas: HTMLCanvasElement,
    private renderer: GraphRenderer,
    private cb: InteractionCallbacks,
  ) {
    this.canvas.style.touchAction = 'none'
    this.bind()
  }

  private listen(target: EventTarget, name: string, callback: EventListener, options?: boolean | AddEventListenerOptions) {
    target.addEventListener(name, callback, options)
    this.listeners.push({ target, name, callback, options })
  }

  private bind(): void {
    const canvas = this.canvas
    this.listen(canvas, 'mousedown', ((e: MouseEvent) => {
      this.flushMove()
      this.onMouseDown(e)
    }) as EventListener)
    this.listen(canvas, 'mousemove', ((e: MouseEvent) => this.queueMove(e)) as EventListener)
    this.listen(window, 'mouseup', ((e: MouseEvent) => this.onMouseUp(e)) as EventListener)
    this.listen(canvas, 'mouseleave', (() => {
      this.cancelGesture()
      if (this.hoverId !== null) {
        this.hoverId = null
        this.cb.onHover(null)
        this.cb.onRender()
      }
    }) as EventListener)
    this.listen(
      canvas,
      'wheel',
      ((e: WheelEvent) => this.onWheel(e)) as EventListener,
      { passive: false },
    )
    this.listen(canvas, 'dblclick', (() => this.cb.onSelect(null)) as EventListener)
    this.listen(canvas, 'touchstart', ((e: TouchEvent) => this.onTouchStart(e)) as EventListener, {
      passive: false,
    })
    this.listen(canvas, 'touchmove', ((e: TouchEvent) => this.onTouchMove(e)) as EventListener, {
      passive: false,
    })
    this.listen(canvas, 'touchend', (() => this.onTouchEnd()) as EventListener)
    this.listen(canvas, 'touchcancel', (() => {
      this.cancelGesture()
      this.pinching = false
      this.pinchDist = 0
    }) as EventListener)
    this.listen(canvas, 'contextmenu', ((e: Event) => e.preventDefault()) as EventListener)
  }

  /** 命中检测每帧只做一次，用最后一次指针位置。 */
  private queueMove(e: MouseEvent): void {
    this.pendingMove = { clientX: e.clientX, clientY: e.clientY }
    if (this.moveFrame !== null) return
    this.moveFrame = requestAnimationFrame(() => {
      this.moveFrame = null
      this.flushMove()
    })
  }

  private flushMove(): void {
    if (this.moveFrame !== null) {
      cancelAnimationFrame(this.moveFrame)
      this.moveFrame = null
    }
    const move = this.pendingMove
    this.pendingMove = null
    if (move) this.onMouseMove(move)
  }

  private cancelGesture(): void {
    this.flushMove()
    this.dragging = false
    this.panning = false
    this.dragNode = null
    this.canvas.style.cursor = 'grab'
  }

  destroy(): void {
    this.cancelGesture()
    this.listeners.forEach((listener) => {
      listener.target.removeEventListener(listener.name, listener.callback, listener.options)
    })
    this.listeners = []
  }

  private onMouseDown(e: MouseEvent): void {
    const pos = getPos(e, this.canvas)
    const hit = this.renderer.hitTestNode(pos.x, pos.y)
    if (hit && e.button === 0) {
      const world = this.renderer.screenToWorld(pos.x, pos.y)
      this.dragging = true
      this.dragNode = hit
      this.dragStart = { x: pos.x, y: pos.y }
      const nodeWorld = this.renderer.screenToWorld(
        pos.x,
        pos.y,
      )
      this.dragOffset = { x: nodeWorld.x - world.x, y: nodeWorld.y - world.y }
      this.canvas.style.cursor = 'grabbing'
      e.preventDefault()
      return
    }
    if (e.button === 0 || e.button === 2) {
      this.panning = true
      this.panStart = {
        ox: 0,
        oy: 0,
        mx: pos.x,
        my: pos.y,
      }
      this.canvas.style.cursor = 'grabbing'
      e.preventDefault()
    }
  }

  private onMouseMove(e: { clientX: number; clientY: number }): void {
    const pos = getPos(e as MouseEvent, this.canvas)

    if (this.dragging && this.dragNode) {
      const world = this.renderer.screenToWorld(pos.x, pos.y)
      this.cb.onNodeMoved(this.dragNode.id, {
        x: world.x - this.dragOffset.x,
        y: world.y - this.dragOffset.y,
      })
      this.cb.onRender()
      return
    }

    if (this.panning) {
      this.renderer.panBy(pos.x - this.panStart.mx, pos.y - this.panStart.my)
      this.panStart.mx = pos.x
      this.panStart.my = pos.y
      this.cb.onRender()
      return
    }

    const hit = this.renderer.hitTestNode(pos.x, pos.y)
    const nextId = hit ? hit.id : null
    if (nextId !== this.hoverId) {
      this.hoverId = nextId
      this.cb.onHover(hit)
      this.canvas.style.cursor = hit ? 'pointer' : 'grab'
      this.cb.onRender()
    }
  }

  private onMouseUp(e: MouseEvent): void {
    this.flushMove()
    const pos = getPos(e, this.canvas)

    // 按下后几乎没动 = 点击；动了 = 拖拽
    if (this.dragging && this.dragNode) {
      const dx = pos.x - this.dragStart.x
      const dy = pos.y - this.dragStart.y
      if (Math.sqrt(dx * dx + dy * dy) < 3) {
        this.cb.onSelect(this.dragNode)
      }
      this.dragging = false
      this.dragNode = null
    } else if (this.panning) {
      const dx = pos.x - this.panStart.mx
      const dy = pos.y - this.panStart.my
      if (Math.sqrt(dx * dx + dy * dy) < 3) {
        this.cb.onSelect(this.renderer.hitTestNode(pos.x, pos.y))
      }
      this.panning = false
    }

    this.canvas.style.cursor = 'grab'
    this.cb.onRender()
  }

  private onWheel(e: WheelEvent): void {
    e.preventDefault()
    const pos = getPos(e, this.canvas)
    const factor = e.deltaY > 0 ? 0.9 : 1.1
    this.renderer.zoomBy(factor, pos)
    this.cb.onRender()
  }

  private onTouchStart(e: TouchEvent): void {
    if (e.touches.length === 1) {
      const touch = e.touches[0]
      this.queueMove({ clientX: touch.clientX, clientY: touch.clientY } as MouseEvent)
    } else if (e.touches.length === 2) {
      this.pinching = true
      this.pinchDist = this.touchDistance(e)
      this.pinchScale = 1
    }
    e.preventDefault()
  }

  private onTouchMove(e: TouchEvent): void {
    if (e.touches.length === 2 && this.pinching) {
      const dist = this.touchDistance(e)
      if (this.pinchDist > 0) {
        const ratio = dist / this.pinchDist
        this.renderer.zoomBy(ratio * this.pinchScale > 1 ? 1.02 : 0.98)
        this.pinchScale = 1
        this.pinchDist = dist
        this.cb.onRender()
      }
      e.preventDefault()
      return
    }
    if (e.touches.length === 1) {
      const touch = e.touches[0]
      this.queueMove({ clientX: touch.clientX, clientY: touch.clientY } as MouseEvent)
    }
    e.preventDefault()
  }

  private onTouchEnd(): void {
    this.pinching = false
    this.pinchDist = 0
    this.dragging = false
    this.panning = false
  }

  private touchDistance(e: TouchEvent): number {
    const a = e.touches[0]
    const b = e.touches[1]
    const dx = a.clientX - b.clientX
    const dy = a.clientY - b.clientY
    return Math.sqrt(dx * dx + dy * dy)
  }
}

export { CFG }
