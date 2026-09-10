import { useCallback, useEffect, useRef, useState } from 'react'
import type { PartyMember, Equipment, CharacterBlock } from '@shared/types/models'
import { usePartyStore } from '../../state/partyStore'
import { useUiStore } from '../../state/uiStore'
import { PortraitBlock } from '../PortraitBlock'
import { VoiceBlock } from '../VoiceBlock'
import { ConfirmDialog } from '../ConfirmDialog'
import { BlockTreeEditor, BlockTreeView } from '../CharacterSheet/BlockTreeEditor'

export function PartyMemberEditor({ member, mode }: { member: PartyMember; mode: 'view' | 'edit' }) {
  const saveBlocks = usePartyStore((s) => s.savePartyMemberBlocks)
  const saveEquipment = usePartyStore((s) => s.savePartyMemberEquipment)
  const remove = usePartyStore((s) => s.removePartyMember)
  const fetchAll = usePartyStore((s) => s.fetchAll)
  const select = useUiStore((s) => s.select)
  const selectInto = useUiStore((s) => s.selectInto)
  const selection = useUiStore((s) => s.selection)
  const setEditDirty = useUiStore((s) => s.setEditDirty)
  const draft = useRef<PartyMember>(structuredClone(member))
  const identityTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    draft.current = structuredClone(member)
  }, [member])

  const flushIdentity = useCallback(() => {
    clearTimeout(identityTimer.current)
    void saveBlocks(draft.current.id, draft.current.blocks, draft.current.basicInfo.name)
    setEditDirty(false)
  }, [saveBlocks, setEditDirty])

  const scheduleFlushIdentity = useCallback(() => {
    clearTimeout(identityTimer.current)
    identityTimer.current = setTimeout(flushIdentity, 600)
  }, [flushIdentity])

  const d = draft.current
  const openBlockId = selection?.kind === 'block' && selection.ownerType === 'member' && selection.ownerId === member.id
    ? selection.blockId
    : undefined

  const updateName = (name: string, immediate?: boolean) => {
    draft.current.basicInfo.name = name
    setEditDirty(true)
    immediate ? flushIdentity() : scheduleFlushIdentity()
  }

  const updateBlocks = (blocks: CharacterBlock[], immediate?: boolean) => {
    draft.current.blocks = blocks
    setEditDirty(true)
    immediate ? flushIdentity() : scheduleFlushIdentity()
  }

  const updateEquip = (key: keyof Equipment, value: string | null) => {
    draft.current.equipment[key] = value
    void saveEquipment(draft.current.id, draft.current.equipment)
  }

  if (mode === 'view') {
    return (
      <div className="space-y-6 p-6">
        {/* Portrait — fixed 3:4, image fills; Edit Portrait opens the crop modal. */}
        <PortraitBlock characterId={member.id} fullUrl={member.portraitFull} cropUrl={member.portraitCrop} onUpdated={() => void fetchAll()} />
        <VoiceBlock characterId={member.id} hasVoice={member.hasVoice} onUpdated={() => void fetchAll()} />

        {/* Basic Info — Equipment (still editable in Play mode; it's a play
            action, not world-editing) renders inline where its block sits. */}
        <Section title="Basic Info">
          <BlockTreeView blocks={d.blocks} equipment={d.equipment} onEquipChange={updateEquip} />
        </Section>
      </div>
    )
  }

  return (
    <div className="space-y-6 p-6">
      {/* Header with Remove */}
      <div className="flex items-start justify-end">
        <RemoveButton onRemove={async () => { await remove(member.id); select(null) }} name={d.basicInfo.name || 'this member'} />
      </div>

      {/* Portrait */}
      <PortraitBlock characterId={member.id} fullUrl={member.portraitFull} cropUrl={member.portraitCrop} onUpdated={() => void fetchAll()} />
      <VoiceBlock characterId={member.id} hasVoice={member.hasVoice} onUpdated={() => void fetchAll()} />

      {/* Basic Info */}
      <Section title="Basic Info">
        <Field label="Name" value={d.basicInfo.name} onChange={(v) => updateName(v)} onBlur={(v) => updateName(v, true)} />
      </Section>

      {/* Character sheet — a toggleable/orderable block list (see CLAUDE.md's
          Character system rebuild section). Species/Sex/Age, Description,
          Personality, Instinct, Strengths (replaces the old separate Field
          Skill section — it's just a text block here now), Other, and the
          Equipment prompt (opened full-screen for the real slot editor) all
          live here as blocks. */}
      <Section title="Character Sheet">
        <BlockTreeEditor
          blocks={d.blocks}
          onChange={updateBlocks}
          onOpenBlock={(blockId) => selectInto({ kind: 'block', ownerType: 'member', ownerId: member.id, blockId })}
          openBlockId={openBlockId}
        />
      </Section>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="font-ui text-[10px] tracking-wider text-textsec uppercase mb-3">{title}</h3>
      {children}
    </section>
  )
}

function Field({ label, value, onChange, onBlur, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; onBlur?: (v: string) => void; placeholder?: string
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-textdim font-body block mb-0.5">{label}</span>
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

function RemoveButton({ onRemove, name }: { onRemove: () => void; name: string }) {
  const [showConfirm, setShowConfirm] = useState(false)
  return (
    <>
      <button
        type="button"
        className="font-ui text-[9px] text-textdim hover:text-text border border-line px-2 py-1 hover:border-line2 transition-colors shrink-0 mt-1"
        onClick={() => setShowConfirm(true)}
      >
        REMOVE
      </button>
      {showConfirm && (
        <ConfirmDialog
          message={`Remove ${name} from the party? This cannot be undone.`}
          confirmLabel="REMOVE"
          onConfirm={onRemove}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </>
  )
}
