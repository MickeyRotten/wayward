import { useCallback, useEffect, useRef, useState } from 'react'
import type { PlayerCharacter, PartyMember, Equipment, CharacterBlock } from '@shared/types/models'
import { useUiStore } from '../../state/uiStore'
import { PortraitBlock } from '../PortraitBlock'
import { ConfirmDialog } from '../ConfirmDialog'
import { BlockTreeEditor, BlockTreeView } from './BlockTreeEditor'
import { EquipmentGrid } from './EquipmentGrid'

type Owner = PlayerCharacter | PartyMember
type Tab = 'sheet' | 'equipment' | 'editor'

const TAB_HEADINGS: Record<Tab, string> = {
  sheet: 'Character Sheet',
  equipment: 'Equipment',
  editor: 'Editor',
}

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
  const setEditDirty = useUiStore((s) => s.setEditDirty)

  const [tab, setTab] = useState<Tab>('editor')
  const [editingName, setEditingName] = useState(false)
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false)

  const draft = useRef<Owner>(structuredClone(owner))
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    draft.current = structuredClone(owner)
  }, [owner])

  // A genuinely different character was selected — land back on Editor and
  // drop any in-progress rename, rather than carrying tab state across.
  useEffect(() => {
    setTab('editor')
    setEditingName(false)
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
    <div className="flex flex-col">
      <div className="p-6 pb-4 border-b border-line space-y-3">
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
          <TabButton label="Sheet" active={tab === 'sheet'} onClick={() => setTab('sheet')} />
          <TabButton label="Equipment" active={tab === 'equipment'} onClick={() => setTab('equipment')} />
          <TabButton label="Editor" active={tab === 'editor'} onClick={() => setTab('editor')} />
        </div>
      </div>

      <div className="p-6">
        <h3 className="font-ui text-[10px] tracking-wider text-textsec uppercase mb-3">{TAB_HEADINGS[tab]}</h3>
        {tab === 'sheet' && <BlockTreeView blocks={d.blocks} />}
        {tab === 'equipment' && <EquipmentGrid equipment={d.equipment} onChange={updateEquip} />}
        {tab === 'editor' && (
          <BlockTreeEditor
            blocks={d.blocks}
            onChange={updateBlocks}
            onOpenBlock={(blockId) => selectInto({ kind: 'block', ownerType, ownerId: owner.id, blockId })}
            openBlockId={openBlockId}
          />
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
