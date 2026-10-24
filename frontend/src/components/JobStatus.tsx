import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Job } from '../api/types'

export function JobStatus({ jobId, onComplete, onFailed }: { jobId: string | null; onComplete?: (job: Job) => void; onFailed?: (message: string) => void }) {
  const completed = useRef<string | null>(null)
  const failed = useRef<string | null>(null)
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: ({ signal }) => api<Job>(`/jobs/${jobId}`, { signal }),
    enabled: Boolean(jobId),
    refetchInterval: (query) => ['queued', 'running'].includes(query.state.data?.state ?? '') ? 1_500 : false,
  })
  const value = job.data
  useEffect(() => {
    if (value?.state === 'succeeded' && completed.current !== value.id) {
      completed.current = value.id
      onComplete?.(value)
    }
    if (value?.state === 'failed' && failed.current !== value.id) {
      failed.current = value.id
      onFailed?.(value.error || 'The job failed.')
    }
  }, [value?.id, value?.state, value?.error, onComplete, onFailed])
  if (!jobId) return null
  if (job.isError) return <div className="error-banner">{job.error.message}</div>
  if (!value) return <div className="job-status">Loading job…</div>
  const detail = value.state === 'failed'
    ? value.error || 'The job failed.'
    : value.message || (value.state === 'succeeded' ? 'Complete.' : 'Waiting…')
  return <div className={`job-status ${value.state}`}>
    <strong>{value.state === 'running' ? 'Working' : value.state}</strong>
    <span>{detail}</span>
  </div>
}
