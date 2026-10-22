export type Membership = {
  id: string
  name: string
  collection_type?: string
  title?: string
}

export type Artist = { id: string; name: string; provider_artist_id?: string }

export type ArtistOverviewRow = {
  id: string
  name: string
  indexed_tracks: number
  lastfm_plays: number
}

export type ArtistOverviewPage = {
  items: ArtistOverviewRow[]
  total: number
  offset: number
  limit: number
  has_more: boolean
}

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
  play_count: number | null
  last_played: string
  tidal_uri: string
  _source_order: number
}

export type Collection = {
  type: 'liked' | 'playlist' | 'event' | 'source' | 'setlist' | 'watched_mix' | 'artist' | 'search' | 'history'
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
  children?: NavigationItem[]
}

export type Navigation = {
  tools: NavigationItem[]
  groups: Array<{ id: string; label: string; items: NavigationItem[] }>
}

export type PublicSettings = {
  dark_mode: boolean
  tags_collapsed_by_default: boolean
  default_sort_direction: 'asc' | 'desc'
  lastfm_username: string
  history_top_tracks: number
  spotify_search_delay_seconds: number
  quick_views: Array<{ id: string; name: string; fields: string[]; default?: boolean }>
  mix_quick_views: Array<{ id: string; name: string; fields: string[]; default?: boolean }>
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

export type MixSummary = {
  folder_name: string
  youtube_url: string
  youtube_analytics_url: string
  tidal_url: string
  tidal_playlist_id: string
  tidal_playlist_name: string
  cover_url: string
  has_cover: boolean
  track_count: number
  updated_at: string
  youtube_title: string
  youtube_upload_date: string
  youtube_duration_seconds: number | null
  youtube_views: number | null
  youtube_thumbnail_impressions: number | null
  youtube_thumbnail_ctr: number | null
  youtube_watch_minutes: number | null
  youtube_average_view_duration: number | null
  youtube_average_view_percentage: number | null
  youtube_likes: number | null
  youtube_comments: number | null
  youtube_subscribers_gained: number | null
  youtube_analytics_fetched_at: string
}

export type YouTubeStatus = {
  configured: boolean
  connected: boolean
  expires_at: number | null
}

export type OrphanedTrack = {
  id: string
  title: string
  artist: string
  album: string
  rating: number
  tag_count: number
  dimension_count: number
  lastfm_plays: number
}

export type OrphanedTracksPage = {
  items: OrphanedTrack[]
  total: number
  offset: number
  limit: number
  has_more: boolean
}

export type OrphanedTracksClearResult = {
  deleted_tracks: number
  cleared_lastfm_matches: number
}
