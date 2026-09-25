import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Membership, Track } from '../../api/types'

export type Column = {
  key: string
  label: string
  value: (track: Track) => ReactNode
  className?: string
}

function memberships(items: Membership[], route: string) {
  if (!items?.length) return <span className="empty-cell">—</span>
  return <div className="cell-pills">{items.map((item) => (
    <Link key={`${route}:${item.id}`} to={`/${route}/${encodeURIComponent(item.id)}`} className="membership-pill" title={item.title || item.name}>{item.name}</Link>
  ))}</div>
}

function dimension(key: string) {
  return (track: Track) => (track.dimensions?.[key] ?? []).join(', ') || <span className="empty-cell">—</span>
}

export const COLUMNS: Column[] = [
  { key: 'mix_position', label: 'Time', value: (t) => t.mix_position || '—', className: 'numeric' },
  { key: 'title', label: 'Title', value: (t) => t.title },
  { key: 'artist', label: 'Artist', value: (t) => t.artists?.length ? <>{t.artists.map((artist, index) => <span key={artist.id}>{index ? ', ' : ''}<Link className="artist-link" to={`/artists/${encodeURIComponent(artist.id)}`}>{artist.name}</Link></span>)}</> : t.artist },
  { key: 'remix', label: 'Remix', value: (t) => t.remix || '—', className: 'column-remix' },
  { key: 'album', label: 'Album', value: (t) => t.album || '—' },
  { key: 'length', label: 'Length', value: (t) => t.length || '—', className: 'numeric' },
  { key: 'bpm', label: 'BPM', value: (t) => t.bpm || '—', className: 'numeric' },
  { key: 'key', label: 'Key', value: (t) => t.key ? <span className="camelot-key" data-key={t.key}>{t.key}</span> : '—' },
  { key: 'year', label: 'Year', value: (t) => t.year || '—', className: 'numeric' },
  { key: 'date_added', label: 'Date added', value: (t) => t.date_added || '—' },
  { key: 'playlists', label: 'Playlists', value: (t) => memberships(t.playlists, 'playlists') },
  { key: 'events', label: 'Events', value: (t) => memberships(t.events, 'events') },
  { key: 'sources', label: 'Sources', value: (t) => memberships(t.sources, 'sources') },
  { key: 'mixes', label: 'Mixes', value: (t) => memberships(t.mixes, 'mixes') },
  { key: 'djmi', label: 'Dj Mix', value: (t) => memberships(t.djmi, 'watched-mixes') },
  { key: 'play_count', label: 'Play count', value: (t) => t.play_count || '—', className: 'numeric' },
  { key: 'last_played', label: 'Last played', value: (t) => t.last_played || '—' },
  ...['rating', 'energy', 'tension', 'vibe', 'movement', 'driver', 'function', 'structure', 'texture', 'scale'].map((key) => ({ key, label: key[0].toUpperCase() + key.slice(1), value: dimension(key) })),
]

export const DEFAULT_FIELDS = ['title', 'artist', 'remix', 'album', 'length', 'bpm', 'key', 'year', 'date_added', 'playlists', 'events', 'play_count', 'last_played', 'sources', 'mixes', 'djmi']
