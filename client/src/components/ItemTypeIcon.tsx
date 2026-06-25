/* Small monochrome icon denoting an item's type (currentColor). */
export function ItemTypeIcon({ type, className }: { type?: string; className?: string }) {
  const common = {
    width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.5,
    strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
    className,
  }
  switch (type) {
    case 'Equipment': // shield
      return <svg {...common}><path d="M12 3l7 3v5c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6l7-3z" /></svg>
    case 'Tool': // wrench
      return <svg {...common}><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.7 2.7-2-2 2.7-2.7z" /></svg>
    case 'Consumable': // flask
      return <svg {...common}><path d="M9 3h6M10 3.5v4.6L5.6 16a2 2 0 0 0 1.8 3h9.2a2 2 0 0 0 1.8-3L14 8.1V3.5" /><path d="M7.5 14h9" /></svg>
    case 'Key Item': // key
      return <svg {...common}><circle cx="8.5" cy="8.5" r="4.5" /><path d="M11.8 11.8 20 20M16.5 16.5l2-2" /></svg>
    case 'Artifact': // gem
      return <svg {...common}><path d="M12 3l8 7-8 11L4 10z" /><path d="M4 10h16M9 4l-2 6 5 11 5-11-2-6" /></svg>
    default: // box
      return <svg {...common}><rect x="4" y="4" width="16" height="16" rx="1" /></svg>
  }
}
