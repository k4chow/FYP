import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api, getToken, setToken } from '../lib/api'

export interface User {
  id: string
  email: string
  display_name?: string | null
  onboarding_completed?: boolean
}

interface AuthContextValue {
  user: User | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signUp: (email: string, password: string, displayName: string) => Promise<void>
  signOut: () => void
  completeOnboarding: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!getToken()) {
      setLoading(false)
      return
    }
    api<User>('/auth/me', { auth: true })
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false))
  }, [])

  async function signIn(email: string, password: string) {
    const res = await api<{ access_token: string; user: User }>('/auth/login', {
      method: 'POST',
      body: { email, password },
    })
    setToken(res.access_token)
    setUser(res.user)
  }

  async function signUp(email: string, password: string, displayName: string) {
    const res = await api<{ access_token: string; user: User }>('/auth/signup', {
      method: 'POST',
      body: { email, password, display_name: displayName || null },
    })
    setToken(res.access_token)
    setUser(res.user)
  }

  function signOut() {
    setToken(null)
    setUser(null)
  }

  async function completeOnboarding() {
    const updated = await api<User>('/auth/onboarding-complete', {
      method: 'POST',
      auth: true,
    })
    setUser(updated)
  }

  return (
    <AuthContext.Provider
      value={{ user, loading, signIn, signUp, signOut, completeOnboarding }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
