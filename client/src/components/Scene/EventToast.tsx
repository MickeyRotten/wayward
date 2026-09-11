// Persistent in-chat toasts (Chronicler notices and player item actions),
// rendered inline in the story log.

import type { ChatEvent } from '@shared/types/models'

export function EventToast({ event }: { event: ChatEvent }) {
  const isChronicler = event.kind === 'chronicler'

  return (
    <div className="mr-auto max-w-[85%] max-lg:max-w-full flex items-start gap-2 px-3 py-1.5">
      {isChronicler ? (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-gold/70 mt-[2px] flex-shrink-0">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
        </svg>
      ) : (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-textsec mt-[2px] flex-shrink-0">
          <path d="M20 7h-9M14 17H5M17 3v8M7 13v8" /><circle cx="17" cy="14" r="3" /><circle cx="7" cy="10" r="3" />
        </svg>
      )}
      <span className="font-ui text-[10px] text-textdim leading-relaxed">
        {isChronicler && <span className="text-gold/70 tracking-wider">CHRONICLER · </span>}
        {event.text}
      </span>
    </div>
  )
}
