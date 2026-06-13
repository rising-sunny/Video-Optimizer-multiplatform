import { useEffect } from 'react'
import { useProjectStore } from '../stores/projectStore'

// Human-friendly names and descriptions for each style
const STYLE_META: Record<string, { emoji: string; desc: string }> = {
  hormozi: { emoji: '🔥', desc: 'Yellow bold + karaoke + emojis' },
  mrbeast: { emoji: '🟢', desc: 'Green pop + karaoke + emojis' },
  tiktok: { emoji: '📱', desc: 'White + karaoke, viral style' },
  minimalist: { emoji: '✨', desc: 'Clean white, no karaoke' },
  documentary: { emoji: '🎬', desc: 'Subtle, professional' },
  gaming: { emoji: '🎮', desc: 'Green neon + karaoke' },
  news: { emoji: '📰', desc: 'Top bar, broadcast style' },
  cinematic: { emoji: '🎥', desc: 'Serif font, dramatic shadow' },
  neon: { emoji: '💜', desc: 'Magenta/cyan glow + karaoke' },
  retro: { emoji: '🕹️', desc: 'Monospace, 80s vibes' },
  elegant: { emoji: '👑', desc: 'Georgia serif, subtle' },
  bold: { emoji: '💪', desc: 'Impact XL + karaoke + emojis' },
  capcut_creator: { emoji: '🎨', desc: 'CapCut Creator Pro' },
  capcut_kinetic: { emoji: '⚡', desc: 'CapCut Kinetic, red accent' },
  capcut_focus: { emoji: '🎯', desc: 'CapCut Focus, centered' },
  capcut_podcast: { emoji: '🎙️', desc: 'CapCut Podcast, minimal' },
  capcut_luxury: { emoji: '💎', desc: 'CapCut Luxury, gold tone' },
}

interface Props {
  value: string
  onChange: (style: string) => void
}

export default function SubtitleStyleSelector({ value, onChange }: Props) {
  const { subtitleStyles, fetchSubtitleStyles } = useProjectStore()

  useEffect(() => {
    if (Object.keys(subtitleStyles).length === 0) fetchSubtitleStyles()
  }, [subtitleStyles, fetchSubtitleStyles])

  // Use dynamic_subtitles_generator styles (17 styles)
  const styleKeys = Object.keys(STYLE_META)

  return (
    <div className="space-y-2">
      <label className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
        Subtitle Style
      </label>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {styleKeys.map((key) => {
          const meta = STYLE_META[key]
          const isSelected = value === key
          return (
            <button
              key={key}
              onClick={() => onChange(key)}
              className={`px-3 py-2 rounded-lg text-left text-xs transition border ${
                isSelected
                  ? 'border-blue-500 bg-blue-900/40 text-white'
                  : 'border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-300'
              }`}
            >
              <span className="font-semibold">
                {meta.emoji} {key.replace(/_/g, ' ')}
              </span>
              <br />
              <span className="text-gray-500 text-[10px]">{meta.desc}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
