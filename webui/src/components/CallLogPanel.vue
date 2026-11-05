<script setup lang="ts">
/** 最近的调用记录：谁调的、提示词是什么、模型怎么答的。 */
import { computed, ref } from 'vue'
import { NButton, NEmpty, NSelect, NSpace, NTag, NText } from 'naive-ui'

export interface CallRecord {
  id: number
  at: number
  client: string
  protocol: string
  entry: string
  status: number
  elapsed_ms: number
  cached: boolean
  prompt: string
  questions: Record<string, unknown>
  state: string
  truncated: boolean
  result: string
  response: unknown
}

const props = defineProps<{
  calls: CallRecord[]
  clients: string[]
  retentionDays: number
}>()

const emit = defineEmits<{
  (e: 'refresh'): void
  (e: 'filter', client: string): void
}>()

const expanded = ref<number | null>(null)

const clientOptions = computed(() => [
  { label: '全部接入对象', value: '' },
  ...props.clients.map((name) => ({ label: name, value: name })),
])

function toggle(id: number): void {
  expanded.value = expanded.value === id ? null : id
}

function timeText(ts: number): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

function shortClient(name: string): string {
  return name.replace(/^astrbot_plugin_/, '') || name || '未知'
}
</script>

<template>
  <div class="call-log">
    <n-space align="center" justify="space-between">
      <n-space align="center" size="small">
        <n-text strong>调用记录</n-text>
        <n-tag size="small" round>{{ calls.length }} 条</n-tag>
        <n-text depth="3" style="font-size: 12px">保留 {{ retentionDays }} 天</n-text>
      </n-space>
      <n-space align="center">
        <n-select
          :value="''"
          :options="clientOptions"
          size="small"
          style="width: 200px"
          @update:value="emit('filter', $event)"
        />
        <n-button size="small" quaternary @click="emit('refresh')">刷新</n-button>
      </n-space>
    </n-space>

    <div v-if="!calls.length" class="empty">
      <n-empty description="还没有调用记录。客户端插件调一次网关就会出现在这里。" size="small" />
    </div>

    <div v-for="call in calls" :key="call.id" class="call">
      <div class="head" @click="toggle(call.id)">
        <n-space align="center" size="small" :wrap="false">
          <n-tag size="small" round :type="call.status === 200 ? 'success' : 'error'">
            {{ call.status || '—' }}
          </n-tag>
          <n-text strong>{{ shortClient(call.client) }}</n-text>
          <n-text depth="3" style="font-size: 12px">{{ call.protocol }}</n-text>
          <n-text depth="3" style="font-size: 12px">{{ call.elapsed_ms }} ms</n-text>
          <n-tag v-if="call.cached" size="small" round>命中去重缓存</n-tag>
          <n-text depth="3" style="font-size: 12px">{{ timeText(call.at) }}</n-text>
        </n-space>
        <n-text depth="3" style="font-size: 12px">{{ expanded === call.id ? '收起' : '展开' }}</n-text>
      </div>

      <div v-if="expanded === call.id" class="detail">
        <div class="block">
          <div class="block-title">提示词</div>
          <pre class="code">{{ call.prompt || '（无）' }}</pre>
        </div>
        <div class="block">
          <div class="block-title">上下文 state{{ call.truncated ? '（已截断）' : '' }}</div>
          <pre class="code">{{ call.state || '（空）' }}</pre>
        </div>
        <div class="block">
          <div class="block-title">结果</div>
          <pre class="code">{{ JSON.stringify(call.response, null, 2) }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.call-log {
  width: 100%;
}

.empty {
  padding: 18px 0;
}

.call {
  border-bottom: 1px solid rgba(128, 128, 128, 0.16);
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 2px;
  cursor: pointer;
}

.detail {
  padding: 4px 2px 12px;
}

.block {
  margin-bottom: 8px;
}

.block-title {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 3px;
}

.code {
  margin: 0;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(128, 128, 128, 0.08);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow: auto;
}
</style>
