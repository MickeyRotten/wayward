import { describe, expect, it } from 'vitest'
import { RARITY_ORDER, sortList } from './sortEntries'
import type { Rarity } from '@shared/types/models'

interface Row { name?: string; type?: string; rarity?: Rarity }

const rows: Row[] = [
  { name: 'Sword', type: 'Equipment', rarity: 'r' },
  { name: 'Apple', type: 'Consumable', rarity: 'c' },
  { name: 'Zither', type: 'Tool', rarity: 'l' },
]

const get = {
  name: (x: Row) => x.name ?? '',
  type: (x: Row) => x.type ?? '',
  rarity: (x: Row) => RARITY_ORDER[x.rarity ?? 'c'],
}

describe('sortList', () => {
  it('newest keeps insertion order; desc reverses it', () => {
    expect(sortList(rows, 'newest', true, get)).toEqual(rows)
    expect(sortList(rows, 'newest', false, get)).toEqual([...rows].reverse())
  })

  it('sorts alphabetically', () => {
    expect(sortList(rows, 'alpha', true, get).map((r) => r.name)).toEqual(['Apple', 'Sword', 'Zither'])
  })

  it('sorts by rarity c→l', () => {
    expect(sortList(rows, 'rarity', true, get).map((r) => r.rarity)).toEqual(['c', 'r', 'l'])
  })

  it('missing fields never throw (the by-type blank-panel regression)', () => {
    const messy: Row[] = [{ name: 'A' }, { type: 'Tool' }, {}]
    expect(() => sortList(messy, 'type', true, get)).not.toThrow()
    expect(() => sortList(messy, 'alpha', true, get)).not.toThrow()
  })
})
