import { useState } from 'react'
import type { CharacterBlock, CharacterBlockType } from '@shared/types/models'

const TAG_OPEN_NAME = 'Open Tag'
const TAG_CLOSE_NAME = 'Close Tag'

const TYPE_LABELS: Record<CharacterBlockType, string> = {
  text: 'Text',
  folder: 'Folder',
  equipment: 'Equipment',
  image: 'Image',
}

const GRIP_ICON = (
  <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor">
    <circle cx="2" cy="2" r="1.3" />
    <circle cx="8" cy="2" r="1.3" />
    <circle cx="2" cy="7" r="1.3" />
    <circle cx="8" cy="7" r="1.3" />
    <circle cx="2" cy="12" r="1.3" />
    <circle cx="8" cy="12" r="1.3" />
  </svg>
)

function newId(): string {
  return (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).replace(/-/g, '').slice(0, 12)
}

function newBlock(type: 'text' | 'folder' | 'equipment', name: string): CharacterBlock {
  const base = { id: newId(), name, enabled: true }
  if (type === 'text') return { ...base, type, content: '' }
  if (type === 'folder') return { ...base, type, children: [] }
  return { ...base, type: 'equipment' }
}

/** Reorders `list` by moving the item at `from` to just before the item
 * currently at `to` (splice-based, so it reads as "drop before this row"
 * regardless of drag direction). */
function moveItemTo<T>(list: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list
  const next = list.slice()
  const [item] = next.splice(from, 1)
  next.splice(from < to ? to - 1 : to, 0, item)
  return next
}

/** Finds a block by id — root level or one level into a folder's children. */
export function findBlock(blocks: CharacterBlock[], id: string): CharacterBlock | undefined {
  for (const b of blocks) {
    if (b.id === id) return b
    if (b.type === 'folder') {
      const child = (b.children ?? []).find((c) => c.id === id)
      if (child) return child
    }
  }
  return undefined
}

/** Patches a block by id (root level or one level into a folder), returning
 * a new tree. Mirrors `findBlock`'s search depth. */
export function updateBlockInTree(blocks: CharacterBlock[], id: string, patch: Partial<CharacterBlock>): CharacterBlock[] {
  return blocks.map((b) => {
    if (b.id === id) return { ...b, ...patch }
    if (b.type === 'folder') {
      const children = (b.children ?? []).map((c) => (c.id === id ? { ...c, ...patch } : c))
      return { ...b, children }
    }
    return b
  })
}

// A drag position: which list it's in ('root', or the id of the containing
// folder block) and its index within that list.
interface DragPos {
  scope: 'root' | string
  index: number
}

/**
 * The TavernAI-style toggleable/orderable block-tree editor: a flat list of
 * blocks, folders nesting one level deep (no roles/depth/merge-groups — see
 * CLAUDE.md's Character system rebuild section). Rows are reordered by
 * dragging (native HTML5 DnD, one drag context per list — root and each
 * folder's children reorder independently). Clicking a text block ("prompt")
 * opens it full-screen in the Inspector via `onOpenBlock` — content is no
 * longer edited inline. `onChange`'s `immediate` flag mirrors the rest of the
 * sheet's fields: everything here (toggle/reorder/add/delete/rename) flushes
 * right away.
 */
