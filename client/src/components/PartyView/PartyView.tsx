import { useState } from 'react'
import { usePartyStore } from '../../state/partyStore'
import { useSettingsStore } from '../../state/settingsStore'
import { useUiStore } from '../../state/uiStore'
import type { PartyMember } from '@shared/types/models'

export function PartyView() {
  const pc = usePartyStore((s) => s.playerCharacter)
  const members = usePartyStore((s) => s.partyMembers)
  const addMember = usePartyStore((s) => s.addPartyMember)
  const setMembership = usePartyStore((s) => s.setMembership)
  const maxPartySize = useSettingsStore((s) => s.maxPartySize)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const [error, setError] = useState('')

  const active = members.filter((m) => m.inParty)
  const benched = members.filter((m) => !m.inParty)
  const full = active.length >= maxPartySize

  const isSelected = (kind: string, id?: string) => {
    if (!selection) return false
    if (kind === 'player') return selection.kind === 'player'
    return selection.kind === 'member' && 'id' in selection && selection.id === id
  }

  const handleAdd = async () => {
    setError('')
    try {
      const pm = await addMember()
      select({ kind: 'member', id: pm.id })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to add member')
    }
  }

  const handleMembership = async (id: string, inParty: boolean) => {
    setError('')
    try {
      await setMembership(id, inParty)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update party')
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-5 pb-4">
        <h1 className="font-disp text-[36px] pt-[5px] leading-none">Wayward</h1>
        <p className="text-[11px] text-textdim font-body mt-1">Alpha Build</p>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1.5">
        {/* Player character */}
        {pc && (
          <button
            type="button"
            className={`w-full text-left px-3 py-2.5 border-[1.5px] transition-colors ${
              isSelected('player') ? 'border-line2 bg-bg0' : 'border-transparent hover:bg-bg2'
            }`}
            onClick={() => select({ kind: 'player' })}
          >
            <div className="flex items-center gap-2.5">
              <Avatar portrait={pc.basicInfo.portrait} fallback="PC" />
              <div className="min-w-0">
                <span className="font-disp text-[18px] pt-[2px] block leading-tight truncate">
                  {pc.basicInfo.name || 'Unnamed'}
                </span>
                <span className="text-[10px] text-textdim font-body">
                  {pc.basicInfo.species}
                  {pc.basicInfo.gender ? ` · ${pc.basicInfo.gender}` : ''}
                </span>
              </div>
            </div>
          </button>
        )}

        {/* Party section header with count */}
        <div className="flex items-center gap-2 px-3 pt-2 pb-1">
          <span className="font-ui text-[9px] text-textdim tracking-wider">PARTY</span>
          <span className={`font-ui text-[9px] tracking-wider ${full ? 'text-gold' : 'text-textdim'}`}>
            {active.length} / {maxPartySize}
          </span>
          <div className="flex-1 border-t border-line" />
        </div>

        {active.map((m) => (
          <MemberRow
            key={m.id}
            member={m}
            selected={isSelected('member', m.id)}
            onSelect={() => select({ kind: 'member', id: m.id })}
            action={{ label: 'Remove from party', glyph: '−', onClick: () => handleMembership(m.id, false) }}
          />
        ))}

        {active.length === 0 && (
          <p className="text-[11px] text-textdim font-body px-3 py-1">No active party members.</p>
        )}

        {/* Add member */}
        <button
          type="button"
          disabled={full}
          title={full ? 'Party is full — raise Max Party Size in Config' : undefined}
          className="w-full font-ui text-[10px] text-textsec border-[1.5px] border-dashed border-line px-3 py-2.5 hover:border-line2 hover:text-text transition-colors mt-1 disabled:opacity-30 disabled:hover:border-line disabled:hover:text-textsec disabled:cursor-not-allowed"
          onClick={handleAdd}
        >
          + ADD MEMBER
        </button>

        {/* Not in party */}
        {benched.length > 0 && (
          <>
            <div className="flex items-center gap-2 px-3 pt-3 pb-1">
              <span className="font-ui text-[9px] text-textdim tracking-wider">NOT IN PARTY</span>
              <div className="flex-1 border-t border-line" />
            </div>
            {benched.map((m) => (
              <MemberRow
                key={m.id}
                member={m}
                dimmed
                selected={isSelected('member', m.id)}
                onSelect={() => select({ kind: 'member', id: m.id })}
                action={{
                  label: full ? 'Party is full' : 'Add to party',
                  glyph: '+',
                  disabled: full,
                  onClick: () => handleMembership(m.id, true),
                }}
              />
            ))}
          </>
        )}

        {error && <p className="text-[11px] text-red-400 font-body px-3 pt-1">{error}</p>}
      </div>
    </div>
  )
}

function MemberRow({
  member,
  selected,
  dimmed,
  onSelect,
  action,
}: {
  member: PartyMember
  selected: boolean
  dimmed?: boolean
  onSelect: () => void
  action: { label: string; glyph: string; disabled?: boolean; onClick: () => void }
}) {
  return (
    <div
      className={`group flex items-center border-[1.5px] transition-colors ${
        selected ? 'border-line2 bg-bg0' : 'border-transparent hover:bg-bg2'
      } ${dimmed ? 'opacity-60' : ''}`}
    >
      <button type="button" className="flex-1 text-left px-3 py-2.5 min-w-0" onClick={onSelect}>
        <div className="flex items-center gap-2.5">
          <Avatar portrait={member.basicInfo.portrait} fallback={(member.basicInfo.name || '?')[0].toUpperCase()} />
          <div className="min-w-0">
            <span className="font-disp text-[18px] pt-[2px] block leading-tight truncate">
              {member.basicInfo.name || 'Unnamed'}
            </span>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-textdim font-body">{member.basicInfo.species}</span>
              {member.fieldSkill.name && (
                <span className="font-ui text-[7px] text-textdim border border-line px-1.5 py-px tracking-wider">
                  {member.fieldSkill.name.toUpperCase()}
                </span>
              )}
            </div>
          </div>
        </div>
      </button>
      <button
        type="button"
        title={action.label}
        aria-label={action.label}
        disabled={action.disabled}
        className="shrink-0 px-3 self-stretch font-ui text-[14px] text-textdim hover:text-gold transition-colors disabled:opacity-30 disabled:hover:text-textdim disabled:cursor-not-allowed"
        onClick={action.onClick}
      >
        {action.glyph}
      </button>
    </div>
  )
}

function Avatar({ portrait, fallback }: { portrait?: string; fallback: string }) {
  if (portrait) {
    return (
      <div className="w-9 h-9 border-[1.5px] border-line overflow-hidden flex-shrink-0">
        <img src={`/portraits/${portrait}`} alt="" className="w-full h-full object-cover object-top" />
      </div>
    )
  }
  return (
    <div className="w-9 h-9 border-[1.5px] border-line bg-bg2 flex items-center justify-center flex-shrink-0">
      <span className="font-ui text-[7px] text-textdim">{fallback}</span>
    </div>
  )
}
