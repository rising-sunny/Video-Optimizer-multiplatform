import { useEffect, useMemo, useState } from 'react'
import { useProjectStore, Voice } from '../stores/projectStore'

interface Props {
  language: string
  value: string
  onChange: (voiceId: string) => void
}

export default function VoiceSelector({ language, value, onChange }: Props) {
  const { voices, fetchVoices } = useProjectStore()
  const [search, setSearch] = useState('')

  useEffect(() => {
    if (voices.length === 0) fetchVoices()
  }, [voices.length, fetchVoices])

  const langPrefix = language === 'en' ? 'en-' : language === 'pt' ? 'pt-' : language === 'fr' ? 'fr-' : 'es-'

  const filtered = useMemo(() => {
    let list = voices.filter((v: Voice) =>
      v.language?.toLowerCase().startsWith(langPrefix) ||
      v.id?.toLowerCase().startsWith(langPrefix)
    )
    if (search) {
      const q = search.toLowerCase()
      list = list.filter((v: Voice) =>
        v.name.toLowerCase().includes(q) || v.id.toLowerCase().includes(q)
      )
    }
    return list.slice(0, 50)
  }, [voices, langPrefix, search])

  const selectedVoice = voices.find((v: Voice) => v.id === value)

  if (voices.length === 0) {
    return <div className="text-xs text-gray-500">Loading voices...</div>
  }

  return (
    <div className="space-y-2">
      <label className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Voice</label>
      <input
        type="text"
        placeholder="Search voices..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full px-3 py-2 bg-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
      />
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 bg-gray-800 rounded-lg text-sm focus:outline-none"
      >
        {selectedVoice && !filtered.find((v: Voice) => v.id === value) && (
          <option value={value}>{selectedVoice.name} (current)</option>
        )}
        {filtered.map((v: Voice) => (
          <option key={v.id} value={v.id}>
            {v.name} {v.gender ? `(${v.gender})` : ''}
          </option>
        ))}
      </select>
      {selectedVoice && (
        <p className="text-xs text-gray-500">
          {selectedVoice.provider} &middot; {selectedVoice.language}
        </p>
      )}
    </div>
  )
}
