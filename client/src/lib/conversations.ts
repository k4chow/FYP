import { api } from './api'
import type { Memory } from './memories'

export interface ConversationFilm {
  id: string
  tmdb_id: number | null
  title: string
  year: number | null
  genres: string[]
  runtime: number | null
  overview: string
  poster_url: string | null
}

export interface Conversation {
  id: string
  type: 'reflection' | 'discovery'
  status: 'active' | 'completed'
  watch_type: 'seen' | 'planning' | null
  title: string | null
  created_at: string
  updated_at: string
  ended_at: string | null
  film: ConversationFilm | null
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  metadata: Record<string, unknown>
  created_at: string
}

export interface CreateConversationInput {
  type?: 'reflection' | 'discovery'
  film_id?: string
  tmdb_id?: number
  watch_type?: 'seen' | 'planning'
  title?: string
}

export const listConversations = (
  status?: 'active' | 'completed',
  type?: 'reflection' | 'discovery',
) => {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (type) params.set('type', type)
  const qs = params.toString()
  return api<{ conversations: Conversation[] }>(
    `/conversations${qs ? `?${qs}` : ''}`,
    { auth: true },
  )
}

export const createConversation = (body: CreateConversationInput) =>
  api<{ conversation: Conversation; messages: ChatMessage[] }>('/conversations', {
    method: 'POST',
    auth: true,
    body,
  })

export const getConversation = (id: string) =>
  api<{ conversation: Conversation; messages: ChatMessage[] }>(`/conversations/${id}`, {
    auth: true,
  })

export const sendMessage = (id: string, content: string, exclude_tmdb_ids: number[] = []) =>
  api<{ user_message: ChatMessage; assistant_message: ChatMessage }>(
    `/conversations/${id}/messages`,
    { method: 'POST', auth: true, body: { content, exclude_tmdb_ids } },
  )

export const endConversation = (id: string) =>
  api<{ conversation: Conversation; proposed_memories: Memory[] }>(
    `/conversations/${id}/end`,
    {
      method: 'POST',
      auth: true,
    },
  )

export const deleteConversation = (id: string) =>
  api<{ deleted: boolean }>(`/conversations/${id}`, {
    method: 'DELETE',
    auth: true,
  })

// --- Ephemeral Film Assistant (Phase 7) -------------------------------------
// The assistant no longer creates a persisted conversation: the transcript
// lives in the client (sessionStorage) and each turn is a stateless request.

export interface AssistantRecommendation {
  tmdb_id: number
  title: string
  year: number | null
  genres: string[]
  runtime: number | null
  overview: string
  poster_url: string | null
  vote_average: number
  themes: string[]
}

interface AssistantMessage {
  role: 'user' | 'assistant'
  content: string
}

export const assistantOpening = () =>
  api<{ reply: string }>('/assistant/opening', { method: 'POST', auth: true })

export const assistantChat = (messages: AssistantMessage[]) =>
  api<{ reply: string; recommendations: AssistantRecommendation[] }>(
    '/assistant/chat',
    { method: 'POST', auth: true, body: { messages } },
  )
