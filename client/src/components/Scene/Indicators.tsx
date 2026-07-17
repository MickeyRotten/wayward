// Working indicators: the live elapsed-seconds counter and the narrator's
// THINKING line. (The Chronicler indicator in ChatScene and the streaming
// window's status lines are composed from these.)

import { useEffect, useState } from 'react'

// A live "Ns" elapsed counter. Counts from `startedAt` if given, else from the
// moment it mounts (used for the Chronicler, which has no shared start time).
export function Elapsed({ startedAt }: { startedAt: number | null }) {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    const start = startedAt ?? Date.now()
    const tick = () => setSecs(Math.floor((Date.now() - start) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [startedAt])
  return <>{secs > 0 ? ` ${secs}s` : ''}</>
}

export function ThinkingIndicator({ startedAt, isSummarizing }: { startedAt: number | null; isSummarizing: boolean }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!startedAt) return
    setElapsed(0)
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => clearInterval(interval)
  }, [startedAt])

  const label = isSummarizing ? 'SUMMARIZING HISTORY' : 'THINKING'

  return (
    <span className="font-ui text-[10px] text-textdim tracking-wider">
      {label}{elapsed > 0 ? ` ${elapsed}s` : ''}
      <span className="animate-pulse"> ···</span>
    </span>
  )
}
