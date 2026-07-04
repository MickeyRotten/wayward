import { useState } from 'react'
import { useTasksStore } from '../../state/tasksStore'
import { useUiStore } from '../../state/uiStore'
import { SelectionBar } from '../SelectionBar'
import type { Task } from '@shared/types/models'

export function TasksPanel() {
  const tasks = useTasksStore((s) => s.tasks)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const activeTasks = tasks.filter((t) => t.status === 'active')
  const doneTasks = tasks.filter((t) => t.status !== 'active')

  const isSelected = (id: string) =>
    selection?.kind === 'task' && selection.id === id

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-5 pb-4">
        <h2 className="font-disp text-[24px] pt-[3px] leading-none text-text">TASKS</h2>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-3">
        {/* Active tasks */}
        <div className="px-2 pb-1">
          <span className="font-ui text-[9px] text-textsec tracking-wider">TO DO</span>
        </div>

        {activeTasks.length === 0 && (
          <p className="text-[12px] text-textdim font-body px-4 py-3 text-center">
            No tasks to do
          </p>
        )}

        <div className="space-y-1">
          {activeTasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              selected={isSelected(task.id)}
              onSelect={() => select({ kind: 'task', id: task.id })}
            />
          ))}
        </div>

        {/* Completed / Failed section */}
        {doneTasks.length > 0 && (
          <DoneSection
            tasks={doneTasks}
            isSelected={isSelected}
            onSelect={(id) => select({ kind: 'task', id })}
          />
        )}

        {/* Divider */}
        <div className="flex items-center gap-2 px-3 pt-4 pb-1">
          <span className="font-ui text-[9px] text-textdim tracking-wider">NEW TASK</span>
          <div className="flex-1 border-t border-line" />
        </div>

        <NewTaskInput />
      </div>
    </div>
  )
}

function TaskRow({
  task,
  selected,
  onSelect,
}: {
  task: Task
  selected: boolean
  onSelect: () => void
}) {
  const setStatus = useTasksStore((s) => s.setStatus)

  return (
    <div
      className={`relative w-full text-left px-3 py-2.5 border rounded-md transition-colors ${
        selected ? 'border-line bg-bg3' : 'border-transparent hover:bg-bg2'
      }`}
    >
      <SelectionBar show={selected} />
      <div className="flex items-center gap-2.5">
        {/* Complete toggle — an empty box the player ticks off. */}
        <button
          type="button"
          className="shrink-0 w-4 h-4 rounded-[3px] border border-line2 hover:border-gold flex items-center justify-center transition-colors"
          onClick={(e) => { e.stopPropagation(); void setStatus(task.id, 'completed') }}
          title="Mark done"
          aria-label="Mark task done"
        />
        <button
          type="button"
          className="font-body text-sm text-text text-left flex-1 min-w-0 truncate"
          onClick={onSelect}
        >
          {task.text}
        </button>
      </div>
    </div>
  )
}

function DoneSection({
  tasks,
  isSelected,
  onSelect,
}: {
  tasks: Task[]
  isSelected: (id: string) => boolean
  onSelect: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const setStatus = useTasksStore((s) => s.setStatus)

  return (
    <div className="mt-3">
      <button
        type="button"
        className="flex items-center gap-2 px-2 pb-1 w-full text-left group"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="font-ui text-[9px] text-textsec tracking-wider group-hover:text-text transition-colors">
          COMPLETED / FAILED
        </span>
        <span className="font-ui text-[9px] text-textdim">{expanded ? '▴' : '▾'}</span>
        <span className="font-ui text-[10px] text-textdim">{tasks.length}</span>
      </button>

      {expanded && (
        <div className="space-y-1">
          {tasks.map((task) => (
            <div
              key={task.id}
              className={`relative w-full text-left px-3 py-2.5 border rounded-md transition-colors ${
                isSelected(task.id) ? 'border-line bg-bg3' : 'border-transparent hover:bg-bg2'
              }`}
            >
              <SelectionBar show={isSelected(task.id)} />
              <div className="flex items-center gap-2.5">
                {/* Re-open toggle */}
                <button
                  type="button"
                  className={`shrink-0 w-4 h-4 rounded-[3px] border flex items-center justify-center transition-colors ${
                    task.status === 'completed' ? 'border-gold bg-gold/20 text-gold' : 'border-danger text-danger'
                  }`}
                  onClick={(e) => { e.stopPropagation(); void setStatus(task.id, 'active') }}
                  title="Re-open"
                  aria-label="Re-open task"
                >
                  {task.status === 'completed' ? (
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
                  ) : (
                    <span className="text-[10px] leading-none">✕</span>
                  )}
                </button>
                <button
                  type="button"
                  className="font-body text-sm text-textdim line-through text-left flex-1 min-w-0 truncate"
                  onClick={() => onSelect(task.id)}
                >
                  {task.text}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function NewTaskInput() {
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const createTask = useTasksStore((s) => s.createTask)
  const select = useUiStore((s) => s.select)

  const handleSubmit = async () => {
    const trimmed = text.trim()
    if (!trimmed) return
    setError('')
    try {
      const task = await createTask(trimmed)
      setText('')
      select({ kind: 'task', id: task.id })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create task')
    }
  }

  return (
    <div className="px-2 space-y-2">
      <input
        className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
        placeholder="New task... (Enter to create)"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            handleSubmit()
          }
        }}
      />
      {error && (
        <p className="text-[11px] text-danger font-body px-1">{error}</p>
      )}
    </div>
  )
}
