// The Tools → View Prompt Log modal — the last assembled LLM prompt.

import { useEffect } from 'react'

export interface PromptLogMessage {
  role: string
  content: string
}

export function PromptLogModal({ messages, onClose }: { messages: PromptLogMessage[]; onClose: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg0/80">
      <div className="bg-bg1 border border-line2 rounded-lg w-[720px] max-w-[90vw] max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-line2">
          <h2 className="font-ui text-[11px] tracking-wider">PROMPT LOG</h2>
          <button
            type="button"
            className="font-ui text-[10px] text-textdim hover:text-text"
            onClick={onClose}
          >
            CLOSE
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {messages.map((m, i) => (
            <div key={i} className="space-y-1">
              <span className="font-ui text-[9px] tracking-wider text-textsec uppercase">
                {m.role}
              </span>
              <pre className="text-[12px] font-body text-text leading-relaxed whitespace-pre-wrap bg-bg0 border border-line p-3 overflow-x-auto">
                {m.content}
              </pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
