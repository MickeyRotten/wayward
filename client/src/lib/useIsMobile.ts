import { useSyncExternalStore } from 'react'

// Single source of truth for the mobile/desktop layout split.
// <1024px → MobileShell (phones + portrait tablets); ≥1024px → desktop AppShell.
const QUERY = '(max-width: 1023px)'

const mql = window.matchMedia(QUERY)

function subscribe(onChange: () => void) {
  mql.addEventListener('change', onChange)
  return () => mql.removeEventListener('change', onChange)
}

/** True when the viewport is narrower than the desktop grid can support. */
export function useIsMobile(): boolean {
  return useSyncExternalStore(subscribe, () => mql.matches)
}
