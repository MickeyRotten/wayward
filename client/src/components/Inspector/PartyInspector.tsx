import { useCallback, useEffect, useRef, useState } from 'react'
import { usePartyStore } from '../../state/partyStore'
import { useItemsStore } from '../../state/itemsStore'
import { useUiStore } from '../../state/uiStore'
import { CharacterSheetEditor } from '../CharacterSheet/CharacterSheetEditor'
import { PartyMemberEditor } from '../PartyMember/PartyMemberEditor'
import type { ItemCatalogEntry, ItemType, Rarity } from '@shared/types/models'

export function PartyInspector() {
  const pc = usePartyStore((s) => s.playerCharacter)
  const members = usePartyStore((s) => s.partyMembers)
  const catalog = useItemsStore((s) => s.catalog)
  const inventory = useItemsStore((s) => s.inventory)
  const selection = useUiStore((s) => s.selection)
  const everSelected = useUiStore((s) => s.everSelected)
  const mode = useUiStore((s) => s.mode)
  const editDirty = useUiStore((s) => s.editDirty)
  const setMode = useUiStore((s) => s.setMode)

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

  const hasSelection = selIsPC || selIsMember || selIsItem

  // Derive entity name for the header
  const entityName = selIsPC
    ? (pc!.basicInfo.name || 'New Character')
    : selIsMember
      ? (selMember!.basicInfo.name || 'New Member')
      : selIsItem
        ? (selItem!.name || 'Unknown Item')
        : ''

  const entityLabel = selIsPC
    ? 'PLAYER CHARACTER'
    : selIsMember
      ? 'PARTY MEMBER'
      : selIsItem
        ? 'ITEM'
        : ''

  return (
    <div className="flex flex-col h-full">
      {/* Inspector Header */}
      {hasSelection && (
        <div className="shrink-0 border-b border-line px-6 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <span className="font-ui text-[9px] text-textdim tracking-wider">{entityLabel}</span>
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
              {/* View/Edit toggle */}
              <button
                type="button"
                className={`font-ui text-[9px] tracking-wider px-2.5 py-1 border-[1.5px] transition-colors ${
                  mode === 'view'
                    ? 'text-textsec border-line hover:text-text hover:border-line2'
                    : 'text-gold border-gold/40 hover:border-gold/60'
                }`}
                onClick={() => setMode(mode === 'view' ? 'edit' : 'view')}
              >
                {mode === 'view' ? 'EDIT' : 'VIEW'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Inspector Body — single scrollable child */}
      <div className="flex-1 overflow-y-auto">
        {hasSelection && <SaveIndicator />}
        {selIsPC ? (
          <CharacterSheetEditor mode={mode} />
        ) : selIsMember ? (
          <PartyMemberEditor key={selMember!.id} member={selMember!} mode={mode} />
        ) : selIsItem ? (
          <ItemInspector key={selItem!.id} item={selItem!} mode={mode} />
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

  return (
    <div
      className={`sticky top-0 z-10 text-right pr-6 pt-2 font-ui text-[9px] text-textdim tracking-wider transition-opacity duration-300 ${
        visible ? 'opacity-100' : 'opacity-0'
      }`}
    >
      SAVED
    </div>
  )
}

// ── Item Inspector ──────────────────────────────────────────────

const RARITY_COLORS: Record<Rarity, string> = {
  c: 'bg-[#6c654f]',
  u: 'bg-[#5a9e6f]',
  r: 'bg-[#7aa6cf]',
  e: 'bg-[#a67ecf]',
  l: 'bg-gold',
}

const RARITY_LABELS: Record<Rarity, string> = {
  c: 'Common',
  u: 'Uncommon',
  r: 'Rare',
  e: 'Epic',
  l: 'Legendary',
}

const RARITY_TEXT_COLORS: Record<Rarity, string> = {
  c: 'text-[#6c654f]',
  u: 'text-[#5a9e6f]',
  r: 'text-[#7aa6cf]',
  e: 'text-[#a67ecf]',
  l: 'text-gold',
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
                className="font-ui text-[9px] text-textdim hover:text-text border-[1.5px] border-line hover:border-line2 px-2 py-1 transition-colors"
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
              <p className="text-[11px] text-red-400 font-body mt-1">{removeError}</p>
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
          className="font-ui text-[9px] text-textdim hover:text-text border-[1.5px] border-line px-2 py-1 hover:border-line2 transition-colors shrink-0"
          onClick={() => setShowDeleteConfirm(true)}
        >
          DELETE ITEM
        </button>
        {showDeleteConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
            <div className="bg-bg2 border border-line p-5 max-w-xs space-y-4">
              <p className="font-body text-sm text-text">
                Delete <strong>{item.name || 'this item'}</strong> from the catalog? This also removes it from inventory.
              </p>
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  className="font-ui text-[9px] text-textdim border-[1.5px] border-line px-3 py-1 hover:border-line2 hover:text-text transition-colors"
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
              className="w-full border-[1.5px] border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
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
              className="w-full border-[1.5px] border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
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
        className="w-full border-[1.5px] border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
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
        className="w-full border-[1.5px] border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
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
      <textarea
        className="w-full border-[1.5px] border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors resize-y min-h-[72px]"
        rows={3}
        defaultValue={value}
        placeholder={placeholder}
        onBlur={(e) => (onBlur ?? onChange)(e.target.value)}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

function EmptyState() {
  return (
    <div className="flex items-center justify-center h-full p-6">
      <div className="text-center space-y-2">
        <p className="font-ui text-[10px] text-textdim tracking-wider">INSPECTOR</p>
        <p className="text-[12px] text-textsec font-body">
          Select a character or item to view and edit details.
        </p>
      </div>
    </div>
  )
}
