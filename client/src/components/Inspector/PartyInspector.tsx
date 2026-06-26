import { useCallback, useEffect, useRef, useState } from 'react'
import { usePartyStore } from '../../state/partyStore'
import { useItemsStore } from '../../state/itemsStore'
import { useQuestsStore } from '../../state/questsStore'
import { useLoreStore } from '../../state/loreStore'
import { useUiStore } from '../../state/uiStore'
import { useChatStore } from '../../state/chatStore'
import { CharacterSheetEditor } from '../CharacterSheet/CharacterSheetEditor'
import { PartyMemberEditor } from '../PartyMember/PartyMemberEditor'
import { ExpandableTextarea } from '../common/ExpandableTextarea'
import type { ItemCatalogEntry, ItemType, Rarity, Quest, LorebookEntry, LoreCategory } from '@shared/types/models'

export function PartyInspector() {
  const pc = usePartyStore((s) => s.playerCharacter)
  const members = usePartyStore((s) => s.partyMembers)
  const catalog = useItemsStore((s) => s.catalog)
  const inventory = useItemsStore((s) => s.inventory)
  const quests = useQuestsStore((s) => s.quests)
  const loreEntries = useLoreStore((s) => s.entries)
  const selection = useUiStore((s) => s.selection)
  const everSelected = useUiStore((s) => s.everSelected)
  const editDirty = useUiStore((s) => s.editDirty)
  const back = useUiStore((s) => s.back)
  const goBack = useUiStore((s) => s.goBack)
  // The Inspector's view/edit state is now driven by the chat's Edit Mode:
  // Edit Mode → always editing; Narration → always viewing. (Game-engine style:
  // Play vs Edit.) The current selection is preserved when you toggle modes.
  const editMode = useChatStore((s) => s.planningMode)
  const mode: 'view' | 'edit' = editMode ? 'edit' : 'view'

  if (!everSelected) return <EmptyState />

  // Resolve the selected entity
  const selIsPC = selection?.kind === 'player' && !!pc
  const selMember = selection?.kind === 'member'
    ? members.find((m) => m.id === selection.id)
    : undefined
  const selIsMember = !!selMember

  // Item selection — look in catalog first, fall back to inventory item data
  const selItem = selection?.kind === 'item'
    ? catalog.find((i) => i.id === selection.id) ??
      inventory.find((s) => s.itemId === selection.id)?.item ??
      undefined
    : undefined
  const selIsItem = !!selItem

  // Quest selection
  const selQuest = selection?.kind === 'quest'
    ? quests.find((q) => q.id === selection.id)
    : undefined
  const selIsQuest = !!selQuest

  // Lore selection
  const selLore = selection?.kind === 'lore'
    ? loreEntries.find((e) => e.id === selection.id)
    : undefined
  const selIsLore = !!selLore

  const hasSelection = selIsPC || selIsMember || selIsItem || selIsQuest || selIsLore

  // Derive entity name for the header
  const entityName = selIsPC
    ? (pc!.basicInfo.name || 'New Character')
    : selIsMember
      ? (selMember!.basicInfo.name || 'New Member')
      : selIsItem
        ? (selItem!.name || 'Unknown Item')
        : selIsQuest
          ? (selQuest!.title || 'Untitled Quest')
          : selIsLore
            ? (selLore!.title || 'Untitled Entry')
            : ''

  const entityLabel = selIsPC
    ? 'PLAYER CHARACTER'
    : selIsMember
      ? 'PARTY MEMBER'
      : selIsItem
        ? 'ITEM'
        : selIsQuest
          ? 'QUEST'
          : selIsLore
            ? 'LOREBOOK ENTRY'
            : ''

  return (
    <div className="flex flex-col h-full">
      {/* Inspector Header */}
      {hasSelection && (
        <div className="shrink-0 border-b border-line px-6 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                {back && (
                  <>
                    <button
                      type="button"
                      className="font-ui text-[9px] text-gold hover:text-gold2 tracking-wider transition-colors"
                      onClick={goBack}
                    >
                      ◀ BACK
                    </button>
                    <span className="font-ui text-[9px] text-textdim">|</span>
                  </>
                )}
                <span className="font-ui text-[9px] text-textdim tracking-wider">{entityLabel}</span>
              </div>
              <h2 className="font-disp text-[24px] pt-0.75 leading-none text-text truncate">
                {entityName}
              </h2>
            </div>
            <div className="flex items-center gap-2 shrink-0 mt-1">
              {/* Edit dirty indicator */}
              {editDirty && (
                <span
                  className="w-1.5 h-1.5 rounded-full bg-gold"
                  title="Unsaved changes"
                />
              )}
              {/* Mode is driven by the chat's Edit Mode — read-only badge */}
              <span
                className={`font-ui text-[9px] tracking-wider px-2.5 py-1 border ${
                  mode === 'edit' ? 'text-gold border-gold/40' : 'text-textdim border-line'
                }`}
                title={mode === 'edit' ? 'Edit Mode is on' : 'Toggle Edit Mode in chat to edit'}
              >
                {mode === 'edit' ? 'EDITING' : 'VIEW'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Inspector Body — single scrollable child */}
      <div className="flex-1 overflow-y-auto relative">
        {hasSelection && <SaveIndicator />}
        {selIsPC ? (
          <CharacterSheetEditor mode={mode} />
        ) : selIsMember ? (
          <PartyMemberEditor key={selMember!.id} member={selMember!} mode={mode} />
        ) : selIsItem ? (
          <ItemInspector key={selItem!.id} item={selItem!} mode={mode} />
        ) : selIsQuest ? (
          <QuestInspector key={selQuest!.id} quest={selQuest!} mode={mode} />
        ) : selIsLore ? (
          <LoreInspector key={selLore!.id} entry={selLore!} mode={mode} />
        ) : (
          <EmptyState />
        )}
      </div>
    </div>
  )
}

