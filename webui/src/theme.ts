/** 明暗主题：跟随 AstrBot 页面主题，没取到就存本地。 */
import type { GlobalThemeOverrides } from 'naive-ui'

export type ThemeMode = 'light' | 'dark'

const THEME_STORAGE_KEY = 'jev-gateway-theme'

export function loadThemeMode(): ThemeMode {
  try {
    const root = document.documentElement.dataset.theme
    if (root === 'dark' || root === 'light') return root
    return localStorage.getItem(THEME_STORAGE_KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function saveThemeMode(mode: ThemeMode) {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, mode)
  } catch {
    /* 隐私模式下忽略 */
  }
}

export function detectThemeMode(): ThemeMode {
  try {
    const root = document.documentElement.dataset.theme
    if (root === 'dark' || root === 'light') return root
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function themeOverrides(mode: ThemeMode): GlobalThemeOverrides {
  return mode === 'dark'
    ? {
        common: {
          primaryColor: '#4f9cf9',
          primaryColorHover: '#6aabfb',
          primaryColorPressed: '#3b86e0',
          borderRadius: '6px',
        },
      }
    : {
        common: {
          primaryColor: '#2563eb',
          primaryColorHover: '#3b82f6',
          primaryColorPressed: '#1d4ed8',
          borderRadius: '6px',
        },
      }
}
