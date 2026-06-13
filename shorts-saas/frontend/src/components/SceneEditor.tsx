import { useRef, useState } from 'react'
import api from '../api/client'
import { useProjectStore } from '../stores/projectStore'

interface Props {
  index: number
  segment: Record<string, unknown>
  projectId: string
}

export default function SceneEditor({ index, segment, projectId }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  const { updateStoryboardSegment } = useProjectStore()
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const [editPrompt, setEditPrompt] = useState('')
  const [saving, setSaving] = useState(false)

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    await api.post(`/projects/${projectId}/scenes/${index}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  }

  const text = (segment.text as string) || ''
  const visualPrompt = (segment.visual_prompt as string) || ''
  const imagePath = segment.image_path as string | undefined
  const mediaSource = (segment.media_source as string) || 'none'
  const duration = segment.duration as number | undefined

  const startEdit = () => {
    setEditText(text)
    setEditPrompt(visualPrompt)
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
  }

  const saveEdit = async () => {
    setSaving(true)
    try {
      await updateStoryboardSegment(projectId, index, {
        text: editText,
        visual_prompt: editPrompt,
      })
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="p-4 bg-gray-900 rounded-xl">
      <div className="flex gap-4">
        {/* Image preview */}
        <div className="w-32 h-32 bg-gray-800 rounded-lg flex-shrink-0 flex items-center justify-center overflow-hidden">
          {imagePath ? (
            <img
              src={imagePath.startsWith('/') || imagePath.startsWith('http') ? imagePath : `/api/media/${imagePath}`}
              alt={`Scene ${index + 1}`}
              className="w-full h-full object-cover"
            />
          ) : (
            <span className="text-gray-600 text-xs">No image</span>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-bold text-gray-500">Scene {index + 1}</span>
            {duration && (
              <span className="text-xs px-2 py-0.5 bg-gray-800 rounded-full text-gray-400">
                {duration.toFixed(1)}s
              </span>
            )}
            {mediaSource !== 'none' && (
              <span className="text-xs px-2 py-0.5 bg-gray-700 rounded-full">
                {mediaSource}
              </span>
            )}
          </div>

          {editing ? (
            <div className="space-y-2">
              <textarea
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                rows={3}
                className="w-full px-3 py-2 bg-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                placeholder="Narration text..."
              />
              <textarea
                value={editPrompt}
                onChange={(e) => setEditPrompt(e.target.value)}
                rows={2}
                className="w-full px-3 py-2 bg-gray-800 rounded-lg text-xs text-gray-300 focus:outline-none focus:ring-2 focus:ring-purple-500 resize-none"
                placeholder="Visual prompt for image generation..."
              />
              <div className="flex gap-2">
                <button
                  onClick={saveEdit}
                  disabled={saving}
                  className="px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-xs font-semibold transition disabled:opacity-50"
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
                <button
                  onClick={cancelEdit}
                  className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs transition"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div onClick={startEdit} className="cursor-pointer group">
              <p className="text-sm mb-1 group-hover:text-blue-300 transition">{text}</p>
              {visualPrompt && (
                <p className="text-xs text-gray-500 italic group-hover:text-gray-400 transition">{visualPrompt}</p>
              )}
              <span className="text-xs text-gray-600 group-hover:text-blue-400 transition">Click to edit</span>
            </div>
          )}
        </div>

        {/* Upload button */}
        <div className="flex-shrink-0">
          <input
            ref={fileRef}
            type="file"
            accept="image/*,video/*"
            onChange={handleUpload}
            className="hidden"
          />
          <button
            onClick={() => fileRef.current?.click()}
            className="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-xs transition"
          >
            Upload
          </button>
        </div>
      </div>
    </div>
  )
}
