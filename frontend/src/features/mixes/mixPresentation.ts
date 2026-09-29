export type YouTubeFacts = {
  channel?: string
  views?: number | null
  uploadDate?: string
}

export function formatYouTubeFacts({ channel, views, uploadDate }: YouTubeFacts): string {
  return [
    channel?.trim(),
    views !== null && views !== undefined ? `${views.toLocaleString()} views` : '',
    uploadDate?.trim() ? `Uploaded ${uploadDate.trim()}` : '',
  ].filter(Boolean).join(' · ')
}

export type WatchedMixPresentationSource = {
  title?: string
  channel_name?: string
  upload_date?: string
  live_title?: string
  live_channel_name?: string
  live_view_count?: number | null
  live_upload_date?: string
}

export function watchedMixPresentation(mix?: WatchedMixPresentationSource) {
  return {
    title: mix?.title || mix?.live_title || 'Untitled watched mix',
    facts: formatYouTubeFacts({
      channel: mix?.live_channel_name || mix?.channel_name,
      views: mix?.live_view_count,
      uploadDate: mix?.live_upload_date || mix?.upload_date,
    }),
  }
}
