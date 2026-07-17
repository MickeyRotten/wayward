// The chat composer — the freeform input under the action panel, with the
// fixed quick actions ("OR DO SOMETHING ELSE:"), the Tools menu, the image
// attach button, the pending-image preview, and SEND/STOP.

import { useRef, useEffect, useState } from 'react'
import { useChatStore } from '../../state/chatStore'
import { useSettingsStore } from '../../state/settingsStore'
import { useItemsStore } from '../../state/itemsStore'
import { ItemCard } from '../ItemCard'

export function Composer({
  showInputRegenerate,
  hasVisibleMessages,
  onSnapToBottom,
  onOpenRegenNote,
  onClearChat,
  onOpenSearch,
  onExportTranscript,
  onShowLog,
}: {
  showInputRegenerate: boolean
  hasVisibleMessages: boolean
  onSnapToBottom: () => void
  onOpenRegenNote: () => void
  onClearChat: () => void
  onOpenSearch: () => void
  onExportTranscript: () => void
  onShowLog: () => void
}) {
  const messages = useChatStore((s) => s.messages)
  const isLoading = useChatStore((s) => s.isLoading)
  const sendTurn = useChatStore((s) => s.sendTurn)
  const continueNarration = useChatStore((s) => s.continueNarration)
  const regenerate = useChatStore((s) => s.regenerate)
  const stopGeneration = useChatStore((s) => s.stopGeneration)
  const planningMode = useChatStore((s) => s.planningMode)
  const failedInput = useChatStore((s) => s.failedInput)
  const clearFailedInput = useChatStore((s) => s.clearFailedInput)
  const apiKeySet = useSettingsStore((s) => s.apiKeySet)
  const inventory = useItemsStore((s) => s.inventory)

  const inputLocked = isLoading

  const [input, setInput] = useState('')
  const [itemPickerOpen, setItemPickerOpen] = useState(false)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [pendingImage, setPendingImage] = useState<string | null>(null)  // data URL, attached to the next send
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)

  // Downscale an attached image client-side (phones produce 10+ MB photos) to
  // a JPEG data URL capped at 1024px on the long edge.
  const handleImageFile = (file: File) => {
    const reader = new FileReader()
    reader.onload = () => {
      const img = new Image()
      img.onload = () => {
        const MAX = 1024
        const scale = Math.min(1, MAX / Math.max(img.width, img.height))
        const canvas = document.createElement('canvas')
        canvas.width = Math.round(img.width * scale)
        canvas.height = Math.round(img.height * scale)
        canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height)
        setPendingImage(canvas.toDataURL('image/jpeg', 0.85))
      }
      img.src = reader.result as string
    }
    reader.readAsDataURL(file)
  }

  // A failed send restores the typed text into the (now empty) input box so a
  // generation error never eats the player's prose.
  useEffect(() => {
    if (!failedInput) return
    setInput((cur) => (cur.trim() ? cur : failedInput))
    clearFailedInput()
  }, [failedInput, clearFailedInput])

  // Auto-grow the input: single row by default, expand with wrapped lines up
  // to a cap, then scroll.
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [input])

  const handleSend = () => {
    const text = input.trim()
    if ((!text && !pendingImage) || inputLocked) return
    setInput('')
    const image = pendingImage
    setPendingImage(null)
    onSnapToBottom() // snap to newest on send
    sendTurn(text || (image ? 'I show this.' : ''), image)
  }

  return (
    <div className="border-t border-line2 p-3 bg-bg1">
      {!planningMode && (
        <>
          <span className="block font-ui text-[10px] tracking-wider text-textdim mb-1.5">
            OR DO SOMETHING ELSE:
          </span>
          <div className="flex flex-wrap items-center gap-1.5 mb-2">
            {/* True Continue: extends the latest narration in place (no new
                turn) — also the rescue for a beat clipped by max tokens. */}
            <QuickActionButton
              label="Continue"
              disabled={inputLocked || !apiKeySet}
              onClick={() => void continueNarration()}
            />
            <QuickActionButton
              label="Look Around"
              disabled={inputLocked || !apiKeySet}
              onClick={() => sendTurn('I look around carefully.')}
            />
            <QuickActionButton
              label="Talk to Party"
              disabled={inputLocked || !apiKeySet}
              onClick={() => sendTurn('I turn to talk to my party.')}
            />
            <QuickActionButton
              label="Rest"
              disabled={inputLocked || !apiKeySet}
              onClick={() => sendTurn('I take a moment to rest.')}
            />
            <div className="relative flex">
              <QuickActionButton
                label="Use an Item"
                disabled={inputLocked || !apiKeySet || inventory.length === 0}
                onClick={() => setItemPickerOpen((o) => !o)}
              />
              {itemPickerOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setItemPickerOpen(false)} />
                  <div className="absolute bottom-full left-0 mb-2 w-64 max-h-72 overflow-y-auto bg-bg2 border border-line2 rounded-md z-20 p-1.5 space-y-1">
                    {inventory.length === 0 ? (
                      <p className="text-[11px] text-textdim font-body px-2 py-1.5">No items.</p>
                    ) : (
                      inventory.map((stack) => stack.item ? (
                        <ItemCard
                          key={stack.itemId}
                          item={stack.item}
                          selected={false}
                          count={stack.count}
                          onClick={() => {
                            setItemPickerOpen(false)
                            sendTurn(`I use the ${stack.item!.name}.`)
                          }}
                        />
                      ) : null)
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </>
      )}
      {/* Pending image preview — attached to the next message */}
      {pendingImage && (
        <div className="flex items-center gap-2 mb-2">
          <img src={pendingImage} alt="Attached" className="h-14 w-14 object-cover rounded-md border border-line2" />
          <span className="font-ui text-[10px] text-textdim tracking-wider">IMAGE ATTACHED</span>
          <button
            type="button"
            className="font-ui text-[10px] text-textdim border border-line px-2 py-1 hover:text-text hover:border-line2 transition-colors"
            onClick={() => setPendingImage(null)}
          >
            REMOVE
          </button>
        </div>
      )}
      <div className="flex items-end gap-2">
        {/* Tools button + dropdown (opens above) */}
        <div className="relative shrink-0">
          {toolsOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setToolsOpen(false)} />
              <div className="absolute bottom-full left-0 mb-2 w-48 bg-bg2 border border-line2 rounded-md z-20 py-1">
                <ToolMenuItem
                  label="Regenerate"
                  disabled={!showInputRegenerate || planningMode}
                  onClick={() => { setToolsOpen(false); regenerate() }}
                />
                <ToolMenuItem
                  label="Regenerate with Note…"
                  disabled={!showInputRegenerate || planningMode}
                  onClick={() => { setToolsOpen(false); onOpenRegenNote() }}
                />
                <ToolMenuItem
                  label="Clear Chat"
                  disabled={messages.length === 0}
                  onClick={() => { setToolsOpen(false); onClearChat() }}
                />
                <ToolMenuItem
                  label="Search Messages…"
                  disabled={!hasVisibleMessages}
                  onClick={() => { setToolsOpen(false); onOpenSearch() }}
                />
                <ToolMenuItem
                  label="Export Transcript"
                  disabled={!hasVisibleMessages}
                  onClick={() => { setToolsOpen(false); onExportTranscript() }}
                />
                <ToolMenuItem
                  label="View Prompt Log"
                  disabled={messages.length === 0}
                  onClick={() => { setToolsOpen(false); onShowLog() }}
                />
              </div>
            </>
          )}
          <button
            type="button"
            title="Tools"
            aria-label="Tools"
            className={`border px-2.5 py-2 transition-colors ${
              toolsOpen || planningMode ? 'border-gold text-gold' : 'border-line text-textsec hover:text-text hover:border-line2'
            }`}
            onClick={() => setToolsOpen((o) => !o)}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.7 2.7-2-2 2.7-2.7z" />
            </svg>
          </button>
        </div>

        {/* Attach image (described to the Narrator/Editor by the vision agent) */}
        <input
          ref={imageInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          title="Attach an image"
          aria-label="Attach an image"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleImageFile(f)
            e.target.value = ''  // allow re-picking the same file
          }}
        />
        <button
          type="button"
          title="Attach an image"
          aria-label="Attach an image"
          disabled={!apiKeySet || inputLocked}
          className={`shrink-0 border px-2.5 py-2 transition-colors disabled:opacity-40 ${
            pendingImage ? 'border-gold text-gold' : 'border-line text-textsec hover:text-text hover:border-line2'
          }`}
          onClick={() => imageInputRef.current?.click()}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <path d="m21 15-5-5L5 21" />
          </svg>
        </button>

        <textarea
          ref={inputRef}
          className="flex-1 border border-line bg-bg0 px-3 py-2 text-sm font-body text-text outline-none focus:border-line2 transition-colors resize-none max-h-[160px] overflow-y-auto"
          rows={1}
          placeholder={!apiKeySet ? 'Set API key in Settings...' : planningMode ? 'Describe what to build or change…' : 'Type your own action…'}
          value={input}
          disabled={!apiKeySet || inputLocked}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
        />

        {isLoading ? (
          <button
            type="button"
            className="shrink-0 font-ui text-[10px] bg-golddeep text-bg0 px-3 py-2 hover:bg-gold transition-colors"
            onClick={stopGeneration}
          >
            STOP
          </button>
        ) : (
          <button
            type="button"
            className="shrink-0 font-ui text-[10px] bg-golddeep text-bg0 px-3 py-2 hover:bg-gold transition-colors disabled:opacity-40"
            disabled={!apiKeySet || (!input.trim() && !pendingImage) || inputLocked}
            onClick={handleSend}
          >
            SEND
          </button>
        )}
      </div>
    </div>
  )
}

// ── Quick action button ──────────────────────────────────────────────

function QuickActionButton({ label, disabled, onClick }: { label: string; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="font-ui text-[9px] uppercase tracking-wider border border-line2 text-textsec px-2.5 py-1 max-lg:py-2 max-lg:px-3 hover:text-text hover:border-gold transition-colors disabled:opacity-40 disabled:hover:text-textsec disabled:hover:border-line2"
    >
      {label}
    </button>
  )
}

// ── Tools menu item ─────────────────────────────────────────────────

function ToolMenuItem({ label, disabled, onClick }: { label: string; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="w-full text-left font-ui text-[10px] tracking-wider uppercase px-3 py-2 text-textsec hover:bg-bg3 hover:text-text transition-colors disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-textsec disabled:cursor-not-allowed"
    >
      {label}
    </button>
  )
}
