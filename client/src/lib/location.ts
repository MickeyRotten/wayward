import type { ChatMessage } from '@shared/types/models'

export const DEFAULT_LOCATION = 'The Void'

/**
 * Derive the current scene location from chat history. The Narrator declares
 * the location via a parsed action field, stored on the assistant message; the
 * current location is the most recently declared one. Falls back to a vague
 * default before the Narrator has established anywhere.
 */
export function deriveCurrentLocation(messages: ChatMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const loc = messages[i].location
    if (loc && loc.trim()) return loc.trim()
  }
  return DEFAULT_LOCATION
}
