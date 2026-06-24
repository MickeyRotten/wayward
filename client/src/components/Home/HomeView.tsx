import { useState } from 'react'
import { usePartyStore } from '../../state/partyStore'
import { useSettingsStore } from '../../state/settingsStore'
import { useChatStore } from '../../state/chatStore'
import { useUiStore } from '../../state/uiStore'
import { deriveCurrentLocation } from '../../lib/location'
import type { PartyMember, PlayerCharacter } from '@shared/types/models'

// Static, hand-authored points of interest for the current scene (alpha stub).
const POIS: { id: string; name: string; blurb: string }[] = [
  { id: 'stone-pillars', name: 'Stone Pillars', blurb: 'Weathered monoliths ringing the clearing, carved with faded sigils.' },
  { id: 'silver-pool', name: 'Silver Pool', blurb: 'A still pond that mirrors the sky a little too perfectly.' },
  { id: 'misty-trail', name: 'Misty Trail', blurb: 'A narrow path that fades into low fog beyond the treeline.' },
]

export function HomeView() {
  const pc = usePartyStore((s) => s.playerCharacter)
  const members = usePartyStore((s) => s.partyMembers)
  const addMember = usePartyStore((s) => s.addPartyMember)
  const setMembership = usePartyStore((s) => s.setMembership)
  const maxPartySize = useSettingsStore((s) => s.maxPartySize)
  const messages = useChatStore((s) => s.messages)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const [error, setError] = useState('')
  const [openPoi, setOpenPoi] = useState<string | null>(null)

  const active = members.filter((m) => m.inParty)
  const benched = members.filter((m) => !m.inParty)
  const full = active.length >= maxPartySize
  const locationName = deriveCurrentLocation(messages)

  const isMemberSelected = (id: string) =>
    selection?.kind === 'member' && 'id' in selection && selection.id === id

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
      <div className="px-5 pt-5 pb-3">
        <h1 className="font-disp text-[36px] pt-[5px] leading-none">Wayward</h1>
        <p className="text-[11px] text-textdim font-body mt-1">Alpha Build</p>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-4 space-y-2">
        {/* Player character */}
        {pc && (
          <CharacterCard
            name={pc.basicInfo.name || 'Unnamed'}
            subtitle={`${pc.basicInfo.species}${pc.basicInfo.gender ? ` · ${pc.basicInfo.gender}` : ''}`}
            portrait={pc.basicInfo.portrait}
            fallback="PC"
            selected={selection?.kind === 'player'}
            onSelect={() => select({ kind: 'player' })}
          />
        )}

        {/* Party */}
        <SectionHeader label="Party" trailing={
          <span className={`font-ui text-[9px] tracking-wider ${full ? 'text-gold' : 'text-textdim'}`}>
            {active.length} / {maxPartySize}
          </span>
        } />

        {active.map((m) => (
          <MemberCard
            key={m.id}
            member={m}
            selected={isMemberSelected(m.id)}
            onSelect={() => select({ kind: 'member', id: m.id })}
            action={{ label: 'Remove from party', glyph: '−', onClick: () => handleMembership(m.id, false) }}
          />
        ))}
        {active.length === 0 && (
          <p className="text-[11px] text-textdim font-body px-3 py-1">No active party members.</p>
        )}

        <button
          type="button"
          disabled={full}
          title={full ? 'Party is full — raise Max Party Size in Config' : undefined}
          className="w-full font-ui text-[10px] text-textsec border border-dashed border-line px-3 py-2.5 hover:border-line2 hover:text-text transition-colors disabled:opacity-30 disabled:hover:border-line disabled:hover:text-textsec disabled:cursor-not-allowed"
          onClick={handleAdd}
        >
          + ADD MEMBER
        </button>

        {benched.length > 0 && (
          <>
            <SectionHeader label="Not in Party" />
            {benched.map((m) => (
              <MemberCard
                key={m.id}
                member={m}
                dimmed
                selected={isMemberSelected(m.id)}
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

        {error && <p className="text-[11px] text-danger font-body px-3 pt-1">{error}</p>}

        {/* Scene */}
        <SectionHeader label="Scene" trailing={
          <span className="font-disp text-[13px] text-gold pt-[1px] leading-none truncate max-w-[160px]">{locationName}</span>
        } />
        <div className="space-y-1.5">
          {POIS.map((poi) => {
            const open = openPoi === poi.id
            return (
              <button
                key={poi.id}
                type="button"
                className={`w-full text-left px-3 py-2 border transition-colors ${
                  open ? 'border-line2 bg-bg0' : 'border-line bg-bg2 hover:border-line2'
                }`}
                onClick={() => setOpenPoi(open ? null : poi.id)}
              >
                <span className="font-body text-sm text-text">{poi.name}</span>
                {open && (
                  <p className="text-[12px] text-textsec font-body mt-1.5 leading-snug">{poi.blurb}</p>
                )}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function SectionHeader({ label, trailing }: { label: string; trailing?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 px-3 pt-3 pb-1">
      <span className="font-ui text-[9px] text-textdim tracking-wider uppercase">{label}</span>
      {trailing}
      <div className="flex-1 border-t border-line" />
    </div>
  )
}

function CharacterCard({
  name, subtitle, portrait, fallback, selected, onSelect,
}: {
  name: string
  subtitle: string
  portrait?: string
  fallback: string
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      className={`w-full text-left px-3 py-2.5 border transition-colors flex items-center gap-3 ${
        selected ? 'border-line2 bg-bg0' : 'border-line bg-bg2 hover:border-line2'
      }`}
      onClick={onSelect}
    >
      <Avatar portrait={portrait} fallback={fallback} />
      <div className="min-w-0">
        <span className="font-disp text-[19px] pt-[2px] block leading-tight truncate">{name}</span>
        <span className="text-[10px] text-textdim font-body">{subtitle}</span>
      </div>
    </button>
  )
}

function MemberCard({
  member, selected, dimmed, onSelect, action,
}: {
  member: PartyMember | PlayerCharacter
  selected: boolean
  dimmed?: boolean
  onSelect: () => void
  action: { label: string; glyph: string; disabled?: boolean; onClick: () => void }
}) {
  const info = member.basicInfo
  return (
    <div
      className={`group flex items-stretch border transition-colors ${
        selected ? 'border-line2 bg-bg0' : 'border-line bg-bg2 hover:border-line2'
      } ${dimmed ? 'opacity-60' : ''}`}
    >
      <button type="button" className="flex-1 text-left px-3 py-2.5 min-w-0 flex items-center gap-3" onClick={onSelect}>
        <Avatar portrait={info.portrait} fallback={(info.name || '?')[0].toUpperCase()} />
        <div className="min-w-0">
          <span className="font-disp text-[19px] pt-[2px] block leading-tight truncate">{info.name || 'Unnamed'}</span>
          <span className="text-[10px] text-textdim font-body">{info.species}</span>
        </div>
      </button>
      <button
        type="button"
        title={action.label}
        aria-label={action.label}
        disabled={action.disabled}
        className="shrink-0 px-3 self-stretch font-ui text-[16px] text-textdim hover:text-gold transition-colors disabled:opacity-30 disabled:hover:text-textdim disabled:cursor-not-allowed border-l border-line"
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
      <div className="w-12 h-12 border border-line overflow-hidden flex-shrink-0">
        <img src={`/portraits/${portrait}`} alt="" className="w-full h-full object-cover object-top" />
      </div>
    )
  }
  return (
    <div className="w-12 h-12 border border-line bg-bg3 flex items-center justify-center flex-shrink-0">
      <span className="font-ui text-[9px] text-textdim">{fallback}</span>
    </div>
  )
}
