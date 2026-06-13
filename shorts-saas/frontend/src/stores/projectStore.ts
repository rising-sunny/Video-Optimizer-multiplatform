import { create } from 'zustand'
import api from '../api/client'

export interface Project {
  id: string
  title: string
  topic: string
  category: string
  language: string
  duration_preset: number
  platform: string
  voice_id: string
  subtitle_style: string
  image_provider: string
  storyboard_data: Record<string, unknown> | null
  status: string
  output_video_path: string | null
  created_at: string
  updated_at: string
}

export interface Job {
  id: string
  project_id: string
  job_type: string
  status: string
  progress: number
  error_message: string | null
  logs: string[]
  created_at: string
}

export interface Voice {
  id: string
  name: string
  language: string
  provider: string
  gender?: string
}

export interface SubtitleStyleInfo {
  name: string
  karaoke: boolean
  animation: string
}

interface ProjectState {
  projects: Project[]
  currentProject: Project | null
  currentJob: Job | null
  loading: boolean
  voices: Voice[]
  subtitleStyles: Record<string, SubtitleStyleInfo>
  fetchProjects: () => Promise<void>
  createProject: (data: Partial<Project>) => Promise<Project>
  fetchProject: (id: string) => Promise<void>
  updateProject: (id: string, data: Partial<Project>) => Promise<void>
  deleteProject: (id: string) => Promise<void>
  generateStoryboard: (id: string, topic: string, category: string, language: string, duration: number) => Promise<Job>
  importJson: (id: string, scriptJson: Record<string, unknown>, voiceId: string, language: string) => Promise<Job>
  generateImages: (id: string) => Promise<Job>
  generateTts: (id: string) => Promise<Job>
  assembleVideo: (id: string) => Promise<Job>
  pollJob: (jobId: string) => Promise<Job>
  fetchVoices: () => Promise<void>
  fetchSubtitleStyles: () => Promise<void>
  updateStoryboardSegment: (id: string, segmentIndex: number, updates: Record<string, unknown>) => Promise<void>
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projects: [],
  currentProject: null,
  currentJob: null,
  loading: false,
  voices: [],
  subtitleStyles: {},

  fetchProjects: async () => {
    set({ loading: true })
    const { data } = await api.get('/projects')
    set({ projects: data, loading: false })
  },

  createProject: async (projectData) => {
    const { data } = await api.post('/projects', projectData)
    set((s) => ({ projects: [data, ...s.projects] }))
    return data
  },

  fetchProject: async (id) => {
    const { data } = await api.get(`/projects/${id}`)
    set({ currentProject: data })
  },

  updateProject: async (id, projectData) => {
    const { data } = await api.put(`/projects/${id}`, projectData)
    set({ currentProject: data })
  },

  deleteProject: async (id) => {
    await api.delete(`/projects/${id}`)
    set((s) => ({ projects: s.projects.filter((p) => p.id !== id) }))
  },

  generateStoryboard: async (id, topic, category, language, duration) => {
    const { data } = await api.post(`/projects/${id}/generate-storyboard`, {
      topic, category, language, duration,
    })
    set({ currentJob: data })
    return data
  },

  importJson: async (id, scriptJson, voiceId, language) => {
    const { data } = await api.post(`/projects/${id}/import-json`, {
      script_json: scriptJson, voice_id: voiceId, language,
    })
    set({ currentJob: data })
    return data
  },

  generateImages: async (id) => {
    const { data } = await api.post(`/projects/${id}/generate-images`)
    set({ currentJob: data })
    return data
  },

  generateTts: async (id) => {
    const { data } = await api.post(`/projects/${id}/generate-tts`)
    set({ currentJob: data })
    return data
  },

  assembleVideo: async (id) => {
    const { data } = await api.post(`/projects/${id}/assemble`)
    set({ currentJob: data })
    return data
  },

  pollJob: async (jobId) => {
    const { data } = await api.get(`/jobs/${jobId}`)
    set({ currentJob: data })
    return data
  },

  fetchVoices: async () => {
    try {
      const { data } = await api.get('/tts/voices')
      const raw = data.voices || {}
      const voiceList: Voice[] = Object.values(raw).map((v: unknown) => {
        const voice = v as Record<string, string>
        return {
          id: voice.id || voice.voice_id || '',
          name: voice.name || voice.id || '',
          language: voice.language || '',
          provider: voice.provider || 'edge-tts',
          gender: voice.gender || '',
        }
      })
      set({ voices: voiceList })
    } catch {
      set({ voices: [] })
    }
  },

  fetchSubtitleStyles: async () => {
    try {
      const { data } = await api.get('/tts/subtitle-styles')
      set({ subtitleStyles: data.styles || {} })
    } catch {
      set({ subtitleStyles: {} })
    }
  },

  updateStoryboardSegment: async (id, segmentIndex, updates) => {
    const project = get().currentProject
    if (!project?.storyboard_data) return
    const storyboard = { ...project.storyboard_data }
    const segments = [...(storyboard.segments as Array<Record<string, unknown>>)]
    const oldText = segments[segmentIndex].text
    segments[segmentIndex] = { ...segments[segmentIndex], ...updates }
    storyboard.segments = segments
    // Mark TTS as outdated if narration text changed and audio already exists
    if (updates.text !== undefined && updates.text !== oldText && storyboard.audio_path) {
      storyboard.tts_outdated = true
    }
    const { data } = await api.put(`/projects/${id}`, { storyboard_data: storyboard })
    set({ currentProject: data })
  },
}))
