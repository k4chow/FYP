import { api } from './api'
import type { Memory } from './memories'

export interface ProfileStats {
  films_watched: number
  watchlist: number
  confirmed_insights: number
  proposed_awaiting_review: number
  reflections_completed: number
  top_genres: { genre: string; count: number }[]
}

// GET /profile/summary (F2): the reflective profile, built only from
// confirmed memories plus basic library statistics.
export interface ProfileSummary {
  display_name: string | null
  stats: ProfileStats
  summary: string | null
  groups: {
    theme: Memory[]
    preference: Memory[]
    insight: Memory[]
  }
}

export const getProfileSummary = () =>
  api<ProfileSummary>('/profile/summary', { auth: true })
