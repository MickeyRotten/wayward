import { useState } from 'react'
import type { CharacterBlock, CharacterBlockType, Equipment } from '@shared/types/models'
import { SelectionBar, LockGlyph } from '../SelectionBar'
import { EquipmentGrid } from './EquipmentGrid'

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

// A drag/drop position: which list it's in ('root', or the id of the
// containing folder block) and its index within that list.
interface DragPos {
  scope: 'root' | string
  index: number
}

/** Removes the block at `pos` from the tree, returning it plus the tree
 * without it (source list re-indexed). */
function removeBlockAt(blocks: CharacterBlock[], pos: DragPos): { block: CharacterBlock; next: CharacterBlock[] } {
  if (pos.scope === 'root') {
    const block = blocks[pos.index]
    return { block, next: blocks.filter((_, i) => i !== pos.index) }
  }
  const parentIndex = blocks.findIndex((b) => b.id === pos.scope)
  const parent = blocks[parentIndex]
  const children = parent.children ?? []
  const block = children[pos.index]
  const nextChildren = children.filter((_, i) => i !== pos.index)
  return { block, next: blocks.map((b, i) => (i === parentIndex ? { ...b, children: nextChildren } : b)) }
}

/** Inserts `block` into the tree at `pos` (a list already NOT containing it —
 * see removeBlockAt), before the item currently at that index. */
function insertBlockAt(blocks: CharacterBlock[], pos: DragPos, block: CharacterBlock): CharacterBlock[] {
  if (pos.scope === 'root') {
    const next = blocks.slice()
    next.splice(pos.index, 0, block)
    return next
  }
  const parentIndex = blocks.findIndex((b) => b.id === pos.scope)
  if (parentIndex === -1) return blocks
  const parent = blocks[parentIndex]
  const children = (parent.children ?? []).slice()
  children.splice(pos.index, 0, block)
  return blocks.map((b, i) => (i === parentIndex ? { ...b, children } : b))
}

function appendToFolder(blocks: CharacterBlock[], folderId: string, block: CharacterBlock): CharacterBlock[] {
  return blocks.map((b) => (b.id === folderId ? { ...b, children: [...(b.children ?? []), block] } : b))
}

/**
 * The TavernAI-style toggleable/orderable block-tree editor: a flat list of
 * blocks, folders nesting one level deep (no roles/depth/merge-groups — see
 * CLAUDE.md's Character system rebuild section). Rows are reordered by
 * dragging (native HTML5 DnD, no library). Dropping a row BETWEEN others
 * reorders at that layer; dropping it ON TOP of a root Folder row nests it
 * inside that folder (only folders accept nest-drops — a folder itself can
 * never be dropped into another folder, since nesting is one level deep).
 * A `locked` block (Open Tag/Close Tag/Equipment) can't be dragged, deleted,
 * or disabled — its content can still be edited full-screen.
 *
 * Nothing else on a row is directly editable — clicking it opens the block
 * full-screen in the Inspector via `onOpenBlock`, where its name, enabled
 * state, and (for text/equipment blocks) content are all edited. `onChange`'s
 * `immediate` flag mirrors the rest of the sheet's fields: toggle/reorder/
 * add/delete flush right away.
 */
