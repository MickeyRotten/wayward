import { useCallback, useEffect, useRef, useState } from 'react'
import type { ItemCatalogEntry, ItemType, Rarity, Equipment, PlayerCharacter, PartyMember } from '@shared/types/models'
import { useItemsStore } from '../../state/itemsStore'
import { usePartyStore } from '../../state/partyStore'
import { useUiStore } from '../../state/uiStore'
import { EQUIP_SLOT_LABELS, pickEquipSlot } from '../../lib/equipSlots'
import { ExpandableTextarea } from '../common/ExpandableTextarea'

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

const ITEM_TYPES: ItemType[] = ['Equipment', 'Tool', 'Consumable', 'Key Item', 'Artifact', 'Currency', 'Other']
// Coarse body-slot categories (match the server's slot compatibility map).
const SLOT_OPTIONS = ['Head', 'Neck', 'Torso', 'Hands', 'Waist', 'Legs', 'Feet', 'Accessory']
const RARITY_OPTIONS: { value: Rarity; label: string }[] = [
  { value: 'c', label: 'Common' },
  { value: 'u', label: 'Uncommon' },
  { value: 'r', label: 'Rare' },
  { value: 'e', label: 'Epic' },
  { value: 'l', label: 'Legendary' },
]

export function ItemInspector({ item, instanceId, lockTypeSlot, openInEdit, onClose }: {
  item: ItemCatalogEntry
  instanceId?: string
  lockTypeSlot?: boolean
  openInEdit?: boolean
  /** Called after the item is deleted from the catalog — lets the caller decide
   * where to land (a standalone selection clears to null; a drilled-into view
   * returns to the owning character's sheet instead of blanking the Inspector). */
  onClose: () => void
}) {
  // View is the default for an existing item; Edit is entered explicitly via
  // the EDIT button, except right after "Create an Item" (Lore or the
  // Equipment tab), which skips straight to Edit since there's nothing to
  // view yet. Local to this component (remounts per item — see the `key` at
  // the call site) rather than the app-wide Play/Edit mode.
  const [editing, setEditing] = useState(!!openInEdit)
  const updateItem = useItemsStore((s) => s.updateItem)
  const deleteItem = useItemsStore((s) => s.deleteItem)
  const removeInstance = useItemsStore((s) => s.removeInstance)
  const inventory = useItemsStore((s) => s.inventory)
  const pc = usePartyStore((s) => s.playerCharacter)
  const members = usePartyStore((s) => s.partyMembers)
  const equipItem = usePartyStore((s) => s.equipItem)
  const unequipSlot = usePartyStore((s) => s.unequipSlot)
  const setEditDirty = useUiStore((s) => s.setEditDirty)

  const draft = useRef<Partial<ItemCatalogEntry>>(structuredClone(item))
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [removeError, setRemoveError] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const [newKeyword, setNewKeyword] = useState('')

  // The specific copy inspected (when opened from an inventory row), plus the
  // aggregate view: every character wearing a copy, and the stowed count.
  const thisInstance = instanceId ? inventory.find((s) => s.instanceId === instanceId) : undefined
  const stowedCount = inventory.filter((s) => s.itemId === item.id && !s.equippedBy).length
  const wornBy = inventory
    .filter((s) => s.itemId === item.id && s.equippedBy)
    .map((s) => ({ charId: s.equippedBy as string, name: s.equippedByName || 'Someone', slot: s.slot as string }))
  const firstStowed = () => inventory.find((s) => s.itemId === item.id && !s.equippedBy)

  const charEquipment = (charId: string): Equipment | undefined =>
    pc && charId === pc.id ? pc.equipment : members.find((m) => m.id === charId)?.equipment

  // Equip a stowed copy onto a character (best-fitting slot; any prior occupant
  // is auto-unequipped by pickEquipSlot + the server). When a specific copy is
  // inspected, equip THAT instance; otherwise pick any stowed copy.
  const equipOnto = async (charId: string) => {
    setPickerOpen(false)
    const equipment = charEquipment(charId)
    if (!equipment) return
    const slot = pickEquipSlot(item.slot, equipment)
    const copyId = thisInstance ? thisInstance.instanceId : firstStowed()?.instanceId
    await equipItem(charId, item.id, slot, copyId)
  }

  const unequipFrom = async (charId: string, slot: string) => {
    await unequipSlot(charId, slot)
  }

  const dropItem = async () => {
    setRemoveError('')
    // Prefer the inspected copy; never drop a worn copy.
    const target = thisInstance ?? firstStowed()
    if (!target || target.equippedBy) return
    try { await removeInstance(target.instanceId) } catch (e: unknown) {
      setRemoveError(e instanceof Error ? e.message : 'Failed')
    }
  }

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

  const update = (key: string, value: unknown, immediate?: boolean) => {
    Object.assign(draft.current, { [key]: value })
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  if (!editing) {
    return (
      <div className="space-y-6 p-6">
        {/* Badges row + Close */}
        <div className="flex items-center justify-between gap-2 flex-wrap">
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
          <button
            type="button"
            aria-label="Close"
            className="font-ui text-[13px] text-textdim hover:text-text transition-colors shrink-0"
            onClick={onClose}
          >
            ✕
          </button>
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

        {/* Lorebook-entry rules — shown for the catalog item (not a single copy),
            since items are lorebook entries with keyword injection. */}
        {!thisInstance && (
          <ItemSection title="Lorebook">
            <div className="flex items-center gap-2 flex-wrap mb-2">
              <span className={`font-ui text-[9px] tracking-wider uppercase px-2 py-0.5 border border-line ${item.enabled ? 'text-[#5a9e6f]' : 'text-textdim'}`}>
                {item.enabled ? 'ENABLED' : 'DISABLED'}
              </span>
              {item.permanent && (
                <span className="font-ui text-[9px] tracking-wider uppercase px-2 py-0.5 border border-line text-gold">
                  PERMANENT
                </span>
              )}
            </div>
            {(item.keywords?.length ?? 0) === 0 ? (
              <p className="text-[12px] text-textdim font-body">No keywords</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {item.keywords.map((kw, i) => (
                  <span key={i} className="font-ui text-[10px] text-gold border border-gold/30 bg-gold/5 px-2 py-0.5 tracking-wider">
                    {kw}
                  </span>
                ))}
              </div>
            )}
          </ItemSection>
        )}

        {thisInstance ? (
          /* Per-instance view: a specific copy was selected in the Inventory —
             show only THAT copy's state and act on it alone. */
          <>
            <ItemSection title="This Copy">
              <div className="flex items-center justify-between gap-2">
                <span className="font-body text-sm text-text">
                  {thisInstance.equippedBy ? (
                    <>
                      Equipped by <span className="text-gold2">{thisInstance.equippedByName || 'Someone'}</span>
                      {thisInstance.slot && (
                        <span className="text-textdim"> · {EQUIP_SLOT_LABELS[thisInstance.slot as keyof Equipment] ?? thisInstance.slot}</span>
                      )}
                    </>
                  ) : (
                    'Stowed in the pack'
                  )}
                </span>
                {!thisInstance.equippedBy && (
                  <button
                    type="button"
                    className="font-ui text-[9px] text-textdim hover:text-danger border border-line hover:border-line2 px-2 py-1 transition-colors shrink-0"
                    onClick={dropItem}
                  >
                    DROP ITEM
                  </button>
                )}
              </div>
              {removeError && <p className="text-[11px] text-danger font-body mt-1">{removeError}</p>}
            </ItemSection>

            {item.type === 'Equipment' && (
              <ItemSection title="Equip">
                <div className="space-y-2">
                  {thisInstance.equippedBy ? (
                    <button
                      type="button"
                      className="w-full font-ui text-[10px] tracking-wider text-textsec border border-line px-3 py-2 hover:border-line2 hover:text-text transition-colors"
                      onClick={() => unequipFrom(thisInstance.equippedBy as string, thisInstance.slot as string)}
                    >
                      Unequip
                    </button>
                  ) : (pickerOpen ? (
                    <EquipPicker pc={pc} members={members} onPick={equipOnto} onCancel={() => setPickerOpen(false)} />
                  ) : (
                    <button
                      type="button"
                      className="w-full font-ui text-[10px] tracking-wider text-textsec border border-dashed border-line px-3 py-2 hover:border-line2 hover:text-text transition-colors"
                      onClick={() => setPickerOpen(true)}
                    >
                      Equip
                    </button>
                  ))}
                </div>
              </ItemSection>
            )}
          </>
        ) : (
          /* Aggregate view: opened from Lore → Items (no specific copy). */
          <>
            {stowedCount > 0 && (
              <ItemSection title="Inventory">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-body text-sm text-text">
                    Stowed: <span className="text-gold">{stowedCount}</span>
                  </span>
                  <button
                    type="button"
                    className="font-ui text-[9px] text-textdim hover:text-danger border border-line hover:border-line2 px-2 py-1 transition-colors shrink-0"
                    onClick={dropItem}
                  >
                    DROP ITEM
                  </button>
                </div>
                {removeError && <p className="text-[11px] text-danger font-body mt-1">{removeError}</p>}
              </ItemSection>
            )}

            {item.type === 'Equipment' && (
              <ItemSection title="Equip">
                <div className="space-y-2">
                  {wornBy.length > 0 ? (
                    wornBy.map((w, i) => (
                      <div key={`${w.charId}-${w.slot}-${i}`} className="flex items-center justify-between gap-2">
                        <span className="font-body text-sm text-text">
                          <span className="text-gold2">{w.name}</span>
                          <span className="text-textdim"> · {EQUIP_SLOT_LABELS[w.slot as keyof Equipment] ?? w.slot}</span>
                        </span>
                        <button
                          type="button"
                          className="font-ui text-[9px] text-textdim hover:text-text border border-line hover:border-line2 px-2 py-1 transition-colors shrink-0"
                          onClick={() => unequipFrom(w.charId, w.slot)}
                        >
                          UNEQUIP
                        </button>
                      </div>
                    ))
                  ) : (
                    <p className="font-body text-[12px] text-textdim">Not equipped by anyone.</p>
                  )}

                  {stowedCount > 0 && (pickerOpen ? (
                    <EquipPicker pc={pc} members={members} onPick={equipOnto} onCancel={() => setPickerOpen(false)} />
                  ) : (
                    <button
                      type="button"
                      className="w-full font-ui text-[10px] tracking-wider text-textsec border border-dashed border-line px-3 py-2 hover:border-line2 hover:text-text transition-colors"
                      onClick={() => setPickerOpen(true)}
                    >
                      + EQUIP TO…
                    </button>
                  ))}
                </div>
              </ItemSection>
            )}
          </>
        )}

        <div className="flex justify-end">
          <button
            type="button"
            className="font-ui text-[9px] tracking-wider text-textdim hover:text-text border border-line px-2.5 py-1 hover:border-line2 transition-colors"
            onClick={() => setEditing(true)}
          >
            EDIT
          </button>
        </div>
      </div>
    )
  }

  // Edit mode
  const d = draft.current
  return (
    <div className="space-y-6 p-6">
      {/* View / Delete buttons + Close */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <button
            type="button"
            className="font-ui text-[9px] text-textdim hover:text-text border border-line px-2 py-1 hover:border-line2 transition-colors shrink-0"
            onClick={() => setEditing(false)}
          >
            VIEW
          </button>
          <button
            type="button"
            className="font-ui text-[9px] text-textdim hover:text-text border border-line px-2 py-1 hover:border-line2 transition-colors shrink-0"
            onClick={() => setShowDeleteConfirm(true)}
          >
            DELETE ITEM
          </button>
        </div>
        <button
          type="button"
          aria-label="Close"
          className="font-ui text-[13px] text-textdim hover:text-text transition-colors shrink-0"
          onClick={onClose}
        >
          ✕
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
                    onClose()
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
              className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              defaultValue={d.type ?? 'Other'}
              disabled={lockTypeSlot}
              onChange={(e) => update('type', e.target.value, true)}
            >
              {ITEM_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            {lockTypeSlot && (
              <span className="text-[10px] text-textdim font-ui block mt-0.5">Locked — created for this slot</span>
            )}
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

          {/* Slot (only meaningful for Equipment) — a dropdown of body slots. */}
          <label className="block">
            <span className="text-[11px] text-textdim font-body block mb-0.5">Slot (equipment only)</span>
            <select
              className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              value={d.slot ?? ''}
              disabled={lockTypeSlot}
              onChange={(e) => update('slot', e.target.value || null, true)}
            >
              <option value="">— None —</option>
              {SLOT_OPTIONS.map((sl) => (
                <option key={sl} value={sl}>{sl}</option>
              ))}
            </select>
          </label>

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

      {/* Lorebook entry rules — items are lorebook entries, so they share the
          same enabled / permanent / keyword-injection controls as other lore. */}
      <ItemSection title="Lorebook">
        <div className="space-y-3">
          <label className="flex items-center gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              defaultChecked={d.enabled ?? true}
              onChange={(e) => update('enabled', e.target.checked, true)}
              className="accent-gold"
            />
            <span className="font-body text-sm text-text">Enabled</span>
          </label>
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
      </ItemSection>

      {/* Keywords */}
      <ItemSection title="Keywords">
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {(d.keywords ?? []).map((kw, i) => (
              <span
                key={i}
                className="font-ui text-[10px] text-gold border border-gold/30 bg-gold/5 px-2 py-0.5 tracking-wider flex items-center gap-1.5"
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

/** Picker: choose a character (PC or any member, incl. benched) to equip onto. */
function EquipPicker({ pc, members, onPick, onCancel }: {
  pc: PlayerCharacter | null
  members: PartyMember[]
  onPick: (charId: string) => void
  onCancel: () => void
}) {
  const chars = [
    ...(pc ? [{ id: pc.id, name: pc.basicInfo?.name || 'You', benched: false }] : []),
    ...members.map((m) => ({ id: m.id, name: m.basicInfo?.name || 'Unnamed', benched: !m.inParty })),
  ]
  return (
    <div className="border border-line2 rounded-md bg-bg1 p-1.5 space-y-0.5">
      <div className="flex items-center justify-between px-1 pb-0.5">
        <span className="font-ui text-[8px] tracking-wider text-textdim uppercase">Equip to…</span>
        <button type="button" className="font-ui text-[10px] text-textdim hover:text-text" onClick={onCancel} aria-label="Cancel">✕</button>
      </div>
      {chars.length === 0 ? (
        <p className="font-body text-[11px] text-textdim px-1 py-1">No characters.</p>
      ) : chars.map((c) => (
        <button
          key={c.id}
          type="button"
          className="w-full text-left font-body text-[13px] text-text px-2 py-1.5 rounded-sm hover:bg-bg3 transition-colors flex items-center gap-2"
          onClick={() => onPick(c.id)}
        >
          <span className="truncate flex-1">{c.name}</span>
          {c.benched && <span className="font-ui text-[8px] tracking-wider text-textdim uppercase shrink-0">benched</span>}
        </button>
      ))}
    </div>
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
