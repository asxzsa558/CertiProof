import { create } from 'zustand'

const STORAGE_KEY = 'verisure-ui-settings'

const loadInitial = () => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return JSON.parse(saved)
  } catch (e) {}
  return { effectsEnabled: true }
}

const persist = (state) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      effectsEnabled: state.effectsEnabled,
    }))
  } catch (e) {}
}

export const useUIStore = create((set, get) => ({
  ...loadInitial(),
  toggleEffects: () => {
    const next = !get().effectsEnabled
    set({ effectsEnabled: next })
    persist({ ...get(), effectsEnabled: next })
  },
}))