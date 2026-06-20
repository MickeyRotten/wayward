import { useCallback, useEffect, useRef } from 'react'
import type { PlayerCharacter, AttributeBlock, Equipment, BasicInfo } from '@shared/types/models'
import { usePartyStore } from '../../state/partyStore'
import { PortraitUpload } from '../PortraitUpload'

const ATTR_KEYS: (keyof AttributeBlock)[] = ['STR', 'CON', 'DEX', 'INT', 'WIS', 'CHA']

const EQUIP_SLOTS: { key: keyof Equipment; label: string }[] = [
  { key: 'head', label: 'Head' },
  { key: 'neck', label: 'Neck' },
  { key: 'torsoOver', label: 'Torso (Over)' },
  { key: 'torsoUnder', label: 'Torso (Under)' },
  { key: 'leftHand', label: 'Left Hand' },
  { key: 'rightHand', label: 'Right Hand' },
  { key: 'waist', label: 'Waist' },
  { key: 'legsOver', label: 'Legs (Over)' },
  { key: 'legsUnder', label: 'Legs (Under)' },
  { key: 'feet', label: 'Feet' },
  { key: 'accessory1', label: 'Accessory 1' },
  { key: 'accessory2', label: 'Accessory 2' },
]

export function CharacterSheetEditor() {
  const pc = usePartyStore((s) => s.playerCharacter)
  const save = usePartyStore((s) => s.savePlayerCharacter)
  const draft = useRef<PlayerCharacter | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    draft.current = pc ? structuredClone(pc) : null
  }, [pc])

  const flush = useCallback(() => {
    clearTimeout(timer.current)
    if (draft.current) save(draft.current)
  }, [save])

  const scheduleFlush = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, 600)
  }, [flush])

  if (!pc) return null
  const d = draft.current ?? pc

  const updateBasic = (key: keyof BasicInfo, value: string | number, immediate?: boolean) => {
    if (!draft.current) return
    Object.assign(draft.current.basicInfo, { [key]: value })
    immediate ? flush() : scheduleFlush()
  }

  const updateAttr = (key: keyof AttributeBlock, value: number, immediate?: boolean) => {
    if (!draft.current) return
    draft.current.attributes[key] = value
    immediate ? flush() : scheduleFlush()
  }

  const updateEquip = (key: keyof Equipment, value: string, immediate?: boolean) => {
    if (!draft.current) return
    draft.current.equipment[key] = value
    immediate ? flush() : scheduleFlush()
  }

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div>
        <span className="font-ui text-[9px] text-textdim tracking-wider">PLAYER CHARACTER</span>
        <h2 className="font-disp text-[28px] pt-[3px] leading-none">
          {d.basicInfo.name || 'New Character'}
        </h2>
      </div>

      {/* Portrait */}
      <PortraitUpload
        portrait={d.basicInfo.portrait}
        onUploaded={(filename) => updateBasic('portrait', filename)}
      />

      {/* Basic Info */}
      <Section title="Basic Info">
        <div className="space-y-3">
          <Field label="Name" value={d.basicInfo.name} onChange={(v) => updateBasic('name', v)} onBlur={(v) => updateBasic('name', v, true)} />
          <div className="grid grid-cols-2 gap-3">
            <Field label="Gender" value={d.basicInfo.gender} onChange={(v) => updateBasic('gender', v)} onBlur={(v) => updateBasic('gender', v, true)} />
            <Field label="Species" value={d.basicInfo.species} onChange={(v) => updateBasic('species', v)} onBlur={(v) => updateBasic('species', v, true)} />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <NumField label="Age" value={d.basicInfo.age} onChange={(v) => updateBasic('age', v)} onBlur={(v) => updateBasic('age', v, true)} />
            <NumField label="Height (cm)" value={d.basicInfo.heightCm} onChange={(v) => updateBasic('heightCm', v)} onBlur={(v) => updateBasic('heightCm', v, true)} />
            <NumField label="Weight (kg)" value={d.basicInfo.weightKg} onChange={(v) => updateBasic('weightKg', v)} onBlur={(v) => updateBasic('weightKg', v, true)} />
          </div>
          <TextArea label="Description" value={d.basicInfo.description} onChange={(v) => updateBasic('description', v)} onBlur={(v) => updateBasic('description', v, true)} />
        </div>
      </Section>

      {/* Attributes */}
      <Section title="Attributes">
        <div className="grid grid-cols-3 gap-3">
          {ATTR_KEYS.map((k) => (
            <NumField key={k} label={k} value={d.attributes[k]} onChange={(v) => updateAttr(k, v)} onBlur={(v) => updateAttr(k, v, true)} />
          ))}
        </div>
      </Section>

      {/* Equipment */}
      <Section title="Equipment">
        <div className="space-y-3">
          {EQUIP_SLOTS.map(({ key, label }) => (
            <Field
              key={key}
              label={label}
              value={d.equipment[key]}
              onChange={(v) => updateEquip(key, v)}
              onBlur={(v) => updateEquip(key, v, true)}
              placeholder="Empty"
            />
          ))}
        </div>
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
        className="w-full border-[1.5px] border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
        defaultValue={value}
        placeholder={placeholder}
        onBlur={(e) => (onBlur ?? onChange)(e.target.value)}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

function NumField({ label, value, onChange, onBlur }: {
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

function TextArea({ label, value, onChange, onBlur }: {
  label: string; value: string; onChange: (v: string) => void; onBlur?: (v: string) => void
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-textdim font-body block mb-0.5">{label}</span>
      <textarea
        className="w-full border-[1.5px] border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors resize-y min-h-[72px]"
        rows={3}
        defaultValue={value}
        onBlur={(e) => (onBlur ?? onChange)(e.target.value)}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}
