import { useCallback, useEffect, useRef, useState } from 'react'
import type { PlayerCharacter, Equipment, BasicInfo, ItemCatalogEntry, Rarity } from '@shared/types/models'
import { usePartyStore } from '../../state/partyStore'
import { useItemsStore } from '../../state/itemsStore'
import { useUiStore } from '../../state/uiStore'
import { PortraitUpload } from '../PortraitUpload'
import { ExpandableTextarea } from '../common/ExpandableTextarea'

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

export function CharacterSheetEditor({ mode }: { mode: 'view' | 'edit' }) {
  const pc = usePartyStore((s) => s.playerCharacter)
  const save = usePartyStore((s) => s.savePlayerCharacter)
  const catalog = useItemsStore((s) => s.catalog)
  const setEditDirty = useUiStore((s) => s.setEditDirty)
  const selectInto = useUiStore((s) => s.selectInto)
  const draft = useRef<PlayerCharacter | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    draft.current = pc ? structuredClone(pc) : null
  }, [pc])

  const flush = useCallback(() => {
    clearTimeout(timer.current)
    if (draft.current) {
      save(draft.current)
      setEditDirty(false)
    }
  }, [save, setEditDirty])

  const scheduleFlush = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, 600)
  }, [flush])

  if (!pc) return null
  const d = draft.current ?? pc

  const updateBasic = (key: keyof BasicInfo, value: string | number, immediate?: boolean) => {
    if (!draft.current) return
    Object.assign(draft.current.basicInfo, { [key]: value })
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  const updateEquip = (key: keyof Equipment, value: string | null, immediate?: boolean) => {
    if (!draft.current) return
    draft.current.equipment[key] = value
    setEditDirty(true)
    immediate ? flush() : scheduleFlush()
  }

  const lookupItem = (id: string | null): ItemCatalogEntry | undefined => {
    if (!id) return undefined
    return catalog.find((i) => i.id === id)
  }

  if (mode === 'view') {
    return (
      <div className="space-y-6 p-6">
        {/* Portrait */}
        {d.basicInfo.portrait && (
          <div className="w-full aspect-3/4 border border-line rounded-md bg-bg2 overflow-hidden">
            <img
              src={`/portraits/${d.basicInfo.portrait}`}
              alt="Portrait"
              className="w-full h-full object-cover object-top"
            />
          </div>
        )}

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
            {d.basicInfo.description && (
              <p className="font-body text-sm text-text2 leading-relaxed mt-2">{d.basicInfo.description}</p>
            )}
          </div>
        </Section>

        {/* Equipment */}
        <Section title="Equipment">
          <div className="grid grid-cols-1 gap-y-1">
            {EQUIP_SLOTS.map(({ key, label }) => {
              const item = lookupItem(d.equipment[key])
              return (
                <EquipViewField
                  key={key}
                  label={label}
                  item={item}
                  onSelect={item ? () => selectInto({ kind: 'item', id: item.id }) : undefined}
                />
              )
            })}
          </div>
        </Section>
      </div>
    )
  }

  return (
    <div className="space-y-6 p-6">
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

      {/* Equipment */}
      <Section title="Equipment">
        <div className="space-y-3">
          {EQUIP_SLOTS.map(({ key, label }) => (
            <EquipSlotField
              key={key}
              label={label}
              value={d.equipment[key]}
              catalog={catalog}
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

function TextArea({ label, value, onChange, onBlur }: {
  label: string; value: string; onChange: (v: string) => void; onBlur?: (v: string) => void
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-textdim font-body block mb-0.5">{label}</span>
      <ExpandableTextarea
        label={label}
        className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors resize-y min-h-[72px]"
        rows={3}
        value={value}
        onChange={onChange}
        onBlur={onBlur ?? onChange}
      />
    </label>
  )
}

function EquipViewField({ label, item, onSelect }: { label: string; item?: ItemCatalogEntry; onSelect?: () => void }) {
  return (
    <div className="flex items-center gap-1.5 py-1 px-1">
      <span className="text-[11px] text-textdim font-body w-[92px] shrink-0">{label}</span>
      {item ? (
        <button
          type="button"
          className="inline-flex items-center gap-1.5 text-left hover:text-gold transition-colors group"
          onClick={onSelect}
          title="Inspect item"
        >
          <span
            className={`w-2 h-2 rounded-full shrink-0 ${RARITY_COLORS[item.rarity] || RARITY_COLORS.c}`}
            title={RARITY_LABELS[item.rarity] || 'Common'}
          />
          <span className="text-sm font-body text-text group-hover:text-gold transition-colors">{item.name}</span>
        </button>
      ) : (
        <span className="text-sm font-body text-textdim italic">Empty</span>
      )}
    </div>
  )
}

function EquipSlotField({ label, value, catalog, onChange }: {
  label: string
  value: string | null
  catalog: ItemCatalogEntry[]
  onChange: (id: string | null) => void
}) {
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const currentItem = value ? catalog.find((i) => i.id === value) : undefined

  const equipItems = catalog.filter((i) => i.type === 'Equipment')
  const results = search.length >= 2
    ? equipItems.filter((i) => i.name.toLowerCase().includes(search.toLowerCase()))
    : []

  const handleSelect = (item: ItemCatalogEntry) => {
    onChange(item.id)
    setSearch('')
    setOpen(false)
  }

  const handleClear = () => {
    onChange(null)
    setSearch('')
    setOpen(false)
  }

  return (
    <div className="relative">
      <span className="text-[11px] text-textdim font-body block mb-0.5">{label}</span>
      {currentItem && !open ? (
        <div className="flex items-center gap-2 w-full border border-line bg-bg0 px-2.5 py-1.5">
          <span
            className={`w-2 h-2 rounded-full shrink-0 ${RARITY_COLORS[currentItem.rarity] || RARITY_COLORS.c}`}
            title={RARITY_LABELS[currentItem.rarity] || 'Common'}
          />
          <span className="text-sm font-body text-text flex-1 truncate">{currentItem.name}</span>
          <button
            type="button"
            className="text-textdim hover:text-text text-xs font-ui shrink-0"
            onClick={() => { setOpen(true); setTimeout(() => inputRef.current?.focus(), 0) }}
            title="Change"
          >CHANGE</button>
          <button
            type="button"
            className="text-textdim hover:text-text text-xs font-ui shrink-0 ml-1"
            onClick={handleClear}
            title="Unequip"
          >&times;</button>
        </div>
      ) : (
        <div>
          <input
            ref={inputRef}
            className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
            placeholder={currentItem ? currentItem.name : 'Search equipment...'}
            value={search}
            onChange={(e) => { setSearch(e.target.value); setOpen(true) }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 200)}
          />
          {open && search.length >= 2 && (
            <div className="absolute z-20 left-0 right-0 mt-0.5 border border-line bg-bg1 max-h-40 overflow-y-auto shadow-lg">
              {results.length === 0 ? (
                <div className="px-2.5 py-2 text-xs text-textdim font-body">No equipment found</div>
              ) : (
                results.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className="w-full flex items-center gap-2 px-2.5 py-1.5 hover:bg-bg2 text-left"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => handleSelect(item)}
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
                ))
              )}
            </div>
          )}
          {open && search.length > 0 && search.length < 2 && (
            <div className="absolute z-20 left-0 right-0 mt-0.5 border border-line bg-bg1 shadow-lg">
              <div className="px-2.5 py-2 text-xs text-textdim font-body">Keep typing...</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