function SaveIndicator() {
  const lastSavedAt = usePartyStore((s) => s.lastSavedAt)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!lastSavedAt) return
    setVisible(true)
    const timer = setTimeout(() => setVisible(false), 1500)
    return () => clearTimeout(timer)
  }, [lastSavedAt])

  // Overlay (absolute) so it never reserves vertical space between the header
  // and the content — it just briefly floats in the top-right after a save.
  return (
    <div
      className={`absolute top-2 right-6 z-10 pointer-events-none font-ui text-[9px] text-textdim tracking-wider transition-opacity duration-300 ${
        visible ? 'opacity-100' : 'opacity-0'
      }`}
    >
      SAVED
    </div>
  )
}

// ── Item Inspector ──────────────────────────────────────────────

const RARITY_LABELS: Record<Rarity, string> = {
  c: 'Common',
  u: 'Uncommon',
  r: 'Rare',
  e: 'Epic',
  l: 'Legendary',
}

const RARITY_TEXT_COLORS: Record<Rarity, string> = {
  c: 'text-rarity-c',
  u: 'text-rarity-u',
  r: 'text-rarity-r',
  e: 'text-rarity-e',
  l: 'text-rarity-l',
}

const ITEM_TYPES: ItemType[] = ['Equipment', 'Tool', 'Consumable', 'Key Item', 'Artifact', 'Other']
const RARITY_OPTIONS: { value: Rarity; label: string }[] = [
  { value: 'c', label: 'Common' },
  { value: 'u', label: 'Uncommon' },
  { value: 'r', label: 'Rare' },
  { value: 'e', label: 'Epic' },
  { value: 'l', label: 'Legendary' },
]

