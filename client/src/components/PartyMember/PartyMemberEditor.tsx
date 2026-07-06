import { useCallback, useEffect, useRef, useState } from 'react'
import type { PartyMember, Equipment, BasicInfo, FieldSkill, Rarity } from '@shared/types/models'
import { usePartyStore } from '../../state/partyStore'
import { useItemsStore } from '../../state/itemsStore'
import { useUiStore } from '../../state/uiStore'
import { PortraitBlock } from '../PortraitBlock'
import { VoiceBlock } from '../VoiceBlock'
import { ConfirmDialog } from '../ConfirmDialog'
import { ExpandableTextarea } from '../common/ExpandableTextarea'
import { itemFitsSlot } from '../../lib/equipSlots'
import { ItemCard } from '../ItemCard'

const RARITY_COLORS: Record<Rarity, string> = {
  c: 'bg-rarity-c',
  u: 'bg-rarity-u',
  r: 'bg-rarity-r',
  e: 'bg-rarity-e',
  l: 'bg-rarity-l',
}

const RARITY_LABELS: Record<Rarity, string> = {
  c: 'Common',
  u: 'Uncommon',
  r: 'Rare',
  e: 'Epic',
  l: 'Legendary',
}

const EQUIP_SLOTS: { key: keyof Equipment; label: string }[] = [
  { key: 'head', label: 'Head' },
  { key: 'neck', label: 'Neck' },
  { key: 'torsoOver', label: 'Torso · Over' },
  { key: 'torsoUnder', label: 'Torso · Under' },
  { key: 'leftHand', label: 'Left Hand' },
  { key: 'rightHand', label: 'Right Hand' },
  { key: 'waist', label: 'Waist' },
  { key: 'legsOver', label: 'Legs · Over' },
  { key: 'legsUnder', label: 'Legs · Under' },
  { key: 'feet', label: 'Feet' },
  { key: 'accessory1', label: 'Accessory I' },
  { key: 'accessory2', label: 'Accessory II' },
]

const FIELD_SKILL_PLACEHOLDER = `Punches as hard as a wrecking ball — able to break stone and put a big dent in metal with her bare fist. Still just a punch — things too big, too tough, or not physical at all are out of her reach.`

