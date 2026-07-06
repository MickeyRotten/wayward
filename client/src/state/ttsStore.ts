import { create } from 'zustand'
import type { ChatMessage, TtsStatus } from '@shared/types/models'
import { api } from '../lib/api'
import { buildMemberResolver, parseSegments } from '../lib/narration'
import { usePartyStore } from './partyStore'
import { useSettingsStore } from './settingsStore'
import { useChatStore } from './chatStore'

// One segment queued for speech: the original segment index (for highlighting)
// plus the text and the voice to speak it with ('narrator' or a character id).
interface SpeakItem {
  index: number
  text: string
  voice: string
}

interface TtsState {
  status: TtsStatus | null
  // The segment currently being voiced (keys SegmentedNarration highlighting).
  playing: { messageId: number; segmentIndex: number } | null
  error: string | null
  fetchStatus: () => Promise<void>
  speakMessage: (message: ChatMessage) => Promise<void>
  runForTurn: (turn: number) => Promise<void>
  stop: () => void
}

// Module-level playback machinery: a single audio element, and a generation
// token so stop()/a newer speakMessage invalidates stale async continuations.
let _audio: HTMLAudioElement | null = null
let _playToken = 0

function getAudio(): HTMLAudioElement {
  if (!_audio) _audio = new Audio()
  return _audio
}

function playUrl(url: string): Promise<void> {
  return new Promise((resolve) => {
    const audio = getAudio()
    const cleanup = () => {
      audio.onended = null
      audio.onerror = null
      resolve()
    }
    audio.onended = cleanup
    audio.onerror = cleanup
    audio.src = url
    audio.play().catch(cleanup)
  })
}

export const useTtsStore = create<TtsState>((set, get) => ({
  status: null,
  playing: null,
  error: null,

  fetchStatus: async () => {
    try {
      set({ status: await api.get<TtsStatus>('/tts/status') })
    } catch {
      // status is a nicety — a failed fetch just leaves it unknown
    }
  },

  speakMessage: async (message) => {
    const settings = useSettingsStore.getState()
    if (!settings.ttsEnabled) return
    const status = get().status
    if (status && !status.installed) return
    if (message.role !== 'assistant' || (message.mode ?? 'narrator') === 'planner') return

    const resolver = buildMemberResolver(usePartyStore.getState().partyMembers)
    const segments = parseSegments(message.content, resolver)
    const items: SpeakItem[] = []
    segments.forEach((seg, i) => {
      // Narration + inscriptions (and NPC lines, which stay narration) use the
      // narrator voice; party dialogue uses that member's cloned voice.
      if (seg.type === 'narration' || seg.type === 'blockquote') {
        items.push({ index: i, text: seg.text, voice: 'narrator' })
      } else if (seg.type === 'dialogue') {
        items.push({ index: i, text: seg.text, voice: seg.member.id })
      }
    })
    if (items.length === 0) return

    get().stop()
    const token = ++_playToken
    set({ error: null })

    // Memoized per-item synthesis requests so item i+1 can be prefetched while
    // item i is playing (CPU synthesis is slow; this hides most of the gap).
    const urls: (Promise<string | null> | undefined)[] = []
    const requestUrl = (i: number): Promise<string | null> => {
      let p = urls[i]
      if (p === undefined) {
        p = api
          .post<{ url: string }>('/tts/speak', { text: items[i].text, voice: items[i].voice })
          .then((r) => r.url)
          .catch((e: unknown) => {
            const msg = e instanceof Error ? e.message : 'TTS request failed'
            // 503 = not installed → stop trying and refresh availability.
            if (msg.startsWith('503')) {
              _playToken++
              void get().fetchStatus()
            }
            set({ error: msg })
            return null
          })
        urls[i] = p
      }
      return p
    }

    for (let i = 0; i < items.length; i++) {
      const url = await requestUrl(i)
      if (_playToken !== token) return
      if (!url) continue // synth failure mid-queue: skip, keep going
      if (i + 1 < items.length) void requestUrl(i + 1)
      set({ playing: { messageId: message.id, segmentIndex: items[i].index } })
      await playUrl(url)
      if (_playToken !== token) return
    }
    set({ playing: null })
  },

  // Autoplay entry: speak the just-finished narration turn (highest variant).
  runForTurn: async (turn) => {
    const settings = useSettingsStore.getState()
    if (!settings.ttsEnabled || !settings.ttsAutoplay) return
    if (get().status === null) await get().fetchStatus()
    const status = get().status
    if (!status?.installed) return

    const candidates = useChatStore
      .getState()
      .messages.filter(
        (m) =>
          m.role === 'assistant' && (m.mode ?? 'narrator') !== 'planner' && m.turnNumber === turn,
      )
    if (candidates.length === 0) return
    const latest = candidates.reduce((a, b) => (b.variant >= a.variant ? b : a))
    await get().speakMessage(latest)
  },

  stop: () => {
    _playToken++
    const audio = _audio
    if (audio) {
      audio.pause()
      audio.onended = null
      audio.onerror = null
    }
    set({ playing: null })
  },
}))
