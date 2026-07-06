import { useRef, useState } from 'react'
import { deleteCharacterVoice, uploadCharacterVoice } from '../lib/voice'

/**
 * Voice-sample controls for a character sheet: upload ~10s of clean speech to
 * clone this character's TTS voice, play it back, or remove it. Renders under
 * the portrait on the PC / party-member sheets.
 */
export function VoiceBlock({
  characterId,
  hasVoice,
  onUpdated,
}: {
  characterId: string
  hasVoice?: boolean
  onUpdated: () => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [busy, setBusy] = useState(false)
  const [playing, setPlaying] = useState(false)

  const handleUpload = async (file: File) => {
    setBusy(true)
    try {
      if (await uploadCharacterVoice(characterId, file)) onUpdated()
    } finally {
      setBusy(false)
    }
  }

  const handlePlay = () => {
    if (playing) {
      audioRef.current?.pause()
      setPlaying(false)
      return
    }
    // Cache-bust: the URL is stable but the sample file can be replaced.
    const audio = new Audio(`/api/characters/${characterId}/voice?t=${Date.now()}`)
    audioRef.current = audio
    audio.onended = () => setPlaying(false)
    audio.onerror = () => setPlaying(false)
    setPlaying(true)
    void audio.play().catch(() => setPlaying(false))
  }

  const handleRemove = async () => {
    audioRef.current?.pause()
    setPlaying(false)
    setBusy(true)
    try {
      if (await deleteCharacterVoice(characterId)) onUpdated()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span className="font-ui text-[9px] text-textdim tracking-wider">VOICE</span>
      <button
        type="button"
        disabled={busy}
        className="font-ui text-[9px] text-textdim hover:text-text border border-line px-1.5 py-0.5 disabled:opacity-40"
        title="Upload ~10 seconds of clean speech to clone this character's voice"
        onClick={() => inputRef.current?.click()}
      >
        {hasVoice ? 'REPLACE SAMPLE' : 'UPLOAD SAMPLE'}
      </button>
      {hasVoice && (
        <>
          <button
            type="button"
            className="font-ui text-[9px] text-textdim hover:text-text border border-line px-1.5 py-0.5"
            onClick={handlePlay}
          >
            {playing ? '■ STOP' : '▶ PLAY'}
          </button>
          <button
            type="button"
            disabled={busy}
            className="font-ui text-[9px] text-textdim hover:text-danger border border-line px-1.5 py-0.5 disabled:opacity-40"
            onClick={() => void handleRemove()}
          >
            REMOVE
          </button>
        </>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="audio/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void handleUpload(file)
          e.target.value = ''
        }}
      />
    </div>
  )
}
