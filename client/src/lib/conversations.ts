import { api } from './api'

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

export const listConversations = (status?: 'active' | 'completed') =>
  api<{ conversations: Conversation[] }>(
    `/conversations${status ? `?status=${status}` : ''}`,
    { auth: true },
  )

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

export const sendMessage = (id: string, content: string) =>
  api<{ user_message: ChatMessage; assistant_message: ChatMessage }>(
    `/conversations/${id}/messages`,
    { method: 'POST', auth: true, body: { content } },
  )

export const endConversation = (id: string) =>
  api<{ conversation: Conversation }>(`/conversations/${id}/end`, {
    method: 'POST',
    auth: true,
  })
