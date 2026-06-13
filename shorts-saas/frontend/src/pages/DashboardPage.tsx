import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import { useProjectStore } from '../stores/projectStore'

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-600',
  storyboard_ready: 'bg-yellow-600',
  rendering: 'bg-blue-600',
  completed: 'bg-green-600',
  failed: 'bg-red-600',
}

export default function DashboardPage() {
  const { user, logout, loadUser } = useAuthStore()
  const { projects, fetchProjects, deleteProject, loading } = useProjectStore()
  const navigate = useNavigate()

  useEffect(() => {
    loadUser()
    fetchProjects()
  }, [loadUser, fetchProjects])

  return (
    <div className="max-w-5xl mx-auto p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">My Projects</h1>
          {user && (
            <p className="text-gray-400 text-sm">
              {user.display_name} &middot; {user.credits_remaining} credits
            </p>
          )}
        </div>
        <div className="flex gap-3">
          <Link
            to="/new"
            className="px-5 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-semibold transition"
          >
            + New Short
          </Link>
          <button
            onClick={logout}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition"
          >
            Logout
          </button>
        </div>
      </div>

      {/* Project list */}
      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : projects.length === 0 ? (
        <div className="text-center py-20">
          <p className="text-gray-500 text-lg mb-4">No projects yet</p>
          <Link
            to="/new"
            className="px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-semibold transition"
          >
            Create your first Short
          </Link>
        </div>
      ) : (
        <div className="grid gap-4">
          {projects.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between p-4 bg-gray-900 rounded-xl hover:bg-gray-800 transition cursor-pointer"
              onClick={() => navigate(`/project/${p.id}`)}
            >
              <div>
                <h3 className="font-semibold">{p.title || 'Untitled'}</h3>
                <p className="text-gray-400 text-sm">
                  {p.topic || 'No topic'} &middot; {p.duration_preset}s &middot;{' '}
                  {new Date(p.created_at).toLocaleDateString()}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <span
                  className={`px-3 py-1 rounded-full text-xs font-medium ${STATUS_COLORS[p.status] || 'bg-gray-600'}`}
                >
                  {p.status}
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    if (confirm('Delete this project?')) deleteProject(p.id)
                  }}
                  className="text-gray-500 hover:text-red-400 transition"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
