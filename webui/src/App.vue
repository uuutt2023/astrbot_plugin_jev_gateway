<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  NButton,
  NCard,
  NConfigProvider,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSpin,
  NTabPane,
  NTabs,
  NTag,
  NAlert,
  NText,
} from 'naive-ui'
import EntryForm from '@/components/EntryForm.vue'
import GatewaySettings from '@/components/GatewaySettings.vue'
import TopologyGraph from '@/components/TopologyGraph.vue'
import type { GraphEdge, GraphNode } from '@/graph/types'
import { useBridge } from '@/composables/useBridge'
import { detectThemeMode, themeOverrides } from '@/theme'

interface Entry {
  id?: string
  protocol: string
  kind: string
  priority: number
  weight: number
  base_url: string
  api_key: string
  model: string
  endpoint_path: string
  timeout: number
  balance_url: string
  balance_field: string
  url?: string
  key_masked?: string
  primary?: boolean
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
const tab = ref('entries')
const loading = ref(false)

const running = ref(false)
const endpointBase = ref('')
const accessTokenSet = ref(false)
const entries = ref<Entry[]>([])
const settings = ref({
  host: '127.0.0.1', port: 8770, advertised_url: '', access_token_set: false,
  lb_strategy: 'round_robin',
})
const draft = ref({
  host: '127.0.0.1', port: 8770, advertised_url: '', access_token: '', lb_strategy: 'round_robin',
})

const balances = ref<Record<string, Balance>>({})
const testProtocol = ref('')
const testState = ref('群里有人在问：明天开会吗？')
const testQuestions = ref(
  JSON.stringify(
    {
      should_reply: { type: 'noul', instructions: 'Is this message worth replying to?' },
    },
    null,
    2,
  ),
)
const testResult = ref<any>(null)
const testBusy = ref(false)

// 拓扑图
const topologyNodes = ref<GraphNode[]>([])
const topologyEdges = ref<GraphEdge[]>([])
const topologyGateway = ref<Record<string, any>>({})
const topologySelected = ref<GraphNode | null>(null)
const topologyAuto = ref(false)
let topologyTimer: number | null = null

// 拓扑里选中的 API 节点 → 配置列表里那一条
const selectedEntry = computed(() => {
  const node = topologySelected.value
  if (!node || node.kind !== 'api') return null
  const entryId = node.id.replace(/^api:/, '')
  return entries.value.find((e) => e.id === entryId) || null
})

const protocolOptions = computed(() =>
  entries.value.map((e) => ({ label: e.protocol, value: e.protocol })),
)

const balanceRows = computed(() =>
  Object.entries(balances.value).map(([protocol, b]) => ({
    protocol,
    ...b,
    text: b.value === null || b.value === undefined ? '—' : String(b.value),
    updated: b.updated_at ? new Date(b.updated_at * 1000).toLocaleString() : '—',
  })),
)

function blankEntry(): Entry {
  return {
    protocol: '',
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
    if (!testProtocol.value && entries.value.length) {
      testProtocol.value = entries.value[0].protocol
    }
  } catch (e: any) {
    toast.value = { type: 'error', text: `读取入口失败：${e?.message || e}` }
  } finally {
    loading.value = false
  }
}

async function saveEntries() {
  loading.value = true
  try {
    // Key 留空表示不改：后端会沿用原来的明文 Key
    const payload = entries.value.map((e) => ({ ...e, api_key: e.api_key || '' }))
    await bridge.apiPost('entries/save', { entries: payload })
    toast.value = { type: 'success', text: '已保存并即时生效' }
    await loadEntries()
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
    await loadEntries()
  } catch (e: any) {
    toast.value = { type: 'error', text: `保存失败：${e?.message || e}` }
  } finally {
    loading.value = false
  }
}

function addEntry() {
  entries.value.push(blankEntry())
}

function removeEntry(index: number) {
  entries.value.splice(index, 1)
}

async function runTest() {
  let questions: any
  try {
    questions = JSON.parse(testQuestions.value)
  } catch (e: any) {
    toast.value = { type: 'error', text: `questions 不是合法 JSON：${e?.message || e}` }
    return
  }
  testBusy.value = true
  testResult.value = null
  try {
    const data = (await bridge.apiPost('test', {
      protocol: testProtocol.value,
      state: testState.value,
      questions,
    })) as any
    testResult.value = data
    if (data.status >= 200 && data.status < 300) {
      toast.value = { type: 'success', text: `请求成功（${data.status}，${data.elapsed_ms}ms）` }
    } else {
      toast.value = { type: 'warning', text: `上游返回 ${data.status}` }
    }
    await loadBalance()
  } catch (e: any) {
    toast.value = { type: 'error', text: `测试失败：${e?.message || e}` }
  } finally {
    testBusy.value = false
  }
}

function onTopologySelect(node: GraphNode | null) {
  console.log('[app] onTopologySelect', node && node.id)
  topologySelected.value = node
}

async function saveSelectedEntry() {
  await saveEntries()
  await loadTopology()
}

async function loadTopology() {
  try {
    const data = (await bridge.apiGet('topology')) as any
    topologyNodes.value = data.nodes || []
    topologyEdges.value = data.edges || []
    topologyGateway.value = data.gateway || {}
  } catch (e) {
    // 拓扑取不到不影响别的页签
  }
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
    topologyTimer = window.setInterval(loadTopology, 5000)
  }
}

