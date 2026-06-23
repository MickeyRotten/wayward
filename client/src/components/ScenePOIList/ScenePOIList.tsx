import { useState } from 'react'
import { useChatStore } from '../../state/chatStore'
import { deriveCurrentLocation } from '../../lib/location'

interface Poi {
  id: string
  name: string
  blurb: string
}

const POIS: Poi[] = [
  {
    id: 'stone-pillars',
    name: 'Stone Pillars',
    blurb: 'Weathered monoliths ringing the clearing, carved with faded sigils.',
  },
  {
    id: 'silver-pool',
    name: 'Silver Pool',
    blurb: 'A still pond that mirrors the sky a little too perfectly.',
  },
  {
    id: 'misty-trail',
    name: 'Misty Trail',
    blurb: 'A narrow path that fades into low fog beyond the treeline.',
  },
]

export function ScenePOIList() {
  const messages = useChatStore((s) => s.messages)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const locationName = deriveCurrentLocation(messages)

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-5 pb-3">
        <h2 className="font-disp text-[24px] pt-[3px] leading-none text-text">SCENE</h2>
        <p className="font-disp text-[15px] pt-[2px] leading-snug text-gold mt-2">
          {locationName}
        </p>
      </div>

      {/* POI list */}
      <div className="flex-1 overflow-y-auto px-3 pb-3">
        <div className="space-y-1">
          {POIS.map((poi) => {
            const isSelected = selectedId === poi.id
            return (
              <button
                key={poi.id}
                type="button"
                className={`w-full text-left px-3 py-2.5 border-[1.5px] transition-colors ${
                  isSelected
                    ? 'border-line2 bg-bg0'
                    : 'border-transparent hover:bg-bg2'
                }`}
                onClick={() => setSelectedId(isSelected ? null : poi.id)}
              >
                <span className="font-body text-sm text-text">{poi.name}</span>
                {isSelected && (
                  <p className="text-[12px] text-textsec font-body mt-1.5 leading-snug">
                    {poi.blurb}
                  </p>
                )}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
