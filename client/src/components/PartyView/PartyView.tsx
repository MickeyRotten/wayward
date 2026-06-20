import { usePartyStore } from '../../state/partyStore'
import { useUiStore } from '../../state/uiStore'

export function PartyView() {
  const pc = usePartyStore((s) => s.playerCharacter)
  const members = usePartyStore((s) => s.partyMembers)
  const addMember = usePartyStore((s) => s.addPartyMember)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const isSelected = (kind: string, id?: string) => {
    if (!selection) return false
    if (kind === 'player') return selection.kind === 'player'
    return selection.kind === 'member' && 'id' in selection && selection.id === id
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-5 pb-4">
        <div className="flex items-start justify-between">
          <h1 className="font-disp text-[36px] pt-[5px] leading-none">Wayward</h1>
        </div>
        <p className="text-[11px] text-textdim font-body mt-1">Alpha Build</p>
      </div>

      {/* Party list */}
      <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1.5">
        {/* Player character */}
        {pc && (
          <button
            type="button"
            className={`w-full text-left px-3 py-2.5 border-[1.5px] transition-colors ${
              isSelected('player')
                ? 'border-line2 bg-bg0'
                : 'border-transparent hover:bg-bg2'
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

        {/* Divider */}
        {members.length > 0 && (
          <div className="flex items-center gap-2 px-3 pt-2 pb-1">
            <span className="font-ui text-[9px] text-textdim tracking-wider">PARTY</span>
            <div className="flex-1 border-t border-line" />
          </div>
        )}

        {/* Party members */}
        {members.map((m) => (
          <button
            key={m.id}
            type="button"
            className={`w-full text-left px-3 py-2.5 border-[1.5px] transition-colors ${
              isSelected('member', m.id)
                ? 'border-line2 bg-bg0'
                : 'border-transparent hover:bg-bg2'
            }`}
            onClick={() => select({ kind: 'member', id: m.id })}
          >
            <div className="flex items-center gap-2.5">
              <Avatar portrait={m.basicInfo.portrait} fallback={(m.basicInfo.name || '?')[0].toUpperCase()} />
              <div className="min-w-0">
                <span className="font-disp text-[18px] pt-[2px] block leading-tight truncate">
                  {m.basicInfo.name || 'Unnamed'}
                </span>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-textdim font-body">
                    {m.basicInfo.species}
                  </span>
                  {m.fieldSkill.name && (
                    <span className="font-ui text-[7px] text-textdim border border-line px-1.5 py-px tracking-wider">
                      {m.fieldSkill.name.toUpperCase()}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </button>
        ))}

        {/* Add member */}
        <button
          type="button"
          className="w-full font-ui text-[10px] text-textsec border-[1.5px] border-dashed border-line px-3 py-2.5 hover:border-line2 hover:text-text transition-colors mt-2"
          onClick={async () => {
            const pm = await addMember()
            select({ kind: 'member', id: pm.id })
          }}
        >
          + ADD MEMBER
        </button>
      </div>
    </div>
  )
}

function Avatar({ portrait, fallback }: { portrait?: string; fallback: string }) {
  if (portrait) {
    return (
      <div className="w-9 h-9 border-[1.5px] border-line overflow-hidden flex-shrink-0">
        <img
          src={`/portraits/${portrait}`}
          alt=""
          className="w-full h-full object-cover object-top"
        />
      </div>
    )
  }
  return (
    <div className="w-9 h-9 border-[1.5px] border-line bg-bg2 flex items-center justify-center flex-shrink-0">
      <span className="font-ui text-[7px] text-textdim">{fallback}</span>
    </div>
  )
}
