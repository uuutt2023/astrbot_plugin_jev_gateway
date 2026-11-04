<script setup lang="ts">
/** 网关自身的设置表单。配置页与拓扑页共用。 */
import {
  NButton,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NText,
} from 'naive-ui'

export interface GatewayDraft {
  host: string
  port: number
  advertised_url: string
  access_token: string
  lb_strategy: string
}

defineProps<{
  draft: GatewayDraft
  accessTokenSet?: boolean
  busy?: boolean
}>()

const emit = defineEmits<{
  (e: 'save'): void
}>()

const STRATEGY_OPTIONS = [
  { label: '轮询', value: 'round_robin' },
  { label: '随机', value: 'random' },
  { label: '加权', value: 'weighted' },
  { label: '最少失败', value: 'least_failure' },
]
</script>

<template>
  <div class="gateway-settings">
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
        <n-form-item label="负载均衡策略" label-placement="top" :show-feedback="false">
          <n-select v-model:value="draft.lb_strategy" :options="STRATEGY_OPTIONS" />
        </n-form-item>
      </n-grid-item>
      <n-grid-item>
        <n-form-item label="访问令牌" label-placement="top" :show-feedback="false">
          <n-input
            v-model:value="draft.access_token"
            type="password"
            show-password-on="click"
            :placeholder="accessTokenSet ? '已设置，留空不改' : '留空＝不校验'"
          />
        </n-form-item>
      </n-grid-item>
    </n-grid>

    <n-space justify="space-between" align="center">
      <n-text depth="3" style="font-size: 12px">
        跨容器/跨机器访问要把监听地址改成 0.0.0.0，对外地址填别的容器能访问到的地址。
      </n-text>
      <n-button type="primary" size="small" :loading="busy" @click="emit('save')">保存并重启</n-button>
    </n-space>
  </div>
</template>

<style scoped>
.gateway-settings {
  width: 100%;
}
</style>
