import { useEffect, useState } from 'react'
import { AppShell } from './components/Layout/AppShell'
import { PartyView } from './components/PartyView/PartyView'
import { ChatScene } from './components/Scene/ChatScene'
import { PartyInspector } from './components/Inspector/PartyInspector'
import { SettingsPanel } from './components/Settings/SettingsPanel'
import { usePartyStore } from './state/partyStore'
import { useNarratorStore } from './state/narratorStore'
import { useChatStore } from './state/chatStore'
import { useSettingsStore } from './state/settingsStore'

function App() {
  const [showSettings, setShowSettings] = useState(false)
  const fetchParty = usePartyStore((s) => s.fetchAll)
  const fetchNarrator = useNarratorStore((s) => s.fetchConfig)
  const fetchChat = useChatStore((s) => s.fetchHistory)
  const fetchSettings = useSettingsStore((s) => s.fetchSettings)

  useEffect(() => {
    fetchParty()
    fetchNarrator()
    fetchChat()
    fetchSettings()
  }, [fetchParty, fetchNarrator, fetchChat, fetchSettings])

  return (
    <>
      <AppShell
        left={<PartyView onOpenSettings={() => setShowSettings(true)} />}
        middle={<ChatScene />}
        right={<PartyInspector />}
      />
      {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}
    </>
  )
}

export default App
