import { create } from 'zustand'

// Device-local UI preference (not world/AI data) — persisted to localStorage,
// applied via a CSS variable so only the chat message prose scales.
export type ChatFontSize = 'small' | 'medium' | 'large' | 'xlarge'

const STORAGE_KEY = 'wayward.chatFontSize'

const SIZE_PX: Record<ChatFontSize, number> = {
  small: 13,
  medium: 14,
  large: 16,
  xlarge: 18,
}

export const CHAT_FONT_SIZES: { value: ChatFontSize; label: string }[] = [
  { value: 'small', label: 'Small' },
  { value: 'medium', label: 'Medium' },
  { value: 'large', label: 'Large' },
  { value: 'xlarge', label: 'Extra Large' },
]

function readStored(): ChatFontSize {
  const v = (typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY)) as ChatFontSize | null
  return v && v in SIZE_PX ? v : 'medium'
}

function applyVar(size: ChatFontSize) {
  document.documentElement.style.setProperty('--chat-font-size', `${SIZE_PX[size]}px`)
}

// Chat background opacity — how strongly the chat's dark wash covers the
// backdrop art (percent; 100 = solid like before backdrops existed).
const OPACITY_KEY = 'wayward.chatBgOpacity'
export const DEFAULT_CHAT_BG_OPACITY = 85

function readStoredOpacity(): number {
  const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(OPACITY_KEY) : null
  const n = raw === null ? NaN : Number(raw)
  return Number.isFinite(n) ? Math.min(100, Math.max(0, Math.round(n))) : DEFAULT_CHAT_BG_OPACITY
}

function applyOpacityVar(pct: number) {
  document.documentElement.style.setProperty('--chat-overlay-opacity', String(pct / 100))
}

/** Read the stored size + opacity and set the CSS vars. Call once on app init
 *  so the preferences are applied before the chat renders. */
export function applyChatFontSize() {
  applyVar(readStored())
  applyOpacityVar(readStoredOpacity())
}

interface AppearanceState {
  chatFontSize: ChatFontSize
  chatBgOpacity: number
  setChatFontSize: (size: ChatFontSize) => void
  setChatBgOpacity: (pct: number) => void
}

export const useAppearanceStore = create<AppearanceState>((set) => ({
  chatFontSize: readStored(),
  chatBgOpacity: readStoredOpacity(),
  setChatFontSize: (size) => {
    try {
      localStorage.setItem(STORAGE_KEY, size)
    } catch {
      // ignore storage failures (private mode, etc.)
    }
    applyVar(size)
    set({ chatFontSize: size })
  },
  setChatBgOpacity: (pct) => {
    const clamped = Math.min(100, Math.max(0, Math.round(pct)))
    try {
      localStorage.setItem(OPACITY_KEY, String(clamped))
    } catch {
      // ignore storage failures (private mode, etc.)
    }
    applyOpacityVar(clamped)
    set({ chatBgOpacity: clamped })
  },
}))
