import { useCallback, useEffect, useRef } from 'react'
import type { PartyMember, AttributeBlock, Equipment, BasicInfo, FieldSkill } from '@shared/types/models'
import { usePartyStore } from '../../state/partyStore'
import { useUiStore } from '../../state/uiStore'
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

const FIELD_SKILL_PLACEHOLDER = `Punches as hard as a wrecking ball — able to break stone and put a big dent in metal with her bare fist. Still just a punch — things too big, too tough, or not physical at all are out of her reach.`

export function PartyMemberEditor({ member }: { member: PartyMember }) {
  const save = usePartyStore((s) => s.savePartyMember)
  const remove = usePartyStore((s) => s.removePartyMember)
  const select = useUiStore((s) => s.select)
  const draft = useRef<PartyMember>(structuredClone(member))
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    draft.current = structuredClone(member)
  }, [member])

  const flush = useCallback(() => {
    clearTimeout(timer.current)
    save(draft.current)
  }, [save])

  const scheduleFlush = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, 600)
  }, [flush])

  const d = draft.current

  const updateBasic = (key: keyof BasicInfo, value: string | number, immediate?: boolean) => {
    Object.assign(draft.current.basicInfo, { [key]: value })
    immediate ? flush() : scheduleFlush()
  }

  const updateAttr = (key: keyof AttributeBlock, value: number, immediate?: boolean) => {
    draft.current.attributes[key] = value
    immediate ? flush() : scheduleFlush()
  }

  const updateEquip = (key: keyof Equipment, value: string, immediate?: boolean) => {
    draft.current.equipment[key] = value
    immediate ? flush() : scheduleFlush()
  }

  const updateSkill = (key: keyof FieldSkill, value: string, immediate?: boolean) => {
    draft.current.fieldSkill[key] = value
    immediate ? flush() : scheduleFlush()
  }

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <span className="font-ui text-[9px] text-text-dim tracking-wider">PARTY MEMBER</span>
          <h2 className="font-h text-[28px] pt-[3px] leading-none">
            {d.basicInfo.name || 'New Member'}
          </h2>
        </div>
        <button
          type="button"
          className="font-ui text-[9px] text-text-dim hover:text-text border-[1.5px] border-mid px-2 py-1 hover:border-border transition-colors flex-shrink-0 mt-1"
          onClick={async () => {
            await remove(member.id)
            select(null)
          }}
        >
          REMOVE
        </button>
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
          <Field label="Personality" value={d.basicInfo.personality ?? ''} onChange={(v) => updateBasic('personality', v)} onBlur={(v) => updateBasic('personality', v, true)} placeholder="e.g. Warm, protective, quietly stubborn" />
          <Field label="Likes" value={d.basicInfo.likes ?? ''} onChange={(v) => updateBasic('likes', v)} onBlur={(v) => updateBasic('likes', v, true)} placeholder="e.g. Cooking, stargazing, friendly sparring" />
          <Field label="Dislikes" value={d.basicInfo.dislikes ?? ''} onChange={(v) => updateBasic('dislikes', v)} onBlur={(v) => updateBasic('dislikes', v, true)} placeholder="e.g. Bullies, being idle, cold weather" />
        </div>
      </Section>

      {/* Field Skill */}
      <Section title="Field Skill">
        <div className="space-y-3">
          <Field label="Skill Name" value={d.fieldSkill.name} onChange={(v) => updateSkill('name', v)} onBlur={(v) => updateSkill('name', v, true)} />
          <TextArea
            label="Skill Description"
            value={d.fieldSkill.description}
            onChange={(v) => updateSkill('description', v)}
            onBlur={(v) => updateSkill('description', v, true)}
            placeholder={FIELD_SKILL_PLACEHOLDER}
          />
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
      <h3 className="font-ui text-[10px] tracking-wider text-text-sec uppercase mb-3">{title}</h3>
      {children}
    </section>
  )
}

function Field({ label, value, onChange, onBlur, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; onBlur?: (v: string) => void; placeholder?: string
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-text-dim font-b block mb-0.5">{label}</span>
      <input
        className="w-full border-[1.5px] border-mid bg-white px-2.5 py-1.5 text-sm font-b text-text outline-none focus:border-border focus:bg-off2 transition-colors"
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
      <span className="text-[11px] text-text-dim font-b block mb-0.5">{label}</span>
      <input
        type="number"
        className="w-full border-[1.5px] border-mid bg-white px-2.5 py-1.5 text-sm font-b text-text outline-none focus:border-border focus:bg-off2 transition-colors"
        defaultValue={value}
        onBlur={(e) => (onBlur ?? onChange)(Number(e.target.value) || 0)}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
      />
    </label>
  )
}

function TextArea({ label, value, onChange, onBlur, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; onBlur?: (v: string) => void; placeholder?: string
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-text-dim font-b block mb-0.5">{label}</span>
      <textarea
        className="w-full border-[1.5px] border-mid bg-white px-2.5 py-1.5 text-sm font-b text-text outline-none focus:border-border focus:bg-off2 transition-colors resize-y min-h-[72px]"
        rows={3}
        defaultValue={value}
        placeholder={placeholder}
        onBlur={(e) => (onBlur ?? onChange)(e.target.value)}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}