function ItemInspector({ item, mode }: { item: ItemCatalogEntry; mode: 'view' | 'edit' }) {
  const updateItem = useItemsStore((s) => s.updateItem)
  const deleteItem = useItemsStore((s) => s.deleteItem)
  const removeFromInventory = useItemsStore((s) => s.removeFromInventory)
  const inventory = useItemsStore((s) => s.inventory)
  const select = useUiStore((s) => s.select)
  const setEditDirty = useUiStore((s) => s.setEditDirty)

  const draft = useRef<Partial<ItemCatalogEntry>>(structuredClone(item))
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [removeError, setRemoveError] = useState('')

  useEffect(() => {
    draft.current = structuredClone(item)
  }, [item])

  const flush = useCallback(() => {
    clearTimeout(timer.current)
    updateItem(item.id, draft.current)
    setEditDirty(false)
  }, [item.id, updateItem, setEditDirty])

  const scheduleFlush = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, 600)
  }, [flush])

  const update = (key: string, value: string | number | null, immediate?: boolean) => {
    Object.assign(draft.current, { [key]: value })
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  const inInventory = inventory.find((s) => s.itemId === item.id)

  if (mode === 'view') {
    return (
      <div className="space-y-6 p-6">
        {/* Badges row */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Type badge */}
          <span className="font-ui text-[9px] tracking-wider uppercase text-textsec border border-line px-2 py-0.5">
            {item.type}
          </span>
          {/* Rarity badge */}
          <span className={`font-ui text-[9px] tracking-wider uppercase px-2 py-0.5 border border-line ${RARITY_TEXT_COLORS[item.rarity]}`}>
            {RARITY_LABELS[item.rarity]}
          </span>
        </div>

        {/* Details */}
        <ItemSection title="Details">
          <div className="space-y-1.5">
            {item.type === 'Equipment' && item.slot && (
              <ItemViewField label="Slot" value={item.slot} />
            )}
            {(item.maxStack ?? 1) > 1 && (
              <ItemViewField label="Max Stack" value={String(item.maxStack)} />
            )}
            {item.uses != null && (
              <ItemViewField label="Uses" value={String(item.uses)} />
            )}
          </div>
        </ItemSection>

        {/* Description */}
        {item.desc && (
          <ItemSection title="Description">
            <p className="font-body text-sm text-text2 leading-relaxed">{item.desc}</p>
          </ItemSection>
        )}

        {/* Inventory info */}
        {inInventory && (
          <ItemSection title="Inventory">
            <div className="flex items-center justify-between">
              <span className="font-body text-sm text-text">
                In inventory: <span className="text-gold">{inInventory.count}</span>
              </span>
              <button
                type="button"
                className="font-ui text-[9px] text-textdim hover:text-text border border-line hover:border-line2 px-2 py-1 transition-colors"
                onClick={async () => {
                  setRemoveError('')
                  try {
                    await removeFromInventory(item.id, 1)
                  } catch (e: unknown) {
                    setRemoveError(e instanceof Error ? e.message : 'Failed')
                  }
                }}
              >
                REMOVE 1
              </button>
            </div>
            {removeError && (
              <p className="text-[11px] text-danger font-body mt-1">{removeError}</p>
            )}
          </ItemSection>
        )}
      </div>
    )
  }

  // Edit mode
  const d = draft.current
  return (
    <div className="space-y-6 p-6">
      {/* Delete button */}
      <div className="flex items-start justify-end">
        <button
          type="button"
          className="font-ui text-[9px] text-textdim hover:text-text border border-line px-2 py-1 hover:border-line2 transition-colors shrink-0"
          onClick={() => setShowDeleteConfirm(true)}
        >
          DELETE ITEM
        </button>
        {showDeleteConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
            <div className="bg-bg2 border border-line rounded-lg p-5 max-w-xs space-y-4">
              <p className="font-body text-sm text-text">
                Delete <strong>{item.name || 'this item'}</strong> from the catalog? This also removes it from inventory.
              </p>
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  className="font-ui text-[9px] text-textdim border border-line px-3 py-1 hover:border-line2 hover:text-text transition-colors"
                  onClick={() => setShowDeleteConfirm(false)}
                >
                  CANCEL
                </button>
                <button
                  type="button"
                  className="font-ui text-[9px] text-bg0 bg-gold hover:bg-gold2 px-3 py-1 transition-colors"
                  onClick={async () => {
                    await deleteItem(item.id)
                    select(null)
                  }}
                >
                  DELETE
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Name */}
      <ItemSection title="Basic Info">
        <div className="space-y-3">
          <ItemField
            label="Name"
            value={d.name ?? ''}
            onChange={(v) => update('name', v)}
            onBlur={(v) => update('name', v, true)}
          />

          {/* Type select */}
          <label className="block">
            <span className="text-[11px] text-textdim font-body block mb-0.5">Type</span>
            <select
              className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
              defaultValue={d.type ?? 'Other'}
              onChange={(e) => update('type', e.target.value, true)}
            >
              {ITEM_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>

          {/* Rarity select */}
          <label className="block">
            <span className="text-[11px] text-textdim font-body block mb-0.5">Rarity</span>
            <select
              className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
              defaultValue={d.rarity ?? 'c'}
              onChange={(e) => update('rarity', e.target.value, true)}
            >
              {RARITY_OPTIONS.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </label>

          {/* Slot (only for Equipment type) */}
          <ItemField
            label="Slot (equipment only)"
            value={d.slot ?? ''}
            onChange={(v) => update('slot', v || null)}
            onBlur={(v) => update('slot', v || null, true)}
            placeholder="e.g. Head, Torso, Hands"
          />

          <div className="grid grid-cols-2 gap-3">
            <ItemNumField
              label="Max Stack"
              value={d.maxStack ?? 1}
              onChange={(v) => update('maxStack', v)}
              onBlur={(v) => update('maxStack', v, true)}
            />
            <ItemNumField
              label="Uses"
              value={d.uses ?? 0}
              onChange={(v) => update('uses', v || null)}
              onBlur={(v) => update('uses', v || null, true)}
            />
          </div>
        </div>
      </ItemSection>

      {/* Description */}
      <ItemSection title="Description">
        <ItemTextArea
          label=""
          value={d.desc ?? ''}
          onChange={(v) => update('desc', v)}
          onBlur={(v) => update('desc', v, true)}
          placeholder="Item description..."
        />
      </ItemSection>
    </div>
  )
}

function ItemSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="font-ui text-[10px] tracking-wider text-textsec uppercase mb-3">{title}</h3>
      {children}
    </section>
  )
}

