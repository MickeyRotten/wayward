import { describe, expect, it } from 'vitest'
import { PHASES, daylightToken, phaseEmoji, sunShape } from './clock'

describe('clock phases', () => {
  it('gives every server phase word a daylight bucket and an icon', () => {
    for (const p of PHASES) {
      expect(daylightToken(p), p).not.toBeNull()
      expect(sunShape(p), p).not.toBeNull()
      expect(phaseEmoji(p), p).not.toBe('')
    }
  })

  it('keeps the legacy freeform values working', () => {
    expect(daylightToken('Day')).toBe('day')
    expect(daylightToken('Night')).toBe('night')
    expect(sunShape('Morning')).toBe('sunrise')
  })

  it('returns null for something that is not a time', () => {
    expect(daylightToken('a cold drizzle')).toBeNull()
    expect(daylightToken(null)).toBeNull()
    expect(phaseEmoji(undefined)).toBe('')
  })

  it('reads the dark phases as night', () => {
    expect(daylightToken('late night')).toBe('night')
    expect(daylightToken('dusk')).toBe('night')
    expect(daylightToken('dawn')).toBe('day')
  })
})
