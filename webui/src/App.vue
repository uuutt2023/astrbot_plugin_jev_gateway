<script setup lang="ts">
/**
 * 网关页面：一张拓扑图 + 点节点后的详情。
 *
 * 配置、测试发送、查余额都收在拓扑图里：
 * - 点 API 入口节点 → 配置 / 测试 / 余额
 * - 点网关节点 → 网关设置
 * - 点接入对象节点 → 调用情况
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NConfigProvider,
  NPopconfirm,
  NSpace,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  NText,
} from 'naive-ui'
import BalancePanel from '@/components/BalancePanel.vue'
import EntryForm from '@/components/EntryForm.vue'
import GatewaySettings from '@/components/GatewaySettings.vue'
import TestPanel from '@/components/TestPanel.vue'
import TopologyGraph from '@/components/TopologyGraph.vue'
import type { GraphEdge, GraphNode } from '@/graph/types'
import { useBridge } from '@/composables/useBridge'
import { detectThemeMode, themeOverrides } from '@/theme'

interface Entry {
  id?: string
  protocol: string
  kind: string
  base_url: string
  api_key: string
  model: string
  endpoint_path: string
  timeout: number
  priority: number
  weight: number
  balance_url: string
  balance_field: string
  url?: string
  key_masked?: string
}

interface Balance {
  unit: string | null
  value: number | null
  source: string
  updated_at: number
  error?: string
}

const toast = ref<{ type: 'success' | 'error' | 'warning'; text: string } | null>(null)
const bridge = useBridge()

const theme = ref(detectThemeMode())
const loading = ref(false)
const running = ref(false)
const endpointBase = ref('')
const accessTokenSet = ref(false)
const entries = ref<Entry[]>([])
const balances = ref<Record<string, Balance>>({})
const settings = ref({
  host: '127.0.0.1',
  port: 8770,
  advertised_url: '',
  access_token_set: false,
  lb_strategy: 'round_robin',
})
const draft = ref({
  host: '127.0.0.1',
  port: 8770,
  advertised_url: '',
  access_token: '',
  lb_strategy: 'round_robin',
})

// 拓扑图
const topologyNodes = ref<GraphNode[]>([])
const topologyEdges = ref<GraphEdge[]>([])
const topologySelected = ref<GraphNode | null>(null)
const topologyAuto = ref(false)
const detailTab = ref('config')
let topologyTimer: number | null = null

const isApiNode = computed(() => topologySelected.value?.kind === 'api')
const isGatewayNode = computed(() => topologySelected.value?.kind === 'gateway')

// 选中的 API 节点 → 配置列表里那一条
const selectedEntry = computed(() => {
  const node = topologySelected.value
  if (!node || node.kind !== 'api') return null
  const entryId = node.id.replace(/^api:/, '')
  return entries.value.find((e) => e.id === entryId) || null
})

// 选中的 API 节点 → 它自己的余额
const selectedBalance = computed(() => {
  const entry = selectedEntry.value
  if (!entry?.id) return null
  return balances.value[entry.id] || null
})

function blankEntry(): Entry {
  return {
    protocol: `入口 ${entries.value.length + 1}`,
    kind: 'systemone',
    base_url: 'https://jevmodel.org',
    api_key: '',
    model: 'jev-latest',
    endpoint_path: '',
    timeout: 10,
    priority: 100,
    weight: 1,
    balance_url: '',
    balance_field: '',
  }
}

async function loadEntries() {
  loading.value = true
  try {
    const data = (await bridge.apiGet('entries')) as any
    entries.value = (data.entries || []).map((e: Entry) => ({
      ...e,
      api_key: '', // 列表不返回明文 Key，留空表示不改
      key_masked: e.key_masked,
    }))
    running.value = !!data.running
    endpointBase.value = data.endpoint_base || ''
    accessTokenSet.value = !!data.access_token_set
    const st = data.settings || {}
    settings.value = {
      host: st.host || '127.0.0.1',
      port: st.port || 8770,
      advertised_url: st.advertised_url || '',
      access_token_set: !!st.access_token_set,
      lb_strategy: st.lb_strategy || 'round_robin',
    }
    draft.value = {
      host: settings.value.host,
      port: settings.value.port,
      advertised_url: settings.value.advertised_url,
      access_token: '',
      lb_strategy: settings.value.lb_strategy,
    }
  } catch (e: any) {
    toast.value = { type: 'error', text: `读取入口失败：${e?.message || e}` }
  } finally {
    loading.value = false
  }
}

async function loadTopology() {
  try {
    const data = (await bridge.apiGet('topology')) as any
    topologyNodes.value = data.nodes || []
    topologyEdges.value = data.edges || []
  } catch (e) {
    // 拓扑取不到不影响别的部分
  }
}

async function loadBalance() {
  try {
    const data = (await bridge.apiGet('balance')) as any
    balances.value = data || {}
  } catch (e) {
    // 余额取不到就先用旧值
  }
}

async function refreshAll() {
  await Promise.all([loadEntries(), loadTopology(), loadBalance()])
}

async function saveEntries() {
  loading.value = true
  try {
    // Key 留空表示不改：后端会沿用原来的明文 Key
    const payload = entries.value.map((e) => ({ ...e, api_key: e.api_key || '' }))
    await bridge.apiPost('entries/save', { entries: payload })
    toast.value = { type: 'success', text: '已保存并即时生效' }
    await refreshAll()
  } catch (e: any) {
    toast.value = { type: 'error', text: `保存失败：${e?.message || e}` }
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  loading.value = true
  try {
    const data = (await bridge.apiPost('settings/save', { ...draft.value })) as any
    endpointBase.value = data?.endpoint_base || endpointBase.value
    toast.value = { type: 'success', text: '网关设置已保存并重启' }
    await refreshAll()
  } catch (e: any) {
    toast.value = { type: 'error', text: `保存失败：${e?.message || e}` }
  } finally {
    loading.value = false
  }
}

async function addEntry() {
  entries.value.push(blankEntry())
  await saveEntries()
  await loadTopology()
}

async function removeSelectedEntry() {
  const entry = selectedEntry.value
  if (!entry) return
  const index = entries.value.findIndex((e) => e.id === entry.id)
  if (index < 0) return
  entries.value.splice(index, 1)
  topologySelected.value = null
  await saveEntries()
  await loadTopology()
}

async function saveSelectedEntry() {
  await saveEntries()
  await loadTopology()
}

function onTopologySelect(node: GraphNode | null) {
  topologySelected.value = node
  detailTab.value = 'config'
}

/** 节点类型的中文名。 */
function kindText(kind: string): string {
  if (kind === 'gateway') return '网关'
  if (kind === 'api') return 'API 入口'
  if (kind === 'client') return '接入对象'
  return kind
}

