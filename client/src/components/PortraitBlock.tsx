import { useState } from 'react'
import { PortraitEditor } from './PortraitEditor'
import { uploadPortraitBlob } from './PortraitUpload'

/**
 * Portrait display (fixed 3:4, image fills) + an Edit/Add Portrait button that
 * opens the crop/zoom editor. On save the cropped image is uploaded and its
 * filename handed back via onChange. Used by the PC and party member sheets.
 */
export function PortraitBlock({
  portrait,
  onChange,
}: {
  portrait?: string
  onChange: (filename: string) => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <div>
      <div className="w-full aspect-[3/4] border border-line rounded-md bg-bg2 overflow-hidden">
        {portrait ? (
          <img src={`/portraits/${portrait}`} alt="Portrait" className="w-full h-full object-cover" />
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
        {portrait ? 'EDIT PORTRAIT' : 'ADD PORTRAIT'}
      </button>
      {open && (
        <PortraitEditor
          initialSrc={portrait ? `/portraits/${portrait}` : undefined}
          onSave={async (blob) => {
            const filename = await uploadPortraitBlob(blob)
            if (filename) onChange(filename)
            setOpen(false)
          }}
          onCancel={() => setOpen(false)}
        />
      )}
    </div>
  )
}
