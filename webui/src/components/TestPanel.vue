<script setup lang="ts">
/** 对选中的 API 入口发一次真实请求，看网关回了什么。 */
import { ref } from 'vue'
import { NAlert, NButton, NFormItem, NSelect, NSpace, NText } from 'naive-ui'
import { useBridge } from '@/composables/useBridge'

const props = defineProps<{
  /** 选中的入口；为空时不能测 */
  protocol: string
  model?: string
}>()

const bridge = useBridge()

const state = ref('群里有人在问：明天开会吗？')
const questions = ref(
  JSON.stringify(
    { should_reply: { type: 'noul', instructions: 'Should we reply to this message?' } },
    null,
    2,
  ),
)
const busy = ref(false)
const result = ref<any>(null)
const error = ref('')

async function send() {
  error.value = ''
  let parsed: unknown
  try {
    parsed = JSON.parse(questions.value)
  } catch (e) {
    error.value = 'questions 不是合法 JSON'
    return
  }
  busy.value = true
  result.value = null
  try {
    const data = (await bridge.apiPost('test', {
      protocol: props.protocol,
      model: props.model || '',
      state: state.value,
      questions: parsed,
    })) as any
    result.value = data
  } catch (e: any) {
    error.value = e?.message || String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="test-panel">
    <n-form label-placement="top" :show-feedback="false">
      <n-grid :x-gap="12" :y-gap="6" cols="1 700 2">
        <n-grid-item>
          <n-form-item label="走哪个协议" label-placement="top">
            <n-input :value="protocol" readonly placeholder="选中 API 入口后自动填上" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label="模型名（留空按入口配置）" label-placement="top">
            <n-input :value="model || ''" readonly placeholder="按入口配置" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item span="1 700 2">
          <n-form-item label="上下文 state" label-placement="top">
            <n-input v-model:value="state" type="textarea" :rows="2" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item span="1 700 2">
          <n-form-item label="问题 questions（JSON）" label-placement="top">
            <n-input v-model:value="questions" type="textarea" :rows="6" />
          </n-form-item>
        </n-grid-item>
      </n-grid>
    </n-form>

    <n-space align="center" justify="space-between">
      <n-text depth="3" style="font-size: 12px">请求经网关发出，实际命中哪个上游由负载均衡决定。</n-text>
      <n-button type="primary" size="small" :loading="busy" :disabled="!protocol" @click="send">发送</n-button>
    </n-space>

    <n-alert v-if="error" type="error" :show-icon="false" style="margin-top: 10px">
      {{ error }}
    </n-alert>

    <div v-if="result" class="result">
      <n-space align="center" size="small">
        <n-tag size="small" round :type="result.status === 200 ? 'success' : 'error'">
          {{ result.status }}
        </n-tag>
        <n-text depth="3" style="font-size: 12px">耗时 {{ result.elapsed_ms }} ms</n-text>
      </n-space>
      <pre class="json">{{ JSON.stringify(result.response, null, 2) }}</pre>
    </div>
  </div>
</template>

<style scoped>
.test-panel {
  width: 100%;
}

.result {
  margin-top: 10px;
}

.json {
  margin: 8px 0 0;
  padding: 10px;
  border-radius: 6px;
  background: rgba(128, 128, 128, 0.08);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow: auto;
}
</style>