async function loadBalance() {
  try {
    const data = (await bridge.apiGet('balance')) as any
    balances.value = data || {}
  } catch (e: any) {
    toast.value = { type: 'error', text: `查余额失败：${e?.message || e}` }
  }
}

// 只有停留在拓扑页签时才轮询
watch(tab, (value) => {
  if (value === 'topology') {
    loadTopology()
    toggleTopologyAuto(topologyAuto.value)
  } else {
    stopTopologyTimer()
  }
})

onBeforeUnmount(() => {
  stopTopologyTimer()
})

onMounted(async () => {
  await bridge.init()
  await loadEntries()
  await loadBalance()
})
</script>

<template>
  <n-config-provider :theme-overrides="themeOverrides(theme)">
    <div class="page">
      <n-space align="center" justify="space-between" style="margin-bottom: 12px">
        <n-space align="center">
          <n-text strong>Jev 决策网关</n-text>
          <n-tag :type="running ? 'success' : 'error'" size="small" round>
            {{ running ? '运行中' : '未运行' }}
          </n-tag>
          <n-text depth="3" style="font-size: 12px">代理地址 {{ endpointBase || '—' }}</n-text>
          <n-tag v-if="accessTokenSet" type="warning" size="small" round>已设访问令牌</n-tag>
        </n-space>
        <n-button size="small" quaternary @click="loadEntries()">刷新</n-button>
      </n-space>

      <n-alert
        v-if="toast"
        :type="toast.type"
        closable
        style="margin-bottom: 10px"
        @close="toast = null"
      >
        {{ toast.text }}
      </n-alert>

      <n-tabs v-model:value="tab" type="line" animated>
        <!-- 配置 -->
        <n-tab-pane name="entries" tab="配置">
          <n-spin :show="loading">
            <n-space vertical size="medium">
              <n-card size="small" title="网关设置">
                <GatewaySettings
                  :draft="draft"
                  :access-token-set="settings.access_token_set"
                  :busy="loading"
                  @save="saveSettings"
                />
              </n-card>

              <n-card v-for="(entry, index) in entries" :key="entry.id || index" size="small" :title="entry.protocol || '新入口'">
                <template #header-extra>
                  <n-button size="tiny" quaternary type="error" @click="removeEntry(index)">删除</n-button>
                </template>
                <EntryForm :entry="entry" :busy="loading" @save="saveEntries" />
              </n-card>

              <n-space justify="space-between">
                <n-button size="small" dashed @click="addEntry">添加入口</n-button>
                <n-button type="primary" size="small" :loading="loading" @click="saveEntries">保存</n-button>
              </n-space>
            </n-space>
          </n-spin>
        </n-tab-pane>

        <!-- 测试 -->
        <n-tab-pane name="test" tab="测试">
          <n-space vertical size="medium">
            <n-card size="small" title="发一次决策请求">
              <n-form label-placement="top">
                <n-space vertical size="small">
                  <n-space align="center">
                    <n-text style="width: 80px">协议</n-text>
                    <n-select
                      v-model:value="testProtocol"
                      :options="protocolOptions"
                      style="width: 260px"
                      placeholder="选一个协议"
                    />
                    <n-button type="primary" size="small" :loading="testBusy" @click="runTest">发送</n-button>
                  </n-space>
                  <n-space vertical size="small">
                    <n-text>state</n-text>
                    <n-input v-model:value="testState" type="textarea" :rows="3" placeholder="交给模型看的上下文" />
                  </n-space>
                  <n-space vertical size="small">
                    <n-text>questions（JSON）</n-text>
                    <n-input v-model:value="testQuestions" type="textarea" :rows="10" />
                  </n-space>
                </n-space>
              </n-form>
            </n-card>

            <n-card v-if="testResult" size="small" title="响应">
              <n-space vertical size="small">
                <n-space align="center">
                  <n-tag :type="testResult.status < 300 ? 'success' : 'error'" size="small" round>
                    HTTP {{ testResult.status }}
                  </n-tag>
                  <n-text depth="3" style="font-size: 12px">{{ testResult.elapsed_ms }} ms</n-text>
                </n-space>
                <pre class="json">{{
                  typeof testResult.response === 'string'
                    ? testResult.response
                    : JSON.stringify(testResult.response, null, 2)
                }}</pre>
              </n-space>
            </n-card>
          </n-space>
        </n-tab-pane>

        <!-- 拓扑 -->
        <n-tab-pane name="topology" tab="拓扑">
          <n-card size="small">
            <template #header>
              <n-space align="center" justify="space-between">
                <n-text>接入对象 → 网关 → API 入口</n-text>
                <n-space align="center">
                  <n-switch v-model:value="topologyAuto" size="small" @update:value="toggleTopologyAuto">
                    <template #checked>自动刷新</template>
                    <template #unchecked>自动刷新</template>
                  </n-switch>
                  <n-button size="small" quaternary @click="loadTopology()">刷新</n-button>
                </n-space>
              </n-space>
            </template>

            <n-space vertical size="small">
              <n-text depth="3" style="font-size: 12px">
                接入对象由客户端插件在请求里自报（请求头 X-Jev-Gateway-Client）；没自报的客户端不会出现在图里。
              </n-text>

              <TopologyGraph
                :nodes="topologyNodes"
                :edges="topologyEdges"
                @select="onTopologySelect"
              />

              <n-card v-if="topologySelected" size="small" :title="topologySelected.label">
                <n-space vertical size="medium">
                  <div v-if="topologySelected.kind !== 'gateway'">
                    <n-text depth="3" style="font-size: 12px">运行状态</n-text>
                    <div class="kv">
                      <template v-for="(value, key) in topologySelected.meta || {}" :key="key">
                        <span class="k">{{ key }}</span>
                        <span class="v">{{ value }}</span>
                      </template>
                    </div>
                  </div>

                  <div v-if="topologySelected.kind === 'gateway'">
                    <n-text depth="3" style="font-size: 12px">网关配置</n-text>
                    <GatewaySettings
                      :draft="draft"
                      :access-token-set="settings.access_token_set"
                      :busy="loading"
                      @save="saveSettings"
                    />
                  </div>

                  <div v-else-if="selectedEntry">
                    <n-text depth="3" style="font-size: 12px">入口配置</n-text>
                    <EntryForm
                      :entry="selectedEntry"
                      :busy="loading"
                      show-save
                      @save="saveSelectedEntry"
                    />
                  </div>

                  <n-alert v-else-if="topologySelected.kind === 'api'" type="warning" :show-icon="false">
                    找不到这条入口的配置，可能已经被删掉了。
                  </n-alert>
                </n-space>
              </n-card>
            </n-space>
          </n-card>
        </n-tab-pane>

        <!-- 余额 -->
        <n-tab-pane name="balance" tab="余额">
          <n-card size="small">
            <template #header>
              <n-space align="center" justify="space-between">
                <n-text>各入口余额</n-text>
                <n-button size="small" quaternary @click="loadBalance()">刷新</n-button>
              </n-space>
            </template>
            <n-space vertical size="small">
              <div v-for="row in balanceRows" :key="row.protocol" class="balance-row">
                <n-text strong style="min-width: 120px">{{ row.protocol }}</n-text>
                <n-text style="min-width: 140px">{{ row.text }} {{ row.unit || '' }}</n-text>
                <n-tag size="small" round>{{ row.source === 'custom' ? '自定义查询' : '响应里带的' }}</n-tag>
                <n-text depth="3" style="font-size: 12px">{{ row.updated }}</n-text>
                <n-text v-if="row.error" depth="3" style="font-size: 12px">{{ row.error }}</n-text>
              </div>
              <n-text v-if="!balanceRows.length" depth="3">还没有余额信息。发一次请求，或给入口配「余额查询地址」。</n-text>
            </n-space>
          </n-card>
        </n-tab-pane>
      </n-tabs>
    </div>
  </n-config-provider>
</template>

<style scoped>
.page {
  padding: 12px 14px 24px;
}
.balance-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.16));
}
.kv {
  display: grid;
  grid-template-columns: 170px 1fr;
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

.json {
  margin: 0;
  padding: 10px;
  border-radius: 6px;
  background: rgba(128, 128, 128, 0.08);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 420px;
  overflow: auto;
}
</style>