export function BlockTreeEditor({
  blocks,
  onChange,
  onOpenBlock,
}: {
  blocks: CharacterBlock[]
  onChange: (blocks: CharacterBlock[], immediate?: boolean) => void
  onOpenBlock: (blockId: string) => void
}) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [addMenuFor, setAddMenuFor] = useState<'root' | string | null>(null)
  const [dragPos, setDragPos] = useState<DragPos | null>(null)
  const [overPos, setOverPos] = useState<DragPos | null>(null)

  const updateRoot = (next: CharacterBlock[], immediate = true) => {
    onChange(next, immediate)
  }

  const updateAt = (index: number, patch: Partial<CharacterBlock>, immediate = true) => {
    const next = blocks.slice()
    next[index] = { ...next[index], ...patch }
    updateRoot(next, immediate)
  }

  const updateChild = (parentIndex: number, childIndex: number, patch: Partial<CharacterBlock>, immediate = true) => {
    const parent = blocks[parentIndex]
    const children = (parent.children ?? []).slice()
    children[childIndex] = { ...children[childIndex], ...patch }
    updateAt(parentIndex, { children }, immediate)
  }

  const deleteRoot = (index: number) => {
    updateRoot(blocks.filter((_, i) => i !== index))
    setConfirmDeleteId(null)
  }

  const deleteChild = (parentIndex: number, childIndex: number) => {
    const parent = blocks[parentIndex]
    updateAt(parentIndex, { children: (parent.children ?? []).filter((_, i) => i !== childIndex) })
    setConfirmDeleteId(null)
  }

  const addRootBlock = (type: 'text' | 'folder' | 'equipment') => {
    const block = newBlock(type, type === 'folder' ? 'New Folder' : type === 'equipment' ? 'Equipment' : 'New Block')
    // Insert before a trailing Close Tag (if any) so new content stays wrapped
    // by the tags, same convention the server's upsert_legacy_field uses.
    const closeIndex = blocks.findIndex((b) => b.name === TAG_CLOSE_NAME)
    const next = closeIndex === -1 ? [...blocks, block] : [...blocks.slice(0, closeIndex), block, ...blocks.slice(closeIndex)]
    updateRoot(next)
    setAddMenuFor(null)
  }

  const addChildBlock = (parentIndex: number, type: 'text' | 'equipment') => {
    const parent = blocks[parentIndex]
    const children = [...(parent.children ?? []), newBlock(type, type === 'equipment' ? 'Equipment' : 'New Block')]
    updateAt(parentIndex, { children })
    setAddMenuFor(null)
  }

  const dragStart = (pos: DragPos) => setDragPos(pos)
  const dragOverRow = (pos: DragPos, e: React.DragEvent) => {
    e.preventDefault()
    if (!dragPos || dragPos.scope !== pos.scope) return
    if (overPos?.scope !== pos.scope || overPos.index !== pos.index) setOverPos(pos)
  }
  const dropRow = (e: React.DragEvent) => {
    e.preventDefault()
    if (dragPos && overPos && dragPos.scope === overPos.scope) {
      if (dragPos.scope === 'root') {
        updateRoot(moveItemTo(blocks, dragPos.index, overPos.index))
      } else {
        const parentIndex = blocks.findIndex((b) => b.id === dragPos.scope)
        if (parentIndex !== -1) {
          const parent = blocks[parentIndex]
          updateAt(parentIndex, { children: moveItemTo(parent.children ?? [], dragPos.index, overPos.index) })
        }
      }
    }
    setDragPos(null)
    setOverPos(null)
  }
  const dragEnd = () => {
    setDragPos(null)
    setOverPos(null)
  }

  return (
    <div className="space-y-1.5">
      {blocks.map((block, i) => (
        <BlockRow
          key={block.id}
          block={block}
          confirmingDelete={confirmDeleteId === block.id}
          onToggle={(enabled) => updateAt(i, { enabled })}
          onRename={(name) => updateAt(i, { name })}
          onRequestDelete={() => setConfirmDeleteId(block.id)}
          onConfirmDelete={() => deleteRoot(i)}
          onCancelDelete={() => setConfirmDeleteId(null)}
          addMenuOpen={addMenuFor === block.id}
          onToggleAddMenu={() => setAddMenuFor(addMenuFor === block.id ? null : block.id)}
          onAddChild={(type) => addChildBlock(i, type)}
          isDragging={dragPos?.scope === 'root' && dragPos.index === i}
          isDragOver={overPos?.scope === 'root' && overPos.index === i && !(dragPos?.scope === 'root' && dragPos.index === i)}
          onDragStart={() => dragStart({ scope: 'root', index: i })}
          onDragOverRow={(e) => dragOverRow({ scope: 'root', index: i }, e)}
          onDropRow={dropRow}
          onDragEndRow={dragEnd}
          onOpen={block.type === 'text' ? () => onOpenBlock(block.id) : undefined}
        >
          {block.type === 'folder' && (
            <div className="ml-5 mt-1.5 space-y-1.5 border-l border-line pl-3">
              {(block.children ?? []).map((child, ci) => (
                <BlockRow
                  key={child.id}
                  block={child}
                  confirmingDelete={confirmDeleteId === child.id}
                  onToggle={(enabled) => updateChild(i, ci, { enabled })}
                  onRename={(name) => updateChild(i, ci, { name })}
                  onRequestDelete={() => setConfirmDeleteId(child.id)}
                  onConfirmDelete={() => deleteChild(i, ci)}
                  onCancelDelete={() => setConfirmDeleteId(null)}
                  isDragging={dragPos?.scope === block.id && dragPos.index === ci}
                  isDragOver={overPos?.scope === block.id && overPos.index === ci && !(dragPos?.scope === block.id && dragPos.index === ci)}
                  onDragStart={() => dragStart({ scope: block.id, index: ci })}
                  onDragOverRow={(e) => dragOverRow({ scope: block.id, index: ci }, e)}
                  onDropRow={dropRow}
                  onDragEndRow={dragEnd}
                  onOpen={child.type === 'text' ? () => onOpenBlock(child.id) : undefined}
                />
              ))}
              {(block.children ?? []).length === 0 && (
                <p className="text-[11px] text-textdim italic font-body py-1">Empty folder</p>
              )}
            </div>
          )}
        </BlockRow>
      ))}

      <div className="relative pt-1">
        <button
          type="button"
          className="font-ui text-[10px] text-textsec border border-dashed border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
          onClick={() => setAddMenuFor(addMenuFor === 'root' ? null : 'root')}
        >
          + ADD BLOCK
        </button>
        {addMenuFor === 'root' && (
          <div className="absolute z-20 left-0 mt-0.5 border border-line bg-bg1 shadow-lg">
            <AddMenuOption label="Text" onClick={() => addRootBlock('text')} />
            <AddMenuOption label="Folder" onClick={() => addRootBlock('folder')} />
            <AddMenuOption label="Equipment" onClick={() => addRootBlock('equipment')} />
          </div>
        )}
      </div>
    </div>
  )
}

