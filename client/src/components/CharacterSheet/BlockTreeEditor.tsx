import { useRef, useState } from 'react'
import type { CharacterBlock, CharacterBlockType } from '@shared/types/models'
import { SelectionBar, LockGlyph } from '../SelectionBar'

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

function newBlock(type: 'text' | 'folder', name: string): CharacterBlock {
  const base = { id: newId(), name, enabled: true }
  if (type === 'text') return { ...base, type, content: '' }
  return { ...base, type, children: [] }
}

/** Deep-clones a block for "Duplicate" — a fresh id (and fresh ids for a
 * folder's children, one level deep), name suffixed " (Copy)". */
function cloneBlock(block: CharacterBlock): CharacterBlock {
  const clone: CharacterBlock = { ...block, id: newId(), name: `${block.name} (Copy)` }
  if (block.type === 'folder') clone.children = (block.children ?? []).map((c) => ({ ...c, id: newId() }))
  return clone
}

/** Char/4 heuristic — mirrors the server's estimate_prompt_tokens
 * (prompt_builder.py). Text blocks count their own content; a folder sums
 * its children. Equipment/Image have no static content to estimate. */
function estimateBlockTokens(block: CharacterBlock): number {
  if (block.type === 'text') return Math.ceil((block.content ?? '').length / 4)
  if (block.type === 'folder') return (block.children ?? []).reduce((sum, c) => sum + estimateBlockTokens(c), 0)
  return 0
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
 * A `locked` block (Open Tag/Close Tag/Equipment) can't be dragged, renamed,
 * duplicated, deleted, or disabled — its content can still be edited
 * full-screen (text blocks only).
 *
 * Nothing else on a row is directly editable except via the row's •••
 * menu (Rename/Duplicate/Remove) and the enabled toggle — clicking the row
 * itself opens it full-screen in the Inspector via `onOpenBlock`, where a
 * text block's content is edited. Clicking the Equipment row instead calls
 * `onOpenEquipment` — Equipment now lives in its own tab, not inline here.
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
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
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

  const renameRoot = (index: number, name: string) => {
    const trimmed = name.trim()
    if (trimmed) updateAt(index, { name: trimmed })
    setRenamingId(null)
  }

  const renameChild = (parentIndex: number, childIndex: number, name: string) => {
    const trimmed = name.trim()
    if (trimmed) updateChild(parentIndex, childIndex, { name: trimmed })
    setRenamingId(null)
  }

  const duplicateRoot = (index: number) => {
    const copy = cloneBlock(blocks[index])
    const next = blocks.slice()
    next.splice(index + 1, 0, copy)
    updateRoot(next)
    setMenuOpenId(null)
  }

  const duplicateChild = (parentIndex: number, childIndex: number) => {
    const parent = blocks[parentIndex]
    const children = (parent.children ?? []).slice()
    const copy = cloneBlock(children[childIndex])
    children.splice(childIndex + 1, 0, copy)
    updateAt(parentIndex, { children })
    setMenuOpenId(null)
  }

  const addRootBlock = (type: 'text' | 'folder') => {
    const block = newBlock(type, type === 'folder' ? 'New Folder' : 'New Block')
    // Insert before a trailing Close Tag (if any) so new content stays wrapped
    // by the tags, same convention the server's upsert_legacy_field uses.
    const closeIndex = blocks.findIndex((b) => b.name === TAG_CLOSE_NAME)
    const next = closeIndex === -1 ? [...blocks, block] : [...blocks.slice(0, closeIndex), block, ...blocks.slice(closeIndex)]
    updateRoot(next)
  }

  const addChildBlock = (parentIndex: number) => {
    const parent = blocks[parentIndex]
    const children = [...(parent.children ?? []), newBlock('text', 'New Block')]
    updateAt(parentIndex, { children })
  }

  const clearDragState = () => {
    setDragPos(null)
    setDraggingBlock(null)
    setOverPos(null)
    setOverNestFolderId(null)
  }

  // Locked normally means "can't move, delete, or disable" (Open/Close Tag
  // are fixed delimiters), but Equipment — locked for the same
  // can't-delete/can't-disable reasons — is still just a block among
  // others, so it stays reorderable.
  const dragStart = (pos: DragPos, block: CharacterBlock) => {
    if (block.locked && block.type !== 'equipment') return
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

  // Equipment isn't opened from here — it's managed in its own tab, and
  // jumping tabs on a click read as disorienting. Only text/folder blocks
  // open the full-screen content editor.
  const openRow = (block: CharacterBlock) => {
    if (block.type !== 'equipment') onOpenBlock(block.id)
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
          onRequestDelete={() => { setConfirmDeleteId(block.id); setMenuOpenId(null) }}
          onConfirmDelete={() => deleteRoot(i)}
          onCancelDelete={() => setConfirmDeleteId(null)}
          menuOpen={menuOpenId === block.id}
          onToggleMenu={() => setMenuOpenId(menuOpenId === block.id ? null : block.id)}
          onRename={() => { setRenamingId(block.id); setMenuOpenId(null) }}
          onDuplicate={() => duplicateRoot(i)}
          renaming={renamingId === block.id}
          onCommitRename={(name) => renameRoot(i, name)}
          onCancelRename={() => setRenamingId(null)}
          addChildEnabled
          onAddChild={() => addChildBlock(i)}
          isDragging={dragPos?.scope === 'root' && dragPos.index === i}
          isDragOver={overPos?.scope === 'root' && overPos.index === i}
          isNestTarget={overNestFolderId === block.id}
          onDragStart={() => dragStart({ scope: 'root', index: i }, block)}
          onDragOverRow={(e) => rootDragOver(block, i, e)}
          onDropRow={dropRow}
          onDragEndRow={clearDragState}
          onOpen={() => openRow(block)}
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
                  onRequestDelete={() => { setConfirmDeleteId(child.id); setMenuOpenId(null) }}
                  onConfirmDelete={() => deleteChild(i, ci)}
                  onCancelDelete={() => setConfirmDeleteId(null)}
                  menuOpen={menuOpenId === child.id}
                  onToggleMenu={() => setMenuOpenId(menuOpenId === child.id ? null : child.id)}
                  onRename={() => { setRenamingId(child.id); setMenuOpenId(null) }}
                  onDuplicate={() => duplicateChild(i, ci)}
                  renaming={renamingId === child.id}
                  onCommitRename={(name) => renameChild(i, ci, name)}
                  onCancelRename={() => setRenamingId(null)}
                  isDragging={dragPos?.scope === block.id && dragPos.index === ci}
                  isDragOver={overPos?.scope === block.id && overPos.index === ci}
                  isNestTarget={false}
                  onDragStart={() => dragStart({ scope: block.id, index: ci }, child)}
                  onDragOverRow={(e) => childDragOver(block.id, ci, e)}
                  onDropRow={dropRow}
                  onDragEndRow={clearDragState}
                  onOpen={() => openRow(child)}
                />
              ))}
              {(block.children ?? []).length === 0 && (
                <p className="text-[11px] text-textdim italic font-body py-1">Empty folder</p>
              )}
            </div>
          )}
        </BlockRow>
      ))}

      <div className="flex gap-2 pt-1">
        <button
          type="button"
          className="font-ui text-[10px] text-textsec border border-dashed border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
          onClick={() => addRootBlock('text')}
        >
          + CREATE BLOCK
        </button>
        <button
          type="button"
          className="font-ui text-[10px] text-textsec border border-dashed border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
          onClick={() => addRootBlock('folder')}
        >
          + CREATE FOLDER
        </button>
      </div>
    </div>
  )
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={(e) => { e.stopPropagation(); onChange(!checked) }}
      className={`shrink-0 relative w-7 h-4 rounded-full transition-colors ${checked ? 'bg-gold' : 'bg-bg3 border border-line'}`}
      title={checked ? 'Enabled — included in the prompt' : 'Disabled — skipped'}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-bg0 transition-transform ${checked ? 'translate-x-3' : 'translate-x-0'}`}
      />
    </button>
  )
}

/** An in-row rename input — an internal cancelled-flag guards against the
 * blur-triggered commit firing after Escape (blur still fires when a
 * focused element unmounts). */
function RenameInput({ initial, onCommit, onCancel }: {
  initial: string
  onCommit: (name: string) => void
  onCancel: () => void
}) {
  const cancelled = useRef(false)
  return (
    <input
      autoFocus
      defaultValue={initial}
      className="flex-1 min-w-0 text-sm font-body text-text bg-bg0 border border-line2 px-1.5 py-0.5 outline-none"
      onClick={(e) => e.stopPropagation()}
      onFocus={(e) => e.currentTarget.select()}
      onBlur={(e) => { if (!cancelled.current) onCommit(e.target.value) }}
      onKeyDown={(e) => {
        // stopPropagation: unmounting this input on Escape can race the
        // app's global "Escape clears the Inspector selection" listener
        // (App.tsx checks document.activeElement's tag — by the time it
        // runs, this input may already be gone). Stop it from bubbling so
        // cancelling a rename never also deselects the whole character.
        if (e.key === 'Enter') { e.stopPropagation(); e.currentTarget.blur() }
        if (e.key === 'Escape') { e.stopPropagation(); cancelled.current = true; onCancel() }
      }}
    />
  )
}

function BlockMenu({ open, onToggle, onRename, onDuplicate, onDelete }: {
  open: boolean
  onToggle: () => void
  onRename: () => void
  onDuplicate: () => void
  onDelete: () => void
}) {
  return (
    <div className="relative shrink-0 mt-1">
      <button
        type="button"
        className="w-6 h-7 flex items-center justify-center text-textdim hover:text-text transition-colors"
        onClick={(e) => { e.stopPropagation(); onToggle() }}
        title="Block actions"
      >
        <span className="text-sm leading-none tracking-widest">&bull;&bull;&bull;</span>
      </button>
      {open && (
        <div
          className="absolute z-20 left-0 top-full mt-0.5 border border-line bg-bg1 shadow-lg w-32"
          onClick={(e) => e.stopPropagation()}
        >
          <MenuItem label="Rename" onClick={onRename} />
          <MenuItem label="Duplicate" onClick={onDuplicate} />
          <MenuItem label="Remove" danger onClick={onDelete} />
        </div>
      )}
    </div>
  )
}

function MenuItem({ label, onClick, danger }: { label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      type="button"
      className={`block w-full text-left px-3 py-1.5 text-xs font-body transition-colors hover:bg-bg2 ${danger ? 'text-danger' : 'text-text'}`}
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
  menuOpen,
  onToggleMenu,
  onRename,
  onDuplicate,
  renaming,
  onCommitRename,
  onCancelRename,
  addChildEnabled,
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
  menuOpen: boolean
  onToggleMenu: () => void
  onRename: () => void
  onDuplicate: () => void
  renaming: boolean
  onCommitRename: (name: string) => void
  onCancelRename: () => void
  addChildEnabled?: boolean
  onAddChild?: () => void
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
  const showTokenCount = block.type === 'text' || block.type === 'folder'
  const isEquipment = block.type === 'equipment'

  // Equipment can be reordered (see dragStart) even though it's locked —
  // it just isn't clickable-to-open (managed in its own tab instead).
  const draggable = !locked || isEquipment

  const base = `group relative border rounded-md overflow-hidden transition-colors ${isEquipment ? 'cursor-default' : 'cursor-pointer'} ${
    isOpen ? 'border-line bg-bg3' : 'border-line bg-bg2 hover:border-line2'
  } ${locked ? 'border-gold/30 bg-gold/5' : ''} ${!block.enabled ? 'opacity-60' : ''} ${
    isDragging ? 'opacity-30' : ''
  } ${isDragOver ? 'ring-1 ring-inset ring-gold' : ''} ${isNestTarget ? 'ring-2 ring-inset ring-gold bg-gold/10' : ''}`

  return (
    <div className="flex items-start gap-1">
      {!locked && (
        <BlockMenu open={menuOpen} onToggle={onToggleMenu} onRename={onRename} onDuplicate={onDuplicate} onDelete={onRequestDelete} />
      )}
      <div
        className={`flex-1 min-w-0 ${base}`}
        onClick={onOpen}
        title={isEquipment ? undefined : 'Click to open'}
      >
        <SelectionBar show={isOpen} />
        <div
          className="flex items-center gap-1.5 pl-3 pr-2 py-1.5"
          // Drag/drop lives on the header strip specifically, not the whole
          // card — an expanded folder's body (children, "+ CREATE BLOCK") is
          // much taller than its header, and the nest-vs-reorder Y-band in
          // rootDragOver() needs the header's own height to mean anything.
          // stopPropagation keeps a nested child row's drag events from
          // bubbling up into its parent Folder row's handlers.
          onDragOver={(e) => { e.stopPropagation(); onDragOverRow(e) }}
          onDrop={(e) => { e.stopPropagation(); onDropRow(e) }}
        >
          <span
            draggable={draggable}
            onDragStart={(e) => { e.stopPropagation(); onDragStart() }}
            onDragEnd={(e) => { e.stopPropagation(); onDragEndRow() }}
            onClick={(e) => e.stopPropagation()}
            className={`shrink-0 px-0.5 ${
              draggable ? 'text-textdim hover:text-text cursor-grab active:cursor-grabbing' : 'text-textdim/40 cursor-not-allowed'
            }`}
            title={draggable ? 'Drag to reorder' : 'Locked — cannot be moved'}
          >
            {GRIP_ICON}
          </span>

          {locked ? <LockGlyph /> : <Toggle checked={block.enabled} onChange={onToggle} />}

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

          {renaming ? (
            <RenameInput initial={block.name} onCommit={onCommitRename} onCancel={onCancelRename} />
          ) : (
            <span className="flex-1 min-w-0 truncate text-sm font-body text-text px-1 py-0.5">
              {block.name}
            </span>
          )}

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
          ) : showTokenCount ? (
            <span className="shrink-0 font-ui text-[9px] text-textdim tabular-nums" title="Estimated tokens">
              {estimateBlockTokens(block)}
            </span>
          ) : null}
        </div>

        {isEquipment && (
          <div className="px-3 pb-2">
            <p className="text-[11px] text-textdim italic font-body">
              Rendered live from equipped gear — open the Equipment tab to manage what's worn.
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
            {addChildEnabled && onAddChild && (
              <button
                type="button"
                className="mt-1 ml-5 font-ui text-[9px] text-textsec border border-dashed border-line px-2 py-1 hover:border-line2 hover:text-text transition-colors"
                onClick={onAddChild}
              >
                + CREATE BLOCK
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/** Read-only rendering for the Sheet tab — enabled blocks only, folders
 * recursed (flattened, not visually nested), tags skipped. Equipment is
 * excluded entirely (it has its own tab now). Image blocks render as
 * placeholder tiles under an "Images" heading — there's no asset-serving
 * route for them yet (image_block_paths() is prep for a future
 * vision-attachment pass), so this stays a label-only stand-in. */
export function BlockTreeView({ blocks }: { blocks: CharacterBlock[] }) {
  type Row = { kind: 'text'; label: string; content: string } | { kind: 'image'; label: string }
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
      } else if (b.type === 'image') {
        rows.push({ kind: 'image', label: b.name })
      }
      // equipment: intentionally skipped — see the Equipment tab instead.
    }
  }
  walk(blocks)

  if (rows.length === 0) {
    return <p className="text-sm text-textdim italic font-body">Nothing written yet.</p>
  }

  const images = rows.filter((r): r is Extract<Row, { kind: 'image' }> => r.kind === 'image')
  const textRows = rows.filter((r): r is Extract<Row, { kind: 'text' }> => r.kind === 'text')

  return (
    <div className="space-y-3">
      {images.length > 0 && (
        <div>
          <span className="text-[11px] text-textdim font-body block mb-1.5">Images</span>
          <div className="grid grid-cols-2 gap-2">
            {images.map((img, i) => (
              <div key={i} className="aspect-square border border-line rounded-md bg-bg2 flex items-center justify-center px-2">
                <span className="font-ui text-[9px] text-textdim tracking-wider text-center">{img.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {textRows.map((r, i) =>
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
