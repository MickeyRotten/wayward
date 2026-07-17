// Persistent in-chat toasts (Chronicler notices, player item actions, and
// server-rolled dice chips), rendered inline in the story log.

import type { ChatEvent } from '@shared/types/models'

export function EventToast({ event }: { event: ChatEvent }) {
  const isChronicler = event.kind === 'chronicler'

  // Dice chip — a server-rolled skill check; success glows gold, failure danger.
  if (event.kind === 'dice') {
    const failed = /Failure$/i.test(event.text)
    return (
      <div className="mr-auto max-w-[85%] max-lg:max-w-full flex items-start gap-2 px-3 py-1.5">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={`mt-[1px] flex-shrink-0 ${failed ? 'text-danger' : 'text-gold'}`}>
          <path d="M12 2 3 7v10l9 5 9-5V7l-9-5z" />
          <path d="M12 22V12" /><path d="M3 7l9 5 9-5" />
        </svg>
        <span className={`font-ui text-[10px] leading-relaxed tracking-wide ${failed ? 'text-danger/90' : 'text-gold/90'}`}>
          {event.text}
        </span>
      </div>
    )
  }

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