function AddMenuOption({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      className="block w-full text-left px-3 py-1.5 text-xs font-body text-text hover:bg-bg2 transition-colors"
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
    >
      {label}
    </button>
  )
}

function BlockRow({
  block,
  confirmingDelete,
  onToggle,
  onRename,
  onRequestDelete,
  onConfirmDelete,
  onCancelDelete,
  addMenuOpen,
  onToggleAddMenu,
  onAddChild,
  isDragging,
  isDragOver,
  onDragStart,
  onDragOverRow,
  onDropRow,
  onDragEndRow,
  onOpen,
  children,
}: {
  block: CharacterBlock
  confirmingDelete: boolean
  onToggle: (enabled: boolean) => void
  onRename: (name: string) => void
  onRequestDelete: () => void
  onConfirmDelete: () => void
  onCancelDelete: () => void
  addMenuOpen?: boolean
  onToggleAddMenu?: () => void
  onAddChild?: (type: 'text' | 'equipment') => void
  isDragging: boolean
  isDragOver: boolean
  onDragStart: () => void
  onDragOverRow: (e: React.DragEvent) => void
  onDropRow: (e: React.DragEvent) => void
  onDragEndRow: () => void
  onOpen?: () => void
  children?: React.ReactNode
}) {
  const isTag = block.name === TAG_OPEN_NAME || block.name === TAG_CLOSE_NAME
  const [expanded, setExpanded] = useState(true)
  const openable = !!onOpen

  return (
    <div
      className={`border bg-bg0/60 transition-colors ${!block.enabled ? 'opacity-50' : ''} ${
        isDragging ? 'opacity-30' : ''
      } ${isDragOver ? 'border-gold' : 'border-line'} ${openable ? 'cursor-pointer hover:bg-bg1/40' : ''}`}
      onDragOver={onDragOverRow}
      onDrop={onDropRow}
      onClick={openable ? onOpen : undefined}
      title={openable ? 'Click to edit this prompt' : undefined}
    >
      <div className="flex items-center gap-1.5 px-2 py-1.5">
        <span
          draggable
          onDragStart={(e) => { e.stopPropagation(); onDragStart() }}
          onDragEnd={(e) => { e.stopPropagation(); onDragEndRow() }}
          onClick={(e) => e.stopPropagation()}
          className="shrink-0 text-textdim hover:text-text cursor-grab active:cursor-grabbing px-0.5"
          title="Drag to reorder"
        >
          {GRIP_ICON}
        </span>

        <input
          type="checkbox"
          checked={block.enabled}
          onChange={(e) => onToggle(e.target.checked)}
          onClick={(e) => e.stopPropagation()}
          className="shrink-0 accent-gold"
          title={block.enabled ? 'Enabled — included in the prompt' : 'Disabled — skipped'}
        />

        {block.type === 'folder' && (
          <button
            type="button"
            className="text-textdim hover:text-text shrink-0 px-0.5"
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
            title={expanded ? 'Collapse' : 'Expand'}
          >
            <span className="text-[10px]">{expanded ? '▾' : '▸'}</span>
          </button>
        )}

        <input
          className="flex-1 min-w-0 bg-transparent text-sm font-body text-text outline-none border-b border-transparent focus:border-line2 px-1 py-0.5"
          value={block.name}
          onChange={(e) => onRename(e.target.value)}
          onClick={(e) => e.stopPropagation()}
        />

        <span className="shrink-0 font-ui text-[9px] tracking-wider text-textdim uppercase border border-line px-1.5 py-0.5">
          {TYPE_LABELS[block.type]}
        </span>

        {confirmingDelete ? (
          <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="font-ui text-[9px] text-danger border border-danger-border px-1.5 py-0.5 hover:bg-danger-bg"
              onClick={onConfirmDelete}
            >
              REMOVE
            </button>
            <button
              type="button"
              className="font-ui text-[9px] text-textdim border border-line px-1.5 py-0.5 hover:border-line2"
              onClick={onCancelDelete}
            >
              CANCEL
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="shrink-0 text-textdim hover:text-danger text-base font-ui leading-none px-1"
            title="Remove block"
            onClick={(e) => { e.stopPropagation(); onRequestDelete() }}
          >
            &times;
          </button>
        )}
      </div>

      {block.type === 'text' && !isTag && (
        <div className="px-2 pb-2 -mt-1">
          <p className="text-[11px] text-textdim font-body truncate">
            {(block.content ?? '').trim() || <span className="italic">Empty — click to write</span>}
          </p>
        </div>
      )}

      {block.type === 'equipment' && (
        <div className="px-2 pb-2">
          <p className="text-[11px] text-textdim italic font-body">
            Rendered live from equipped gear — see the Equipment section below.
          </p>
        </div>
      )}

      {block.type === 'image' && (
        <div className="px-2 pb-2">
          <p className="text-[11px] text-textdim italic font-body">
            {block.file || 'Reference image'} — uploading new image blocks isn't supported yet.
          </p>
        </div>
      )}

      {block.type === 'folder' && expanded && (
        <div className="px-2 pb-2" onClick={(e) => e.stopPropagation()}>
          {children}
          {onAddChild && (
            <div className="relative mt-1 ml-5">
              <button
                type="button"
                className="font-ui text-[9px] text-textsec border border-dashed border-line px-2 py-1 hover:border-line2 hover:text-text transition-colors"
                onClick={onToggleAddMenu}
              >
                + ADD INSIDE
              </button>
              {addMenuOpen && (
                <div className="absolute z-20 left-0 mt-0.5 border border-line bg-bg1 shadow-lg">
                  <AddMenuOption label="Text" onClick={() => onAddChild('text')} />
                  <AddMenuOption label="Equipment" onClick={() => onAddChild('equipment')} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** Read-only rendering for Play mode — enabled blocks only, folders recursed,
 * tags/equipment/image skipped (Equipment already has its own sheet section). */
export function BlockTreeView({ blocks }: { blocks: CharacterBlock[] }) {
  const rows: { label: string; content: string }[] = []
  const walk = (items: CharacterBlock[]) => {
    for (const b of items) {
      if (!b.enabled) continue
      if (b.type === 'folder') {
        walk(b.children ?? [])
      } else if (b.type === 'text') {
        const content = (b.content ?? '').trim()
        if (!content || b.name === TAG_OPEN_NAME || b.name === TAG_CLOSE_NAME) continue
        rows.push({ label: b.name, content })
      }
    }
  }
  walk(blocks)

  if (rows.length === 0) {
    return <p className="text-sm text-textdim italic font-body">Nothing written yet.</p>
  }

  return (
    <div className="space-y-3">
      {rows.map((r, i) =>
        r.label === 'Description' ? (
          <p key={i} className="font-body text-sm text-text2 leading-relaxed">{r.content}</p>
        ) : (
          <div key={i}>
            <span className="text-[11px] text-textdim font-body block mb-0.5">{r.label}</span>
            <p className="font-body text-sm text-text2 leading-relaxed">{r.content}</p>
          </div>
        )
      )}
    </div>
  )
}
