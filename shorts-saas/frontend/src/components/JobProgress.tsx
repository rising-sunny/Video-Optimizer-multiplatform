interface Job {
  id: string
  job_type: string
  status: string
  progress: number
  error_message: string | null
  logs: string[]
}

export default function JobProgress({ job }: { job: Job }) {
  const isRunning = job.status === 'running' || job.status === 'queued'
  const isFailed = job.status === 'failed'

  return (
    <div className={`mb-6 p-4 rounded-xl ${isFailed ? 'bg-red-900/30' : 'bg-gray-900'}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-sm">
          {job.job_type.replace(/_/g, ' ')}
        </span>
        <span className={`text-xs font-medium px-2 py-1 rounded-full ${
          isRunning ? 'bg-blue-600' : isFailed ? 'bg-red-600' : 'bg-green-600'
        }`}>
          {job.status}
        </span>
      </div>

      {/* Progress bar */}
      {isRunning && (
        <div className="w-full bg-gray-700 rounded-full h-2 mb-3">
          <div
            className="bg-blue-500 h-2 rounded-full transition-all duration-500"
            style={{ width: `${job.progress}%` }}
          />
        </div>
      )}

      {/* Error */}
      {isFailed && job.error_message && (
        <p className="text-red-400 text-sm mb-2">{job.error_message}</p>
      )}

      {/* Logs */}
      {job.logs.length > 0 && (
        <div className="bg-gray-950 rounded-lg p-3 max-h-40 overflow-y-auto">
          {job.logs.map((line, i) => (
            <p key={i} className="text-xs text-gray-400 font-mono">{line}</p>
          ))}
        </div>
      )}
    </div>
  )
}
