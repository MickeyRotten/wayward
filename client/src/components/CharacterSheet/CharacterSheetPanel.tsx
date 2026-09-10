import { useCallback, useEffect, useRef, useState } from 'react'
import type { PlayerCharacter, PartyMember, Equipment, CharacterBlock } from '@shared/types/models'
import { useUiStore, type SelectionKind } from '../../state/uiStore'
import { useItemsStore } from '../../state/itemsStore'
import { PortraitBlock } from '../PortraitBlock'
import { ConfirmDialog } from '../ConfirmDialog'
import { BlockTreeEditor, BlockTreeView, findBlock } from './BlockTreeEditor'
import { EquipmentGrid } from './EquipmentGrid'
import { ItemInspector } from './ItemInspector'
import { BlockContentInspector } from './BlockContentInspector'

type Owner = PlayerCharacter | PartyMember
type Tab = 'sheet' | 'equipment' | 'editor'

const TAB_HEADINGS: Record<Tab, string> = {
  sheet: 'Character Sheet',
  equipment: 'Equipment',
  editor: 'Editor',
}

// Fully navigating away from a character (to another character, or to the
// Items/Lore tab) and back still unmounts/remounts this panel, so plain
// useState would forget which tab was open. Module-level, keyed per owner, so
// it survives that remount without needing to lift tab state into uiStore.
// (Drilling into an item/block from THIS panel no longer unmounts it at all —
// see the drilledItem/drilledBlock handling below — so this cache only needs
// to cover the cross-character/cross-tab-away case now.)
const lastTabByOwner: Record<string, Tab> = {}

/**
 * The shared Sheet / Equipment / Editor panel for both the PC and a party
 * member — a compact header (portrait + inline-editable name + i/Export/
 * Delete) over three tabs. This is the character's ONLY header — the
 * Inspector's own generic entity header is suppressed for PC/member
 * selections (PartyInspector.tsx) so the name isn't shown twice. Owner-
 * specific save/remove plumbing is passed in by the thin wrappers
 * (CharacterSheetEditor for the PC, PartyMemberEditor for a member) so this
 * component itself doesn't need to know which store actions to call.
 */
