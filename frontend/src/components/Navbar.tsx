import { SlidersHorizontal, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import type { ViewName } from '../types/astronomy'
const items: Array<{ id: ViewName; label: string }> = [
  { id: 'explorer', label: 'Explorer' },
  { id: 'science', label: 'Science' },
  { id: 'shift-stack', label: 'Shift & Stack' },
  { id: 'motion', label: 'Motion' },
  { id: 'discover', label: 'Discover' },
  { id: 'spectrum', label: 'Spectrum' },
  { id: 'compare', label: 'Compare' },
  { id: 'notebook', label: 'Notebook' },
  { id: 'guide', label: 'Guide' },
]
export default function Navbar({
  view,
  onView,
  settingsOpen,
  onToggleSettings,
  hasObservations,
}: {
  view: ViewName
  onView: (view: ViewName) => void
  settingsOpen: boolean
  onToggleSettings: () => void
  hasObservations: boolean
}) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-title">SKYFRAME OBSERVATORY</span>
      </div>
      <nav aria-label="Main navigation" className="nav-links">
        {items
          .filter(
            (item) =>
              hasObservations ||
              !['motion', 'discover', 'spectrum', 'compare'].includes(item.id),
          )
          .map((item) => (
            <button
              type="button"
              className={`nav-item ${view === item.id ? 'nav-item-active' : ''}`}
              key={item.id}
              onClick={() => onView(item.id)}
              aria-current={view === item.id ? 'page' : undefined}
            >
              {item.label}
            </button>
          ))}
      </nav>
      <button
        type="button"
        className={`settings-trigger ${settingsOpen ? 'settings-trigger-active' : ''}`}
        onClick={onToggleSettings}
        aria-pressed={settingsOpen}
        aria-label={
          settingsOpen ? 'Hide search and settings' : 'Show search and settings'
        }
      >
        {settingsOpen ? (
          <PanelLeftClose size={17} />
        ) : (
          <PanelLeftOpen size={17} />
        )}
        <SlidersHorizontal size={16} />
        <span>Settings</span>
      </button>
    </header>
  )
}
