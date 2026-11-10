import { api } from './api'

// Phase 6 (F8/F9/F11): reflection-informed recommendations with
// explanations and an explicit feedback loop.

export interface SourceMemory {
  id: string
  content: string
}

export interface Recommendation {
  tmdb_id: number
  title: string
  year: number | null
  genres: string[]
  poster_url: string | null
  overview: string
  vote_average: number
  score: number
  why: string
  source_memories: SourceMemory[]
}

export type FeedbackSignal = 'more_like_this' | 'not_for_me'

export const getRecommendations = (limit = 12, refresh = false, excludeTmdbIds?: number[]) => {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  if (refresh) params.set('refresh', '1')
  if (excludeTmdbIds?.length) params.set('exclude_tmdb_ids', excludeTmdbIds.join(','))
  return api<{ recommendations: Recommendation[] }>(`/recommendations?${params.toString()}`, {
    auth: true,
  })
}

export const sendFeedback = (tmdbId: number, signal: FeedbackSignal, title: string) =>
  api<{ tmdb_id: number; signal: FeedbackSignal }>('/recommendations/feedback', {
    method: 'POST',
    auth: true,
    body: { tmdb_id: tmdbId, signal, title },
  })

export const clearFeedback = (tmdbId: number) =>
  api<{ tmdb_id: number; signal: null }>(`/recommendations/feedback/${tmdbId}`, {
    method: 'DELETE',
    auth: true,
  })
