import { useCallback, useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useProjectStore } from '../stores/projectStore'
import { useJobPolling } from '../hooks/useJobPolling'
import JobProgress from '../components/JobProgress'
import SceneEditor from '../components/SceneEditor'
import VoiceSelector from '../components/VoiceSelector'
import SubtitleStyleSelector from '../components/SubtitleStyleSelector'

export default function ProjectEditorPage() {
  const { id } = useParams<{ id: string }>()
  const {
    currentProject,
    currentJob,
    fetchProject,
    updateProject,
    generateImages,
    generateTts,
    assembleVideo,
  } = useProjectStore()

  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)

  useEffect(() => {
    if (id) fetchProject(id)
  }, [id, fetchProject])

  const onJobComplete = useCallback(() => {
    if (id) fetchProject(id)
    setActiveJobId(null)
  }, [id, fetchProject])

  useJobPolling(activeJobId, onJobComplete)

  if (!currentProject) {
    return <div className="p-6 text-gray-400">Loading project...</div>
  }

  const storyboard = currentProject.storyboard_data as Record<string, unknown> | null
  const segments = storyboard?.segments as Array<Record<string, unknown>> | undefined
  const ttsOutdated = storyboard?.tts_outdated === true
  const hasAudio = !!storyboard?.audio_path

  const handleGenerateImages = async () => {
    if (!id) return
    const job = await generateImages(id)
    setActiveJobId(job.id)
  }

  const handleGenerateTts = async () => {
    if (!id) return
    const job = await generateTts(id)
    setActiveJobId(job.id)
  }

  const handleAssemble = async () => {
    if (!id) return
    if (ttsOutdated) {
      const ok = window.confirm(
        'The narration text was edited after TTS was generated.\n\n' +
        'The voice and subtitles will be OUT OF SYNC.\n\n' +
        'Regenerate TTS first?'
      )
      if (ok) {
        const job = await generateTts(id)
        setActiveJobId(job.id)
        return
      }
    }
    const job = await assembleVideo(id)
    setActiveJobId(job.id)
  }

  const handleVoiceChange = async (voiceId: string) => {
    if (!id) return
    await updateProject(id, { voice_id: voiceId } as Partial<typeof currentProject>)
  }

  const handleSubtitleStyleChange = async (style: string) => {
    if (!id) return
    await updateProject(id, { subtitle_style: style } as Partial<typeof currentProject>)
  }

  const storyboardTitle = storyboard?.title as string | undefined

  return (
    <div className="max-w-4xl mx-auto p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <Link to="/" className="text-gray-400 hover:text-white text-sm">&larr; Back</Link>
          <h1 className="text-2xl font-bold">{storyboardTitle || currentProject.title}</h1>
          <p className="text-gray-400 text-sm">
            {currentProject.topic} &middot; {currentProject.duration_preset}s &middot;{' '}
            <span className={
              currentProject.status === 'completed' ? 'text-green-400' :
              currentProject.status === 'failed' ? 'text-red-400' :
              'text-yellow-400'
            }>
              {currentProject.status}
            </span>
          </p>
        </div>
        <button
          onClick={() => setShowSettings(!showSettings)}
          className={`px-4 py-2 rounded-lg text-sm font-semibold transition ${
            showSettings ? 'bg-gray-600' : 'bg-gray-800 hover:bg-gray-700'
          }`}
        >
          Settings
        </button>
      </div>

      {/* TTS outdated warning */}
      {ttsOutdated && hasAudio && (
        <div className="mb-4 p-3 bg-yellow-900/40 border border-yellow-600 rounded-lg flex items-center justify-between">
          <p className="text-yellow-300 text-sm">
            Text was edited after TTS generation. Regenerate TTS to keep voice and subtitles in sync.
          </p>
          <button
            onClick={handleGenerateTts}
            disabled={!!activeJobId}
            className="px-3 py-1 bg-yellow-600 hover:bg-yellow-700 rounded text-xs font-semibold transition disabled:opacity-50 flex-shrink-0 ml-3"
          >
            Regenerate TTS
          </button>
        </div>
      )}

      {/* Settings panel */}
      {showSettings && (
        <div className="mb-6 p-5 bg-gray-900 rounded-xl space-y-5 border border-gray-800">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <VoiceSelector
              language={currentProject.language}
              value={currentProject.voice_id}
              onChange={handleVoiceChange}
            />
            <div className="space-y-2">
              <label className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Info</label>
              <div className="text-sm text-gray-300 space-y-1">
                <p>Language: <span className="text-white font-medium">{currentProject.language}</span></p>
                <p>Platform: <span className="text-white font-medium">{currentProject.platform}</span></p>
                <p>Voice: <span className="text-white font-medium">{currentProject.voice_id}</span></p>
                <p>Subtitles: <span className="text-white font-medium">{currentProject.subtitle_style}</span></p>
              </div>
            </div>
          </div>
          <SubtitleStyleSelector
            value={currentProject.subtitle_style}
            onChange={handleSubtitleStyleChange}
          />
        </div>
      )}

      {/* Active job progress */}
      {activeJobId && currentJob && (
        <JobProgress job={currentJob} />
      )}

      {/* Pipeline actions */}
      <div className="flex gap-3 mb-6 flex-wrap">
        <button
          onClick={handleGenerateImages}
          disabled={!!activeJobId || !segments}
          className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-semibold transition disabled:opacity-50"
        >
          Generate Images
        </button>
        <button
          onClick={handleGenerateTts}
          disabled={!!activeJobId || !segments}
          className={`px-4 py-2 rounded-lg text-sm font-semibold transition disabled:opacity-50 ${
            ttsOutdated && hasAudio
              ? 'bg-yellow-600 hover:bg-yellow-700 ring-2 ring-yellow-400'
              : 'bg-green-600 hover:bg-green-700'
          }`}
        >
          {ttsOutdated && hasAudio ? 'Regenerate TTS' : 'Generate TTS'}
        </button>
        <button
          onClick={handleAssemble}
          disabled={!!activeJobId || !segments}
          className="px-4 py-2 bg-orange-600 hover:bg-orange-700 rounded-lg text-sm font-semibold transition disabled:opacity-50"
        >
          Assemble Video
        </button>
        {currentProject.status === 'completed' && currentProject.output_video_path && (
          <a
            href={`/api/media/projects/${currentProject.id}/download`}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-semibold transition"
          >
            Download MP4
          </a>
        )}
      </div>

      {/* Scene list */}
      {segments ? (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold">
            Scenes ({segments.length})
            <span className="text-xs text-gray-500 font-normal ml-2">Click any scene to edit</span>
          </h2>
          {segments.map((seg, idx) => (
            <SceneEditor
              key={idx}
              index={idx}
              segment={seg}
              projectId={currentProject.id}
            />
          ))}
        </div>
      ) : (
        <div className="text-center py-12 text-gray-500">
          <p>Generating storyboard... check the progress above.</p>
        </div>
      )}
    </div>
  )
}
