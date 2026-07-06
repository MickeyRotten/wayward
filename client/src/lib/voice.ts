// Voice-sample upload helpers (multipart, so raw fetch like PortraitUpload).
// A sample is ~10s of clean speech used to clone the voice for TTS.

export async function uploadCharacterVoice(characterId: string, file: File): Promise<boolean> {
  const form = new FormData()
  form.append('file', file, file.name || 'voice.wav')
  const res = await fetch(`/api/characters/${characterId}/voice`, { method: 'POST', body: form })
  return res.ok
}

export async function deleteCharacterVoice(characterId: string): Promise<boolean> {
  const res = await fetch(`/api/characters/${characterId}/voice`, { method: 'DELETE' })
  return res.ok
}

export async function uploadNarratorVoice(file: File): Promise<boolean> {
  const form = new FormData()
  form.append('file', file, file.name || 'voice.wav')
  const res = await fetch('/api/narrator/voice', { method: 'POST', body: form })
  return res.ok
}

export async function deleteNarratorVoice(): Promise<boolean> {
  const res = await fetch('/api/narrator/voice', { method: 'DELETE' })
  return res.ok
}
