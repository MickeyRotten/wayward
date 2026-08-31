import { useEffect } from 'react'

/**
 * Make the Android hardware Back button (and the browser's Back gesture) close
 * whatever is open on top, instead of leaving the app.
 *
 * The APK is a WebView, so Back is a history navigation with nothing to go back
 * to — one press quit the app from a full-screen Inspector, which on a phone is
 * most of the time. The fix is the standard one for a single-page shell: while
 * an overlay is open, push ONE spare history entry and treat the resulting
 * `popstate` as "close this". Popping it back off on unmount keeps the stack
 * from growing with every open/close cycle.
 *
 * Nested overlays each claim their own entry, so Back unwinds them in order —
 * the deepest one registered is the one that answers, because it pushed last.
 *
 * @param active whether the overlay is currently open
 * @param onBack called instead of navigating; should close the overlay
 */
export function useBackHandler(active: boolean, onBack: () => void): void {
  useEffect(() => {
    if (!active) return

    // The marker distinguishes OUR entry from a real navigation, so a Back press
    // arriving from somewhere else is not swallowed.
    const token = { waywardOverlay: Date.now() }
    window.history.pushState(token, '')

    let closing = false
    const onPop = () => {
      closing = true // the entry is already gone; don't pop it again on cleanup
      onBack()
    }
    window.addEventListener('popstate', onPop)

    return () => {
      window.removeEventListener('popstate', onPop)
      // Closed by tapping Back-in-app rather than by the hardware button: our
      // spare entry is still on the stack, so take it off. Guarded on the
      // marker in case something else navigated in the meantime.
      if (!closing && (window.history.state as typeof token | null)?.waywardOverlay === token.waywardOverlay) {
        window.history.back()
      }
    }
  }, [active, onBack])
}
