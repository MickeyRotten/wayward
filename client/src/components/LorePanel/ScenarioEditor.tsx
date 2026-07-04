import { useCallback, useEffect, useRef, useState } from 'react'
import { useChatStore } from '../../state/chatStore'
import { useScenarioStore } from '../../state/scenarioStore'
import { useNarratorStore } from '../../state/narratorStore'
import { ExpandableTextarea } from '../common/ExpandableTextarea'
import type { ScenarioFields } from '@shared/types/models'

const FIELD_DEFS: { key: keyof ScenarioFields; label: string }[] = [
  { key: 'setting', label: 'Setting' },
  { key: 'historyBrief', label: 'History (Brief)' },
  { key: 'species', label: 'Species' },
  { key: 'geography', label: 'Geography' },
  { key: 'techAndMagic', label: 'Technology & Magic' },
  { key: 'other', label: 'Other' },
]

export function ScenarioEditor() {
  const editMode = useChatStore((s) => s.planningMode)
  const scenario = useScenarioStore((s) => s)
  const save = useScenarioStore((s) => s.save)

  const draft = useRef<Partial<ScenarioFields>>({})
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const flush = useCallback(() => {
    clearTimeout(timer.current)
    if (Object.keys(draft.current).length === 0) return
    const toSave = draft.current
    draft.current = {}
    save(toSave)
  }, [save])

  const scheduleFlush = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, 600)
  }, [flush])

  const update = (key: keyof ScenarioFields, value: string, immediate?: boolean) => {
    draft.current = { ...draft.current, [key]: value }
    if (immediate) flush()
    else scheduleFlush()
  }

  if (!editMode) {
    return (
      <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-5">
        {FIELD_DEFS.map(({ key, label }) => (
          <div key={key}>
            <span className="font-ui text-[10px] tracking-wider text-textsec uppercase">{label}</span>
            <p className="font-body text-sm text-text2 leading-relaxed whitespace-pre-wrap mt-1">
              {scenario[key] || <span className="text-textdim">(empty)</span>}
            </p>
          </div>
        ))}
        <FirstMessageField editable={false} />
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-4">
      {FIELD_DEFS.map(({ key, label }) => (
        <label key={key} className="block space-y-1">
          <span className="font-ui text-[10px] tracking-wider text-textsec uppercase">{label}</span>
          <ExpandableTextarea
            label={label}
            className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2 resize-y min-h-[80px]"
            rows={4}
            value={scenario[key]}
            onChange={(v) => update(key, v)}
            onBlur={(v) => update(key, v, true)}
          />
        </label>
      ))}
      <FirstMessageField editable />
    </div>
  )
}

// The opening narration. It lives on the NarratorConfig (not the Scenario), but
// it's edited here on the Scenario tab as a convenience — clearly separated.
function FirstMessageField({ editable }: { editable: boolean }) {
  const firstMessage = useNarratorStore((s) => s.firstMessage)
  const save = useNarratorStore((s) => s.save)
  const [value, setValue] = useState(firstMessage)

  useEffect(() => { setValue(firstMessage) }, [firstMessage])

  const commit = (v: string) => { if (v !== firstMessage) save({ firstMessage: v }) }

  return (
    <div className="pt-4 mt-2 border-t border-line space-y-1">
      <span className="font-ui text-[10px] tracking-wider text-textsec uppercase">First Message</span>
      {editable ? (
        <ExpandableTextarea
          label="First Message"
          className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2 resize-y min-h-[80px]"
          rows={4}
          value={value}
          placeholder="The opening narration shown before the player's first turn."
          onChange={setValue}
          onBlur={commit}
        />
      ) : (
        <p className="font-body text-sm text-text2 leading-relaxed whitespace-pre-wrap mt-1">
          {firstMessage || <span className="text-textdim">(empty)</span>}
        </p>
      )}
      <span className="block text-[10px] text-textdim font-body">
        The drop-capped opening message, included in context. Not part of the Scenario.
      </span>
    </div>
  )
}
