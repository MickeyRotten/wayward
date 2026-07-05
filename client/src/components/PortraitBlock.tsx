import { useState } from 'react'
import { PortraitEditor } from './PortraitEditor'
import { uploadCharacterPortrait } from './PortraitUpload'

/**
 * Character portrait for the Inspector: shows the FULL art (fixed 3:4), with an
 * Edit/Add Portrait button that opens the crop/zoom editor. Saving uploads both
 * the full source and the framed crop to the character's file (replacing the
 * old images), then calls onUpdated so the sheet re-fetches the fresh URLs.
 */
export function PortraitBlock({
  characterId,
  fullUrl,
  cropUrl,
  onUpdated,
}: {
  characterId: string
  fullUrl?: string | null
  cropUrl?: string | null
  onUpdated?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [version, setVersion] = useState(0)  // cache-buster after a save

  const display = fullUrl || cropUrl
  const bust = (u: string) => `${u}${u.includes('?') ? '&' : '?'}v=${version}`

  return (
    <div>
      <div className="w-full aspect-[3/4] border border-line rounded-md bg-bg2 overflow-hidden">
        {display ? (
          <img src={bust(display)} alt="Portrait" className="w-full h-full object-cover" />
        ) : (
          <div className="flex items-center justify-center h-full font-ui text-[9px] text-textdim tracking-wider">
            NO PORTRAIT
          </div>
        )}
      </div>
      <button
        type="button"
        className="mt-1.5 w-full font-ui text-[10px] tracking-wider text-textsec border border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
        onClick={() => setOpen(true)}
      >
        {display ? 'EDIT PORTRAIT' : 'ADD PORTRAIT'}
      </button>
      {open && (
        <PortraitEditor
          initialSrc={fullUrl ? bust(fullUrl) : (cropUrl ? bust(cropUrl) : undefined)}
          onSave={async (crop, full) => {
            const ok = await uploadCharacterPortrait(characterId, crop, full)
            if (ok) {
              setVersion((v) => v + 1)
              onUpdated?.()
            }
            setOpen(false)
          }}
          onCancel={() => setOpen(false)}
        />
      )}
    </div>
  )
}
