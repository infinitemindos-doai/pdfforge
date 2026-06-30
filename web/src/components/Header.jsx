export default function Header() {
  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="logo">
          <svg width="32" height="32" viewBox="0 0 64 64" fill="none">
            <rect width="64" height="64" rx="12" fill="#1a1a2e"/>
            <rect x="16" y="10" width="32" height="44" rx="3" fill="none" stroke="#00d4ff" stroke-width="3"/>
            <line x1="22" y1="22" x2="42" y2="22" stroke="#00d4ff" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="22" y1="30" x2="38" y2="30" stroke="#00d4ff" stroke-width="2.5" stroke-linecap="round"/>
            <rect x="22" y="38" width="8" height="8" rx="1.5" fill="none" stroke="#00d4ff" stroke-width="2.5"/>
            <line x1="34" y1="42" x2="42" y2="42" stroke="#00d4ff" stroke-width="2.5" stroke-linecap="round"/>
          </svg>
          <span className="logo-text">pdfforge</span>
        </div>
        <p className="tagline">Upload a flat PDF → detect fields → download fillable</p>
      </div>
    </header>
  )
}