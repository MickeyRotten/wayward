import { usePartyStore } from '../../state/partyStore'
import { useUiStore } from '../../state/uiStore'

export function PartyView({ onOpenSettings }: { onOpenSettings: () => void }) {
  const pc = usePartyStore((s) => s.playerCharacter)
  const members = usePartyStore((s) => s.partyMembers)
  const addMember = usePartyStore((s) => s.addPartyMember)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const isSelected = (type: string, id?: string) => {
    if (!selection) return false
    if (type === 'player') return selection.type === 'player'
    return selection.type === 'member' && selection.id === id
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-5 pb-4">
        <div className="flex items-start justify-between">
          <h1 className="font-h text-[36px] pt-[5px] leading-none">Wayward</h1>
          <button
            type="button"
            className="font-ui text-[9px] text-text-sec hover:text-text border-[1.5px] border-mid px-2 py-1 hover:border-border transition-colors mt-2"
            onClick={onOpenSettings}
          >
            SETTINGS
          </button>
        </div>
        <p className="text-[11px] text-text-dim font-b mt-1">Alpha Build</p>
      </div>

      {/* Party list */}
      <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1.5">
        {/* Player character */}
        {pc && (
          <button
            type="button"
            className={`w-full text-left px-3 py-2.5 border-[1.5px] transition-colors ${
              isSelected('player')
                ? 'border-border bg-white'
                : 'border-transparent hover:bg-off2'
            }`}
            onClick={() => select({ type: 'player' })}
          >
            <div className="flex items-center gap-2.5">
              <Avatar portrait={pc.basicInfo.portrait} fallback="PC" />
              <div className="min-w-0">
                <span className="font-h text-[18px] pt-[2px] block leading-tight truncate">
                  {pc.basicInfo.name || 'Unnamed'}
                </span>
                <span className="text-[10px] text-text-dim font-b">
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
            <span className="font-ui text-[9px] text-text-dim tracking-wider">PARTY</span>
            <div className="flex-1 border-t border-mid" />
          </div>
        )}

        {/* Party members */}
        {members.map((m) => (
          <button
            key={m.id}
            type="button"
            className={`w-full text-left px-3 py-2.5 border-[1.5px] transition-colors ${
              isSelected('member', m.id)
                ? 'border-border bg-white'
                : 'border-transparent hover:bg-off2'
            }`}
            onClick={() => select({ type: 'member', id: m.id })}
          >
            <div className="flex items-center gap-2.5">
              <Avatar portrait={m.basicInfo.portrait} fallback={(m.basicInfo.name || '?')[0].toUpperCase()} />
              <div className="min-w-0">
                <span className="font-h text-[18px] pt-[2px] block leading-tight truncate">
                  {m.basicInfo.name || 'Unnamed'}
                </span>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-text-dim font-b">
                    {m.basicInfo.species}
                  </span>
                  {m.fieldSkill.name && (
                    <span className="font-ui text-[7px] text-text-dim border border-mid px-1.5 py-px tracking-wider">
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
          className="w-full font-ui text-[10px] text-text-sec border-[1.5px] border-dashed border-mid px-3 py-2.5 hover:border-border hover:text-text transition-colors mt-2"
          onClick={async () => {
            const pm = await addMember()
            select({ type: 'member', id: pm.id })
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
      <div className="w-9 h-9 border-[1.5px] border-mid overflow-hidden flex-shrink-0">
        <img
          src={`/portraits/${portrait}`}
          alt=""
          className="w-full h-full object-cover object-top"
        />
      </div>
    )
  }
  return (
    <div className="w-9 h-9 border-[1.5px] border-mid bg-off2 flex items-center justify-center flex-shrink-0">
      <span className="font-ui text-[7px] text-text-dim">{fallback}</span>
    </div>
  )
}
