const API_URL =
  (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'

const TOKEN_KEY = 'noacf_token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)

export const setToken = (token: string | null) => {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

interface ApiOptions {
  method?: string
  body?: unknown
  auth?: boolean
}

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (options.auth) {
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }

  const res = await fetch(`${API_URL}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })

  if (!res.ok) {
    let message = res.statusText
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') message = data.detail
    } catch {
      // keep statusText
    }
    throw new ApiError(res.status, message)
  }

  return res.json() as Promise<T>
}
