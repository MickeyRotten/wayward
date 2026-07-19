import { useEffect, useRef } from 'react'
import { AppShell } from './components/Layout/AppShell'
import { MobileShell } from './components/Layout/MobileShell'
import { IconRail } from './components/IconRail/IconRail'
import { HomeView } from './components/Home/HomeView'
import { ItemsPanel } from './components/ItemsPanel/ItemsPanel'
import { TasksPanel } from './components/TasksPanel/TasksPanel'
import { LorePanel } from './components/LorePanel/LorePanel'
import { SuggestionsPanel } from './components/Suggestions/SuggestionsPanel'
import { JournalPanel } from './components/Journal/JournalPanel'
import { SaveLoadView } from './components/SaveLoad/SaveLoadView'
import { ChatScene } from './components/Scene/ChatScene'
import { PartyInspector } from './components/Inspector/PartyInspector'
import { SettingsPanel } from './components/Settings/SettingsPanel'
import { usePartyStore } from './state/partyStore'
import { useNarratorStore } from './state/narratorStore'
import { useChatStore } from './state/chatStore'
import { useSettingsStore } from './state/settingsStore'
import { useItemsStore } from './state/itemsStore'
import { useTasksStore } from './state/tasksStore'
import { useLoreStore } from './state/loreStore'
import { useScenarioStore } from './state/scenarioStore'
import { useCampaignRulesStore } from './state/campaignRulesStore'
import { useStoryStyleStore } from './state/storyStyleStore'
import { useWorldbuildStore } from './state/worldbuildStore'
import { useAdventuresStore } from './state/adventuresStore'
import { useCampaignsStore } from './state/campaignsStore'
import { useJournalStore } from './state/journalStore'
import { useTtsStore } from './state/ttsStore'
import { useUiStore } from './state/uiStore'
import type { TabId } from './state/uiStore'
import { applyChatFontSize } from './state/appearanceStore'
import { useIsMobile } from './lib/useIsMobile'

function App() {
  const activeTab = useUiStore((s) => s.activeTab)
  const setActiveTab = useUiStore((s) => s.setActiveTab)
  const mobileView = useUiStore((s) => s.mobileView)
  const select = useUiStore((s) => s.select)
  const isMobile = useIsMobile()
  const editMode = useChatStore((s) => s.planningMode)
  const prevTabRef = useRef<TabId>('home')

  // Re-skin the whole app (edit-theme.css) while Edit Mode is active.
  useEffect(() => {
    document.body.classList.toggle('edit-mode', editMode)
    return () => document.body.classList.remove('edit-mode')
  }, [editMode])

  // Apply the stored chat font-size preference (CSS var) before the chat renders.
  useEffect(() => {
    applyChatFontSize()
  }, [])

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
  const fetchTasks = useTasksStore((s) => s.fetchTasks)
  const fetchLoreEntries = useLoreStore((s) => s.fetchEntries)
  const fetchLoreConfig = useLoreStore((s) => s.fetchConfig)
  const fetchRules = useCampaignRulesStore((s) => s.fetchRules)
  const fetchScenario = useScenarioStore((s) => s.fetchScenario)
  const fetchStoryStyle = useStoryStyleStore((s) => s.fetchFields)
  const fetchProposals = useWorldbuildStore((s) => s.fetchProposals)
  const fetchAdventures = useAdventuresStore((s) => s.fetch)
  const fetchCampaigns = useCampaignsStore((s) => s.fetch)
  const fetchTtsStatus = useTtsStore((s) => s.fetchStatus)
  const fetchJournal = useJournalStore((s) => s.fetch)
  const scopeLoading = useUiStore((s) => s.scopeLoading)

  useEffect(() => {
    fetchCampaigns()
    fetchParty()
    fetchNarrator()
    fetchChat()
    fetchSettings()
    fetchCatalog()
    fetchInventory()
    fetchTasks()
    fetchLoreEntries()
    fetchLoreConfig()
    fetchRules()
    fetchScenario()
    fetchStoryStyle()
    fetchProposals()
    fetchAdventures()
    fetchTtsStatus()
    fetchJournal(true)
  }, [fetchParty, fetchNarrator, fetchChat, fetchSettings, fetchCatalog, fetchInventory, fetchTasks, fetchLoreEntries, fetchLoreConfig, fetchRules, fetchScenario, fetchStoryStyle, fetchProposals, fetchAdventures, fetchCampaigns, fetchTtsStatus, fetchJournal])

  const handleTabChange = (tab: TabId) => {
    prevTabRef.current = tab
    setActiveTab(tab)
  }

  const panelFor = (tab: TabId) => {
    switch (tab) {
      case 'home':
        return <HomeView />
      case 'items':
        return <ItemsPanel />
      case 'tasks':
        return <TasksPanel />
      case 'lore':
        return <LorePanel />
      case 'journal':
        return <JournalPanel />
      case 'suggestions':
        return <SuggestionsPanel />
      case 'saves':
        return <SaveLoadView />
      case 'config':
        return <SettingsPanel />
      default:
        return <HomeView />
    }
  }

  // While a campaign/adventure switch reloads every store, unmount the panes
  // entirely — rendering them against half-swapped state is what used to blank
  // the app — and show a proper loading screen instead.
  if (scopeLoading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-bg0">
        <span className="font-disp text-[22px] text-gold pt-[3px]">
          {scopeLoading}<span className="animate-pulse"> …</span>
        </span>
        <span className="font-ui text-[11px] tracking-wider text-textdim">PREPARING THE WORLD</span>
      </div>
    )
  }

  return isMobile ? (
    <MobileShell
      main={mobileView === 'chat' ? <ChatScene /> : panelFor(mobileView)}
      inspector={<PartyInspector />}
    />
  ) : (
    <AppShell
      iconRail={<IconRail activeTab={activeTab} onTabChange={handleTabChange} />}
      left={panelFor(activeTab)}
      middle={<ChatScene />}
      right={<PartyInspector />}
    />
  )
}

export default App
