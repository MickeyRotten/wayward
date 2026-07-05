# Mobile / Responsive UI — Design

**Date:** 2026-07-06 · **Status:** approved ("Make it so")

## Problem

The app shell is a fixed 4-column grid (`66px rail | 288px left panel | chat |
344px inspector`) with zero responsive breakpoints. ~700px of fixed chrome
makes the app unusable below ~1100px and completely broken on phones.

## Decision

A dedicated **MobileShell** (Approach A), chosen at runtime by a
`useIsMobile()` matchMedia hook. Every existing panel component is reused
unchanged; only the layout container differs.

- **Breakpoint:** `<1024px` → MobileShell; `≥1024px` → existing `AppShell`,
  pixel-identical. Portrait tablets get the mobile UI (desktop grid would
  leave chat ~330px there).

## MobileShell

Vertical flex, full height:

- **Main area** — one view at a time: Chat (default) or a panel view.
  Panels are the same components the desktop left column renders.
- **Bottom nav** (~56px + `env(safe-area-inset-bottom)`):
  `CHAT · HOME · ITEMS · LORE · MORE`. **More** opens a bottom sheet with
  Tasks, Ideas, Saves, Config. Ideas' pending badge shows on the sheet item
  and rolls up onto the More button.
- **State:** `uiStore` gains `mobileView: 'chat' | TabId` (+ setter).
  Desktop ignores it. Default `'chat'`.

## Inspector on mobile

Full-screen slide-over rendered whenever `uiStore.selection !== null`, with a
`← Back` header calling `select(null)`. Contains the same `PartyInspector`.
Preserves tap→inspect→edit everywhere including Edit Mode — full parity,
nothing mobile-disabled.

## Platform fixes

- `100dvh` heights (address-bar collapse) with `100%` fallback.
- Viewport meta: `viewport-fit=cover, interactive-widget=resizes-content`.
- Safe-area padding on the bottom nav.
- `ConfirmDialog` fixed `w-[360px]` → add `max-w-[calc(100vw-2rem)]`.
- Chat banner (location/day/time/Play toggle) truncation/compression at
  narrow widths; touch targets ≥44px in the nav.

## Untouched

Stores' data flow, all server code, desktop rendering.

## Verification

Playwright at 390×844 (phone) and 1440×900 (desktop): both shells render,
bottom nav switches views, More sheet opens, inspector slide-over opens/closes,
chat input usable, desktop unchanged.
