import { useEffect, useRef, useState } from 'react'
import { AppShell } from './components/Layout/AppShell'
import { IconRail } from './components/IconRail/IconRail'
import { PartyView } from './components/PartyView/PartyView'
import { ItemsPanel } from './components/ItemsPanel/ItemsPanel'
import { ChatScene } from './components/Scene/ChatScene'
import { PartyInspector } from './components/Inspector/PartyInspector'
import { SettingsPanel } from './components/Settings/SettingsPanel'
import { usePartyStore } from './state/partyStore'
import { useNarratorStore } from './state/narratorStore'
import { useChatStore } from './state/chatStore'
import { useSettingsStore } from './state/settingsStore'
import { useItemsStore } from './state/itemsStore'
import { useUiStore } from './state/uiStore'
import type { TabId } from './state/uiStore'

function App() {
  const [showSettings, setShowSettings] = useState(false)
  const activeTab = useUiStore((s) => s.activeTab)
  const setActiveTab = useUiStore((s) => s.setActiveTab)
  const prevTabRef = useRef<TabId>('party')

  const fetchParty = usePartyStore((s) => s.fetchAll)
  const fetchNarrator = useNarratorStore((s) => s.fetchConfig)
  const fetchChat = useChatStore((s) => s.fetchHistory)
  const fetchSettings = useSettingsStore((s) => s.fetchSettings)
  const fetchCatalog = useItemsStore((s) => s.fetchCatalog)
  const fetchInventory = useItemsStore((s) => s.fetchInventory)

  useEffect(() => {
    fetchParty()
    fetchNarrator()
    fetchChat()
    fetchSettings()
    fetchCatalog()
    fetchInventory()
  }, [fetchParty, fetchNarrator, fetchChat, fetchSettings, fetchCatalog, fetchInventory])

  const handleTabChange = (tab: TabId) => {
    if (tab === 'config') {
      setShowSettings(true)
      // Don't change the active tab — stay on whatever was active before
      return
    }
    prevTabRef.current = tab
    setActiveTab(tab)
  }

  const leftPanel = (() => {
    switch (activeTab) {
      case 'party':
        return <PartyView />
      case 'scene':
        return <TabPlaceholder label="SCENE" description="Points of interest in the current location" />
      case 'items':
        return <ItemsPanel />
      case 'quests':
        return <TabPlaceholder label="QUESTS" description="Active and completed quests" />
      case 'lore':
        return <TabPlaceholder label="LORE" description="World, Characters, Items, Monsters, Spells" />
      default:
        return <PartyView />
    }
  })()

  return (
    <>
      <AppShell
        iconRail={<IconRail activeTab={activeTab} onTabChange={handleTabChange} />}
        left={leftPanel}
        middle={<ChatScene />}
        right={<PartyInspector />}
      />
      {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}
    </>
  )
}

function TabPlaceholder({ label, description }: { label: string; description: string }) {
  return (
    <div className="flex flex-col h-full">
      <div className="px-5 pt-5 pb-4">
        <h2 className="font-disp text-[24px] pt-[3px] leading-none text-text">{label}</h2>
        <p className="text-[11px] text-textdim font-body mt-2">{description}</p>
      </div>
      <div className="flex-1 flex items-center justify-center px-6">
        <p className="font-ui text-[10px] text-textdim tracking-wider text-center">
          COMING SOON
        </p>
      </div>
    </div>
  )
}

export default App
