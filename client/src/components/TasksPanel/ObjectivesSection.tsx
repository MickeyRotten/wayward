import { useState } from 'react'
import { useObjectivesStore } from '../../state/objectivesStore'
import type { Objective } from '@shared/types/models'

/** Overarching, direction-setting goals (bigger than tasks). Inline-editable —
 *  these steer the Narrator, so they live right at the top of the panel. */
export function ObjectivesSection() {
  const objectives = useObjectivesStore((s) => s.objectives)
  const active = objectives.filter((o) => o.status === 'active')
  const done = objectives.filter((o) => o.status !== 'active')

  return (
    <div className="pb-3">
      <div className="flex items-center gap-2 px-2 pb-1">
        <span className="font-ui text-[9px] text-gold tracking-wider">OBJECTIVES</span>
        <span className="font-ui text-[9px] text-textdim tracking-wider">— GUIDING GOALS</span>
      </div>

      {active.length === 0 && done.length === 0 && (
        <p className="text-[11px] text-textdim font-body px-4 py-1.5">
          No objectives yet — the big goals steering your story.
        </p>
      )}

      <div className="space-y-1">
        {active.map((o) => (
          <ObjectiveRow key={o.id} objective={o} />
        ))}
        {done.map((o) => (
          <ObjectiveRow key={o.id} objective={o} />
        ))}
      </div>

      <NewObjectiveInput />
    </div>
  )
}

function ObjectiveRow({ objective }: { objective: Objective }) {
  const setStatus = useObjectivesStore((s) => s.setStatus)
  const updateObjective = useObjectivesStore((s) => s.updateObjective)
  const deleteObjective = useObjectivesStore((s) => s.deleteObjective)
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(objective.text)
  const [detail, setDetail] = useState(objective.detail)

  const done = objective.status !== 'active'

  const commit = () => {
    const t = text.trim()
    if (t !== objective.text || detail !== objective.detail) {
      void updateObjective(objective.id, { text: t || objective.text, detail })
    }
  }

  return (
    <div className="border border-line/60 rounded-md bg-bg2/40">
      <div className="flex items-center gap-2.5 px-3 py-2">
        <button
          type="button"
          className={`shrink-0 w-4 h-4 rounded-[3px] border flex items-center justify-center transition-colors ${
            objective.status === 'completed'
              ? 'border-gold bg-gold/20 text-gold'
              : objective.status === 'failed'
                ? 'border-danger text-danger'
                : 'border-line2 hover:border-gold'
          }`}
          onClick={() => void setStatus(objective.id, done ? 'active' : 'completed')}
          title={done ? 'Re-open' : 'Mark achieved'}
          aria-label="Toggle objective status"
        >
          {objective.status === 'completed' ? (
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
          ) : objective.status === 'failed' ? (
            <span className="text-[10px] leading-none">✕</span>
          ) : (
            <span className="text-gold/70 text-[11px] leading-none">◆</span>
          )}
        </button>
        <button
          type="button"
          className={`font-body text-sm text-left flex-1 min-w-0 truncate ${done ? 'text-textdim line-through' : 'text-text'}`}
          onClick={() => setOpen(!open)}
          title={objective.detail || undefined}
        >
          {objective.text || 'Untitled objective'}
        </button>
        <span className="font-ui text-[9px] text-textdim">{open ? '▴' : '▾'}</span>
      </div>

      {open && (
        <div className="px-3 pb-3 pt-1 space-y-2 border-t border-line/40">
          <textarea
            className="w-full border border-line bg-bg0 px-2 py-1 text-[13px] font-body text-text outline-none focus:border-line2 focus:bg-bg2 resize-y min-h-[34px]"
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onBlur={commit}
            placeholder="Objective..."
          />
          <textarea
            className="w-full border border-line bg-bg0 px-2 py-1 text-[12px] font-body text-text2 outline-none focus:border-line2 focus:bg-bg2 resize-y min-h-[44px]"
            rows={2}
            value={detail}
            onChange={(e) => setDetail(e.target.value)}
            onBlur={commit}
            placeholder="Stakes / detail — what's at risk, the looming threat..."
          />
          <div className="flex gap-2">
            {objective.status !== 'failed' && (
              <button
                type="button"
                className="font-ui text-[9px] tracking-wider text-textsec border border-line px-2 py-1 hover:text-danger hover:border-danger-border transition-colors"
                onClick={() => void setStatus(objective.id, 'failed')}
              >
                MARK FAILED
              </button>
            )}
            <button
              type="button"
              className="font-ui text-[9px] tracking-wider text-textdim border border-line px-2 py-1 hover:text-danger hover:border-danger-border transition-colors ml-auto"
              onClick={() => void deleteObjective(objective.id)}
            >
              DELETE
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function NewObjectiveInput() {
  const [text, setText] = useState('')
  const createObjective = useObjectivesStore((s) => s.createObjective)

  const submit = async () => {
    const t = text.trim()
    if (!t) return
    await createObjective(t)
    setText('')
  }

  return (
    <div className="px-2 pt-2">
      <input
        className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
        placeholder="New objective... (Enter)"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            void submit()
          }
        }}
      />
    </div>
  )
}
