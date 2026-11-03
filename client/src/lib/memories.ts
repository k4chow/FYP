import { api } from './api'

export type MemoryStatus = 'proposed' | 'confirmed' | 'rejected'
export type MemoryKind = 'theme' | 'preference' | 'insight'

export interface MemorySourceMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
}

export interface Memory {
  id: string
  conversation_id: string | null
  content: string
  kind: MemoryKind
  status: MemoryStatus
  explanation: string
  source_message_ids: string[]
  source_messages: MemorySourceMessage[]
  created_at: string
  updated_at: string
}

export const listMemories = (status?: MemoryStatus) =>
  api<{ memories: Memory[] }>(`/memories${status ? `?status=${status}` : ''}`, {
    auth: true,
  })

export const getConversationMemories = (conversationId: string) =>
  api<{ memories: Memory[] }>(`/conversations/${conversationId}/memories`, {
    auth: true,
  })

export const reviewMemory = (
  id: string,
  status: 'confirmed' | 'rejected',
  content?: string,
) =>
  api<{ memory: Memory }>(`/memories/${id}`, {
    method: 'PATCH',
    auth: true,
    body: content === undefined ? { status } : { status, content },
  })
