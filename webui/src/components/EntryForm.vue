<script setup lang="ts">
/** 单个 API 入口的配置表单。配置页与拓扑页共用。 */
import { computed } from 'vue'
import {
  NButton,
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
  /** 是否自带保存按钮。配置页有全局「保存」，这里就不重复放 */
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
  <div class="entry-form">
    <n-grid :x-gap="12" :y-gap="6" cols="1 600 2 900 3">
      <n-grid-item>
        <n-form-item label="入口名称" label-placement="top" :show-feedback="false">
          <n-input v-model:value="entry.protocol" placeholder="主 Key / 备用 Key" />
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
        <n-form-item label="优先级" label-placement="top" :show-feedback="false">
          <n-input-number v-model:value="entry.priority" :min="1" :max="999" style="width: 100%" />
        </n-form-item>
      </n-grid-item>
      <n-grid-item>
        <n-form-item label="权重" label-placement="top" :show-feedback="false">
          <n-input-number v-model:value="entry.weight" :min="0" :max="999" style="width: 100%" />
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
            :placeholder="keyPlaceholder"
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

    <n-space v-if="showSave" justify="end">
      <n-button type="primary" size="small" :loading="busy" @click="emit('save')">保存这个入口</n-button>
    </n-space>
  </div>
</template>

<style scoped>
.entry-form {
  width: 100%;
}
</style>
