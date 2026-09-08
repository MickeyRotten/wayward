import { useState } from 'react'
import type { CharacterBlock, CharacterBlockType } from '@shared/types/models'
import { ExpandableTextarea } from '../common/ExpandableTextarea'

const TAG_OPEN_NAME = 'Open Tag'
const TAG_CLOSE_NAME = 'Close Tag'

const TYPE_LABELS: Record<CharacterBlockType, string> = {
  text: 'Text',
  folder: 'Folder',
  equipment: 'Equipment',
  image: 'Image',
}

function newId(): string {
  return (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).replace(/-/g, '').slice(0, 12)
}

function newBlock(type: 'text' | 'folder' | 'equipment', name: string): CharacterBlock {
  const base = { id: newId(), name, enabled: true }
  if (type === 'text') return { ...base, type, content: '' }
  if (type === 'folder') return { ...base, type, children: [] }
  return { ...base, type: 'equipment' }
}

function moveItem<T>(list: T[], index: number, dir: -1 | 1): T[] {
  const target = index + dir
  if (target < 0 || target >= list.length) return list
  const next = list.slice()
  ;[next[index], next[target]] = [next[target], next[index]]
  return next
}

/**
 * The TavernAI-style toggleable/orderable block-tree editor: a flat list of
 * blocks, folders nesting one level deep (no roles/depth/merge-groups — see
 * CLAUDE.md's Character system rebuild section). `onChange`'s `immediate`
 * flag mirrors the rest of the sheet's fields: text edits debounce upstream,
 * everything else (toggle/reorder/add/delete/rename) flushes right away.
 */
