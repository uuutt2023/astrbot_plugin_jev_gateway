<script setup lang="ts">
/** 选中入口的余额。 */
import { NButton, NSpace, NTag, NText } from 'naive-ui'

export interface Balance {
  unit: string | null
  value: number | null
  source: string
  updated_at: number
  error?: string
}

defineProps<{
  balance: Balance | null
  entryName?: string
}>()

const emit = defineEmits<{
  (e: 'refresh'): void
}>()

function sourceText(source: string): string {
  if (source === 'custom') return '自定义查询'
  if (source === 'response') return '响应里带的'
  return source || '—'
}

function timeText(ts?: number): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="balance-panel">
    <n-space align="center" justify="space-between">
      <n-space align="center" size="small">
        <n-text strong>{{ entryName || '选中入口' }}</n-text>
        <n-tag v-if="balance" size="small" round>{{ sourceText(balance.source) }}</n-tag>
        <n-text depth="3" style="font-size: 12px">更新于 {{ timeText(balance?.updated_at) }}</n-text>
      </n-space>
      <n-button size="small" quaternary @click="emit('refresh')">刷新余额</n-button>
    </n-space>

    <div v-if="balance && balance.value !== null && balance.value !== undefined" class="value">
      {{ balance.unit === 'usd' ? '$' : '' }}{{ balance.value.toLocaleString() }}
      <span class="unit">{{ balance.unit === 'tokens' ? 'tokens' : balance.unit || '' }}</span>
    </div>

    <n-text v-else-if="balance && balance.error" depth="3" style="font-size: 12px">
      {{ balance.error }}
    </n-text>
    <n-text v-else depth="3" style="font-size: 12px">
      还没有余额信息。发一次请求，或给入口配「余额查询地址」。
    </n-text>
  </div>
</template>

<style scoped>
.balance-panel {
  width: 100%;
}

.value {
  margin-top: 10px;
  font-size: 26px;
  font-weight: 600;
  color: #2f343a;
}

.unit {
  margin-left: 4px;
  font-size: 13px;
  font-weight: 400;
  color: #6b7280;
}
</style>
