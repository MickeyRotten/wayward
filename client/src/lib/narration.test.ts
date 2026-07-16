import { describe, expect, it } from 'vitest'
import type { PartyMember } from '@shared/types/models'
import { buildMemberResolver, parseSegments } from './narration'

function member(name: string, inParty = true): PartyMember {
  return {
    id: `id-${name.toLowerCase().replace(/\s+/g, '-')}`,
    schemaVersion: 1,
    basicInfo: { name, gender: '', species: '', age: 0, heightCm: 0, weightKg: 0, description: '' },
    fieldSkill: { name: '', description: '' },
    equipment: {} as PartyMember['equipment'],
    lastSpokeTurn: 0,
    inParty,
  } as PartyMember
}

const resolver = buildMemberResolver([member('Tifa Lockhart'), member('Varena')])

describe('buildMemberResolver', () => {
  it('keys by full and first name, in-party only', () => {
    expect(resolver.get('tifa lockhart')?.name).toBe('Tifa Lockhart')
    expect(resolver.get('tifa')?.name).toBe('Tifa Lockhart')
    expect(buildMemberResolver([member('Benched', false)]).size).toBe(0)
  })
})

describe('parseSegments', () => {
  it('turns a member "Name: ..." line into a dialogue block', () => {
    const segs = parseSegments('Varena: "Stay close to me."', resolver)
    expect(segs).toEqual([
      { type: 'dialogue', member: expect.objectContaining({ name: 'Varena' }), text: '"Stay close to me."' },
    ])
  })

  it('leaves unknown NPC "Name: ..." lines as narration', () => {
    const segs = parseSegments('Innkeeper: "No rooms tonight."', resolver)
    expect(segs).toEqual([{ type: 'narration', text: 'Innkeeper: "No rooms tonight."' }])
  })

  it('keeps interleaved attribution inside one dialogue beat (last-quote rule)', () => {
    const line = 'Varena: "Deer are thick this year. Or," she adds, "there\'s always goblins."'
    const segs = parseSegments(line, resolver)
    expect(segs).toHaveLength(1)
    expect(segs[0].type).toBe('dialogue')
    expect((segs[0] as { text: string }).text).toContain('always goblins.')
  })

  it('splits a pure trailing tag out of the dialogue box', () => {
    const segs = parseSegments('Varena: "We should move." she said, softly.', resolver)
    expect(segs[0]).toEqual({
      type: 'dialogue',
      member: expect.objectContaining({ name: 'Varena' }),
      text: '"We should move."',
    })
    expect(segs[1]).toEqual({ type: 'narration', text: 'she said, softly.' })
  })

  it('parses blockquotes and dividers', () => {
    const segs = parseSegments('The sign reads:\n> KEEP OUT\n\n* * *\n\nDawn comes.', resolver)
    expect(segs.map((s) => s.type)).toEqual(['narration', 'blockquote', 'divider', 'narration'])
    expect(segs[1]).toEqual({ type: 'blockquote', text: 'KEEP OUT' })
  })

  it('is robust to single- and double-newline paragraphs', () => {
    const single = parseSegments('First beat.\nStill first beat.', resolver)
    expect(single).toEqual([{ type: 'narration', text: 'First beat.\nStill first beat.' }])
    const double = parseSegments('First beat.\n\nSecond beat.', resolver)
    expect(double.map((s) => s.type)).toEqual(['narration', 'narration'])
  })
})
