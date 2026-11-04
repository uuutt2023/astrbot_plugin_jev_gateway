<script setup lang="ts">
/**
 * 拓扑图画布：接入对象 → 网关 → API 入口。
 *
 * 渲染引擎移植自 astrbot_plugin_livingmemory 的 canvas 图谱，
 * 这里只负责把数据喂进去、把交互事件抛出去。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { GraphInteraction } from '@/graph/interaction'
import { ForceLayout } from '@/graph/layout'
import { GraphRenderer } from '@/graph/renderer'
import { buildSeed } from '@/graph/seed'
import type { GraphEdge, GraphNode } from '@/graph/types'

const props = defineProps<{
  nodes: GraphNode[]
  edges: GraphEdge[]
}>()

const emit = defineEmits<{
  (e: 'select', node: GraphNode | null): void
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const hoverNode = ref<GraphNode | null>(null)
const selectedNode = ref<GraphNode | null>(null)

let renderer: GraphRenderer | null = null
let interaction: GraphInteraction | null = null
let layout: ForceLayout | null = null
let raf = 0
let resizeObserver: ResizeObserver | null = null

function buildLayout(): void {
  if (!renderer || !layout) return
  const seed = buildSeed(props.nodes, props.edges)
  const hubId = props.nodes.find((n) => n.kind === 'gateway')?.id ?? null
  layout.compute(props.nodes, props.edges, seed.positions, hubId)
  renderer.setPositions(layout.positions())
  renderer.configure(props.nodes, props.edges)
}

function frame(): void {
  if (renderer) {
    renderer.render({ hoverId: hoverNode.value?.id ?? null, selectedId: selectedNode.value?.id ?? null })
  }
  raf = requestAnimationFrame(frame)
}

function zoomIn(): void {
  renderer?.zoomBy(1.2)
}

function zoomOut(): void {
  renderer?.zoomBy(0.83)
}

function resetView(): void {
  renderer?.resetView()
  buildLayout()
}

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  renderer = new GraphRenderer(canvas)
  layout = new ForceLayout()
  buildLayout()

  interaction = new GraphInteraction(canvas, renderer, {
    onHover: (node) => {
      hoverNode.value = node
    },
    onSelect: (node) => {
      selectedNode.value = node
      emit('select', node)
    },
    onRender: () => {},
    onNodeMoved: (nodeId, world) => {
      renderer?.moveNode(nodeId, world.x, world.y)
    },
  })

  resizeObserver = new ResizeObserver(() => {
    renderer?.resize()
  })
  resizeObserver.observe(canvas)

  raf = requestAnimationFrame(frame)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  interaction?.destroy()
  resizeObserver?.disconnect()
})

watch(
  () => [props.nodes, props.edges],
  () => {
    buildLayout()
  },
  { deep: true },
)

defineExpose({ resetView })
</script>

<template>
  <div class="topology-graph">
    <canvas ref="canvasRef" class="canvas" />

    <div class="toolbar">
      <n-button size="tiny" quaternary @click="zoomIn">＋</n-button>
      <n-button size="tiny" quaternary @click="zoomOut">－</n-button>
      <n-button size="tiny" quaternary @click="resetView">复位</n-button>
    </div>

    <div class="legend">
      <span><i class="dot gateway" />网关</span>
      <span><i class="dot client" />接入对象</span>
      <span><i class="dot api" />API 入口</span>
      <span><i class="dot api-down" />异常入口</span>
    </div>

    <div v-if="hoverNode" class="tooltip">
      <strong>{{ hoverNode.label }}</strong>
      <span>{{ hoverNode.detail }}</span>
    </div>
  </div>
</template>

<style scoped>
.topology-graph {
  position: relative;
  width: 100%;
  height: 460px;
  border-radius: 6px;
  overflow: hidden;
  background: #fbfcfd;
}

.canvas {
  width: 100%;
  height: 100%;
  display: block;
  cursor: grab;
}

.toolbar {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  gap: 4px;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid #e6e9ef;
  border-radius: 5px;
  padding: 2px;
}

.legend {
  position: absolute;
  left: 10px;
  bottom: 10px;
  display: flex;
  gap: 14px;
  font-size: 12px;
  color: #5b6472;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid #e6e9ef;
  border-radius: 5px;
  padding: 4px 10px;
}

.legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  display: inline-block;
}

.dot.gateway {
  background: #5b6ef5;
}
.dot.client {
  background: #2a9e96;
}
.dot.api {
  background: #78a94b;
}
.dot.api-down {
  background: #df6d62;
}

.tooltip {
  position: absolute;
  top: 10px;
  left: 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: #5b6472;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid #e6e9ef;
  border-radius: 5px;
  padding: 6px 10px;
  pointer-events: none;
}

.tooltip strong {
  color: #2f343a;
  font-size: 13px;
}
</style>
