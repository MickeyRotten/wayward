/** Map the narrator-declared freeform weather ("Light rain", "Snowstorm",
 *  "Thick fog rolling in") onto the effect the chat renders over the backdrop.
 *  Order matters: "snowstorm"/"blizzard" must win over the generic storm words,
 *  and sand/dust reads as drifting haze, not rain. */
export type WeatherKind = 'rain' | 'storm' | 'snow' | 'fog'

const KINDS: [WeatherKind, string[]][] = [
  ['snow', ['snow', 'blizzard', 'flurr', 'sleet', 'hail', 'wintry']],
  ['fog', ['sandstorm', 'dust', 'fog', 'mist', 'haz', 'smog', 'murk']],
  ['storm', ['thunder', 'lightning', 'storm', 'tempest', 'squall']],
  ['rain', ['rain', 'drizzl', 'shower', 'downpour', 'monsoon', 'pouring']],
]

export function weatherKind(weather: string | null | undefined): WeatherKind | null {
  if (!weather) return null
  const w = weather.toLowerCase()
  for (const [kind, words] of KINDS) {
    if (words.some((t) => w.includes(t))) return kind
  }
  return null
}
