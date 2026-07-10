import { Component, type ReactNode } from 'react'

// Last-resort guard: a render crash anywhere used to unmount the whole tree to
// a blank page (the "UI goes empty until refresh" failure). Show a themed
// recovery screen instead.
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error('Wayward crashed while rendering:', error)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 bg-bg0 px-6 text-center">
        <span className="font-disp text-[22px] text-gold pt-[3px]">Something went astray</span>
        <span className="max-w-md font-body text-sm text-textsec">
          The interface hit an unexpected error. Your adventure is saved — reloading will pick up right where you left off.
        </span>
        <button
          type="button"
          className="font-ui text-[11px] tracking-wider bg-golddeep text-bg0 px-4 py-2 hover:bg-gold transition-colors"
          onClick={() => window.location.reload()}
        >
          RELOAD
        </button>
      </div>
    )
  }
}
