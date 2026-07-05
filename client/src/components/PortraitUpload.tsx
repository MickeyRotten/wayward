import { useRef } from 'react'

/** Upload an image blob (e.g. a cropped canvas export) → returns the filename. */
export async function uploadPortraitBlob(blob: Blob): Promise<string | null> {
  const form = new FormData()
  form.append('file', blob, 'portrait.jpg')
  const res = await fetch('/api/portraits/upload', { method: 'POST', body: form })
  if (!res.ok) return null
  const data = await res.json()
  return data.filename as string
}

/** Save a character's portrait: the framed crop (chat/avatars) and optionally the
    full source image (Inspector). Replaces the character's previous portrait. */
export async function uploadCharacterPortrait(
  characterId: string, crop: Blob, full: Blob | null,
): Promise<boolean> {
  const form = new FormData()
  form.append('crop', crop, 'crop.jpg')
  if (full) form.append('full', full, 'full.jpg')
  const res = await fetch(`/api/characters/${characterId}/portrait`, { method: 'POST', body: form })
  return res.ok
}

export function PortraitUpload({
  portrait,
  onUploaded,
}: {
  portrait?: string
  onUploaded: (filename: string) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)

  const handleUpload = async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch('/api/portraits/upload', { method: 'POST', body: form })
    if (!res.ok) return
    const data = await res.json()
    onUploaded(data.filename)
  }

  const portraitUrl = portrait ? `/portraits/${portrait}` : null

  return (
    <div
      className="relative w-full aspect-[3/4] border border-line bg-bg2 overflow-hidden cursor-pointer group"
      onClick={() => inputRef.current?.click()}
    >
      {portraitUrl ? (
        <img
          src={portraitUrl}
          alt="Portrait"
          className="w-full h-full object-cover object-top"
        />
      ) : (
        <div className="flex items-center justify-center h-full">
          <span className="font-ui text-[9px] text-textdim tracking-wider">UPLOAD PORTRAIT</span>
        </div>
      )}
      <div className="absolute inset-0 bg-bg0/0 group-hover:bg-bg0/30 transition-colors flex items-center justify-center">
        <span className="font-ui text-[9px] text-text opacity-0 group-hover:opacity-100 transition-opacity tracking-wider">
          {portraitUrl ? 'CHANGE' : 'UPLOAD'}
        </span>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) handleUpload(file)
          e.target.value = ''
        }}
      />
    </div>
  )
}
