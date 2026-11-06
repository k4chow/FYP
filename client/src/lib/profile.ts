import { api } from './api'
import type { Memory } from './memories'

export interface ProfileStats {
  films_watched: number
  watchlist: number
  confirmed_insights: number
  proposed_awaiting_review: number
  reflections_completed: number
  top_genres: { genre: string; count: number }[]
  // Every genre across the watched library (the Genres tab); top_genres is
  // just the first few of these, kept for the summary sentence.
  genre_counts: { genre: string; count: number }[]
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

// N6 (Phase 6): the recommendation style slider, persisted on the users row.
export interface Preferences {
  recommendation_style: number // 0 = more like what I love, 100 = surprise me
}

export const getPreferences = () =>
  api<Preferences>('/profile/preferences', { auth: true })

export const updatePreferences = (style: number) =>
  api<Preferences>('/profile/preferences', {
    method: 'PATCH',
    auth: true,
    body: { recommendation_style: style },
  })

// D38: onboarding about-you answers are user-authored, so they are saved
// straight into the profile as confirmed preferences.
export interface QuestionnaireAnswer {
  question: string
  answer: string
}

export const saveQuestionnaire = (answers: QuestionnaireAnswer[]) =>
  api<{ saved: number }>('/profile/questionnaire', {
    method: 'POST',
    auth: true,
    body: { answers },
  })
