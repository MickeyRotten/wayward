// The chat message bubble — PC / party-member / narrator (and Editor) styles —
// plus its actions bar, inventory/equipment change notices, and inline editor.
//
// React.memo'd with a callback-tolerant comparator, so every derived prop
// passed in from ChatScene (memberResolver, chipEntities, catalogMap,
// sceneHeaders, …) must stay useMemo'd there.

import { useRef, useEffect, useState, useCallback, useMemo, memo, forwardRef } from 'react'
import { useChatStore } from '../../state/chatStore'
import { useSettingsStore } from '../../state/settingsStore'
import { useItemsStore } from '../../state/itemsStore'
import { useTtsStore } from '../../state/ttsStore'
import { ExpandIconButton, TextEditorModal } from '../common/ExpandableTextarea'
import { parseSegments, type Segment, type MemberLite } from '../../lib/narration'
import {
  CHAT_PORTRAIT_SIZE,
  Portrait,
  NarrationHtml,
  SceneHeader,
  SegmentedNarration,
  applyEntityChips,
  formatNarration,
  type ChipEntity,
} from './Narration'
import { EditorActionsFeed } from './EditorActionsFeed'
import type { ChatMessage, ItemCatalogEntry, InventoryDelta, EquipmentChange } from '@shared/types/models'

// Equality for React.memo: shallow-compare everything except the callback
// props — they're fresh closures every parent render, but everything they
// capture that affects output (variant counts, busy, ids) arrives via the
// other, compared props. This is what stops streaming chunks / unrelated store
// updates from re-rendering (and re-parsing) the whole message history.
function bubblePropsEqual(prev: Record<string, unknown>, next: Record<string, unknown>): boolean {
  for (const k of Object.keys(next)) {
    const a = prev[k]
    const b = next[k]
    if (typeof a === 'function' && typeof b === 'function') continue
    if (a !== b) return false
  }
  return true
}

