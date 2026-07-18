// The Campaign Builder: guided Story Style options that compose the Narrator's
// narration voice. StyleFieldsEditor is shared by the New Campaign modal and the
// Config → Story Style section; NewCampaignModal wraps it with a name + demo-world
// checkbox. Field defs (with each option's label/hint) come from the server; the
// prompt snippets stay server-side.

import { useEffect, useState } from 'react'
import type { StoryStyleFields, StyleFieldDef } from '@shared/types/models'
import { ExpandableTextarea } from '../common/ExpandableTextarea'

const CUSTOM = '__custom__'

/** Selections a fresh campaign starts from — these keep new campaigns reading
 *  the same as before Story Style existed (perspective/length/rating). */
export const BUILDER_DEFAULTS: Partial<StoryStyleFields> = {
  perspective: 'second_person',
  verbosity: 'standard',
  contentLimit: 'adult',
}

type FieldKey = keyof StoryStyleFields

const selectCls =
  'w-full border border-line2 bg-bg0 px-2 py-1.5 text-sm font-body text-text outline-none'
const inputCls =
  'w-full border border-line2 bg-bg0 px-2 py-1.5 text-sm font-body text-text outline-none focus:bg-bg2'

/** A grid of dropdowns (one per Story Style field, each with an optional custom
 *  value) plus the freeform custom-instructions box. `fields` is the current
 *  selection; `onChange` receives a partial patch. */
export function StyleFieldsEditor({
  defs,
  fields,
  onChange,
}: {
  defs: StyleFieldDef[]
  fields: StoryStyleFields
  onChange: (patch: Partial<StoryStyleFields>) => void
}) {
  // Fields the user explicitly switched into "Custom…" (so an empty custom value
  // is distinguishable from "unset").
  const [customMode, setCustomMode] = useState<Record<string, boolean>>({})

  if (defs.length === 0) {
    return <p className="text-[11px] text-textdim font-body">Loading options…</p>
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {defs.map((def) => {
          const key = def.key as FieldKey
          const value = fields[key] ?? ''
          const matchesOption = def.options.some((o) => o.id === value)
          const isCustom = def.allowCustom && (customMode[def.key] || (!!value && !matchesOption))
          const selectValue = isCustom ? CUSTOM : matchesOption ? value : ''
          const selectedOpt = def.options.find((o) => o.id === value)

          return (
            <label key={def.key} className="block space-y-1">
              <span className="text-[11px] text-textdim font-body">{def.label}</span>
              <select
                className={selectCls}
                value={selectValue}
                onChange={(e) => {
                  const v = e.target.value
                  if (v === CUSTOM) {
                    setCustomMode((m) => ({ ...m, [def.key]: true }))
                    onChange({ [key]: '' } as Partial<StoryStyleFields>)
                  } else {
                    setCustomMode((m) => ({ ...m, [def.key]: false }))
                    onChange({ [key]: v } as Partial<StoryStyleFields>)
                  }
                }}
              >
                <option value="">— No preference —</option>
                {def.options.map((o) => (
                  <option key={o.id} value={o.id}>{o.label}</option>
                ))}
                {def.allowCustom && <option value={CUSTOM}>Custom…</option>}
              </select>
              {isCustom && (
                <input
                  autoFocus
                  className={inputCls}
                  placeholder={`Describe the ${def.label.toLowerCase()}…`}
                  value={value}
                  onChange={(e) => onChange({ [key]: e.target.value } as Partial<StoryStyleFields>)}
                />
              )}
              {!isCustom && selectedOpt?.hint && (
                <span className="block text-[10px] text-textdim font-body leading-relaxed">{selectedOpt.hint}</span>
              )}
            </label>
          )
        })}
      </div>

      <label className="block space-y-1">
        <span className="text-[11px] text-textdim font-body">Additional Instructions</span>
        <ExpandableTextarea
          label="Additional Instructions"
          className="w-full border border-line2 bg-bg0 px-2 py-1.5 text-[12px] font-body text-text2 outline-none focus:bg-bg2 resize-y min-h-[56px]"
          rows={3}
          value={fields.customInstructions ?? ''}
          placeholder="Anything else the narrator should always keep in mind (optional)."
          onChange={(v) => onChange({ customInstructions: v })}
        />
      </label>
    </div>
  )
}

const EMPTY: StoryStyleFields = {
  genre: '', tone: '', writingStyle: '', verbosity: '', contentLimit: '',
  perspective: '', structure: '', customInstructions: '',
}

export function NewCampaignModal({
  busy,
  defs,
  onCreate,
  onCancel,
}: {
  busy: boolean
  defs: StyleFieldDef[]
  onCreate: (name: string, style: Partial<StoryStyleFields>, demo: boolean) => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [demo, setDemo] = useState(false)
  const [fields, setFields] = useState<StoryStyleFields>({ ...EMPTY, ...BUILDER_DEFAULTS })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  const submit = () => onCreate(name.trim(), fields, demo)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onCancel}>
      <div
        className="w-full max-w-lg max-h-[88vh] overflow-y-auto border border-line2 bg-bg1 rounded-md p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-disp text-[18px] pt-[2px] leading-none text-text">NEW CAMPAIGN</h3>

        <label className="block space-y-1">
          <span className="text-[11px] text-textdim font-body">Name</span>
          <input
            autoFocus
            className={inputCls}
            placeholder="My Campaign"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !busy) submit() }}
          />
        </label>

        <div className="space-y-1">
          <span className="text-[11px] text-textdim font-body">Story Style</span>
          <p className="text-[10px] text-textdim font-body leading-relaxed">
            Shape how the Narrator tells your story. Everything here is optional and fully editable later in Config → Story Style.
          </p>
          <div className="pt-1">
            <StyleFieldsEditor
              defs={defs}
              fields={fields}
              onChange={(patch) => setFields((f) => ({ ...f, ...patch }))}
            />
          </div>
        </div>

        <label className="flex items-start gap-2 pt-1 cursor-pointer">
          <input
            type="checkbox"
            className="mt-0.5 accent-gold"
            checked={demo}
            onChange={(e) => {
              setDemo(e.target.checked)
              if (e.target.checked && !fields.genre) setFields((f) => ({ ...f, genre: 'high_fantasy' }))
            }}
          />
          <span className="text-[11px] font-body text-textsec leading-snug">
            Start from the Fantasy demo world
            <span className="block text-[10px] text-textdim">A sample world, party, and opening scene to explore. Your Story Style still applies.</span>
          </span>
        </label>

        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            type="button"
            className="font-ui text-[10px] tracking-wider text-textsec border border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
            onClick={onCancel}
          >
            CANCEL
          </button>
          <button
            type="button"
            disabled={busy}
            className="font-ui text-[10px] tracking-wider bg-golddeep text-bg0 px-4 py-1.5 hover:bg-gold transition-colors disabled:opacity-40"
            onClick={submit}
          >
            CREATE
          </button>
        </div>
      </div>
    </div>
  )
}
