import { useState } from 'react'
import { useWishlistStore } from '../../state/wishlistStore'
import type { Wish, WishPriority } from '@shared/types/models'

const PRIORITY_META: Record<WishPriority, { label: string; cls: string }> = {
  0: { label: '—', cls: 'text-textdim border-line' },
  1: { label: 'LOW', cls: 'text-textsec border-line' },
  2: { label: 'MED', cls: 'text-gold border-gold/40' },
  3: { label: 'HIGH', cls: 'text-gold2 border-gold/60' },
}

const PRIORITY_CYCLE: WishPriority[] = [0, 1, 2, 3]

/** The player's Wishlist — things they hope to see happen. Player-authored only
 *  (the agents never touch it); the Narrator keeps these in mind. */
export function WishlistSection() {
  const wishes = useWishlistStore((s) => s.wishes)

  return (
    <div className="mt-4">
      <div className="flex items-center gap-2 px-3 pb-1">
        <span className="font-ui text-[9px] text-textsec tracking-wider">WISHLIST</span>
        <div className="flex-1 border-t border-line" />
      </div>
      <p className="text-[10px] text-textdim font-body px-3 pb-1.5">
        Things you'd like to see — the Narrator weaves them in when it fits.
      </p>

      {wishes.length === 0 && (
        <p className="text-[11px] text-textdim font-body px-4 py-1.5">No wishes yet.</p>
      )}

      <div className="space-y-1">
        {wishes.map((w) => (
          <WishRow key={w.id} wish={w} />
        ))}
      </div>

      <NewWishInput />
    </div>
  )
}

function WishRow({ wish }: { wish: Wish }) {
  const updateWish = useWishlistStore((s) => s.updateWish)
  const deleteWish = useWishlistStore((s) => s.deleteWish)
  const [text, setText] = useState(wish.text)
  const [editing, setEditing] = useState(false)

  const meta = PRIORITY_META[wish.priority]

  const cyclePriority = () => {
    const next = PRIORITY_CYCLE[(PRIORITY_CYCLE.indexOf(wish.priority) + 1) % PRIORITY_CYCLE.length]
    void updateWish(wish.id, { priority: next })
  }

  const commit = () => {
    setEditing(false)
    const t = text.trim()
    if (t && t !== wish.text) void updateWish(wish.id, { text: t })
    else setText(wish.text)
  }

  return (
    <div className="group flex items-center gap-2 px-3 py-1.5 border border-transparent hover:bg-bg2 rounded-md">
      <button
        type="button"
        className={`shrink-0 font-ui text-[8px] tracking-wider border rounded px-1.5 py-0.5 w-11 text-center transition-colors ${meta.cls}`}
        onClick={cyclePriority}
        title="Cycle priority"
      >
        {meta.label}
      </button>
      {editing ? (
        <input
          autoFocus
          className="flex-1 min-w-0 border border-line bg-bg0 px-2 py-1 text-[13px] font-body text-text outline-none focus:border-line2"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); commit() }
            if (e.key === 'Escape') { setText(wish.text); setEditing(false) }
          }}
        />
      ) : (
        <button
          type="button"
          className="flex-1 min-w-0 text-left font-body text-[13px] text-text2 truncate"
          onClick={() => setEditing(true)}
        >
          {wish.text || 'Untitled wish'}
        </button>
      )}
      <button
        type="button"
        className="shrink-0 font-ui text-[11px] text-textdim opacity-0 group-hover:opacity-100 hover:text-danger transition-all"
        onClick={() => void deleteWish(wish.id)}
        title="Remove wish"
        aria-label="Remove wish"
      >
        ✕
      </button>
    </div>
  )
}

function NewWishInput() {
  const [text, setText] = useState('')
  const createWish = useWishlistStore((s) => s.createWish)

  const submit = async () => {
    const t = text.trim()
    if (!t) return
    await createWish(t)
    setText('')
  }

  return (
    <div className="px-2 pt-2">
      <input
        className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
        placeholder="I hope to... (Enter)"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            void submit()
          }
        }}
      />
    </div>
  )
}