function stopTopologyTimer() {
  if (topologyTimer !== null) {
    window.clearInterval(topologyTimer)
    topologyTimer = null
  }
}

function toggleTopologyAuto(on: boolean) {
  stopTopologyTimer()
  if (on) {
    topologyTimer = window.setInterval(refreshAll, 5000)
  }
}

onMounted(async () => {
  await refreshAll()
})

onBeforeUnmount(() => {
  stopTopologyTimer()
})
</script>

<template>
  <n-config-provider :theme-overrides="themeOverrides(theme)">
    <div class="page">
      <header class="head">
        <n-space align="center">
          <n-text strong>Jev 决策网关</n-text>
          <n-tag :type="running ? 'success' : 'error'" size="small" round>
            {{ running ? '运行中' : '未运行' }}
          </n-tag>
          <n-text depth="3" style="font-size: 12px">代理地址 {{ endpointBase || '—' }}</n-text>
          <n-tag v-if="accessTokenSet" type="warning" size="small" round>已设访问令牌</n-tag>
        </n-space>
        <n-space align="center">
          <n-text depth="3" style="font-size: 12px">自动刷新</n-text>
          <n-switch v-model:value="topologyAuto" size="small" @update:value="toggleTopologyAuto" />
          <n-button size="small" quaternary :loading="loading" @click="refreshAll()">刷新</n-button>
        </n-space>
      </header>

      <n-alert
        v-if="toast"
        :type="toast.type"
        closable
        style="margin-bottom: 10px"
        @close="toast = null"
      >
        {{ toast.text }}
      </n-alert>

      <n-card size="small">
        <template #header>
          <n-space align="center" justify="space-between">
            <n-text>接入对象 → 网关 → API 入口</n-text>
            <n-space align="center">
              <n-button size="small" dashed @click="addEntry">添加入口</n-button>
            </n-space>
          </n-space>
        </template>

        <n-space vertical size="small">
          <n-text depth="3" style="font-size: 12px">
            点节点就能改配置、测一次、看余额。接入对象由客户端插件在请求里自报（请求头 X-Jev-Gateway-Client）。
          </n-text>

          <TopologyGraph
            :nodes="topologyNodes"
            :edges="topologyEdges"
            @select="onTopologySelect"
          />
        </n-space>
      </n-card>

      <n-card
        v-if="topologySelected"
        size="small"
        class="detail"
        :title="`${topologySelected.label} · ${kindText(topologySelected.kind)}`"
      >
        <n-space vertical size="medium">
          <div v-if="!isGatewayNode" class="status">
            <div class="section-title">运行状态</div>
            <div class="kv">
              <template v-for="(value, key) in topologySelected.meta || {}" :key="key">
                <span class="k">{{ key }}</span>
                <span class="v">{{ value }}</span>
              </template>
            </div>
          </div>

          <n-tabs v-if="isApiNode" v-model:value="detailTab" type="line" size="small" animated>
            <n-tab-pane name="config" tab="配置">
              <EntryForm
                v-if="selectedEntry"
                :entry="selectedEntry"
                :busy="loading"
                show-save
                @save="saveSelectedEntry"
              />
              <n-alert v-else type="warning" :show-icon="false">
                找不到这条入口的配置，可能已经被删掉了。
              </n-alert>
              <n-space v-if="selectedEntry" justify="end" style="margin-top: 10px">
                <n-popconfirm @positive-click="removeSelectedEntry">
                  <template #trigger>
                    <n-button size="small" quaternary type="error">删除这个入口</n-button>
                  </template>
                  删掉之后重新加回来即可，确定？
                </n-popconfirm>
              </n-space>
            </n-tab-pane>

            <n-tab-pane name="test" tab="测试">
              <TestPanel
                :protocol="selectedEntry?.kind || ''"
                :model="selectedEntry?.model || ''"
              />
            </n-tab-pane>

            <n-tab-pane name="balance" tab="余额">
              <BalancePanel
                :balance="selectedBalance"
                :entry-name="selectedEntry?.protocol || ''"
                @refresh="loadBalance()"
              />
            </n-tab-pane>
          </n-tabs>

          <GatewaySettings
            v-else-if="isGatewayNode"
            :draft="draft"
            :access-token-set="settings.access_token_set"
            :busy="loading"
            @save="saveSettings"
          />
        </n-space>
      </n-card>

      <n-text v-else depth="3" style="font-size: 12px; padding: 10px 2px">
        点上面图里的节点，配置、测试、余额都在那儿改。
      </n-text>
    </div>
  </n-config-provider>
</template>

<style scoped>
.page {
  padding: 12px 14px 24px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.detail {
  margin-top: 12px;
}

.status {
  margin-bottom: 4px;
}

.section-title {
  font-size: 12px;
  color: #6b7280;
  padding-bottom: 4px;
  margin-bottom: 8px;
  border-bottom: 1px solid rgba(128, 128, 128, 0.16);
}

.kv {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 5px 14px;
  font-size: 13px;
  align-items: baseline;
}

.k {
  color: #6b7280;
}

.v {
  color: #2f343a;
  word-break: break-all;
}
</style>