export function PartyMemberEditor({ member, mode }: { member: PartyMember; mode: 'view' | 'edit' }) {
  const save = usePartyStore((s) => s.savePartyMember)
  const remove = usePartyStore((s) => s.removePartyMember)
  const fetchAll = usePartyStore((s) => s.fetchAll)
  const select = useUiStore((s) => s.select)
  const setEditDirty = useUiStore((s) => s.setEditDirty)
  const draft = useRef<PartyMember>(structuredClone(member))
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    draft.current = structuredClone(member)
  }, [member])

  const flush = useCallback(() => {
    clearTimeout(timer.current)
    save(draft.current)
    setEditDirty(false)
  }, [save, setEditDirty])

  const scheduleFlush = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, 600)
  }, [flush])

  const d = draft.current

  const updateBasic = (key: keyof BasicInfo, value: string | number, immediate?: boolean) => {
    Object.assign(draft.current.basicInfo, { [key]: value })
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  const updateEquip = (key: keyof Equipment, value: string | null, immediate?: boolean) => {
    draft.current.equipment[key] = value
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  const updateSkill = (key: keyof FieldSkill, value: string, immediate?: boolean) => {
    draft.current.fieldSkill[key] = value
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  if (mode === 'view') {
    return (
      <div className="space-y-6 p-6">
        {/* Portrait — fixed 3:4, image fills; Edit Portrait opens the crop modal. */}
        <PortraitBlock characterId={member.id} fullUrl={member.portraitFull} cropUrl={member.portraitCrop} onUpdated={() => void fetchAll()} />
        <VoiceBlock characterId={member.id} hasVoice={member.hasVoice} onUpdated={() => void fetchAll()} />

        {/* Basic Info */}
        <Section title="Basic Info">
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              <ViewField label="Gender" value={d.basicInfo.gender} />
              <ViewField label="Species" value={d.basicInfo.species} />
              <ViewField label="Age" value={d.basicInfo.age ? String(d.basicInfo.age) : ''} />
              <ViewField label="Height" value={d.basicInfo.heightCm ? `${d.basicInfo.heightCm} cm` : ''} />
              <ViewField label="Weight" value={d.basicInfo.weightKg ? `${d.basicInfo.weightKg} kg` : ''} />
            </div>
            {d.basicInfo.personality && (
              <ViewField label="Personality" value={d.basicInfo.personality} />
            )}
            {d.basicInfo.likes && (
              <ViewField label="Likes" value={d.basicInfo.likes} />
            )}
            {d.basicInfo.dislikes && (
              <ViewField label="Dislikes" value={d.basicInfo.dislikes} />
            )}
            {d.basicInfo.description && (
              <p className="font-body text-sm text-text2 leading-relaxed mt-2">{d.basicInfo.description}</p>
            )}
          </div>
        </Section>

        {/* Field Skill */}
        {(d.fieldSkill.name || d.fieldSkill.description) && (
          <Section title="Field Skill">
            {d.fieldSkill.name && (
              <p className="font-disp text-[15px] text-gold pt-0.5 mb-1">{d.fieldSkill.name}</p>
            )}
            {d.fieldSkill.description && (
              <p className="font-body text-sm text-text2 leading-relaxed">{d.fieldSkill.description}</p>
            )}
          </Section>
        )}

        {/* Equipment — editable in View/Play mode too (gear management is a
            play action, not world-editing). */}
        <Section title="Equipment">
          <div className="space-y-3">
            {EQUIP_SLOTS.map(({ key, label }) => (
              <EquipSlotField
                key={key}
                slotKey={key}
                label={label}
                value={d.equipment[key]}
                onChange={(id) => updateEquip(key, id, true)}
              />
            ))}
          </div>
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

      {/* Equipment */}
      <Section title="Equipment">
        <div className="space-y-3">
          {EQUIP_SLOTS.map(({ key, label }) => (
            <EquipSlotField
              key={key}
              slotKey={key}
              label={label}
              value={d.equipment[key]}
              onChange={(id) => updateEquip(key, id, true)}
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

function ViewField({ label, value, emptyText }: { label: string; value: string; emptyText?: string }) {
  return (
    <div className="py-0.5">
      <span className="text-[11px] text-textdim font-body">{label}</span>
      <span className="text-[11px] text-textdim font-body mx-1">&middot;</span>
      <span className={`text-sm font-body ${value ? 'text-text' : 'text-textdim italic'}`}>
        {value || emptyText || '—'}
      </span>
    </div>
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

function NumField({ label, value, onChange, onBlur }: {
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

function TextArea({ label, value, onChange, onBlur, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; onBlur?: (v: string) => void; placeholder?: string
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-textdim font-body block mb-0.5">{label}</span>
      <ExpandableTextarea
        label={label}
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

/* Equipment slot — mirrors the Inventory "Add Item" pattern, sourced from the
   party's Inventory and filtered to items that fit this slot: an "Equip" button
   when empty, the item + a small remove (×) button when full, and a filterable
   dropdown (no minimum query length) when picking. */
function EquipSlotField({ slotKey, label, value, onChange }: {
  slotKey: keyof Equipment
  label: string
  value: string | null  // an item INSTANCE id (or null)
  onChange: (instanceId: string | null) => void
}) {
  const inventory = useItemsStore((s) => s.inventory)
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Resolve the equipped instance id → its catalog item.
  const currentItem = value ? inventory.find((s) => s.instanceId === value)?.item : undefined

  const q = search.toLowerCase().trim()
  // STOWED equipment instances that fit this slot (each copy is selectable).
  const results = inventory
    .filter((s) => !s.equippedBy && s.item && s.item.type === 'Equipment' && itemFitsSlot(s.item.slot, slotKey))
    .filter((s) => !q || (s.item!.name.toLowerCase().includes(q)))
    .sort((a, b) => (a.item!.name).localeCompare(b.item!.name))

  const openPicker = () => { setSearch(''); setOpen(true); setTimeout(() => inputRef.current?.focus(), 0) }
  const closePicker = () => { setOpen(false); setSearch('') }

  const handleSelect = (instanceId: string) => {
    onChange(instanceId)
    closePicker()
  }

  const handleClear = () => {
    onChange(null)
    closePicker()
  }

  return (
    <div className="relative">
      {open ? (
        <div>
          <input
            ref={inputRef}
            className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
            placeholder={`Filter for ${label}…`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onBlur={() => setTimeout(closePicker, 200)}
          />
          <div className="absolute z-20 left-0 right-0 mt-0.5 border border-line bg-bg1 max-h-40 overflow-y-auto shadow-lg">
            {results.length === 0 ? (
              <div className="px-2.5 py-2 text-xs text-textdim font-body">No matching items in inventory</div>
            ) : (
              results.map((stack) => {
                const item = stack.item!
                return (
                  <button
                    key={stack.instanceId}
                    type="button"
                    className="w-full flex items-center gap-2 px-2.5 py-1.5 hover:bg-bg2 text-left"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => handleSelect(stack.instanceId)}
                  >
                    <span
                      className={`w-2 h-2 rounded-full shrink-0 ${RARITY_COLORS[item.rarity] || RARITY_COLORS.c}`}
                      title={RARITY_LABELS[item.rarity] || 'Common'}
                    />
                    <span className="text-sm font-body text-text truncate">{item.name}</span>
                    {item.slot && (
                      <span className="text-[10px] text-textdim font-ui ml-auto shrink-0">{item.slot}</span>
                    )}
                  </button>
                )
              })
            )}
          </div>
        </div>
      ) : currentItem ? (
        // Filled slot → the item's card (click to swap). The slot name is
        // omitted; the icon + context convey it. A × unequips it.
        <div className="relative">
          <ItemCard item={currentItem} selected={false} onClick={openPicker} />
          <button
            type="button"
            className="absolute right-1.5 top-1/2 -translate-y-1/2 z-10 text-textdim hover:text-danger text-base font-ui leading-none px-1 bg-bg2/80 rounded"
            onClick={(e) => { e.stopPropagation(); handleClear() }}
            title={`Unequip ${label}`}
          >&times;</button>
        </div>
      ) : (
        // Empty slot → a placeholder that reads the slot's name.
        <button
          type="button"
          className="w-full font-ui text-[11px] text-textsec border border-dashed border-line rounded-md px-3 py-2 hover:border-line2 hover:text-text transition-colors text-left"
          onClick={openPicker}
        >
          {label}
        </button>
      )}
    </div>
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
