import { useEffect, useRef } from 'react'
import { AppShell } from './components/Layout/AppShell'
import { IconRail } from './components/IconRail/IconRail'
import { PartyView } from './components/PartyView/PartyView'
import { ItemsPanel } from './components/ItemsPanel/ItemsPanel'
import { QuestsPanel } from './components/QuestsPanel/QuestsPanel'
import { LorePanel } from './components/LorePanel/LorePanel'
import { ScenePOIList } from './components/ScenePOIList/ScenePOIList'
import { ChatScene } from './components/Scene/ChatScene'
import { PartyInspector } from './components/Inspector/PartyInspector'
import { SettingsPanel } from './components/Settings/SettingsPanel'
import { usePartyStore } from './state/partyStore'
import { useNarratorStore } from './state/narratorStore'
import { useChatStore } from './state/chatStore'
import { useSettingsStore } from './state/settingsStore'
import { useItemsStore } from './state/itemsStore'
import { useQuestsStore } from './state/questsStore'
import { useLoreStore } from './state/loreStore'
import { useUiStore } from './state/uiStore'
import type { TabId } from './state/uiStore'

function App() {
  const activeTab = useUiStore((s) => s.activeTab)
  const setActiveTab = useUiStore((s) => s.setActiveTab)
  const select = useUiStore((s) => s.select)
  const prevTabRef = useRef<TabId>('party')

  // Esc clears the inspector selection (back to the default inspector view),
  // unless the user is typing in a field (let that field handle Escape).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      const el = document.activeElement as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return
      select(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [select])

  const fetchParty = usePartyStore((s) => s.fetchAll)
  const fetchNarrator = useNarratorStore((s) => s.fetchConfig)
  const fetchChat = useChatStore((s) => s.fetchHistory)
  const fetchSettings = useSettingsStore((s) => s.fetchSettings)
  const fetchCatalog = useItemsStore((s) => s.fetchCatalog)
  const fetchInventory = useItemsStore((s) => s.fetchInventory)
  const fetchQuests = useQuestsStore((s) => s.fetchQuests)
  const fetchLoreEntries = useLoreStore((s) => s.fetchEntries)
  const fetchLoreConfig = useLoreStore((s) => s.fetchConfig)

  useEffect(() => {
    fetchParty()
    fetchNarrator()
    fetchChat()
    fetchSettings()
    fetchCatalog()
    fetchInventory()
    fetchQuests()
    fetchLoreEntries()
    fetchLoreConfig()
  }, [fetchParty, fetchNarrator, fetchChat, fetchSettings, fetchCatalog, fetchInventory, fetchQuests, fetchLoreEntries, fetchLoreConfig])

  const handleTabChange = (tab: TabId) => {
    prevTabRef.current = tab
    setActiveTab(tab)
  }

  const leftPanel = (() => {
    switch (activeTab) {
      case 'party':
        return <PartyView />
      case 'scene':
        return <ScenePOIList />
      case 'items':
        return <ItemsPanel />
      case 'quests':
        return <QuestsPanel />
      case 'lore':
        return <LorePanel />
      case 'config':
        return <SettingsPanel />
      default:
        return <PartyView />
    }
  })()

  return (
    <AppShell
      iconRail={<IconRail activeTab={activeTab} onTabChange={handleTabChange} />}
      left={leftPanel}
      middle={<ChatScene />}
      right={<PartyInspector />}
    />
  )
}

export default App
