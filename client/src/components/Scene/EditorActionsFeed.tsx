// Shows what the Editor did this turn — streamed live during the turn and
// rendered from the persisted record on the finished message.

import { editorActionLabel } from '../../state/chatStore'

export function EditorActionsFeed({ actions, live }: { actions: { name: string; result: string }[]; live?: boolean }) {
  if (actions.length === 0) return null
  return (
    <div className="flex flex-col gap-1 border-l-2 border-gold/40 pl-2.5 my-1">
      {actions.map((a, i) => (
        <div key={i} className="flex items-baseline gap-2">
          <span className="font-ui text-[9px] tracking-wider text-gold/80 uppercase shrink-0 min-w-[92px]">
            {editorActionLabel(a.name)}
          </span>
          <span className="font-body text-[12px] text-textsec leading-snug">{a.result}</span>
        </div>
      ))}
      {live && (
        <span className="font-ui text-[9px] tracking-wider text-textdim animate-pulse">···</span>
      )}
    </div>
  )
}
