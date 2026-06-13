import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useProjectStore, Voice } from '../stores/projectStore'

export default function NewProjectPage() {
  const navigate = useNavigate()
  const { createProject, generateStoryboard, importJson, voices, fetchVoices } = useProjectStore()

  const [mode, setMode] = useState<'ai' | 'json'>('ai')
  const [title, setTitle] = useState('')
  const [topic, setTopic] = useState('')
  const [category, setCategory] = useState('general')
  const [language, setLanguage] = useState('es')
  const [duration, setDuration] = useState(60)
  const [voiceId, setVoiceId] = useState('es-ES-AlvaroNeural')
  const [jsonText, setJsonText] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (voices.length === 0) fetchVoices()
  }, [voices.length, fetchVoices])

  // Filter voices by selected language
  const langPrefix = language === 'en' ? 'en-' : language === 'pt' ? 'pt-' : language === 'fr' ? 'fr-' : 'es-'
  const filteredVoices = voices.filter((v: Voice) =>
    v.language?.toLowerCase().startsWith(langPrefix) ||
    v.id?.toLowerCase().startsWith(langPrefix)
  )

  // Auto-select first voice when language changes
  useEffect(() => {
    if (filteredVoices.length > 0 && !filteredVoices.find((v: Voice) => v.id === voiceId)) {
      setVoiceId(filteredVoices[0].id)
    }
  }, [language, filteredVoices, voiceId])

  const handleCreate = async () => {
    setError('')
    setLoading(true)
    try {
      const project = await createProject({
        title: title || topic || 'Untitled',
        topic,
        category,
        language,
        duration_preset: duration,
        voice_id: voiceId,
      })

      if (mode === 'ai') {
        await generateStoryboard(project.id, topic, category, language, duration)
      } else {
        const parsed = JSON.parse(jsonText)
        await importJson(project.id, parsed, voiceId, language)
      }

      navigate(`/project/${project.id}`)
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message || 'Error creating project'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">New Short</h1>

      {/* Mode selector */}
      <div className="flex gap-3 mb-6">
        <button
          onClick={() => setMode('ai')}
          className={`flex-1 py-3 rounded-lg font-semibold transition ${
            mode === 'ai' ? 'bg-blue-600' : 'bg-gray-800 hover:bg-gray-700'
          }`}
        >
          AI Generate
        </button>
        <button
          onClick={() => setMode('json')}
          className={`flex-1 py-3 rounded-lg font-semibold transition ${
            mode === 'json' ? 'bg-blue-600' : 'bg-gray-800 hover:bg-gray-700'
          }`}
        >
          Import JSON
        </button>
      </div>

      <div className="space-y-4">
        <input
          type="text"
          placeholder="Title (optional)"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="w-full px-4 py-3 bg-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />

        {mode === 'ai' ? (
          <>
            <input
              type="text"
              placeholder="Topic (e.g. 'History of the Roman Empire')"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              required
              className="w-full px-4 py-3 bg-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <div className="grid grid-cols-3 gap-3">
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="px-4 py-3 bg-gray-800 rounded-lg focus:outline-none"
              >
                <option value="general">General</option>
                <option value="education">Education</option>
                <option value="entertainment">Entertainment</option>
                <option value="technology">Technology</option>
                <option value="history">History</option>
                <option value="science">Science</option>
                <option value="business">Business</option>
              </select>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="px-4 py-3 bg-gray-800 rounded-lg focus:outline-none"
              >
                <option value="es">Spanish</option>
                <option value="en">English</option>
                <option value="pt">Portuguese</option>
                <option value="fr">French</option>
              </select>
              <select
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="px-4 py-3 bg-gray-800 rounded-lg focus:outline-none"
              >
                <option value={15}>15s</option>
                <option value={30}>30s</option>
                <option value={45}>45s</option>
                <option value={60}>60s</option>
              </select>
            </div>
          </>
        ) : (
          <textarea
            placeholder='Paste your JSON script here...\n{"segments": [{"text": "...", "visual_prompt": "..."}]}'
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            rows={10}
            className="w-full px-4 py-3 bg-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-sm"
          />
        )}

        {/* Voice selection */}
        <div>
          <label className="block text-sm font-semibold text-gray-400 mb-2">Voice</label>
          <select
            value={voiceId}
            onChange={(e) => setVoiceId(e.target.value)}
            className="w-full px-4 py-3 bg-gray-800 rounded-lg focus:outline-none"
          >
            {filteredVoices.length > 0 ? (
              filteredVoices.map((v: Voice) => (
                <option key={v.id} value={v.id}>
                  {v.name} {v.gender ? `(${v.gender})` : ''}
                </option>
              ))
            ) : (
              <option value={voiceId}>{voiceId}</option>
            )}
          </select>
        </div>

        {error && <p className="text-red-400 text-sm">{error}</p>}

        <div className="flex gap-3">
          <button
            onClick={() => navigate('/')}
            className="px-6 py-3 bg-gray-700 hover:bg-gray-600 rounded-lg transition"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={loading || (mode === 'ai' && !topic)}
            className="flex-1 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-semibold transition disabled:opacity-50"
          >
            {loading ? 'Creating...' : 'Create & Generate'}
          </button>
        </div>
      </div>
    </div>
  )
}
