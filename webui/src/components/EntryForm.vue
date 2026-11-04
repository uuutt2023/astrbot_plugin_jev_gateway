<script setup lang="ts">
/** 单个 API 入口的配置表单。拓扑详情里点节点就能改。 */
import { computed } from 'vue'
import {
  NButton,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
} from 'naive-ui'

export interface Entry {
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

const props = defineProps<{
  entry: Entry
  busy?: boolean
  /** 是否自带保存按钮。列表页有全局「保存」，这里就不重复放 */
  showSave?: boolean
}>()

const emit = defineEmits<{
  (e: 'save'): void
}>()

const KIND_OPTIONS = [
  { label: 'SystemOne（官方 Jev / TypeSafe）', value: 'systemone' },
  { label: 'OpenAI Decisions', value: 'decisions' },
  { label: 'Custom（自定义协议）', value: 'custom' },
]

const keyPlaceholder = computed(() => props.entry.key_masked || 'sk- 开头')
</script>

<template>
  <n-form label-placement="top" :show-feedback="false" class="entry-form">
    <section class="section">
      <div class="section-title">基本信息</div>
      <n-grid :x-gap="14" :y-gap="4" cols="1 640 2 1000 3">
        <n-grid-item>
          <n-form-item label="入口名称">
            <n-input v-model:value="entry.protocol" placeholder="主 Key / 备用 Key" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label="协议类型">
            <n-select v-model:value="entry.kind" :options="KIND_OPTIONS" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label="模型名">
            <n-input v-model:value="entry.model" placeholder="jev-latest" />
          </n-form-item>
        </n-grid-item>
      </n-grid>
    </section>

    <section class="section">
      <div class="section-title">连接</div>
      <n-grid :x-gap="14" :y-gap="4" cols="1 640 2 1000 3">
        <n-grid-item span="1 640 2 1000 3">
          <n-form-item label="接口地址">
            <n-input v-model:value="entry.base_url" placeholder="https://jevmodel.org" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label="端点路径">
            <n-input v-model:value="entry.endpoint_path" placeholder="留空按类型默认" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label="API Key">
            <n-input
              v-model:value="entry.api_key"
              type="password"
              show-password-on="click"
              :placeholder="keyPlaceholder"
            />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label="超时（秒）">
            <n-input-number v-model:value="entry.timeout" :min="1" :max="300" style="width: 100%" />
          </n-form-item>
        </n-grid-item>
      </n-grid>
    </section>

    <section class="section">
      <div class="section-title">调度</div>
      <n-grid :x-gap="14" :y-gap="4" cols="1 640 2 1000 3">
        <n-grid-item>
          <n-form-item label="优先级">
            <n-input-number v-model:value="entry.priority" :min="1" :max="999" style="width: 100%" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label="权重">
            <n-input-number v-model:value="entry.weight" :min="0" :max="999" style="width: 100%" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label=" ">
            <n-text depth="3" style="font-size: 12px">数字越小越优先；权重只在「加权」策略下生效。</n-text>
          </n-form-item>
        </n-grid-item>
      </n-grid>
    </section>

    <section class="section">
      <div class="section-title">余额</div>
      <n-grid :x-gap="14" :y-gap="4" cols="1 640 2 1000 3">
        <n-grid-item>
          <n-form-item label="余额查询地址">
            <n-input v-model:value="entry.balance_url" placeholder="留空＝不查" />
          </n-form-item>
        </n-grid-item>
        <n-grid-item>
          <n-form-item label="余额字段">
            <n-input v-model:value="entry.balance_field" placeholder="如 data.balance" />
          </n-form-item>
        </n-grid-item>
      </n-grid>
    </section>

    <n-space v-if="showSave" justify="end">
      <n-button type="primary" size="small" :loading="busy" @click="emit('save')">保存这个入口</n-button>
    </n-space>
  </n-form>
</template>

<style scoped>
.entry-form {
  width: 100%;
}

.section {
  margin-bottom: 14px;
}

.section-title {
  font-size: 12px;
  color: #6b7280;
  padding-bottom: 4px;
  margin-bottom: 8px;
  border-bottom: 1px solid rgba(128, 128, 128, 0.16);
}
</style>
