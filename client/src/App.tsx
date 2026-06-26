import { useEffect, useRef } from 'react'
import { AppShell } from './components/Layout/AppShell'
import { IconRail } from './components/IconRail/IconRail'
import { HomeView } from './components/Home/HomeView'
import { ItemsPanel } from './components/ItemsPanel/ItemsPanel'
import { QuestsPanel } from './components/QuestsPanel/QuestsPanel'
import { LorePanel } from './components/LorePanel/LorePanel'
import { SuggestionsPanel } from './components/Suggestions/SuggestionsPanel'
import { SaveLoadView } from './components/SaveLoad/SaveLoadView'
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
import { useWorldbuildStore } from './state/worldbuildStore'
import { useAdventuresStore } from './state/adventuresStore'
import { useCampaignsStore } from './state/campaignsStore'
import { useUiStore } from './state/uiStore'
import type { TabId } from './state/uiStore'

function App() {
  const activeTab = useUiStore((s) => s.activeTab)
  const setActiveTab = useUiStore((s) => s.setActiveTab)
  const select = useUiStore((s) => s.select)
  const editMode = useChatStore((s) => s.planningMode)
  const prevTabRef = useRef<TabId>('home')

  // Re-skin the whole app (edit-theme.css) while Edit Mode is active.
  useEffect(() => {
    document.body.classList.toggle('edit-mode', editMode)
    return () => document.body.classList.remove('edit-mode')
  }, [editMode])

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
  const fetchProposals = useWorldbuildStore((s) => s.fetchProposals)
  const fetchAdventures = useAdventuresStore((s) => s.fetch)
  const fetchCampaigns = useCampaignsStore((s) => s.fetch)
  const switching = useCampaignsStore((s) => s.busy) || useAdventuresStore((s) => s.busy)

  useEffect(() => {
    fetchCampaigns()
    fetchParty()
    fetchNarrator()
    fetchChat()
    fetchSettings()
    fetchCatalog()
    fetchInventory()
    fetchQuests()
    fetchLoreEntries()
    fetchLoreConfig()
    fetchProposals()
    fetchAdventures()
  }, [fetchParty, fetchNarrator, fetchChat, fetchSettings, fetchCatalog, fetchInventory, fetchQuests, fetchLoreEntries, fetchLoreConfig, fetchProposals, fetchAdventures, fetchCampaigns])

  const handleTabChange = (tab: TabId) => {
    prevTabRef.current = tab
    setActiveTab(tab)
  }

  const leftPanel = (() => {
    switch (activeTab) {
      case 'home':
        return <HomeView />
      case 'items':
        return <ItemsPanel />
      case 'quests':
        return <QuestsPanel />
      case 'lore':
        return <LorePanel />
      case 'suggestions':
        return <SuggestionsPanel />
      case 'saves':
        return <SaveLoadView />
      case 'config':
        return <SettingsPanel />
      default:
        return <HomeView />
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
      {switching && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-bg0/85">
          <span className="font-disp text-[20px] text-gold pt-[3px]">
            Loading<span className="animate-pulse"> …</span>
          </span>
        </div>
      )}
    </>
  )
}

export default App
