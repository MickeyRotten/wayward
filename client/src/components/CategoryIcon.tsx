/* Small monochrome icon for a lorebook category (currentColor). */
export function CategoryIcon({ cat, className }: { cat: string; className?: string }) {
  const common = {
    width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.5,
    strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
    className,
  }
  switch (cat) {
    case 'pillars': // classical columns (world rules)
      return <svg {...common}><path d="M3 8l9-4 9 4M4 8v9M9 8v9M15 8v9M20 8v9M3 21h18M3 17h18" /></svg>
    case 'world': // map pin (locations)
      return <svg {...common}><path d="M12 21s7-6.3 7-11a7 7 0 0 0-14 0c0 4.7 7 11 7 11z" /><circle cx="12" cy="10" r="2.5" /></svg>
    case 'species': // fanged maw
      return <svg {...common}><path d="M4 8a8 8 0 0 1 16 0v5a7 7 0 0 1-16 0z" /><path d="M8 13l1.5 3 1.5-3 1.5 3 1.5-3 1.5 3 1.5-3" /></svg>
    case 'spells': // sparkle
      return <svg {...common}><path d="M12 3l1.6 5.4L19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6z" /></svg>
    default: // book
      return <svg {...common}><path d="M5 4.5A2 2 0 0 1 7 3h12v16H7a2 2 0 0 0-2 2z" /><path d="M5 4.5V21" /></svg>
  }
}
