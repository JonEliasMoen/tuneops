import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'

type EventMedia = {
  event_name: string
  youtube_url: string
  concert_archives_url: string
  thumbnail_url: string
  updated_at: string
}

export function EventMedia({ eventId }: { eventId: string }) {
  const client = useQueryClient()
  const media = useQuery({
    queryKey: ['event-media', eventId],
    queryFn: () => api<EventMedia>(`/events/${encodeURIComponent(eventId)}/media`),
  })
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [concertUrl, setConcertUrl] = useState('')
  useEffect(() => {
    if (!media.data) return
    setYoutubeUrl(media.data.youtube_url)
    setConcertUrl(media.data.concert_archives_url)
  }, [media.data?.youtube_url, media.data?.concert_archives_url])
  const save = useMutation({
    mutationFn: () => api<EventMedia>(`/events/${encodeURIComponent(eventId)}/media`, {
      method: 'PUT',
      body: JSON.stringify({ youtube_url: youtubeUrl, concert_archives_url: concertUrl }),
    }),
    onSuccess: (saved) => {
      client.setQueryData(['event-media', eventId], saved)
      setYoutubeUrl(saved.youtube_url)
      setConcertUrl(saved.concert_archives_url)
    },
  })
  if (media.isPending || media.isError || !media.data) return null
  const { youtube_url: savedYoutubeUrl, concert_archives_url: savedConcertUrl, thumbnail_url: thumbnailUrl } = media.data
  return <section className="event-media" aria-label="Event media">
    {thumbnailUrl ? <img src={thumbnailUrl} alt="" /> : null}
    <div>
      <p className="eyebrow">Event media</p>
      <h2>{media.data.event_name}</h2>
      <div className="button-row">
        {savedYoutubeUrl ? <a className="button-link" href={savedYoutubeUrl} target="_blank" rel="noreferrer">Open on YouTube</a> : null}
        {savedConcertUrl ? <a className="button-link quiet-link" href={savedConcertUrl} target="_blank" rel="noreferrer">Concert Archives</a> : null}
      </div>
      <div className="event-media-fields">
        <label>YouTube video URL<input type="url" value={youtubeUrl} onChange={(event) => setYoutubeUrl(event.target.value)} placeholder="https://youtube.com/watch?v=…" /></label>
        <label>Concert Archives URL<input type="url" value={concertUrl} onChange={(event) => setConcertUrl(event.target.value)} placeholder="https://www.concertarchives.org/..." /></label>
        <div className="button-row"><button type="button" className="primary" onClick={() => save.mutate()} disabled={save.isPending}>Save links</button>{save.isSuccess ? <span className="good">Saved.</span> : null}</div>
        {save.isError ? <div className="error-banner">{save.error.message}</div> : null}
      </div>
    </div>
  </section>
}