export const MessageBubble = memo(function MessageBubble({
  message,
  variantCount,
  activeVariant,
  onSwipe,
  onSwipeNew,
  isLastAssistant,
  onDelete,
  isFirstNarrator,
  pcName,
  pcPortrait,
  partyMemberMap,
  memberResolver,
  chipEntities,
  catalogMap,
  resolveCharName,
  sceneHeader,
  editTargetId,
  onEditOpened,
}: {
  message: ChatMessage
  variantCount: number
  activeVariant: number
  onSwipe?: (dir: 'left' | 'right') => void
  onSwipeNew?: () => void
  isLastAssistant?: boolean
  onDelete?: () => void
  isFirstNarrator?: boolean
  pcName: string
  pcPortrait: string
  partyMemberMap: Map<string, { id: string; basicInfo: { name: string }; portraitCrop?: string | null }>
  memberResolver: Map<string, MemberLite>
  chipEntities: ChipEntity[]
  catalogMap: Map<string, ItemCatalogEntry>
  resolveCharName: (id: string) => string
  sceneHeader?: { location?: string | null; timeOfDay?: string | null }
  editTargetId?: number | null
  onEditOpened?: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(message.content)
  const editMessage = useChatStore((s) => s.editMessage)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  // TTS replay: only offered on persisted narrator messages when the server
  // has the engine installed and TTS is enabled in Settings.
  const ttsReady = useTtsStore((s) => !!s.status?.installed) && useSettingsStore((s) => s.ttsEnabled)
  const speakingThis = useTtsStore((s) => s.playing?.messageId === message.id)
  const speakMessage = useTtsStore((s) => s.speakMessage)
  const stopSpeaking = useTtsStore((s) => s.stop)

  // Editor/Planner prose is rendered plainly; only narration gets JRPG segments.
  // Parsed once per (content, resolver) — not on every render of the list.
  const isPlanner = message.mode === 'planner'
  const segments = useMemo<Segment[]>(
    () =>
      isPlanner
        ? [{ type: 'narration', text: message.content }]
        : parseSegments(message.content, memberResolver),
    [isPlanner, message.content, memberResolver],
  )

  useEffect(() => {
    setEditText(message.content)
  }, [message.content])

  // Open the editor when a keyboard shortcut targets this message.
  useEffect(() => {
    if (editTargetId === message.id && message.id > 0 && !editing) {
      setEditing(true)
      onEditOpened?.()
    }
  }, [editTargetId, message.id, editing, onEditOpened])

  useEffect(() => {
    if (editing && textareaRef.current) {
      textareaRef.current.focus()
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px'
    }
  }, [editing])

  const handleSaveEdit = useCallback(async () => {
    if (message.id < 0) return
    const trimmed = editText.trim()
    if (trimmed && trimmed !== message.content) {
      await editMessage(message.id, trimmed)
    }
    setEditing(false)
  }, [editText, message.id, message.content, editMessage])

  const isUser = message.role === 'user'
  const isNarrator = message.role === 'assistant' && (message.speaker === 'narrator' || !message.speaker)

  // Check if this is a party member speaking (assistant message with a party member speaker)
  const partyMember = !isUser && !isNarrator && message.speaker
    ? partyMemberMap.get(message.speaker)
    : undefined

  // Determine rendering style based on speaker type
  if (isUser) {
    // ── Player Character message (left-aligned, like the rest — no alternating) ──
    return (
      <div className="max-w-[85%] max-lg:max-w-full mr-auto group">
        {/* Player line — styled like a party dialogue block, with a blue accent.
            The px-4 py-3 matches the narrator message so the portrait lines up
            with the party dialogue blocks rendered inside it. */}
        <div className="flex items-stretch gap-3 px-4 py-3">
          {/* Portrait */}
          <Portrait
            src={pcPortrait}
            name={pcName}
            borderColor="border-blue"
            className={CHAT_PORTRAIT_SIZE}
          />

          <div className="flex-1 min-w-0 flex flex-col">
            {/* Name plate */}
            <span className="font-disp text-[14px] text-blue pt-[2px] mb-1">
              {pcName} <span className="font-ui text-[9px] text-blue/60 tracking-wider">YOU</span>
            </span>

            {/* Message content */}
            <div className="flex-1 border-l-2 border-blue/60 bg-blue/5 rounded-r-md px-4 py-3">
              {/* Player-attached image (described to the narrator by the vision agent) */}
              {message.imageUrl && (
                <img
                  src={message.imageUrl}
                  alt={message.imageDescription || 'Attached image'}
                  title={message.imageDescription || undefined}
                  className="max-h-64 max-w-full rounded-md border border-line2 mb-2"
                />
              )}
              {editing ? (
                <EditArea
                  ref={textareaRef}
                  value={editText}
                  onChange={setEditText}
                  onSave={handleSaveEdit}
                  onCancel={() => { setEditText(message.content); setEditing(false) }}
                />
              ) : (
                <NarrationHtml
                  className="chat-prose font-body text-text whitespace-pre-wrap"
                  html={applyEntityChips(formatNarration(message.content), chipEntities)}
                />
              )}
            </div>
          </div>
        </div>

        {/* Actions bar */}
        {!editing && (
          <div className="flex items-center gap-2 mt-1 px-1 opacity-0 group-hover:opacity-100 transition-opacity">
            {message.id > 0 && (
              <button
                type="button"
                className="font-ui text-[9px] text-textdim hover:text-text"
                onClick={() => setEditing(true)}
              >
                EDIT
              </button>
            )}
            <CopyButton text={message.content} />
            {onDelete && (
              <button
                type="button"
                className="font-ui text-[9px] text-textdim hover:text-text"
                onClick={onDelete}
              >
                DELETE
              </button>
            )}
          </div>
        )}
      </div>
    )
  }

  if (partyMember) {
    // ── Party Member message ──
    const pmName = partyMember.basicInfo?.name || 'Party Member'
    const pmPortrait = partyMember.portraitCrop || ''

    return (
      <div className="max-w-[85%] max-lg:max-w-full mr-auto group">
        <div className="flex items-start gap-3">
          {/* Portrait */}
          <Portrait
            src={pmPortrait}
            name={pmName}
            borderColor="border-line2"
          />

          <div className="flex-1 min-w-0">
            {/* Name header + spotlight badge */}
            <div className="mb-1 flex items-center gap-2">
              <span className="font-disp text-[13px] text-gold pt-[2px]">
                {pmName.split(' ')[0]}
              </span>
              {message.spotlightReason && (
                <span className={`text-[10px] font-ui px-1.5 py-0.5 border rounded-full ${
                  message.spotlightReason === 'Hasn\'t spoken in a while'
                    ? 'border-golddeep text-golddeep'
                    : 'border-gold text-gold'
                }`}>
                  {message.spotlightReason}
                </span>
              )}
            </div>

            {/* Message content */}
            <div className="px-4 py-3">
              {editing ? (
                <EditArea
                  ref={textareaRef}
                  value={editText}
                  onChange={setEditText}
                  onSave={handleSaveEdit}
                  onCancel={() => { setEditText(message.content); setEditing(false) }}
                />
              ) : (
                <NarrationHtml
                  className="chat-prose font-body text-text2 whitespace-pre-wrap"
                  html={applyEntityChips(formatNarration(message.content), chipEntities)}
                />
              )}
            </div>
          </div>
        </div>

        {/* Inventory / equipment change notices */}
        <ChangeNotices
          message={message}
          catalogMap={catalogMap}
          resolveCharName={resolveCharName}
        />

        {/* Actions bar */}
        <ActionsBar
          editing={editing}
          isUser={false}
          variantCount={variantCount}
          activeVariant={activeVariant}
          onSwipe={onSwipe}
          onSwipeNew={onSwipeNew}
          isLastAssistant={isLastAssistant}
          onDelete={onDelete}
          onEdit={message.id > 0 ? () => setEditing(true) : undefined}
          copyText={message.content}
          usageText={usageLabel(message)}
        />
      </div>
    )
  }

  // ── Narrator / Planner message (default for assistant) ──
  return (
    <div className="max-w-[85%] max-lg:max-w-full mr-auto group">
      {isPlanner && (
        <div className="flex items-center gap-1.5 px-4 pt-1">
          <span className="font-ui text-[9px] tracking-wider text-gold">⚙ EDITOR</span>
        </div>
      )}
      {isPlanner && message.editorActions && message.editorActions.length > 0 && (
        <div className="px-4 pt-1.5">
          <EditorActionsFeed actions={message.editorActions} />
        </div>
      )}
      {sceneHeader && (sceneHeader.location || sceneHeader.timeOfDay) && (
        <SceneHeader location={sceneHeader.location} timeOfDay={sceneHeader.timeOfDay} />
      )}
      <div className="px-4 py-3">
        {editing ? (
          <EditArea
            ref={textareaRef}
            value={editText}
            onChange={setEditText}
            onSave={handleSaveEdit}
            onCancel={() => { setEditText(message.content); setEditing(false) }}
          />
        ) : (
          <SegmentedNarration
            segments={segments}
            chipEntities={chipEntities}
            dropCap={isFirstNarrator}
            messageId={message.id}
          />
        )}
      </div>

      {/* Inventory / equipment change notices */}
      <ChangeNotices
        message={message}
        catalogMap={catalogMap}
        resolveCharName={resolveCharName}
      />

      {/* Actions bar */}
      <ActionsBar
        editing={editing}
        isUser={false}
        variantCount={variantCount}
        activeVariant={activeVariant}
        onSwipe={onSwipe}
        isLastAssistant={isLastAssistant}
        onDelete={onDelete}
        onEdit={message.id > 0 ? () => setEditing(true) : undefined}
        copyText={message.content}
        onSpeak={
          ttsReady && !isPlanner && message.id > 0
            ? () => (speakingThis ? stopSpeaking() : void speakMessage(message))
            : undefined
        }
        speaking={speakingThis}
        usageText={usageLabel(message)}
      />
    </div>
  )
}, bubblePropsEqual)

// ── Inventory / Equipment change notices ───────────────────────────

const SLOT_LABELS: Record<string, string> = {
  head: 'Head', neck: 'Neck', torsoOver: 'Torso (over)', torsoUnder: 'Torso (under)',
  leftHand: 'Left Hand', rightHand: 'Right Hand', waist: 'Waist',
  legsOver: 'Legs (over)', legsUnder: 'Legs (under)', feet: 'Feet',
  accessory1: 'Accessory', accessory2: 'Accessory',
}

function ChangeNotices({
  message,
  catalogMap,
  resolveCharName,
}: {
  message: ChatMessage
  catalogMap: Map<string, ItemCatalogEntry>
  resolveCharName: (id: string) => string
}) {
  const invDeltas = (message.appliedInventoryDeltas ?? []) as InventoryDelta[]
  const equipChanges = (message.appliedEquipmentChanges ?? []) as EquipmentChange[]
  const inventory = useItemsStore((s) => s.inventory)

  if (invDeltas.length === 0 && equipChanges.length === 0) return null

  // Equipment-change ids are item INSTANCE ids — resolve via the instance list,
  // falling back to the catalog (for inventory deltas, which carry catalog ids).
  const itemName = (id: string | null) => {
    if (!id) return 'nothing'
    const inst = inventory.find((s) => s.instanceId === id)
    return inst?.item?.name ?? catalogMap.get(id)?.name ?? 'an item'
  }

  return (
    <div className="px-4 mt-1 space-y-1.5">
      {invDeltas.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-ui text-xs text-textsec tracking-wider">Inventory</span>
          {invDeltas.map((d, i) => {
            const name = catalogMap.get(d.itemId)?.name ?? 'Unknown item'
            const positive = d.delta > 0
            const sign = positive ? '+' : '−' // − minus sign
            return (
              <span
                key={`${d.itemId}-${i}`}
                className="inline-flex items-center gap-1 text-sm"
              >
                <span className="text-gold2 bg-gold/10 px-1 rounded font-ui text-sm">
                  {name}
                </span>
                <span
                  className={`font-ui text-xs ${positive ? 'text-gold2' : 'text-danger'}`}
                >
                  {sign}{Math.abs(d.delta)}
                </span>
              </span>
            )
          })}
        </div>
      )}

      {equipChanges.length > 0 && (
        <div className="flex flex-col gap-1">
          {equipChanges.map((c, i) => (
            <div key={`${c.characterId}-${c.slot}-${i}`} className="flex items-center gap-2 flex-wrap text-sm">
              <span className="font-ui text-xs text-textsec tracking-wider">Equipment</span>
              <span className="font-disp text-[12px] text-gold pt-[2px]">
                {resolveCharName(c.characterId)}
              </span>
              <span className="font-ui text-[10px] text-textdim tracking-wider">
                {SLOT_LABELS[c.slot] ?? c.slot}
              </span>
              <span className="text-textdim line-through">{itemName(c.previousItemId)}</span>
              <span className="font-ui text-[10px] text-textdim">&#8594;</span>
              <span className="text-gold2 bg-gold/10 px-1 rounded font-ui text-sm">
                {itemName(c.newItemId)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Shared Actions Bar ──────────────────────────────────────────────

/** Real provider accounting for a message ("12,345 → 512 tok · $0.0042"),
 *  or null when the provider didn't report usage. */
function usageLabel(m: ChatMessage): string | null {
  if (m.promptTokens == null && m.completionTokens == null) return null
  const fmt = (n?: number | null) => (n ?? 0).toLocaleString()
  const cost = m.cost != null && m.cost > 0 ? ` · $${m.cost.toFixed(4)}` : ''
  return `${fmt(m.promptTokens)} → ${fmt(m.completionTokens)} tok${cost}`
}

function ActionsBar({
  editing,
  isUser,
  variantCount,
  activeVariant,
  onSwipe,
  onSwipeNew,
  isLastAssistant,
  onDelete,
  onEdit,
  copyText,
  onSpeak,
  speaking,
  usageText,
}: {
  editing: boolean
  isUser: boolean
  variantCount: number
  activeVariant: number
  onSwipe?: (dir: 'left' | 'right') => void
  onSwipeNew?: () => void
  isLastAssistant?: boolean
  onDelete?: () => void
  onEdit?: () => void
  copyText?: string
  onSpeak?: () => void
  speaking?: boolean
  usageText?: string | null
}) {
  if (editing) return null

  return (
    <div
      className="flex items-center gap-2 mt-1 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
      style={(!isUser && (variantCount > 1 || isLastAssistant || onSwipeNew)) ? { opacity: 1 } : undefined}
    >
      {!isUser && (variantCount > 1 || onSwipeNew) && (
        <>
          <button
            type="button"
            className="font-ui text-[10px] text-textdim hover:text-text disabled:opacity-30"
            disabled={activeVariant === 0}
            onClick={() => onSwipe?.('left')}
          >
            &#9664;
          </button>
          <span className="font-ui text-[8px] text-textdim tracking-wider">
            {activeVariant + 1}/{variantCount}
          </span>
          <button
            type="button"
            className="font-ui text-[10px] text-textdim hover:text-text disabled:opacity-30"
            disabled={activeVariant === variantCount - 1}
            onClick={() => onSwipe?.('right')}
          >
            &#9654;
          </button>
          {onSwipeNew && (
            <button
              type="button"
              className="font-ui text-[11px] text-textdim hover:text-gold ml-1"
              title="Generate new variant"
              onClick={onSwipeNew}
            >
              &#8635;
            </button>
          )}
        </>
      )}
      <div className="flex items-center gap-2 ml-auto">
        {usageText && (
          <span
            className="font-ui text-[8px] text-textdim tracking-wider"
            title="Real token usage reported by the provider (prompt → response) and its cost"
          >
            {usageText}
          </span>
        )}
        {onSpeak && (
          <button
            type="button"
            className={`font-ui text-[9px] ${speaking ? 'text-gold' : 'text-textdim hover:text-text'}`}
            title={speaking ? 'Stop speaking' : 'Read this message aloud'}
            onClick={onSpeak}
          >
            {speaking ? '■ STOP' : '♪ SPEAK'}
          </button>
        )}
        {onEdit && (
          <button
            type="button"
            className="font-ui text-[9px] text-textdim hover:text-text"
            onClick={onEdit}
          >
            EDIT
          </button>
        )}
        {copyText && <CopyButton text={copyText} />}
        {onDelete && (
          <button
            type="button"
            className="font-ui text-[9px] text-textdim hover:text-text"
            onClick={onDelete}
          >
            DELETE
          </button>
        )}
      </div>
    </div>
  )
}

// Copy a message's text to the clipboard, with a brief "COPIED" confirmation.
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      className="font-ui text-[9px] text-textdim hover:text-text"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setCopied(true)
          setTimeout(() => setCopied(false), 1200)
        } catch { /* clipboard unavailable */ }
      }}
    >
      {copied ? 'COPIED' : 'COPY'}
    </button>
  )
}

// ── Edit Area (shared between all message types) ────────────────────

const EditArea = forwardRef<
  HTMLTextAreaElement,
  {
    value: string
    onChange: (v: string) => void
    onSave: () => void
    onCancel: () => void
  }
>(function EditArea({ value, onChange, onSave, onCancel }, ref) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="space-y-2">
      <div className="relative">
        <textarea
          ref={ref}
          title="Edit message"
          className="w-full text-sm font-body text-text bg-bg0 border border-line p-2 outline-none focus:border-line2 resize-y min-h-[48px]"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && e.ctrlKey) {
              e.preventDefault()
              onSave()
            }
            if (e.key === 'Escape') {
              onCancel()
            }
          }}
          onClick={(e) => e.stopPropagation()}
        />
        <ExpandIconButton
          onClick={() => setExpanded(true)}
          className="absolute top-1 right-1"
        />
        {expanded && (
          <div onClick={(e) => e.stopPropagation()}>
            <TextEditorModal
              label="Edit Message"
              value={value}
              onChange={onChange}
              onClose={() => setExpanded(false)}
            />
          </div>
        )}
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          className="font-ui text-[9px] text-bg0 bg-golddeep px-2 py-0.5 hover:bg-gold"
          onClick={(e) => { e.stopPropagation(); onSave() }}
        >
          SAVE
        </button>
        <button
          type="button"
          className="font-ui text-[9px] text-textdim hover:text-text px-2 py-0.5"
          onClick={(e) => {
            e.stopPropagation()
            onCancel()
          }}
        >
          CANCEL
        </button>
        <span className="font-ui text-[8px] text-textdim self-center">CTRL+ENTER TO SAVE</span>
      </div>
    </div>
  )
})
