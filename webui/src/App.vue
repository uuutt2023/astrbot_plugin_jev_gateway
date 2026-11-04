<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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
import { useBridge } from '@/composables/useBridge'
import { detectThemeMode, themeOverrides } from '@/theme'

interface Entry {
  protocol: string
  kind: string
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
const settings = ref({ host: '127.0.0.1', port: 8770, advertised_url: '', access_token_set: false })
const draft = ref({ host: '127.0.0.1', port: 8770, advertised_url: '', access_token: '' })

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

const KIND_OPTIONS = [
  { label: 'SystemOne（官方 Jev / TypeSafe）', value: 'systemone' },
  { label: 'OpenAI Decisions', value: 'decisions' },
  { label: '自定义协议', value: 'custom' },
]

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
    }
    draft.value = {
      host: settings.value.host,
      port: settings.value.port,
      advertised_url: settings.value.advertised_url,
      access_token: '',
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

async function loadBalance() {
  try {
    const data = (await bridge.apiGet('balance')) as any
    balances.value = data || {}
  } catch (e: any) {
    toast.value = { type: 'error', text: `查余额失败：${e?.message || e}` }
  }
}

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
                <n-grid :x-gap="12" :y-gap="6" cols="1 600 2 900 4">
                  <n-grid-item>
                    <n-form-item label="监听地址" label-placement="top" :show-feedback="false">
                      <n-input v-model:value="draft.host" placeholder="127.0.0.1" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item label="监听端口" label-placement="top" :show-feedback="false">
                      <n-input-number v-model:value="draft.port" :min="1" :max="65535" style="width: 100%" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item label="对外地址" label-placement="top" :show-feedback="false">
                      <n-input v-model:value="draft.advertised_url" placeholder="Docker 里填 http://容器名:8770" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item label="访问令牌" label-placement="top" :show-feedback="false">
                      <n-input
                        v-model:value="draft.access_token"
                        type="password"
                        show-password-on="click"
                        :placeholder="settings.access_token_set ? '已设置，留空不改' : '留空＝不校验'"
                      />
                    </n-form-item>
                  </n-grid-item>
                </n-grid>
                <n-space justify="space-between" align="center">
                  <n-text depth="3" style="font-size: 12px">
                    跨容器/跨机器访问要把监听地址改成 0.0.0.0，对外地址填别的容器能访问到的地址。
                  </n-text>
                  <n-button type="primary" size="small" :loading="loading" @click="saveSettings">保存并重启</n-button>
                </n-space>
              </n-card>

              <n-card v-for="(entry, index) in entries" :key="index" size="small" :title="entry.protocol || '新入口'">
                <template #header-extra>
                  <n-button size="tiny" quaternary type="error" @click="removeEntry(index)">删除</n-button>
                </template>
                <n-grid :x-gap="12" :y-gap="6" cols="1 600 2 900 3">
                  <n-grid-item>
                    <n-form-item label="协议名" label-placement="top" :show-feedback="false">
                      <n-input v-model:value="entry.protocol" placeholder="systemone" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item label="协议类型" label-placement="top" :show-feedback="false">
                      <n-select v-model:value="entry.kind" :options="KIND_OPTIONS" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item label="超时（秒）" label-placement="top" :show-feedback="false">
                      <n-input-number v-model:value="entry.timeout" :min="1" :max="300" style="width: 100%" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item label="接口地址" label-placement="top" :show-feedback="false">
                      <n-input v-model:value="entry.base_url" placeholder="https://jevmodel.org" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item label="API Key" label-placement="top" :show-feedback="false">
                      <n-input
                        v-model:value="entry.api_key"
                        type="password"
                        show-password-on="click"
                        :placeholder="entry.key_masked || 'sk- 开头'"
                      />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item label="模型名" label-placement="top" :show-feedback="false">
                      <n-input v-model:value="entry.model" placeholder="jev-latest" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item label="端点路径" label-placement="top" :show-feedback="false">
                      <n-input v-model:value="entry.endpoint_path" placeholder="留空按类型默认" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item label="余额查询地址" label-placement="top" :show-feedback="false">
                      <n-input v-model:value="entry.balance_url" placeholder="留空＝不查" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item>
                    <n-form-item label="余额字段" label-placement="top" :show-feedback="false">
                      <n-input v-model:value="entry.balance_field" placeholder="如 data.balance" />
                    </n-form-item>
                  </n-grid-item>
                </n-grid>
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
