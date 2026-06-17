import { useRef } from 'react'

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
      className="relative w-full aspect-[3/4] border-[1.5px] border-mid bg-off2 overflow-hidden cursor-pointer group"
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
          <span className="font-ui text-[9px] text-text-dim tracking-wider">UPLOAD PORTRAIT</span>
        </div>
      )}
      <div className="absolute inset-0 bg-border/0 group-hover:bg-border/10 transition-colors flex items-center justify-center">
        <span className="font-ui text-[9px] text-white opacity-0 group-hover:opacity-100 transition-opacity tracking-wider">
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