function ItemViewField({ label, value }: { label: string; value: string }) {
  return (
    <div className="py-0.5">
      <span className="text-[11px] text-textdim font-body">{label}</span>
      <span className="text-[11px] text-textdim font-body mx-1">&middot;</span>
      <span className="text-sm font-body text-text">{value}</span>
    </div>
  )
}

function ItemField({ label, value, onChange, onBlur, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; onBlur?: (v: string) => void; placeholder?: string
}) {
  return (
    <label className="block">
      {label && <span className="text-[11px] text-textdim font-body block mb-0.5">{label}</span>}
      <input
        className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
        defaultValue={value}
        placeholder={placeholder}
        onBlur={(e) => (onBlur ?? onChange)(e.target.value)}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

function ItemNumField({ label, value, onChange, onBlur }: {
  label: string; value: number; onChange: (v: number) => void; onBlur?: (v: number) => void
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-textdim font-body block mb-0.5">{label}</span>
      <input
        type="number"
        className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
        defaultValue={value}
        onBlur={(e) => (onBlur ?? onChange)(Number(e.target.value) || 0)}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
      />
    </label>
  )
}

function ItemTextArea({ label, value, onChange, onBlur, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; onBlur?: (v: string) => void; placeholder?: string
}) {
  return (
    <label className="block">
      {label && <span className="text-[11px] text-textdim font-body block mb-0.5">{label}</span>}
      <ExpandableTextarea
        label={label || 'Edit'}
        className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors resize-y min-h-[72px]"
        rows={3}
        value={value}
        placeholder={placeholder}
        onChange={onChange}
        onBlur={onBlur ?? onChange}
      />
    </label>
  )
}

// ── Quest Inspector ──────────────────────────────────────────────

const STATUS_OPTIONS: { value: Quest['status']; label: string }[] = [
  { value: 'active', label: 'Active' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
]

function QuestInspector({ quest, mode }: { quest: Quest; mode: 'view' | 'edit' }) {
  const updateQuest = useQuestsStore((s) => s.updateQuest)
  const deleteQuest = useQuestsStore((s) => s.deleteQuest)
  const addObjective = useQuestsStore((s) => s.addObjective)
  const updateObjective = useQuestsStore((s) => s.updateObjective)
  const deleteObjective = useQuestsStore((s) => s.deleteObjective)
  const allLoreEntries = useLoreStore((s) => s.entries)
  const setActiveTab = useUiStore((s) => s.setActiveTab)
  const setLoreCategory = useLoreStore((s) => s.setCategory)
  const select = useUiStore((s) => s.select)
  const selectInto = useUiStore((s) => s.selectInto)
  const setEditDirty = useUiStore((s) => s.setEditDirty)

  const draft = useRef<Partial<Pick<Quest, 'title' | 'status' | 'desc' | 'notes'>>>(
    { title: quest.title, status: quest.status, desc: quest.desc, notes: quest.notes }
  )
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [newObjText, setNewObjText] = useState('')

  useEffect(() => {
    draft.current = { title: quest.title, status: quest.status, desc: quest.desc, notes: quest.notes }
  }, [quest])

  const flush = useCallback(() => {
    clearTimeout(timer.current)
    updateQuest(quest.id, draft.current)
    setEditDirty(false)
  }, [quest.id, updateQuest, setEditDirty])

  const scheduleFlush = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, 600)
  }, [flush])

  const update = (key: string, value: string, immediate?: boolean) => {
    Object.assign(draft.current, { [key]: value })
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  const doneCount = quest.objectives.filter((o) => o.done).length
  const totalCount = quest.objectives.length

  if (mode === 'view') {
    return (
      <div className="space-y-6 p-6">
        {/* Status badge */}
        <div className="flex items-center gap-2">
          <span className={`font-ui text-[9px] tracking-wider uppercase px-2 py-0.5 border border-line ${
            quest.status === 'active'
              ? 'text-gold'
              : quest.status === 'completed'
                ? 'text-textsec'
                : 'text-danger'
          }`}>
            {quest.status.toUpperCase()}
          </span>
          {totalCount > 0 && (
            <span className={`font-ui text-[10px] ${
              doneCount === totalCount ? 'text-gold' : 'text-textsec'
            }`}>
              {doneCount}/{totalCount}
            </span>
          )}
        </div>

        {/* Description */}
        {quest.desc && (
          <QuestSection title="Description">
            <p className="font-body text-sm text-text2 leading-relaxed">{quest.desc}</p>
          </QuestSection>
        )}

        {/* Objectives */}
        <QuestSection title="Objectives">
          {quest.objectives.length === 0 ? (
            <p className="text-[12px] text-textdim font-body">No objectives yet</p>
          ) : (
            <div className="space-y-2">
              {quest.objectives.map((obj) => (
                <label key={obj.id} className="flex items-start gap-2.5 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={obj.done}
                    onChange={() => updateObjective(quest.id, obj.id, { done: !obj.done })}
                    className="mt-0.5 accent-gold shrink-0"
                  />
                  <span className={`font-body text-sm leading-relaxed ${
                    obj.done ? 'text-textdim line-through' : 'text-text'
                  }`}>
                    {obj.text}
                  </span>
                </label>
              ))}
            </div>
          )}
        </QuestSection>

        {/* Notes */}
        {quest.notes && (
          <QuestSection title="Notes">
            <p className="font-body text-sm text-text2 leading-relaxed whitespace-pre-wrap">{quest.notes}</p>
          </QuestSection>
        )}

        {/* Related Lore */}
        {quest.relatedLore.length > 0 && (
          <QuestSection title="Related Lore">
            <div className="flex flex-wrap gap-1.5">
              {quest.relatedLore.map((loreId) => {
                const loreEntry = allLoreEntries.find((e) => e.id === loreId)
                return (
                  <button
                    key={loreId}
                    type="button"
                    className="font-ui text-[10px] text-gold border border-gold/30 bg-gold/5 px-2 py-0.5 tracking-wider hover:bg-gold/10 hover:border-gold/50 transition-colors cursor-pointer"
                    onClick={() => {
                      if (loreEntry) {
                        setLoreCategory(loreEntry.cat)
                      }
                      setActiveTab('lore')
                      selectInto({ kind: 'lore', id: loreId })
                    }}
                    title={loreEntry ? `Jump to: ${loreEntry.title}` : loreId}
                  >
                    {loreEntry ? loreEntry.title : loreId}
                  </button>
                )
              })}
            </div>
          </QuestSection>
        )}
      </div>
    )
  }

  // Edit mode
  const d = draft.current
  return (
    <div className="space-y-6 p-6">
      {/* Delete button */}
      <div className="flex items-start justify-end">
        <button
          type="button"
          className="font-ui text-[9px] text-textdim hover:text-text border border-line px-2 py-1 hover:border-line2 transition-colors shrink-0"
          onClick={() => setShowDeleteConfirm(true)}
        >
          DELETE QUEST
        </button>
        {showDeleteConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
            <div className="bg-bg2 border border-line rounded-lg p-5 max-w-xs space-y-4">
              <p className="font-body text-sm text-text">
                Delete <strong>{quest.title || 'this quest'}</strong>? This removes all objectives.
              </p>
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  className="font-ui text-[9px] text-textdim border border-line px-3 py-1 hover:border-line2 hover:text-text transition-colors"
                  onClick={() => setShowDeleteConfirm(false)}
                >
                  CANCEL
                </button>
                <button
                  type="button"
                  className="font-ui text-[9px] text-bg0 bg-gold hover:bg-gold2 px-3 py-1 transition-colors"
                  onClick={async () => {
                    await deleteQuest(quest.id)
                    select(null)
                  }}
                >
                  DELETE
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Title & Status */}
      <QuestSection title="Basic Info">
        <div className="space-y-3">
          <QuestField
            label="Title"
            value={d.title ?? ''}
            onChange={(v) => update('title', v)}
            onBlur={(v) => update('title', v, true)}
          />
          <label className="block">
            <span className="text-[11px] text-textdim font-body block mb-0.5">Status</span>
            <select
              className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
              defaultValue={d.status ?? 'active'}
              onChange={(e) => update('status', e.target.value, true)}
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </label>
        </div>
      </QuestSection>

      {/* Description */}
      <QuestSection title="Description">
        <QuestTextArea
          value={d.desc ?? ''}
          onChange={(v) => update('desc', v)}
          onBlur={(v) => update('desc', v, true)}
          placeholder="Quest description..."
        />
      </QuestSection>

      {/* Objectives */}
      <QuestSection title="Objectives">
        <div className="space-y-2">
          {quest.objectives.map((obj) => (
            <div key={obj.id} className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={obj.done}
                onChange={() => updateObjective(quest.id, obj.id, { done: !obj.done })}
                className="mt-1.5 accent-gold shrink-0"
                title={`Toggle: ${obj.text}`}
              />
              <ObjectiveEditRow
                text={obj.text}
                onUpdate={(text) => updateObjective(quest.id, obj.id, { text })}
                onDelete={() => deleteObjective(quest.id, obj.id)}
              />
            </div>
          ))}

          {/* Add objective */}
          <div className="flex items-center gap-2 pt-1">
            <input
              className="flex-1 border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
              placeholder="New objective... (Enter)"
              value={newObjText}
              onChange={(e) => setNewObjText(e.target.value)}
              onKeyDown={async (e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  const trimmed = newObjText.trim()
                  if (!trimmed) return
                  await addObjective(quest.id, trimmed)
                  setNewObjText('')
                }
              }}
            />
          </div>
        </div>
      </QuestSection>

      {/* Notes */}
      <QuestSection title="Notes">
        <QuestTextArea
          value={d.notes ?? ''}
          onChange={(v) => update('notes', v)}
          onBlur={(v) => update('notes', v, true)}
          placeholder="Freeform notes..."
        />
      </QuestSection>

      {/* Related Lore — toggle list */}
      <QuestSection title="Related Lore">
        {allLoreEntries.length === 0 ? (
          <p className="text-[12px] text-textdim font-body">
            No lore entries exist yet. Create entries in the Lorebook tab to link them here.
          </p>
        ) : (
          <div className="space-y-1 max-h-[200px] overflow-y-auto">
            {allLoreEntries.map((loreEntry) => {
              const linked = quest.relatedLore.includes(loreEntry.id)
              return (
                <button
                  key={loreEntry.id}
                  type="button"
                  className={`w-full text-left flex items-center gap-2.5 px-2 py-1.5 border transition-colors ${
                    linked
                      ? 'border-gold/30 bg-gold/5'
                      : 'border-transparent hover:bg-bg2'
                  }`}
                  onClick={() => {
                    const updated = linked
                      ? quest.relatedLore.filter((id) => id !== loreEntry.id)
                      : [...quest.relatedLore, loreEntry.id]
                    updateQuest(quest.id, { relatedLore: updated })
                  }}
                >
                  <span className={`w-2 h-2 rounded-full shrink-0 border ${
                    linked
                      ? 'bg-gold border-gold'
                      : 'border-line2'
                  }`} />
                  <span className={`font-body text-sm truncate ${
                    linked ? 'text-gold' : 'text-text'
                  }`}>
                    {loreEntry.title || 'Untitled'}
                  </span>
                  <span className="font-ui text-[9px] text-textdim tracking-wider shrink-0 ml-auto">
                    {loreEntry.cat.toUpperCase()}
                  </span>
                </button>
              )
            })}
          </div>
        )}
      </QuestSection>
    </div>
  )
}

