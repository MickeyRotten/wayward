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

/** Read the stored size and set the CSS var. Call once on app init so the
 *  preference is applied before the chat renders. */
export function applyChatFontSize() {
  applyVar(readStored())
}

interface AppearanceState {
  chatFontSize: ChatFontSize
  setChatFontSize: (size: ChatFontSize) => void
}

export const useAppearanceStore = create<AppearanceState>((set) => ({
  chatFontSize: readStored(),
  setChatFontSize: (size) => {
    try {
      localStorage.setItem(STORAGE_KEY, size)
    } catch {
      // ignore storage failures (private mode, etc.)
    }
    applyVar(size)
    set({ chatFontSize: size })
  },
}))
