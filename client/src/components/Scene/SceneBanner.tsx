// The chat header — the Play/Edit mode toggle, the declared location + day on
// the left, and time-of-day + weather on the right (Play mode only).

import type { SceneBanner as SceneBannerState } from '../../lib/location'

export function SceneBanner({
  banner,
  planningMode,
  inputLocked,
  onToggleMode,
}: {
  banner: SceneBannerState
  planningMode: boolean
  inputLocked: boolean
  onToggleMode: () => void
}) {
  return (
    <div
      className="flex-shrink-0 border-b border-line2 bg-bg2 px-4 pt-3 pb-2.5 flex items-start justify-between gap-3"
      style={{
        backgroundImage:
          'radial-gradient(circle, rgba(201,165,88,0.08) 1px, transparent 1px)',
        backgroundSize: '4px 4px',
      }}
    >
      <div className="flex items-start gap-2.5 min-w-0">
        {/* Play / Edit mode toggle (Unity-style): lit while playing (Narration). */}
        <button
          type="button"
          disabled={inputLocked}
          title={planningMode ? 'Exit Edit Mode — back to play' : 'Edit Mode — work on the world'}
          onClick={onToggleMode}
          className={`shrink-0 mt-[1px] w-7 h-7 flex items-center justify-center border rounded-sm transition-colors disabled:opacity-40 ${
            planningMode
              ? 'border-line2 text-textsec hover:text-text'
              : 'border-gold text-gold bg-gold/10'
          }`}
        >
          {planningMode ? (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14.06 9.02l.92.92L5.92 19H5v-.92l9.06-9.06M17.66 3c-.25 0-.51.1-.7.29l-1.83 1.83 3.75 3.75 1.83-1.83a.996.996 0 0 0 0-1.41l-2.34-2.34c-.2-.2-.45-.29-.71-.29z" />
            </svg>
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
          )}
        </button>
        <div className="min-w-0">
        <span className="font-ui text-[8px] tracking-[0.2em] uppercase text-textdim block">
          {planningMode ? 'Mode' : 'Location'}
        </span>
        <h1 className="font-disp text-[22px] max-lg:text-[18px] leading-none text-gold pt-[3px] truncate">
          {planningMode ? 'Edit Mode' : banner.location}
        </h1>
        {!planningMode && banner.day && (
          <span className="font-ui text-[9px] tracking-wider uppercase text-textsec block mt-1">
            Day {banner.day}
          </span>
        )}
        </div>
      </div>
      {!planningMode && (banner.timeOfDay || banner.weather) && (
        <div className="shrink-0 text-right">
          {banner.timeOfDay && (
            <div className="flex items-center justify-end gap-1.5 text-gold">
              <TimeOfDayIcon timeOfDay={banner.timeOfDay} />
              <span className="font-ui text-[11px] tracking-wider uppercase">{banner.timeOfDay}</span>
            </div>
          )}
          {banner.weather && (
            <span className="font-body text-[12px] text-textsec block mt-1">{banner.weather}</span>
          )}
        </div>
      )}
    </div>
  )
}

// ── Time-of-day icon ────────────────────────────────────────────────

function TimeOfDayIcon({ timeOfDay }: { timeOfDay: string }) {
  const key = timeOfDay.trim().toLowerCase()
  const common = {
    width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }
  if (key === 'night') {
    return <svg {...common}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
  }
  if (key === 'morning') {
    return (
      <svg {...common}>
        <path d="M3 18h18M7 18a5 5 0 0 1 10 0" />
        <path d="M12 3v3M9.5 6.5 12 4l2.5 2.5" />
      </svg>
    )
  }
  if (key === 'evening') {
    return (
      <svg {...common}>
        <path d="M3 18h18M7 18a5 5 0 0 1 10 0" />
        <path d="M12 7V4M9.5 4.5 12 7l2.5-2.5" />
      </svg>
    )
  }
  if (key === 'afternoon') {
    return (
      <svg {...common}>
        <circle cx="8" cy="8" r="3" />
        <path d="M7 17h8a3 3 0 0 0 .3-6 4.5 4.5 0 0 0-8.7-1.2A3.1 3.1 0 0 0 7 17z" />
      </svg>
    )
  }
  // day (and default): full sun
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
    </svg>
  )
}
