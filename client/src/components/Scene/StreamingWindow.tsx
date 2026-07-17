// Sole subscriber to the per-chunk streaming state (streamingContent, tool
// status, thinking timer). SSE chunks arrive many times per second; keeping
// those subscriptions out of ChatScene means each chunk re-renders only this
// node instead of the entire message history.

import { useEffect, useMemo } from 'react'
import { useChatStore } from '../../state/chatStore'
import { parseSegments, type Segment, type MemberLite } from '../../lib/narration'
import { SegmentedNarration, type ChipEntity } from './Narration'
import { EditorActionsFeed } from './EditorActionsFeed'
import { Elapsed, ThinkingIndicator } from './Indicators'

export function StreamingWindow({
  planningMode,
  memberResolver,
  chipEntities,
  listRef,
  atBottom,
}: {
  planningMode: boolean
  memberResolver: Map<string, MemberLite>
  chipEntities: ChipEntity[]
  listRef: React.RefObject<HTMLDivElement | null>
  atBottom: boolean
}) {
  const isLoading = useChatStore((s) => s.isLoading)
  const streamingContent = useChatStore((s) => s.streamingContent)
  const thinkingStartedAt = useChatStore((s) => s.thinkingStartedAt)
  const toolStatus = useChatStore((s) => s.toolStatus)
  const isSummarizing = useChatStore((s) => s.isSummarizing)
  const reasoningChars = useChatStore((s) => s.reasoningChars)
  const editorActions = useChatStore((s) => s.editorActions)

  // Follow the stream while the user is pinned to the bottom (rAF-batched so
  // we never force a sync reflow per chunk).
  useEffect(() => {
    if (!atBottom || !streamingContent || !listRef.current) return
    const el = listRef.current
    const raf = requestAnimationFrame(() => { el.scrollTop = el.scrollHeight })
    return () => cancelAnimationFrame(raf)
  }, [streamingContent, atBottom, listRef])

  // Inline suggestions mode: the narration ends with a machine-read
  // <<<OPTIONS>>> block — never show it (or a partial prefix of the marker
  // mid-chunk) while streaming; the server strips it before persisting.
  const displayContent = useMemo(() => {
    const idx = streamingContent.indexOf('<<<')
    return idx === -1 ? streamingContent : streamingContent.slice(0, idx)
  }, [streamingContent])

  const segments = useMemo<Segment[]>(
    () =>
      planningMode
        ? [{ type: 'narration', text: displayContent }]
        : parseSegments(displayContent, memberResolver),
    [planningMode, displayContent, memberResolver],
  )

  if (!isLoading) return null

  // The Editor's live action feed — prints each create/edit/delete as it
  // happens during a planning turn, above whatever else is showing.
  const liveFeed = planningMode && editorActions.length > 0
    ? <EditorActionsFeed actions={editorActions} live /> : null

  // Streaming response — routed through the segmenter so dialogue boxes,
  // dividers, etc. form live as text streams.
  if (streamingContent) {
    return (
      <div className="max-w-[85%] max-lg:max-w-full mr-auto px-4 py-3">
        {liveFeed && <div className="mb-2">{liveFeed}</div>}
        <SegmentedNarration segments={segments} chipEntities={chipEntities} />
      </div>
    )
  }

  // Generating indicator — narrator/planner avatar with animated dots.
  return (
    <div className="mr-auto max-w-[85%] max-lg:max-w-full">
      {liveFeed && <div className="px-4 pt-1">{liveFeed}</div>}
      <div className="flex items-start gap-3 px-1 py-3">
        <div className="w-10 h-10 rounded-sm border border-gold bg-bg2 flex items-center justify-center flex-shrink-0">
          <span className="font-disp text-[16px] text-gold pt-[2px]">{planningMode ? 'P' : 'N'}</span>
        </div>
        <div className="pt-2">
          {reasoningChars > 0 ? (
            // A reasoning model's thinking phase — show live progress instead
            // of a silent stall (~6 chars per word is close enough).
            <span className="font-ui text-[10px] text-gold/80 tracking-wider">
              REASONING · ~{Math.max(1, Math.round(reasoningChars / 6))} WORDS
              <Elapsed startedAt={thinkingStartedAt} /><span className="animate-pulse"> ···</span>
            </span>
          ) : toolStatus ? (
            <span className="font-ui text-[10px] text-gold/80 tracking-wider">
              {toolStatus.toUpperCase()}<Elapsed startedAt={thinkingStartedAt} /><span className="animate-pulse"> ···</span>
            </span>
          ) : planningMode ? (
            <span className="font-ui text-[10px] text-textdim tracking-wider">
              THE EDITOR IS WORKING<Elapsed startedAt={thinkingStartedAt} /><span className="animate-pulse"> ···</span>
            </span>
          ) : (
            <ThinkingIndicator startedAt={thinkingStartedAt} isSummarizing={isSummarizing} />
          )}
        </div>
      </div>
    </div>
  )
}
