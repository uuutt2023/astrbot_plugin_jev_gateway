import { createApp } from 'vue'
import { Icon } from '@iconify/vue'
import App from './App.vue'
import { loadThemeMode } from './theme'

// 首帧前同步主题到根节点，避免明暗切换闪烁
document.documentElement.dataset.theme = loadThemeMode()

const app = createApp(App)
app.component('Icon', Icon)
app.mount('#app')
