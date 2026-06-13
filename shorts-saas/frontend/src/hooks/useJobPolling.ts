import { useEffect, useRef } from 'react'
import { useProjectStore } from '../stores/projectStore'

export function useJobPolling(jobId: string | null, onComplete?: () => void) {
  const pollJob = useProjectStore((s) => s.pollJob)
  const currentJob = useProjectStore((s) => s.currentJob)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!jobId) return

    intervalRef.current = setInterval(async () => {
      const job = await pollJob(jobId)
      if (job.status === 'completed' || job.status === 'failed') {
        if (intervalRef.current) clearInterval(intervalRef.current)
        onComplete?.()
      }
    }, 2000)

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [jobId, pollJob, onComplete])

  return currentJob
}
