import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { usePartyStore } from '../../state/partyStore'
import { useItemsStore } from '../../state/itemsStore'
import { useTasksStore } from '../../state/tasksStore'
import { useLoreStore } from '../../state/loreStore'
import { useScenarioStore } from '../../state/scenarioStore'
import { useNarratorStore } from '../../state/narratorStore'
import { useUiStore } from '../../state/uiStore'
import { useChatStore } from '../../state/chatStore'
import { CharacterSheetEditor } from '../CharacterSheet/CharacterSheetEditor'
import { PartyMemberEditor } from '../PartyMember/PartyMemberEditor'
import { ExpandableTextarea } from '../common/ExpandableTextarea'
import { EQUIP_SLOT_LABELS, pickEquipSlot } from '../../lib/equipSlots'
import { SCENARIO_FIELD_DEFS, FIRST_MESSAGE_ID, openingIndexOf } from '../../lib/scenarioFields'
import type { ItemCatalogEntry, ItemType, Rarity, Task, LorebookEntry, LoreCategory, Equipment, PlayerCharacter, PartyMember } from '@shared/types/models'

export function PartyInspector() {
  const pc = usePartyStore((s) => s.playerCharacter)
  const members = usePartyStore((s) => s.partyMembers)
  const catalog = useItemsStore((s) => s.catalog)
  const inventory = useItemsStore((s) => s.inventory)
  const tasks = useTasksStore((s) => s.tasks)
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
  const setPlanningMode = useChatStore((s) => s.setPlanningMode)
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

  // Task selection
  const selTask = selection?.kind === 'task'
    ? tasks.find((t) => t.id === selection.id)
    : undefined
  const selIsTask = !!selTask

  // Lore selection
  const selLore = selection?.kind === 'lore'
    ? loreEntries.find((e) => e.id === selection.id)
    : undefined
  const selIsLore = !!selLore

  // Scenario field selection (a Scenario tab card — field key or firstMessage)
  const selScenarioId = selection?.kind === 'scenario' ? selection.id : undefined
  const selIsScenario = !!selScenarioId

  const hasSelection = selIsPC || selIsMember || selIsItem || selIsTask || selIsLore || selIsScenario

  // Derive entity name for the header
  const entityName = selIsPC
    ? (pc!.basicInfo.name || 'New Character')
    : selIsMember
      ? (selMember!.basicInfo.name || 'New Member')
      : selIsItem
        ? (selItem!.name || 'Unknown Item')
        : selIsTask
          ? (selTask!.text || 'Untitled Task')
          : selIsLore
            ? (selLore!.title || 'Untitled Entry')
            : selIsScenario
              ? (() => {
                  const oi = selScenarioId ? openingIndexOf(selScenarioId) : null
                  if (oi === 0) return 'First Message'
                  if (oi !== null) return `Alternate ${oi}`
                  return SCENARIO_FIELD_DEFS.find((d) => d.key === selScenarioId)?.label ?? 'Scenario'
                })()
              : ''

  const entityLabel = selIsPC
    ? 'PLAYER CHARACTER'
    : selIsMember
      ? 'PARTY MEMBER'
      : selIsItem
        ? 'ITEM'
        : selIsTask
          ? 'TASK'
          : selIsLore
            ? 'LOREBOOK ENTRY'
            : selIsScenario
              ? (selScenarioId && openingIndexOf(selScenarioId) !== null ? 'OPENING NARRATION' : 'SCENARIO')
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
              {/* Mode follows the chat's Edit Mode — tap to toggle it in place
                  (the selection is preserved across mode flips). */}
              <button
                type="button"
                className={`font-ui text-[9px] tracking-wider px-2.5 py-1 border transition-colors ${
                  mode === 'edit'
                    ? 'text-gold border-gold/40 hover:border-gold'
                    : 'text-textdim border-line hover:text-textsec hover:border-line2'
                }`}
                title={mode === 'edit' ? 'Switch to Play mode (view)' : 'Switch to Edit Mode to edit'}
                onClick={() => setPlanningMode(!editMode)}
              >
                {mode === 'edit' ? 'EDITING' : 'VIEW'}
              </button>
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
          <ItemInspector
            key={(selection?.kind === 'item' ? selection.instanceId : '') || selItem!.id}
            item={selItem!}
            instanceId={selection?.kind === 'item' ? selection.instanceId : undefined}
            mode={mode}
          />
        ) : selIsTask ? (
          <TaskInspector key={selTask!.id} task={selTask!} mode={mode} />
        ) : selIsLore ? (
          <LoreInspector key={selLore!.id} entry={selLore!} mode={mode} />
        ) : selIsScenario ? (
          <ScenarioFieldInspector key={selScenarioId} fieldKey={selScenarioId!} mode={mode} />
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

function ItemInspector({ item, instanceId, mode }: { item: ItemCatalogEntry; instanceId?: string; mode: 'view' | 'edit' }) {
  const updateItem = useItemsStore((s) => s.updateItem)
  const deleteItem = useItemsStore((s) => s.deleteItem)
  const removeInstance = useItemsStore((s) => s.removeInstance)
  const inventory = useItemsStore((s) => s.inventory)
  const pc = usePartyStore((s) => s.playerCharacter)
  const members = usePartyStore((s) => s.partyMembers)
  const equipItem = usePartyStore((s) => s.equipItem)
  const unequipSlot = usePartyStore((s) => s.unequipSlot)
  const select = useUiStore((s) => s.select)
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

          {/* Slot (only meaningful for Equipment) — a dropdown of body slots. */}
          <label className="block">
            <span className="text-[11px] text-textdim font-body block mb-0.5">Slot (equipment only)</span>
            <select
              className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
              value={d.slot ?? ''}
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

// ── Task Inspector ──────────────────────────────────────────────

const STATUS_OPTIONS: { value: Task['status']; label: string }[] = [
  { value: 'active', label: 'To do' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
]

function TaskInspector({ task, mode }: { task: Task; mode: 'view' | 'edit' }) {
  const updateTask = useTasksStore((s) => s.updateTask)
  const deleteTask = useTasksStore((s) => s.deleteTask)
  const select = useUiStore((s) => s.select)
  const setEditDirty = useUiStore((s) => s.setEditDirty)

  const draft = useRef<Partial<Pick<Task, 'text' | 'status' | 'notes'>>>(
    { text: task.text, status: task.status, notes: task.notes }
  )
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  useEffect(() => {
    draft.current = { text: task.text, status: task.status, notes: task.notes }
  }, [task])

  const flush = useCallback(() => {
    clearTimeout(timer.current)
    updateTask(task.id, draft.current)
    setEditDirty(false)
  }, [task.id, updateTask, setEditDirty])

  const scheduleFlush = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, 600)
  }, [flush])

  const update = (key: string, value: string, immediate?: boolean) => {
    Object.assign(draft.current, { [key]: value })
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  if (mode === 'view') {
    return (
      <div className="space-y-6 p-6">
        {/* Status badge */}
        <div className="flex items-center gap-2">
          <span className={`font-ui text-[9px] tracking-wider uppercase px-2 py-0.5 border border-line ${
            task.status === 'active'
              ? 'text-gold'
              : task.status === 'completed'
                ? 'text-textsec'
                : 'text-danger'
          }`}>
            {task.status === 'active' ? 'TO DO' : task.status.toUpperCase()}
          </span>
        </div>

        {/* Task text */}
        <TaskSection title="Task">
          <p className={`font-body text-sm leading-relaxed ${task.status === 'completed' ? 'text-textdim line-through' : 'text-text2'}`}>
            {task.text || 'Untitled task'}
          </p>
        </TaskSection>

        {/* Quick status actions */}
        <div className="flex gap-2">
          {task.status !== 'completed' && (
            <button
              type="button"
              className="font-ui text-[10px] tracking-wider text-textsec border border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
              onClick={() => updateTask(task.id, { status: 'completed' })}
            >
              MARK DONE
            </button>
          )}
          {task.status !== 'active' && (
            <button
              type="button"
              className="font-ui text-[10px] tracking-wider text-textsec border border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
              onClick={() => updateTask(task.id, { status: 'active' })}
            >
              RE-OPEN
            </button>
          )}
          {task.status !== 'failed' && (
            <button
              type="button"
              className="font-ui text-[10px] tracking-wider text-textdim border border-line px-3 py-1.5 hover:border-danger hover:text-danger transition-colors"
              onClick={() => updateTask(task.id, { status: 'failed' })}
            >
              FAILED
            </button>
          )}
        </div>

        {/* Notes */}
        {task.notes && (
          <TaskSection title="Notes">
            <p className="font-body text-sm text-text2 leading-relaxed whitespace-pre-wrap">{task.notes}</p>
          </TaskSection>
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
          DELETE TASK
        </button>
        {showDeleteConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
            <div className="bg-bg2 border border-line rounded-lg p-5 max-w-xs space-y-4">
              <p className="font-body text-sm text-text">
                Delete <strong>{task.text || 'this task'}</strong>?
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
                    await deleteTask(task.id)
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

      {/* Task text & Status */}
      <TaskSection title="Task">
        <div className="space-y-3">
          <TaskTextArea
            value={d.text ?? ''}
            onChange={(v) => update('text', v)}
            onBlur={(v) => update('text', v, true)}
            placeholder="What needs doing..."
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
      </TaskSection>

      {/* Notes */}
      <TaskSection title="Notes">
        <TaskTextArea
          value={d.notes ?? ''}
          onChange={(v) => update('notes', v)}
          onBlur={(v) => update('notes', v, true)}
          placeholder="Freeform notes..."
        />
      </TaskSection>
    </div>
  )
}

function TaskSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="font-ui text-[10px] tracking-wider text-textsec uppercase mb-3">{title}</h3>
      {children}
    </section>
  )
}

function TaskTextArea({ value, onChange, onBlur, placeholder }: {
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
  { value: 'pillars', label: 'Pillars' },
  { value: 'world', label: 'Locations' },
  { value: 'characters', label: 'Characters' },
  { value: 'items', label: 'Items' },
  { value: 'monsters', label: 'Monsters' },
  { value: 'spells', label: 'Spells' },
]

const CATEGORY_BADGE_COLORS: Record<LoreCategory, string> = {
  pillars: 'text-[#d0a15a]',
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

// ── Scenario Field Inspector ────────────────────────────────────
// A Scenario tab card opens here — view in Play, edit in Edit Mode, like any
// other lore entry. The save path is unchanged: fields go through the same
// debounced partial PUT /scenario the old inline tab editor used (composing
// into the locked World entry), and First Message saves on the NarratorConfig.

function ScenarioFieldInspector({ fieldKey, mode }: { fieldKey: string; mode: 'view' | 'edit' }) {
  const openIndex = openingIndexOf(fieldKey)  // 0 = First Message, k>0 = alternate, null = scenario field
  const isOpening = openIndex !== null
  const altIndex = openIndex !== null && openIndex > 0 ? openIndex - 1 : -1
  const def = SCENARIO_FIELD_DEFS.find((d) => d.key === fieldKey)
  const scenarioValue = useScenarioStore((s) => (def ? s[def.key] : ''))
  const saveScenario = useScenarioStore((s) => s.save)
  const firstMessage = useNarratorStore((s) => s.firstMessage)
  const firstMessageOptions = useNarratorStore((s) => s.firstMessageOptions)
  const firstMessageAlternates = useNarratorStore((s) => s.firstMessageAlternates)
  const saveNarrator = useNarratorStore((s) => s.save)
  const setEditDirty = useUiStore((s) => s.setEditDirty)
  const select = useUiStore((s) => s.select)

  // The message + scripted options for the specific opening being edited.
  const openingMessage = openIndex === 0
    ? firstMessage
    : (altIndex >= 0 ? (firstMessageAlternates[altIndex]?.message ?? '') : '')
  const openingOptions = useMemo(
    () => (openIndex === 0
      ? firstMessageOptions
      : (altIndex >= 0 ? (firstMessageAlternates[altIndex]?.options ?? []) : [])),
    [openIndex, altIndex, firstMessageOptions, firstMessageAlternates],
  )

  const [options, setOptions] = useState<string[]>(openingOptions)
  useEffect(() => { setOptions(openingOptions) }, [openingOptions])
  // An alternate's message and options share one field (firstMessageAlternates),
  // so each partial write must merge onto the FRESHEST array from the store —
  // reading the closure could clobber a concurrent debounced save of the other.
  const commitOptions = (next: string[]) => {
    setOptions(next)
    if (openIndex === 0) void saveNarrator({ firstMessageOptions: next })
    else if (altIndex >= 0) {
      const cur = useNarratorStore.getState().firstMessageAlternates
      void saveNarrator({
        firstMessageAlternates: cur.map((a, j) => (j === altIndex ? { ...a, options: next } : a)),
      })
    }
  }

  const removeOpening = () => {
    if (altIndex < 0) return
    void saveNarrator({ firstMessageAlternates: firstMessageAlternates.filter((_, j) => j !== altIndex) })
    select({ kind: 'scenario', id: FIRST_MESSAGE_ID })
  }

  const stored = isOpening ? openingMessage : scenarioValue
  const label = openIndex === 0 ? 'First Message' : altIndex >= 0 ? `Alternate ${openIndex}` : def?.label ?? 'Scenario'
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const commit = useCallback((v: string) => {
    clearTimeout(timer.current)
    setEditDirty(false)
    if (openIndex === 0) void saveNarrator({ firstMessage: v })
    else if (altIndex >= 0) {
      const cur = useNarratorStore.getState().firstMessageAlternates
      void saveNarrator({
        firstMessageAlternates: cur.map((a, j) => (j === altIndex ? { ...a, message: v } : a)),
      })
    } else if (def) void saveScenario({ [def.key]: v })
  }, [openIndex, altIndex, def, saveNarrator, saveScenario, setEditDirty])

  const scheduleCommit = (v: string) => {
    setEditDirty(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => commit(v), 600)
  }

  const note = isOpening
    ? 'The drop-capped opening, included in context. Its options show at turn 0. Not part of the Scenario.'
    : 'Part of the Scenario — composed into the permanent, locked World entry and always injected into the narration.'

  if (mode === 'view') {
    return (
      <div className="space-y-6 p-6">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-ui text-[9px] tracking-wider uppercase px-2 py-0.5 border border-line text-gold">
            {isOpening ? 'NARRATOR CONFIG' : 'SCENARIO'}
          </span>
          {!isOpening && (
            <span className="font-ui text-[9px] tracking-wider uppercase px-2 py-0.5 border border-line text-gold2">
              LOCKED
            </span>
          )}
        </div>
        <LoreSection title={label}>
          {stored ? (
            <p className="font-body text-sm text-text2 leading-relaxed whitespace-pre-wrap">{stored}</p>
          ) : (
            <p className="text-[12px] text-textdim font-body">(empty)</p>
          )}
        </LoreSection>
        {isOpening && openingOptions.length > 0 && (
          <LoreSection title="Opening Options">
            <div className="space-y-1">
              {openingOptions.map((opt, i) => (
                <p key={i} className="font-body text-sm text-text2 leading-relaxed">
                  <span className="font-ui text-[11px] text-golddeep mr-2">{i + 1}.</span>{opt}
                </p>
              ))}
            </div>
          </LoreSection>
        )}
        <span className="block text-[10px] text-textdim font-body">{note}</span>
      </div>
    )
  }

  // Edit mode — uncontrolled save-on-blur textarea, same pattern (and the same
  // debounce cadence) the Scenario tab's inline editor used before the cards.
  return (
    <div className="space-y-3 p-6">
      <LoreSection title={label}>
        <ExpandableTextarea
          label={label}
          className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2 resize-y min-h-[160px]"
          rows={10}
          value={stored}
          placeholder={isOpening ? "The opening narration shown before the player's first turn." : undefined}
          onChange={scheduleCommit}
          onBlur={commit}
        />
      </LoreSection>
      {isOpening && (
        <LoreSection title="Opening Options">
          <div className="space-y-1.5">
            {options.map((opt, i) => (
              <div key={i} className="flex items-center gap-1.5">
                <span className="font-ui text-[10px] text-golddeep w-4 text-right shrink-0">{i + 1}.</span>
                <input
                  className="flex-1 border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2"
                  value={opt}
                  placeholder="I step into the shadow of the trees."
                  onChange={(e) => setOptions(options.map((o, j) => (j === i ? e.target.value : o)))}
                  onBlur={() => commitOptions(options)}
                />
                <button
                  type="button"
                  title="Remove this option"
                  className="font-ui text-[11px] text-textdim border border-line px-2 py-1 hover:text-danger hover:border-danger-border transition-colors"
                  onClick={() => commitOptions(options.filter((_, j) => j !== i))}
                >
                  ✕
                </button>
              </div>
            ))}
            <button
              type="button"
              disabled={options.length >= 6}
              className="font-ui text-[10px] tracking-wider text-textsec border border-line px-2 py-1 hover:text-text hover:border-line2 transition-colors disabled:opacity-30"
              onClick={() => setOptions([...options, ''])}
            >
              + ADD OPTION
            </button>
          </div>
          <span className="mt-1 block text-[10px] text-textdim font-body">
            Scripted choices shown with this opening at turn 0 — the AI generates options only after real turns begin.
          </span>
        </LoreSection>
      )}
      {altIndex >= 0 && (
        <button
          type="button"
          className="font-ui text-[10px] tracking-wider text-textdim border border-line px-2 py-1 hover:text-danger hover:border-danger-border transition-colors"
          onClick={removeOpening}
        >
          ✕ REMOVE THIS OPENING
        </button>
      )}
      <span className="block text-[10px] text-textdim font-body">{note}</span>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex items-center justify-center h-full p-6">
      <div className="text-center space-y-2">
        <p className="font-ui text-[10px] text-textdim tracking-wider">INSPECTOR</p>
        <p className="text-[12px] text-textsec font-body">
          Select a character, item, task, or lore entry to view and edit details.
        </p>
      </div>
    </div>
  )
}