export function BlockTreeEditor({
  blocks,
  onChange,
}: {
  blocks: CharacterBlock[]
  onChange: (blocks: CharacterBlock[], immediate?: boolean) => void
}) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [addMenuFor, setAddMenuFor] = useState<'root' | string | null>(null)

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

  const moveRoot = (index: number, dir: -1 | 1) => updateRoot(moveItem(blocks, index, dir))

  const moveChild = (parentIndex: number, childIndex: number, dir: -1 | 1) => {
    const parent = blocks[parentIndex]
    updateAt(parentIndex, { children: moveItem(parent.children ?? [], childIndex, dir) })
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

  return (
    <div className="space-y-1.5">
      {blocks.map((block, i) => (
        <BlockRow
          key={block.id}
          block={block}
          isFirst={i === 0}
          isLast={i === blocks.length - 1}
          confirmingDelete={confirmDeleteId === block.id}
          onToggle={(enabled) => updateAt(i, { enabled })}
          onRename={(name) => updateAt(i, { name })}
          onContentChange={(content) => updateAt(i, { content }, false)}
          onContentBlur={(content) => updateAt(i, { content }, true)}
          onMoveUp={() => moveRoot(i, -1)}
          onMoveDown={() => moveRoot(i, 1)}
          onRequestDelete={() => setConfirmDeleteId(block.id)}
          onConfirmDelete={() => deleteRoot(i)}
          onCancelDelete={() => setConfirmDeleteId(null)}
          addMenuOpen={addMenuFor === block.id}
          onToggleAddMenu={() => setAddMenuFor(addMenuFor === block.id ? null : block.id)}
          onAddChild={(type) => addChildBlock(i, type)}
        >
          {block.type === 'folder' && (
            <div className="ml-5 mt-1.5 space-y-1.5 border-l border-line pl-3">
              {(block.children ?? []).map((child, ci) => (
                <BlockRow
                  key={child.id}
                  block={child}
                  isFirst={ci === 0}
                  isLast={ci === (block.children?.length ?? 0) - 1}
                  confirmingDelete={confirmDeleteId === child.id}
                  onToggle={(enabled) => updateChild(i, ci, { enabled })}
                  onRename={(name) => updateChild(i, ci, { name })}
                  onContentChange={(content) => updateChild(i, ci, { content }, false)}
                  onContentBlur={(content) => updateChild(i, ci, { content }, true)}
                  onMoveUp={() => moveChild(i, ci, -1)}
                  onMoveDown={() => moveChild(i, ci, 1)}
                  onRequestDelete={() => setConfirmDeleteId(child.id)}
                  onConfirmDelete={() => deleteChild(i, ci)}
                  onCancelDelete={() => setConfirmDeleteId(null)}
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
  isFirst,
  isLast,
  confirmingDelete,
  onToggle,
  onRename,
  onContentChange,
  onContentBlur,
  onMoveUp,
  onMoveDown,
  onRequestDelete,
  onConfirmDelete,
  onCancelDelete,
  addMenuOpen,
  onToggleAddMenu,
  onAddChild,
  children,
}: {
  block: CharacterBlock
  isFirst: boolean
  isLast: boolean
  confirmingDelete: boolean
  onToggle: (enabled: boolean) => void
  onRename: (name: string) => void
  onContentChange: (content: string) => void
  onContentBlur: (content: string) => void
  onMoveUp: () => void
  onMoveDown: () => void
  onRequestDelete: () => void
  onConfirmDelete: () => void
  onCancelDelete: () => void
  addMenuOpen?: boolean
  onToggleAddMenu?: () => void
  onAddChild?: (type: 'text' | 'equipment') => void
  children?: React.ReactNode
}) {
  const isTag = block.name === TAG_OPEN_NAME || block.name === TAG_CLOSE_NAME
  const [expanded, setExpanded] = useState(true)

  return (
    <div className={`border border-line bg-bg0/60 ${!block.enabled ? 'opacity-50' : ''}`}>
      <div className="flex items-center gap-1.5 px-2 py-1.5">
        <div className="flex flex-col shrink-0">
          <button
            type="button"
            disabled={isFirst}
            className="text-textdim hover:text-text disabled:opacity-20 disabled:hover:text-textdim leading-none px-0.5"
            title="Move up"
            onClick={onMoveUp}
          >
            <span className="text-[9px]">▲</span>
          </button>
          <button
            type="button"
            disabled={isLast}
            className="text-textdim hover:text-text disabled:opacity-20 disabled:hover:text-textdim leading-none px-0.5"
            title="Move down"
            onClick={onMoveDown}
          >
            <span className="text-[9px]">▼</span>
          </button>
        </div>

        <input
          type="checkbox"
          checked={block.enabled}
          onChange={(e) => onToggle(e.target.checked)}
          className="shrink-0 accent-gold"
          title={block.enabled ? 'Enabled — included in the prompt' : 'Disabled — skipped'}
        />

        {block.type === 'folder' && (
          <button
            type="button"
            className="text-textdim hover:text-text shrink-0 px-0.5"
            onClick={() => setExpanded(!expanded)}
            title={expanded ? 'Collapse' : 'Expand'}
          >
            <span className="text-[10px]">{expanded ? '▾' : '▸'}</span>
          </button>
        )}

        <input
          className="flex-1 min-w-0 bg-transparent text-sm font-body text-text outline-none border-b border-transparent focus:border-line2 px-1 py-0.5"
          value={block.name}
          onChange={(e) => onRename(e.target.value)}
        />

        <span className="shrink-0 font-ui text-[9px] tracking-wider text-textdim uppercase border border-line px-1.5 py-0.5">
          {TYPE_LABELS[block.type]}
        </span>

        {confirmingDelete ? (
          <div className="flex items-center gap-1 shrink-0">
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
            onClick={onRequestDelete}
          >
            &times;
          </button>
        )}
      </div>

      {block.type === 'text' && expanded !== false && (
        <div className="px-2 pb-2">
          <ExpandableTextarea
            label={block.name || 'Block'}
            className="w-full border border-line bg-bg0 px-2 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors resize-y min-h-[56px]"
            rows={isTag ? 1 : 3}
            value={block.content ?? ''}
            placeholder={isTag ? undefined : 'Content the Narrator reads for this block…'}
            onChange={onContentChange}
            onBlur={onContentBlur}
          />
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
        <div className="px-2 pb-2">
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
