export type Membership = {
  id: string
  name: string
  collection_type?: string
  title?: string
}

export type Artist = { id: string; name: string; provider_artist_id?: string }

export type Track = {
  id: string
  title: string
  artist: string
  artists: Artist[]
  remix: string
  album: string
  album_art_url: string
  length: string
  bpm: string
  key: string
  year: string
  date_added: string
  mix_position?: string
  playlists: Membership[]
  events: Membership[]
  sources: Membership[]
  mixes: Membership[]
  djmi: Membership[]
  dimensions: Record<string, string[]>
  play_count: number
  last_played: string
  tidal_uri: string
  _source_order: number
}

export type Collection = {
  type: 'liked' | 'playlist' | 'event' | 'source' | 'setlist' | 'watched_mix' | 'artist' | 'search'
  id: string
  name: string
  collection_type: string
}

export type CollectionStats = {
  top_artists: Array<{ id: string; name: string; count: number }>
  artist_options: Array<{ label: string; value: string }>
  bpm_min: number | null
  bpm_max: number | null
  vibe: string
  vibe_count: number
}

export type TrackPage = {
  collection: Collection
  items: Track[]
  total: number
  offset: number
  limit: number
  has_more: boolean
  stats: CollectionStats
}

export type NavigationItem = {
  id: string
  label: string
  path: string
  kind: string
  icon: string
}

export type Navigation = {
  tools: NavigationItem[]
  groups: Array<{ id: string; label: string; items: NavigationItem[] }>
}

export type PublicSettings = {
  dark_mode: boolean
  tags_collapsed_by_default: boolean
  ollama_model: string
  ollama_url: string
  lastfm_username: string
  spotify_search_delay_seconds: number
  quick_views: Array<{ id: string; name: string; fields: string[]; default?: boolean }>
  lastfm_api_key_configured: boolean
}

export type Job = {
  id: string
  kind: string
  state: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  message: string
  current: number
  total: number | null
  result: unknown
  error: string
  created_at: string
}