export function CharacterSheetPanel({
  owner,
  ownerType,
  onSaveBlocks,
  onSaveEquipment,
  onRemove,
  onPortraitUpdated,
}: {
  owner: Owner
  ownerType: 'player' | 'member'
  onSaveBlocks: (blocks: CharacterBlock[], name: string) => void
  onSaveEquipment: (equipment: Equipment) => void
  /** Party members only — presence of this prop is what shows Delete. */
  onRemove?: () => void
  onPortraitUpdated: () => void
}) {
  const selectInto = useUiStore((s) => s.selectInto)
  const selection = useUiStore((s) => s.selection)
  const back = useUiStore((s) => s.back)
  const select = useUiStore((s) => s.select)
  const setEditDirty = useUiStore((s) => s.setEditDirty)
  const catalog = useItemsStore((s) => s.catalog)
  const inventory = useItemsStore((s) => s.inventory)

  const [tab, setTabState] = useState<Tab>(() => lastTabByOwner[owner.id] ?? 'editor')
  const [editingName, setEditingName] = useState(false)
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false)

  const setTab = (next: Tab) => {
    lastTabByOwner[owner.id] = next
    setTabState(next)
  }

  const draft = useRef<Owner>(structuredClone(owner))
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const prevOwnerId = useRef(owner.id)

  useEffect(() => {
    draft.current = structuredClone(owner)
  }, [owner])

  // A genuinely different character was selected — land back on Editor and
  // drop any in-progress rename. Guarded so this doesn't also fire on the
  // very first mount, which would immediately stomp the tab just restored
  // from lastTabByOwner above (e.g. after Back from a drilled-into item).
  useEffect(() => {
    if (prevOwnerId.current !== owner.id) {
      setTab('editor')
      setEditingName(false)
      prevOwnerId.current = owner.id
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [owner.id])

  const flush = useCallback(() => {
    clearTimeout(timer.current)
    onSaveBlocks(draft.current.blocks, draft.current.basicInfo.name)
    setEditDirty(false)
  }, [onSaveBlocks, setEditDirty])

  const scheduleFlush = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, 600)
  }, [flush])

  const d = draft.current
  const openBlockId = selection?.kind === 'block' && selection.ownerType === ownerType && selection.ownerId === owner.id
    ? selection.blockId
    : undefined

  // Is this selection reference (the breadcrumb `back`, or nothing) pointing
  // at THIS owner? Used to tell an item drilled from this sheet apart from a
  // standalone item selection elsewhere (Items/Lore panel), which PartyInspector
  // renders on its own rather than inside this panel.
  const isMineRef = (ref: SelectionKind) =>
    !!ref && (
      (ref.kind === 'player' && ownerType === 'player') ||
      (ref.kind === 'member' && ownerType === 'member' && ref.id === owner.id)
    )

  const drilledItem = selection?.kind === 'item' && isMineRef(back)
    ? (catalog.find((i) => i.id === selection.id) ?? inventory.find((s) => s.itemId === selection.id)?.item)
    : undefined
  const drilledBlock = openBlockId ? findBlock(d.blocks, openBlockId) : undefined

  const backToOwner = () => select(ownerType === 'player' ? { kind: 'player' } : { kind: 'member', id: owner.id })

  // Clicking a tab always shows that tab's normal content — including
  // backing out of a currently-open item/block drill, so the tab row doubles
  // as the "back" control while one is open.
  const gotoTab = (next: Tab) => {
    setTab(next)
    if (drilledItem || drilledBlock) backToOwner()
  }

  const updateName = (name: string, immediate?: boolean) => {
    draft.current.basicInfo.name = name
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  const updateBlocks = (blocks: CharacterBlock[], immediate?: boolean) => {
    draft.current.blocks = blocks
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  const updateEquip = (key: keyof Equipment, value: string | null) => {
    draft.current.equipment[key] = value
    onSaveEquipment(draft.current.equipment)
  }

  return (
    <div className="flex flex-col h-full">
      <div className="shrink-0 p-6 pb-4 border-b border-line space-y-3">
        <div className="flex items-stretch gap-4">
          <PortraitBlock compact characterId={owner.id} fullUrl={owner.portraitFull} cropUrl={owner.portraitCrop} onUpdated={onPortraitUpdated} />
          <div className="min-w-0 flex-1 flex flex-col justify-center gap-2">
            {editingName ? (
              <input
                autoFocus
                defaultValue={d.basicInfo.name}
                className="w-full font-disp text-[22px] leading-none bg-transparent border-b border-line2 outline-none text-text pb-0.5"
                onFocus={(e) => e.currentTarget.select()}
                onBlur={(e) => { updateName(e.target.value, true); setEditingName(false) }}
                onKeyDown={(e) => {
                  // stopPropagation: same race as the block rename input —
                  // don't let Escape also trigger App.tsx's global
                  // "clear the Inspector selection" shortcut.
                  if (e.key === 'Enter') { e.stopPropagation(); e.currentTarget.blur() }
                  if (e.key === 'Escape') { e.stopPropagation(); setEditingName(false) }
                }}
              />
            ) : (
              <h2
                className="font-disp text-[22px] pt-0.5 leading-none text-text truncate cursor-text"
                onClick={() => setEditingName(true)}
                title="Click to rename"
              >
                {d.basicInfo.name || 'Unnamed'}
              </h2>
            )}

            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled
                className="font-ui text-[10px] text-textdim/40 border border-line/40 w-6 h-6 flex items-center justify-center cursor-not-allowed"
                title="Not yet available"
              >
                i
              </button>
              <button
                type="button"
                disabled
                className="font-ui text-[9px] tracking-wider text-textdim/40 border border-line/40 px-2.5 py-1 cursor-not-allowed"
                title="Not yet available"
              >
                EXPORT
              </button>
              {onRemove && (
                <button
                  type="button"
                  className="font-ui text-[9px] tracking-wider text-textdim hover:text-danger border border-line px-2.5 py-1 hover:border-danger-border transition-colors"
                  onClick={() => setShowRemoveConfirm(true)}
                >
                  DELETE
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="flex gap-1.5 pt-1">
          <TabButton label="Sheet" active={tab === 'sheet'} onClick={() => gotoTab('sheet')} />
          <TabButton label="Equipment" active={tab === 'equipment'} onClick={() => gotoTab('equipment')} />
          <TabButton label="Editor" active={tab === 'editor'} onClick={() => gotoTab('editor')} />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {drilledItem ? (
          <ItemInspector
            key={(selection?.kind === 'item' ? selection.instanceId : '') || drilledItem.id}
            item={drilledItem}
            instanceId={selection?.kind === 'item' ? selection.instanceId : undefined}
            lockTypeSlot={selection?.kind === 'item' ? selection.lockTypeSlot : undefined}
            openInEdit={selection?.kind === 'item' ? selection.openInEdit : undefined}
            onClose={backToOwner}
          />
        ) : drilledBlock ? (
          <BlockContentInspector
            key={drilledBlock.id}
            owner={owner}
            ownerType={ownerType}
            block={drilledBlock}
            mode="edit"
            onClose={backToOwner}
          />
        ) : (
          <div className="p-6">
            <h3 className="font-ui text-[10px] tracking-wider text-textsec uppercase mb-3">{TAB_HEADINGS[tab]}</h3>
            {tab === 'sheet' && <BlockTreeView blocks={d.blocks} />}
            {tab === 'equipment' && <EquipmentGrid equipment={d.equipment} onChange={updateEquip} characterId={owner.id} />}
            {tab === 'editor' && (
              <BlockTreeEditor
                blocks={d.blocks}
                onChange={updateBlocks}
                onOpenBlock={(blockId) => selectInto({ kind: 'block', ownerType, ownerId: owner.id, blockId })}
                openBlockId={openBlockId}
              />
            )}
          </div>
        )}
      </div>

      {showRemoveConfirm && onRemove && (
        <ConfirmDialog
          message={`Remove ${d.basicInfo.name || 'this member'} from the party? This cannot be undone.`}
          confirmLabel="REMOVE"
          onConfirm={() => { setShowRemoveConfirm(false); onRemove() }}
          onCancel={() => setShowRemoveConfirm(false)}
        />
      )}
    </div>
  )
}

function TabButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className={`font-ui text-[10px] tracking-wider uppercase px-3 py-1.5 border transition-colors ${
        active ? 'border-line2 bg-bg3 text-text' : 'border-line text-textsec hover:border-line2 hover:text-text'
      }`}
      onClick={onClick}
    >
      {label}
    </button>
  )
}
