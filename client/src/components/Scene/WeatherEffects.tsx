import { useEffect, useRef } from 'react'
import type { WeatherKind } from '../../lib/weather'

// Ambient weather rendered on a canvas over the backdrop art (under the
// messages). Deliberately cheap: modest particle counts scaled to area,
// delta-time movement, paused while the tab is hidden, capped DPR, and
// nothing at all under prefers-reduced-motion.

interface Drop { x: number; y: number; len: number; speed: number }
interface Flake { x: number; y: number; r: number; vy: number; phase: number }
interface Blob { x: number; y: number; r: number; vx: number; alpha: number }

export function WeatherEffects({ kind }: { kind: WeatherKind }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    let W = 0
    let H = 0
    const rand = (a: number, b: number) => a + Math.random() * (b - a)

    let drops: Drop[] = []
    let flakes: Flake[] = []
    let blobs: Blob[] = []

    const storm = kind === 'storm'
    const populate = () => {
      const area = W * H
      if (kind === 'rain' || storm) {
        const n = Math.round(Math.min(140, Math.max(40, area / 12000)) * (storm ? 1.5 : 1))
        drops = Array.from({ length: n }, () => ({
          x: rand(0, W), y: rand(0, H), len: rand(9, 18), speed: rand(650, 1050) * (storm ? 1.2 : 1),
        }))
      } else if (kind === 'snow') {
        const n = Math.round(Math.min(90, Math.max(30, area / 18000)))
        flakes = Array.from({ length: n }, () => ({
          x: rand(0, W), y: rand(0, H), r: rand(1, 2.6), vy: rand(22, 55), phase: rand(0, Math.PI * 2),
        }))
      } else {
        blobs = Array.from({ length: 6 }, (_, i) => ({
          x: rand(0, W), y: rand(0.1, 0.9) * H, r: rand(180, 380),
          vx: rand(5, 14) * (i % 2 ? 1 : -1), alpha: rand(0.05, 0.1),
        }))
      }
    }

    const resize = () => {
      W = canvas.clientWidth
      H = canvas.clientHeight
      canvas.width = Math.max(1, Math.round(W * dpr))
      canvas.height = Math.max(1, Math.round(H * dpr))
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      populate()
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(canvas)

    // Storm lightning: an occasional double-pulse whitewash.
    let nextFlash = performance.now() + rand(3000, 8000)
    let flashAt = -1

    const wind = storm ? 160 : 60 // horizontal rain drift, px/s
    let last = performance.now()
    let raf = 0

    const step = (now: number) => {
      raf = requestAnimationFrame(step)
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      if (document.hidden || W === 0 || H === 0) return
      ctx.clearRect(0, 0, W, H)

      if (kind === 'rain' || storm) {
        ctx.strokeStyle = 'rgba(173, 196, 230, 0.38)'
        ctx.lineWidth = 1
        ctx.beginPath()
        const slope = wind / 900 // x drift per y fallen
        for (const d of drops) {
          d.y += d.speed * dt
          d.x += wind * dt
          if (d.y - d.len > H) { d.y = -d.len; d.x = rand(-0.1, 1) * W }
          if (d.x > W + 20) d.x -= W + 40
          ctx.moveTo(d.x, d.y)
          ctx.lineTo(d.x - slope * d.len, d.y - d.len)
        }
        ctx.stroke()

        if (storm) {
          if (now >= nextFlash) { flashAt = now; nextFlash = now + rand(4000, 11000) }
          const since = now - flashAt
          if (flashAt > 0 && since < 450) {
            // two quick decaying pulses
            const pulse = Math.max(0, 1 - since / 160) + Math.max(0, 1 - Math.abs(since - 240) / 120) * 0.7
            ctx.fillStyle = `rgba(235, 240, 255, ${Math.min(0.32, pulse * 0.32)})`
            ctx.fillRect(0, 0, W, H)
          }
        }
      } else if (kind === 'snow') {
        ctx.fillStyle = 'rgba(240, 244, 250, 0.75)'
        for (const f of flakes) {
          f.y += f.vy * dt
          f.x += Math.sin(now / 900 + f.phase) * 12 * dt + 6 * dt
          if (f.y - f.r > H) { f.y = -f.r; f.x = rand(0, W) }
          if (f.x - f.r > W) f.x = -f.r
          ctx.globalAlpha = 0.35 + (f.r / 2.6) * 0.45
          ctx.beginPath()
          ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2)
          ctx.fill()
        }
        ctx.globalAlpha = 1
      } else {
        // fog / haze: large soft blobs drifting sideways
        for (const b of blobs) {
          b.x += b.vx * dt
          if (b.vx > 0 && b.x - b.r > W) b.x = -b.r
          if (b.vx < 0 && b.x + b.r < 0) b.x = W + b.r
          const g = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.r)
          g.addColorStop(0, `rgba(206, 197, 178, ${b.alpha})`)
          g.addColorStop(1, 'rgba(206, 197, 178, 0)')
          ctx.fillStyle = g
          ctx.fillRect(b.x - b.r, b.y - b.r, b.r * 2, b.r * 2)
        }
      }
    }
    raf = requestAnimationFrame(step)

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [kind])

  return <canvas ref={ref} data-weather={kind} className="absolute inset-0 h-full w-full" aria-hidden="true" />
}
