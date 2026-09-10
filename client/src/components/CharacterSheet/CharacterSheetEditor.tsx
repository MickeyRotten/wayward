import { useCallback, useEffect, useRef } from 'react'
import type { PlayerCharacter, Equipment, CharacterBlock } from '@shared/types/models'
import { usePartyStore } from '../../state/partyStore'
import { useUiStore } from '../../state/uiStore'
import { PortraitBlock } from '../PortraitBlock'
import { VoiceBlock } from '../VoiceBlock'
import { BlockTreeEditor, BlockTreeView } from './BlockTreeEditor'

export function CharacterSheetEditor({ mode }: { mode: 'view' | 'edit' }) {
  const pc = usePartyStore((s) => s.playerCharacter)
  const saveBlocks = usePartyStore((s) => s.savePlayerCharacterBlocks)
  const saveEquipment = usePartyStore((s) => s.savePlayerCharacterEquipment)
  const fetchAll = usePartyStore((s) => s.fetchAll)
  const setEditDirty = useUiStore((s) => s.setEditDirty)
  const selectInto = useUiStore((s) => s.selectInto)
  const selection = useUiStore((s) => s.selection)
  const draft = useRef<PlayerCharacter | null>(null)
  const identityTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    draft.current = pc ? structuredClone(pc) : null
  }, [pc])

  const flushIdentity = useCallback(() => {
    clearTimeout(identityTimer.current)
    if (draft.current) {
      void saveBlocks(draft.current.blocks, draft.current.basicInfo.name)
      setEditDirty(false)
    }
  }, [saveBlocks, setEditDirty])

  const scheduleFlushIdentity = useCallback(() => {
    clearTimeout(identityTimer.current)
    identityTimer.current = setTimeout(flushIdentity, 600)
  }, [flushIdentity])

  if (!pc) return null
  const d = draft.current ?? pc
  const openBlockId = selection?.kind === 'block' && selection.ownerType === 'player' && selection.ownerId === pc.id
    ? selection.blockId
    : undefined

  const updateName = (name: string, immediate?: boolean) => {
    if (!draft.current) return
    draft.current.basicInfo.name = name
    setEditDirty(true)
    immediate ? flushIdentity() : scheduleFlushIdentity()
  }

  const updateBlocks = (blocks: CharacterBlock[], immediate?: boolean) => {
    if (!draft.current) return
    draft.current.blocks = blocks
    setEditDirty(true)
    immediate ? flushIdentity() : scheduleFlushIdentity()
  }

  const updateEquip = (key: keyof Equipment, value: string | null) => {
    if (!draft.current) return
    draft.current.equipment[key] = value
    void saveEquipment(draft.current.equipment)
  }

  if (mode === 'view') {
    return (
      <div className="space-y-6 p-6">
        {/* Portrait — fixed 3:4, image fills; Edit Portrait opens the crop modal. */}
        <PortraitBlock characterId={pc!.id} fullUrl={pc?.portraitFull} cropUrl={pc?.portraitCrop} onUpdated={() => void fetchAll()} />
        <VoiceBlock characterId={pc!.id} hasVoice={pc?.hasVoice} onUpdated={() => void fetchAll()} />

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
      {/* Portrait */}
      <PortraitBlock characterId={pc!.id} fullUrl={pc?.portraitFull} cropUrl={pc?.portraitCrop} onUpdated={() => void fetchAll()} />
      <VoiceBlock characterId={pc!.id} hasVoice={pc?.hasVoice} onUpdated={() => void fetchAll()} />

      {/* Basic Info */}
      <Section title="Basic Info">
        <Field label="Name" value={d.basicInfo.name} onChange={(v) => updateName(v)} onBlur={(v) => updateName(v, true)} />
      </Section>

      {/* Character sheet — a toggleable/orderable block list (see
          CLAUDE.md's Character system rebuild section). Species/Sex/Age,
          Description, Personality, Instinct, Strengths, Other, and the
          Equipment prompt (opened full-screen for the real slot editor) all
          live here as blocks. */}
      <Section title="Character Sheet">
        <BlockTreeEditor
          blocks={d.blocks}
          onChange={updateBlocks}
          onOpenBlock={(blockId) => selectInto({ kind: 'block', ownerType: 'player', ownerId: pc!.id, blockId })}
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