function ObjectiveEditRow({
  text,
  onUpdate,
  onDelete,
}: {
  text: string
  onUpdate: (text: string) => void
  onDelete: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(text)

  if (editing) {
    return (
      <div className="flex-1 flex items-center gap-1.5">
        <input
          className="flex-1 border border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2 transition-colors"
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              const trimmed = editText.trim()
              if (trimmed && trimmed !== text) {
                onUpdate(trimmed)
              }
              setEditing(false)
            } else if (e.key === 'Escape') {
              setEditText(text)
              setEditing(false)
            }
          }}
          onBlur={() => {
            const trimmed = editText.trim()
            if (trimmed && trimmed !== text) {
              onUpdate(trimmed)
            }
            setEditing(false)
          }}
          autoFocus
        />
      </div>
    )
  }

  return (
    <div className="flex-1 flex items-center gap-1.5 group">
      <span
        className="font-body text-sm text-text flex-1 cursor-pointer hover:text-gold transition-colors"
        onClick={() => setEditing(true)}
      >
        {text}
      </span>
      <button
        type="button"
        className="font-ui text-[9px] text-textdim opacity-0 group-hover:opacity-100 hover:text-danger-hover transition-all shrink-0"
        onClick={onDelete}
        title="Delete objective"
      >
        &times;
      </button>
    </div>
  )
}

function QuestSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="font-ui text-[10px] tracking-wider text-textsec uppercase mb-3">{title}</h3>
      {children}
    </section>
  )
}

function QuestField({ label, value, onChange, onBlur, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; onBlur?: (v: string) => void; placeholder?: string
}) {
  return (
    <label className="block">
      {label && <span className="text-[11px] text-textdim font-body block mb-0.5">{label}</span>}
      <input
        className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
        defaultValue={value}
        placeholder={placeholder}
        onBlur={(e) => (onBlur ?? onChange)(e.target.value)}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

function QuestTextArea({ value, onChange, onBlur, placeholder }: {
  value: string; onChange: (v: string) => void; onBlur?: (v: string) => void; placeholder?: string
}) {
  return (
    <ExpandableTextarea
      label={placeholder || 'Edit'}
      className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors resize-y min-h-[72px]"
      rows={3}
      value={value}
      placeholder={placeholder}
      onChange={onChange}
      onBlur={onBlur ?? onChange}
    />
  )
}

// ── Lore Inspector ──────────────────────────────────────────────

const LORE_CATEGORIES: { value: LoreCategory; label: string }[] = [
  { value: 'world', label: 'World' },
  { value: 'characters', label: 'Characters' },
  { value: 'items', label: 'Items' },
  { value: 'monsters', label: 'Monsters' },
  { value: 'spells', label: 'Spells' },
]

const CATEGORY_BADGE_COLORS: Record<LoreCategory, string> = {
  world: 'text-gold',
  characters: 'text-[#7aa6cf]',
  items: 'text-[#5a9e6f]',
  monsters: 'text-[#cf7a7a]',
  spells: 'text-[#a67ecf]',
}

function LoreInspector({ entry, mode }: { entry: LorebookEntry; mode: 'view' | 'edit' }) {
  const updateEntry = useLoreStore((s) => s.updateEntry)
  const deleteEntry = useLoreStore((s) => s.deleteEntry)
  const select = useUiStore((s) => s.select)
  const setEditDirty = useUiStore((s) => s.setEditDirty)

  const draft = useRef<Partial<Omit<LorebookEntry, 'id'>>>(structuredClone(entry))
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [newKeyword, setNewKeyword] = useState('')

  useEffect(() => {
    draft.current = structuredClone(entry)
  }, [entry])

  const flush = useCallback(() => {
    clearTimeout(timer.current)
    const { ...data } = draft.current
    updateEntry(entry.id, data)
    setEditDirty(false)
  }, [entry.id, updateEntry, setEditDirty])

  const scheduleFlush = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, 600)
  }, [flush])

  const update = (key: string, value: unknown, immediate?: boolean) => {
    Object.assign(draft.current, { [key]: value })
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  if (mode === 'view') {
    return (
      <div className="space-y-6 p-6">
        {/* Badges row */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Category badge */}
          <span className={`font-ui text-[9px] tracking-wider uppercase px-2 py-0.5 border border-line ${CATEGORY_BADGE_COLORS[entry.cat]}`}>
            {entry.cat}
          </span>
          {/* Enabled badge */}
          <span className={`font-ui text-[9px] tracking-wider uppercase px-2 py-0.5 border border-line ${
            entry.enabled ? 'text-[#5a9e6f]' : 'text-textdim'
          }`}>
            {entry.enabled ? 'ENABLED' : 'DISABLED'}
          </span>
          {/* Permanent badge */}
          {entry.permanent && (
            <span className="font-ui text-[9px] tracking-wider uppercase px-2 py-0.5 border border-line text-gold">
              PERMANENT
            </span>
          )}
          {/* Locked badge */}
          {entry.locked && (
            <span className="font-ui text-[9px] tracking-wider uppercase px-2 py-0.5 border border-line text-gold2">
              LOCKED
            </span>
          )}
        </div>

        {/* Content */}
        {entry.content && (
          <LoreSection title="Content">
            <p className="font-body text-sm text-text2 leading-relaxed whitespace-pre-wrap">{entry.content}</p>
          </LoreSection>
        )}

        {/* Keywords */}
        <LoreSection title="Keywords">
          {entry.keywords.length === 0 ? (
            <p className="text-[12px] text-textdim font-body">No keywords</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {entry.keywords.map((kw, i) => (
                <span
                  key={i}
                  className="font-ui text-[10px] text-gold border border-gold/30 bg-gold/5 px-2 py-0.5 tracking-wider"
                >
                  {kw}
                </span>
              ))}
            </div>
          )}
        </LoreSection>
      </div>
    )
  }

  // Edit mode
  const d = draft.current
  return (
    <div className="space-y-6 p-6">
      {/* Delete button — hidden for locked entries (e.g. the Scenario) */}
      <div className="flex items-start justify-end">
        {entry.locked ? (
          <span className="font-ui text-[9px] tracking-wider uppercase text-textdim border border-line px-2 py-1 shrink-0">
            Locked · cannot delete
          </span>
        ) : (
          <button
            type="button"
            className="font-ui text-[9px] text-textdim hover:text-text border border-line px-2 py-1 hover:border-line2 transition-colors shrink-0"
            onClick={() => setShowDeleteConfirm(true)}
          >
            DELETE ENTRY
          </button>
        )}
        {showDeleteConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
            <div className="bg-bg2 border border-line rounded-lg p-5 max-w-xs space-y-4">
              <p className="font-body text-sm text-text">
                Delete <strong>{entry.title || 'this entry'}</strong> from the lorebook?
              </p>
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  className="font-ui text-[9px] text-textdim border border-line px-3 py-1 hover:border-line2 hover:text-text transition-colors"
                  onClick={() => setShowDeleteConfirm(false)}
                >
                  CANCEL
                </button>
                <button
                  type="button"
                  className="font-ui text-[9px] text-bg0 bg-gold hover:bg-gold2 px-3 py-1 transition-colors"
                  onClick={async () => {
                    await deleteEntry(entry.id)
                    select(null)
                  }}
                >
                  DELETE
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Title */}
      <LoreSection title="Basic Info">
        <div className="space-y-3">
          <LoreField
            label="Title"
            value={d.title ?? ''}
            onChange={(v) => update('title', v)}
            onBlur={(v) => update('title', v, true)}
          />

          {/* Category select */}
          <label className="block">
            <span className="text-[11px] text-textdim font-body block mb-0.5">Category</span>
            <select
              className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
              defaultValue={d.cat ?? 'world'}
              onChange={(e) => update('cat', e.target.value, true)}
            >
              {LORE_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </label>

          {/* Enabled checkbox */}
          <label className="flex items-center gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              defaultChecked={d.enabled ?? true}
              onChange={(e) => update('enabled', e.target.checked, true)}
              className="accent-gold"
            />
            <span className="font-body text-sm text-text">Enabled</span>
          </label>

          {/* Permanent checkbox */}
          <label className="flex items-center gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              defaultChecked={d.permanent ?? false}
              onChange={(e) => update('permanent', e.target.checked, true)}
              className="accent-gold"
            />
            <span className="font-body text-sm text-text">Permanent</span>
            <span className="font-ui text-[9px] text-textdim tracking-wider">(always inject)</span>
          </label>
        </div>
      </LoreSection>

      {/* Content */}
      <LoreSection title="Content">
        <LoreTextArea
          value={d.content ?? ''}
          onChange={(v) => update('content', v)}
          onBlur={(v) => update('content', v, true)}
          placeholder="Entry content..."
        />
      </LoreSection>

      {/* Keywords */}
      <LoreSection title="Keywords">
        <div className="space-y-2">
          {/* Existing keywords */}
          <div className="flex flex-wrap gap-1.5">
            {(d.keywords ?? []).map((kw, i) => (
              <span
                key={i}
                className="font-ui text-[10px] text-gold border border-gold/30 bg-gold/5 px-2 py-0.5 tracking-wider flex items-center gap-1.5 group"
              >
                {kw}
                <button
                  type="button"
                  className="text-textdim hover:text-text transition-colors text-[11px] leading-none"
                  onClick={() => {
                    const updated = (d.keywords ?? []).filter((_, idx) => idx !== i)
                    update('keywords', updated, true)
                  }}
                  title="Remove keyword"
                >
                  &times;
                </button>
              </span>
            ))}
          </div>

          {/* Add keyword input */}
          <input
            className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
            placeholder="Type keyword + Enter"
            value={newKeyword}
            onChange={(e) => setNewKeyword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                const trimmed = newKeyword.trim()
                if (!trimmed) return
                const current = d.keywords ?? []
                if (!current.includes(trimmed)) {
                  update('keywords', [...current, trimmed], true)
                }
                setNewKeyword('')
              }
            }}
          />
        </div>
      </LoreSection>
    </div>
  )
}

function LoreSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="font-ui text-[10px] tracking-wider text-textsec uppercase mb-3">{title}</h3>
      {children}
    </section>
  )
}

function LoreField({ label, value, onChange, onBlur, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; onBlur?: (v: string) => void; placeholder?: string
}) {
  return (
    <label className="block">
      {label && <span className="text-[11px] text-textdim font-body block mb-0.5">{label}</span>}
      <input
        className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
        defaultValue={value}
        placeholder={placeholder}
        onBlur={(e) => (onBlur ?? onChange)(e.target.value)}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

function LoreTextArea({ value, onChange, onBlur, placeholder }: {
  value: string; onChange: (v: string) => void; onBlur?: (v: string) => void; placeholder?: string
}) {
  return (
    <ExpandableTextarea
      label={placeholder || 'Edit'}
      className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors resize-y min-h-[72px]"
      rows={4}
      value={value}
      placeholder={placeholder}
      onChange={onChange}
      onBlur={onBlur ?? onChange}
    />
  )
}

function EmptyState() {
  return (
    <div className="flex items-center justify-center h-full p-6">
      <div className="text-center space-y-2">
        <p className="font-ui text-[10px] text-textdim tracking-wider">INSPECTOR</p>
        <p className="text-[12px] text-textsec font-body">
          Select a character, item, quest, or lore entry to view and edit details.
        </p>
      </div>
    </div>
  )
}
