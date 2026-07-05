import { useCallback, useEffect, useRef, useState } from 'react'

// Fixed portrait aspect (3:4). The on-screen crop frame and the exported image
// share this ratio, so the baked result fills any 3:4 display container exactly.
const FRAME_W = 300
const FRAME_H = 400
const OUT_W = 600
const OUT_H = 800
const MAX_ZOOM = 5

/**
 * A self-contained crop/zoom portrait editor (no external deps). Pan by dragging,
 * zoom with the wheel or the slider; Save bakes the framed region to a JPEG blob.
 */
export function PortraitEditor({
  initialSrc,
  onSave,
  onCancel,
}: {
  initialSrc?: string
  // crop = the framed 3:4 JPEG; full = the chosen source image (null when the
  // user kept the existing portrait and only re-cropped).
  onSave: (crop: Blob, full: Blob | null) => void | Promise<void>
  onCancel: () => void
}) {
  const [src, setSrc] = useState<string | undefined>(initialSrc)
  const [img, setImg] = useState<HTMLImageElement | null>(null)
  const [sourceBlob, setSourceBlob] = useState<Blob | null>(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [saving, setSaving] = useState(false)
  const dragRef = useRef<{ px: number; py: number; startX: number; startY: number } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  // Load the image whenever the source changes.
  useEffect(() => {
    if (!src) { setImg(null); return }
    const im = new Image()
    im.onload = () => { setImg(im); setZoom(1); setPan({ x: 0, y: 0 }) }
    im.src = src
  }, [src])

  // Esc closes.
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onCancel])

  const baseScale = img ? Math.max(FRAME_W / img.naturalWidth, FRAME_H / img.naturalHeight) : 1
  const scale = baseScale * zoom
  const displayW = img ? img.naturalWidth * scale : 0
  const displayH = img ? img.naturalHeight * scale : 0
  const maxPanX = Math.max(0, (displayW - FRAME_W) / 2)
  const maxPanY = Math.max(0, (displayH - FRAME_H) / 2)

  const clampPan = useCallback(
    (p: { x: number; y: number }) => ({
      x: Math.max(-maxPanX, Math.min(maxPanX, p.x)),
      y: Math.max(-maxPanY, Math.min(maxPanY, p.y)),
    }),
    [maxPanX, maxPanY],
  )

  const cpan = clampPan(pan)
  const left = (FRAME_W - displayW) / 2 + cpan.x
  const top = (FRAME_H - displayH) / 2 + cpan.y

  const onPointerDown = (e: React.PointerEvent) => {
    if (!img) return
    dragRef.current = { px: e.clientX, py: e.clientY, startX: cpan.x, startY: cpan.y }
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current
    if (!d) return
    setPan(clampPan({ x: d.startX + (e.clientX - d.px), y: d.startY + (e.clientY - d.py) }))
  }
  const onPointerUp = () => { dragRef.current = null }

  const onWheel = (e: React.WheelEvent) => {
    if (!img) return
    const next = Math.max(1, Math.min(MAX_ZOOM, zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1)))
    setZoom(next)
  }

  const pickFile = (file: File) => {
    setSourceBlob(file)  // keep the original as the "full" art
    const reader = new FileReader()
    reader.onload = () => setSrc(reader.result as string)
    reader.readAsDataURL(file)
  }

  const handleSave = async () => {
    if (!img) return
    setSaving(true)
    try {
      const sx = -left / scale
      const sy = -top / scale
      const sW = FRAME_W / scale
      const sH = FRAME_H / scale
      const canvas = document.createElement('canvas')
      canvas.width = OUT_W
      canvas.height = OUT_H
      const ctx = canvas.getContext('2d')
      if (!ctx) { setSaving(false); return }
      ctx.drawImage(img, sx, sy, sW, sH, 0, 0, OUT_W, OUT_H)
      const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, 'image/jpeg', 0.9))
      if (blob) await onSave(blob, sourceBlob)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-bg0/80 flex items-center justify-center p-4" onClick={onCancel}>
      <div
        className="bg-bg2 border border-line2 rounded-md p-4 w-[340px] max-w-full flex flex-col gap-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <span className="font-ui text-[10px] tracking-wider text-textsec uppercase">Edit Portrait</span>
          <button type="button" className="font-ui text-[11px] text-textdim hover:text-text" onClick={onCancel}>✕</button>
        </div>

        {/* Crop frame (3:4) */}
        <div
          className="relative mx-auto overflow-hidden border border-line2 bg-bg0 touch-none select-none"
          style={{ width: FRAME_W, height: FRAME_H, cursor: img ? 'grab' : 'default' }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onWheel={onWheel}
        >
          {img ? (
            <img
              src={src}
              alt="Portrait source"
              draggable={false}
              className="absolute max-w-none pointer-events-none"
              style={{ left, top, width: displayW, height: displayH }}
            />
          ) : (
            <button
              type="button"
              className="absolute inset-0 flex items-center justify-center font-ui text-[10px] tracking-wider text-textdim hover:text-text"
              onClick={() => fileRef.current?.click()}
            >
              CHOOSE IMAGE
            </button>
          )}
        </div>

        {/* Zoom */}
        {img && (
          <div className="flex items-center gap-2">
            <span className="font-ui text-[9px] text-textdim tracking-wider">ZOOM</span>
            <input
              type="range"
              min={1}
              max={MAX_ZOOM}
              step={0.01}
              value={zoom}
              onChange={(e) => setZoom(Number(e.target.value))}
              className="flex-1 accent-gold"
            />
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="font-ui text-[10px] tracking-wider text-textsec border border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
            onClick={() => fileRef.current?.click()}
          >
            {img ? 'CHANGE IMAGE' : 'CHOOSE IMAGE'}
          </button>
          <div className="flex-1" />
          <button
            type="button"
            className="font-ui text-[10px] tracking-wider text-textdim border border-line px-3 py-1.5 hover:text-text hover:border-line2 transition-colors"
            onClick={onCancel}
          >
            CANCEL
          </button>
          <button
            type="button"
            disabled={!img || saving}
            className="font-ui text-[10px] tracking-wider bg-golddeep text-bg0 px-3 py-1.5 hover:bg-gold transition-colors disabled:opacity-40"
            onClick={handleSave}
          >
            {saving ? 'SAVING…' : 'SAVE'}
          </button>
        </div>

        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) pickFile(f)
            e.target.value = ''
          }}
        />
      </div>
    </div>
  )
}
