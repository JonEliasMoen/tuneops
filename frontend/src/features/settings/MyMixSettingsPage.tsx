import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { Job, MyMixSettings } from '../../api/types'
import { JobStatus } from '../../components/JobStatus'

export function MyMixSettingsPage() {
  const client = useQueryClient()
  const settings = useQuery({
    queryKey: ['my-mix-settings'],
    queryFn: () => api<MyMixSettings>('/settings/my-mixes'),
  })
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobError, setJobError] = useState('')
  const [jobNotice, setJobNotice] = useState('')
  const discovery = useMutation({
    mutationFn: () => api<Job>('/mixes/discover-tidal', { method: 'POST' }),
    onSuccess: (job) => {
      setJobError('')
      setJobNotice('')
      setJobId(job.id)
    },
  })

  function refreshAfterDiscovery(job: Job) {
    setJobNotice(job.message || 'Discovery complete.')
    setJobId(null)
    void client.invalidateQueries({ queryKey: ['my-mix-settings'] })
    void client.invalidateQueries({ queryKey: ['mixes'] })
    void client.invalidateQueries({ queryKey: ['navigation'] })
  }

  return <section className="settings-page my-mix-settings-page">
    <header className="tool-heading">
      <div>
        <p className="eyebrow">Settings</p>
        <h1>My Mixes settings</h1>
        <p>TuneOps scans playlists owned by your TIDAL account. A playlist named <code>djset &lt;name&gt;</code> becomes the My Mix <code>&lt;name&gt;</code>.</p>
      </div>
      <div className="button-row">
        <Link className="button-link quiet-link" to="/settings">Back to Settings</Link>
        <button className="primary" type="button" disabled={discovery.isPending || Boolean(jobId)} onClick={() => discovery.mutate()}>
          {discovery.isPending || jobId ? 'Discovering…' : 'Discover automatically'}
        </button>
      </div>
    </header>

    <section className="settings-card my-mix-discovery-help">
      <h2>Safe one-time import</h2>
      <p>Discovery imports the tracks only when a TIDAL playlist has not been connected before. Existing My Mix mappings and tracks are left unchanged. Re-run discovery whenever you create another <code>djset …</code> playlist.</p>
      <JobStatus jobId={jobId} onComplete={refreshAfterDiscovery} onFailed={(message) => { setJobId(null); setJobError(message) }} />
      {jobNotice ? <p className="good">{jobNotice}</p> : null}
      {discovery.isError ? <div className="error-banner">{discovery.error.message}</div> : null}
      {jobError ? <div className="error-banner">{jobError}</div> : null}
    </section>

    {settings.isLoading ? <p>Loading My Mixes…</p> : settings.isError ? <div className="error-banner">{settings.error.message}</div> :
      <section className="settings-card my-mix-discovery-list">
        <div className="settings-card-heading"><div><h2>Known mixes</h2><p>{settings.data?.items.length ?? 0} mixes stored in TuneOps.</p></div></div>
        {settings.data?.items.length ? <div className="orphaned-track-table-wrap"><table className="orphaned-track-table"><thead><tr><th>Mix</th><th>Expected TIDAL playlist</th><th>Connected playlist</th><th>Tracks</th><th>Status</th></tr></thead><tbody>
          {settings.data.items.map((mix) => <tr key={mix.internal_name}>
            <td><Link className="mix-name-link" to={`/mixes/${encodeURIComponent(mix.internal_name)}`}>{mix.internal_name}</Link></td>
            <td>{mix.expected_tidal_name}</td>
            <td>{mix.tidal_playlist_name || '—'}</td>
            <td>{mix.track_count.toLocaleString()}</td>
            <td><span className={mix.status === 'connected' ? 'good' : 'muted'}>{mix.status === 'connected' ? 'Connected' : 'Not discovered'}</span></td>
          </tr>)}
        </tbody></table></div> : <p>No My Mixes are stored yet. Create a TIDAL playlist named <code>djset &lt;name&gt;</code>, then run discovery.</p>}
      </section>}
  </section>
}
