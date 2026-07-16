import { describe, expect, it } from 'vitest'
import { DEFAULT_BACKDROP, pickBackdrop, type Backdrop } from './backdrops'

const b = (file: string): Backdrop => ({ file, url: `/api/backdrops/${file}` })
const AVAILABLE = [b('forest_day.png'), b('forest_night.png'), b('city_day.png'), b('city_night.png')]

describe('pickBackdrop', () => {
  it('matches location and time tokens', () => {
    expect(pickBackdrop(AVAILABLE, 'City Market', 'Day')?.file).toBe('city_day.png')
    expect(pickBackdrop(AVAILABLE, 'City Market', 'Night')?.file).toBe('city_night.png')
  })

  it('maps narrator times onto day/night filename vocabulary', () => {
    expect(pickBackdrop(AVAILABLE, 'Deep Forest', 'Morning')?.file).toBe('forest_day.png')
    expect(pickBackdrop(AVAILABLE, 'Deep Forest', 'Evening')?.file).toBe('forest_night.png')
  })

  it('falls back to the default art when nothing matches', () => {
    expect(pickBackdrop(AVAILABLE, 'The Void', null)?.file).toBe(DEFAULT_BACKDROP)
  })

  it('falls back to the first file when the default is absent', () => {
    const noDefault = [b('city_day.png'), b('city_night.png')]
    expect(pickBackdrop(noDefault, 'The Void', null)?.file).toBe('city_day.png')
  })

  it('returns null with no art at all', () => {
    expect(pickBackdrop([], 'City', 'Day')).toBeNull()
  })
})
