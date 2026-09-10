import { useCallback, useEffect, useRef } from 'react'
import type { PlayerCharacter, PartyMember, CharacterBlock } from '@shared/types/models'
import { usePartyStore } from '../../state/partyStore'
import { useUiStore } from '../../state/uiStore'
import { LoreSection, LoreField } from '../common/LoreFormFields'
import { updateBlockInTree } from './BlockTreeEditor'

// A character-sheet "prompt" block, opened in place from the block list
// (BlockTreeEditor) via selectInto — the ✕ in the corner returns to the
// owning sheet (CharacterSheetPanel also lets a tab click back out).

export function BlockContentInspector({ owner, ownerType, block, mode, onClose }: {
  owner: PlayerCharacter | PartyMember
  ownerType: 'player' | 'member'
  block: CharacterBlock
  mode: 'view' | 'edit'
  onClose: () => void
}) {
  const saveBlocksPC = usePartyStore((s) => s.savePlayerCharacterBlocks)
  const saveBlocksMember = usePartyStore((s) => s.savePartyMemberBlocks)
  const setEditDirty = useUiStore((s) => s.setEditDirty)

  const draft = useRef<Pick<CharacterBlock, 'name' | 'content' | 'enabled'>>(
    { name: block.name, content: block.content ?? '', enabled: block.enabled }
  )
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    draft.current = { name: block.name, content: block.content ?? '', enabled: block.enabled }
  }, [block])

  const flush = useCallback(() => {
    clearTimeout(timer.current)
    // Only text blocks have meaningful content — don't write a stray `content`
    // field onto folder/equipment/image blocks that never had one.
    const patch: Partial<CharacterBlock> = { name: draft.current.name, enabled: draft.current.enabled }
    if (block.type === 'text') patch.content = draft.current.content
    const nextBlocks = updateBlockInTree(owner.blocks, block.id, patch)
    if (ownerType === 'player') void saveBlocksPC(nextBlocks, owner.basicInfo.name)
    else void saveBlocksMember(owner.id, nextBlocks, owner.basicInfo.name)
    setEditDirty(false)
  }, [owner, ownerType, block.id, block.type, saveBlocksPC, saveBlocksMember, setEditDirty])

  const scheduleFlush = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, 600)
  }, [flush])

  const update = (patch: Partial<Pick<CharacterBlock, 'name' | 'content' | 'enabled'>>, immediate?: boolean) => {
    Object.assign(draft.current, patch)
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  const d = draft.current

  const nonTextNote = block.type === 'folder'
    ? 'A folder groups other blocks — expand it in the Character Sheet list to manage its contents.'
    : `${block.file || 'Reference image'} — uploading new image blocks isn't supported yet.`

  if (mode === 'view') {
    return (
      <div className="space-y-6 p-6">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <span className={`font-ui text-[9px] tracking-wider uppercase px-2 py-0.5 border border-line ${
            block.enabled ? 'text-[#5a9e6f]' : 'text-textdim'
          }`}>
            {block.enabled ? 'ENABLED' : 'DISABLED'}
          </span>
          <button
            type="button"
            aria-label="Close"
            className="font-ui text-[13px] text-textdim hover:text-text transition-colors shrink-0"
            onClick={onClose}
          >
            ✕
          </button>
        </div>
        {block.type === 'text' ? (
          <LoreSection title="Content">
            {(block.content ?? '').trim() ? (
              <p className="font-body text-sm text-text2 leading-relaxed whitespace-pre-wrap">{block.content}</p>
            ) : (
              <p className="text-[12px] text-textdim font-body">(empty)</p>
            )}
          </LoreSection>
        ) : (
          <p className="text-[12px] text-textdim font-body italic">{nonTextNote}</p>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-end">
        <button
          type="button"
          aria-label="Close"
          className="font-ui text-[13px] text-textdim hover:text-text transition-colors shrink-0"
          onClick={onClose}
        >
          ✕
        </button>
      </div>

      <LoreSection title="Basic Info">
        <div className="space-y-3">
          <LoreField
            label="Name"
            value={d.name}
            onChange={(v) => update({ name: v })}
            onBlur={(v) => update({ name: v }, true)}
          />
          {block.locked ? (
            <div className="flex items-center gap-2">
              <span className="font-ui text-[9px] text-gold2" title="Locked">&#128274;</span>
              <span className="font-body text-sm text-textdim">Mandatory — always enabled, can't be removed or moved</span>
            </div>
          ) : (
            <label className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                defaultChecked={d.enabled}
                onChange={(e) => update({ enabled: e.target.checked }, true)}
                className="accent-gold"
              />
              <span className="font-body text-sm text-text">Enabled — included in the prompt</span>
            </label>
          )}
        </div>
      </LoreSection>

      {block.type === 'text' ? (
        <LoreSection title="Content">
          <textarea
            className="w-full border border-line bg-bg0 px-3 py-2.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors resize-y min-h-[50vh]"
            defaultValue={d.content}
            placeholder="Content the Narrator reads for this block…"
            onChange={(e) => update({ content: e.target.value })}
            onBlur={(e) => update({ content: e.target.value }, true)}
          />
        </LoreSection>
      ) : (
        <p className="text-[12px] text-textdim font-body italic">{nonTextNote}</p>
      )}
    </div>
  )
}