export function BlockTreeEditor({
  blocks,
  onChange,
  onOpenBlock,
  openBlockId,
}: {
  blocks: CharacterBlock[]
  onChange: (blocks: CharacterBlock[], immediate?: boolean) => void
  onOpenBlock: (blockId: string) => void
  openBlockId?: string
}) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [addMenuFor, setAddMenuFor] = useState<'root' | string | null>(null)
  const [dragPos, setDragPos] = useState<DragPos | null>(null)
  const [draggingBlock, setDraggingBlock] = useState<CharacterBlock | null>(null)
  const [overPos, setOverPos] = useState<DragPos | null>(null)
  const [overNestFolderId, setOverNestFolderId] = useState<string | null>(null)

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

  const clearDragState = () => {
    setDragPos(null)
    setDraggingBlock(null)
    setOverPos(null)
    setOverNestFolderId(null)
  }

  const dragStart = (pos: DragPos, block: CharacterBlock) => {
    if (block.locked) return
    setDragPos(pos)
    setDraggingBlock(block)
  }

  // Root rows: a Folder row splits into a nest-band (middle) vs reorder
  // (edges); any other root row is a plain reorder target.
  const rootDragOver = (block: CharacterBlock, index: number, e: React.DragEvent) => {
    e.preventDefault()
    if (!dragPos || !draggingBlock || block.id === draggingBlock.id) return
    if (block.type === 'folder' && draggingBlock.type !== 'folder') {
      const rect = e.currentTarget.getBoundingClientRect()
      const frac = (e.clientY - rect.top) / rect.height
      if (frac > 0.25 && frac < 0.75) {
        if (overNestFolderId !== block.id) setOverNestFolderId(block.id)
        if (overPos) setOverPos(null)
        return
      }
    }
    if (overNestFolderId) setOverNestFolderId(null)
    if (overPos?.scope !== 'root' || overPos.index !== index) setOverPos({ scope: 'root', index })
  }

  // A folder's children are always plain (non-folder) blocks, so child rows
  // are always reorder targets — but a dragged Folder can never land inside
  // one (folders nest one level deep, never within each other).
  const childDragOver = (folderId: string, index: number, e: React.DragEvent) => {
    e.preventDefault()
    if (!dragPos || !draggingBlock || draggingBlock.type === 'folder') return
    if (overNestFolderId) setOverNestFolderId(null)
    if (overPos?.scope !== folderId || overPos.index !== index) setOverPos({ scope: folderId, index })
  }

  const moveBlockToPosition = (from: DragPos, to: DragPos) => {
    if (from.scope === to.scope) {
      if (to.scope === 'root') {
        updateRoot(moveItemTo(blocks, from.index, to.index))
      } else {
        const parentIndex = blocks.findIndex((b) => b.id === to.scope)
        if (parentIndex !== -1) {
          const parent = blocks[parentIndex]
          updateAt(parentIndex, { children: moveItemTo(parent.children ?? [], from.index, to.index) })
        }
      }
      return
    }
    // Cross-scope move (e.g. root ↔ a folder's children, or folder ↔ folder).
    const { block, next } = removeBlockAt(blocks, from)
    if (block.locked || block.type === 'folder') return
    updateRoot(insertBlockAt(next, to, block))
  }

  const moveBlockToFolder = (from: DragPos, folderId: string) => {
    const { block, next } = removeBlockAt(blocks, from)
    if (block.locked || block.type === 'folder') return
    updateRoot(appendToFolder(next, folderId, block))
  }

  const dropRow = (e: React.DragEvent) => {
    e.preventDefault()
    if (dragPos) {
      if (overNestFolderId) {
        moveBlockToFolder(dragPos, overNestFolderId)
      } else if (overPos) {
        moveBlockToPosition(dragPos, overPos)
      }
    }
    clearDragState()
  }

  return (
    <div className="space-y-1.5">
      {blocks.map((block, i) => (
        <BlockRow
          key={block.id}
          block={block}
          isOpen={openBlockId === block.id}
          confirmingDelete={confirmDeleteId === block.id}
          onToggle={(enabled) => updateAt(i, { enabled })}
          onRequestDelete={() => setConfirmDeleteId(block.id)}
          onConfirmDelete={() => deleteRoot(i)}
          onCancelDelete={() => setConfirmDeleteId(null)}
          addMenuOpen={addMenuFor === block.id}
          onToggleAddMenu={() => setAddMenuFor(addMenuFor === block.id ? null : block.id)}
          onAddChild={(type) => addChildBlock(i, type)}
          isDragging={dragPos?.scope === 'root' && dragPos.index === i}
          isDragOver={overPos?.scope === 'root' && overPos.index === i}
          isNestTarget={overNestFolderId === block.id}
          onDragStart={() => dragStart({ scope: 'root', index: i }, block)}
          onDragOverRow={(e) => rootDragOver(block, i, e)}
          onDropRow={dropRow}
          onDragEndRow={clearDragState}
          onOpen={() => onOpenBlock(block.id)}
        >
          {block.type === 'folder' && (
            <div className="ml-5 mt-1.5 space-y-1.5 border-l border-line pl-3">
              {(block.children ?? []).map((child, ci) => (
                <BlockRow
                  key={child.id}
                  block={child}
                  isOpen={openBlockId === child.id}
                  confirmingDelete={confirmDeleteId === child.id}
                  onToggle={(enabled) => updateChild(i, ci, { enabled })}
                  onRequestDelete={() => setConfirmDeleteId(child.id)}
                  onConfirmDelete={() => deleteChild(i, ci)}
                  onCancelDelete={() => setConfirmDeleteId(null)}
                  isDragging={dragPos?.scope === block.id && dragPos.index === ci}
                  isDragOver={overPos?.scope === block.id && overPos.index === ci}
                  isNestTarget={false}
                  onDragStart={() => dragStart({ scope: block.id, index: ci }, child)}
                  onDragOverRow={(e) => childDragOver(block.id, ci, e)}
                  onDropRow={dropRow}
                  onDragEndRow={clearDragState}
                  onOpen={() => onOpenBlock(child.id)}
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
  isOpen,
  confirmingDelete,
  onToggle,
  onRequestDelete,
  onConfirmDelete,
  onCancelDelete,
  addMenuOpen,
  onToggleAddMenu,
  onAddChild,
  isDragging,
  isDragOver,
  isNestTarget,
  onDragStart,
  onDragOverRow,
  onDropRow,
  onDragEndRow,
  onOpen,
  children,
}: {
  block: CharacterBlock
  isOpen: boolean
  confirmingDelete: boolean
  onToggle: (enabled: boolean) => void
  onRequestDelete: () => void
  onConfirmDelete: () => void
  onCancelDelete: () => void
  addMenuOpen?: boolean
  onToggleAddMenu?: () => void
  onAddChild?: (type: 'text' | 'equipment') => void
  isDragging: boolean
  isDragOver: boolean
  isNestTarget: boolean
  onDragStart: () => void
  onDragOverRow: (e: React.DragEvent) => void
  onDropRow: (e: React.DragEvent) => void
  onDragEndRow: () => void
  onOpen: () => void
  children?: React.ReactNode
}) {
  const [expanded, setExpanded] = useState(true)
  const locked = !!block.locked

  const base = `group relative border rounded-md overflow-hidden transition-colors cursor-pointer ${
    isOpen ? 'border-line bg-bg3' : 'border-line bg-bg2 hover:border-line2'
  } ${locked ? 'border-gold/30 bg-gold/5' : ''} ${!block.enabled ? 'opacity-60' : ''} ${
    isDragging ? 'opacity-30' : ''
  } ${isDragOver ? 'ring-1 ring-inset ring-gold' : ''} ${isNestTarget ? 'ring-2 ring-inset ring-gold bg-gold/10' : ''}`

  return (
    <div
      className={base}
      onClick={onOpen}
      title="Click to open"
    >
      <SelectionBar show={isOpen} />
      <div
        className="flex items-center gap-1.5 pl-3 pr-2 py-1.5"
        // Drag/drop lives on the header strip specifically, not the whole
        // card — an expanded folder's body (children, "+ ADD INSIDE") is
        // much taller than its header, and the nest-vs-reorder Y-band in
        // rootDragOver() needs the header's own height to mean anything.
        // stopPropagation keeps a nested child row's drag events from
        // bubbling up into its parent Folder row's handlers.
        onDragOver={(e) => { e.stopPropagation(); onDragOverRow(e) }}
        onDrop={(e) => { e.stopPropagation(); onDropRow(e) }}
      >
        <span
          draggable={!locked}
          onDragStart={(e) => { e.stopPropagation(); onDragStart() }}
          onDragEnd={(e) => { e.stopPropagation(); onDragEndRow() }}
          onClick={(e) => e.stopPropagation()}
          className={`shrink-0 px-0.5 ${
            locked ? 'text-textdim/40 cursor-not-allowed' : 'text-textdim hover:text-text cursor-grab active:cursor-grabbing'
          }`}
          title={locked ? 'Locked — cannot be moved' : 'Drag to reorder'}
        >
          {GRIP_ICON}
        </span>

        {locked ? (
          <LockGlyph />
        ) : (
          <input
            type="checkbox"
            checked={block.enabled}
            onChange={(e) => onToggle(e.target.checked)}
            onClick={(e) => e.stopPropagation()}
            className="shrink-0 accent-gold"
            title={block.enabled ? 'Enabled — included in the prompt' : 'Disabled — skipped'}
          />
        )}

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

        <span className="flex-1 min-w-0 truncate text-sm font-body text-text px-1 py-0.5">
          {block.name}
        </span>

        <span className="shrink-0 font-ui text-[9px] tracking-wider text-textdim uppercase border border-line px-1.5 py-0.5">
          {TYPE_LABELS[block.type]}
        </span>

        {!locked && (
          confirmingDelete ? (
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
          )
        )}
      </div>

      {block.type === 'equipment' && (
        <div className="px-3 pb-2">
          <p className="text-[11px] text-textdim italic font-body">
            Rendered live from equipped gear — open to manage what's worn.
          </p>
        </div>
      )}

      {block.type === 'image' && (
        <div className="px-3 pb-2">
          <p className="text-[11px] text-textdim italic font-body">
            {block.file || 'Reference image'} — uploading new image blocks isn't supported yet.
          </p>
        </div>
      )}

      {block.type === 'folder' && expanded && (
        <div className="px-3 pb-2" onClick={(e) => e.stopPropagation()}>
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

/** Read-only rendering for Play mode — enabled blocks only, folders recursed
 * (flattened, not visually nested), tags skipped. The Equipment block is the
 * one thing that stays interactive here (equipment is a play action, not
 * world-editing) — it renders the real slot grid in place. */
export function BlockTreeView({ blocks, equipment, onEquipChange }: {
  blocks: CharacterBlock[]
  equipment: Equipment
  onEquipChange: (slotKey: keyof Equipment, instanceId: string | null) => void
}) {
  type Row = { kind: 'text'; label: string; content: string } | { kind: 'equipment' }
  const rows: Row[] = []
  const walk = (items: CharacterBlock[]) => {
    for (const b of items) {
      if (!b.enabled) continue
      if (b.type === 'folder') {
        walk(b.children ?? [])
      } else if (b.type === 'text') {
        const content = (b.content ?? '').trim()
        if (!content || b.name === TAG_OPEN_NAME || b.name === TAG_CLOSE_NAME) continue
        rows.push({ kind: 'text', label: b.name, content })
      } else if (b.type === 'equipment') {
        rows.push({ kind: 'equipment' })
      }
    }
  }
  walk(blocks)

  if (rows.length === 0) {
    return <p className="text-sm text-textdim italic font-body">Nothing written yet.</p>
  }

  return (
    <div className="space-y-3">
      {rows.map((r, i) => {
        if (r.kind === 'equipment') {
          return (
            <div key={i}>
              <span className="text-[11px] text-textdim font-body block mb-1.5">Equipment</span>
              <EquipmentGrid equipment={equipment} onChange={onEquipChange} />
            </div>
          )
        }
        return r.label === 'Description' ? (
          <p key={i} className="font-body text-sm text-text2 leading-relaxed">{r.content}</p>
        ) : (
          <div key={i}>
            <span className="text-[11px] text-textdim font-body block mb-0.5">{r.label}</span>
            <p className="font-body text-sm text-text2 leading-relaxed">{r.content}</p>
          </div>
        )
      })}
    </div>
  )
}
