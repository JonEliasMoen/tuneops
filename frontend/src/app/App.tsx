import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { PublicSettings } from '../api/types'
import { Shell } from '../components/Shell'
import { TrackBrowser } from '../features/track-browser/TrackBrowser'
import { PlaylistSyncPage } from '../features/playlist-sync/PlaylistSyncPage'
import { SettingsPage } from '../features/settings/SettingsPage'
import { MixDetailPage, MixesPage, PendingPage, WatchedMixDetailPage, WatchedMixesPage } from '../features/mixes/MixPages'

function TrackRoute({ type }: { type: 'liked' | 'playlist' | 'event' | 'source' | 'setlist' | 'watched_mix' | 'artist' | 'search' | 'history' }) {
  const { id = '' } = useParams()
  const collectionId = type === 'liked' ? 'liked' : type === 'search' ? 'library' : decodeURIComponent(id)
  return <TrackBrowser collectionType={type} collectionId={collectionId} />
}

export function App() {
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<PublicSettings>('/settings') })
  const dark = settings.data?.dark_mode ?? true

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  }, [dark])

  return (
    <Shell>
      <Routes>
        <Route path="/" element={<PlaylistSyncPage />} />
        <Route path="/liked-tracks" element={<TrackRoute type="liked" />} />
        <Route path="/search" element={<TrackRoute type="search" />} />
        <Route path="/history/:id" element={<TrackRoute type="history" />} />
        <Route path="/artists/:id" element={<TrackRoute type="artist" />} />
        <Route path="/playlists/:id" element={<TrackRoute type="playlist" />} />
        <Route path="/events/:id" element={<TrackRoute type="event" />} />
        <Route path="/sources/:id" element={<TrackRoute type="source" />} />
        <Route path="/mixes" element={<MixesPage />} />
        <Route path="/mixes/:id" element={<MixDetailPage />} />
        <Route path="/watched-mixes" element={<WatchedMixesPage />} />
        <Route path="/watched-mixes/pending" element={<PendingPage />} />
        <Route path="/watched-mixes/:id" element={<WatchedMixDetailPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}
