import { describe, expect, it } from 'vitest'
import { weatherKind } from './weather'

describe('weatherKind', () => {
  it('maps the basic kinds', () => {
    expect(weatherKind('Light rain')).toBe('rain')
    expect(weatherKind('Thunderstorm rolling in')).toBe('storm')
    expect(weatherKind('Gentle snowfall')).toBe('snow')
    expect(weatherKind('Thick fog')).toBe('fog')
  })

  it('snowstorm/blizzard beat the generic storm words', () => {
    expect(weatherKind('Snowstorm')).toBe('snow')
    expect(weatherKind('Howling blizzard')).toBe('snow')
  })

  it('sand and dust read as drifting haze, not rain', () => {
    expect(weatherKind('Sandstorm')).toBe('fog')
    expect(weatherKind('Dust on the wind')).toBe('fog')
  })

  it('clear or unknown weather yields no effect', () => {
    expect(weatherKind('Clear skies')).toBeNull()
    expect(weatherKind('')).toBeNull()
    expect(weatherKind(null)).toBeNull()
    expect(weatherKind(undefined)).toBeNull()
  })
})
