/** 后端接口封装：同源走 /admin，独立部署时可用 window.HM2API_API 覆盖。 */

const API: string =
  (window as unknown as { HM2API_API?: string }).HM2API_API ??
  (location.pathname.startsWith('/dashboard') ? '/admin' : 'http://127.0.0.1:8788/admin')

let csrfToken: string | null = null

export function setCsrf(token: string | null) {
  csrfToken = token
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

interface CallOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
}

export async function call<T>(path: string, options: CallOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken

  const response = await fetch(API + path, {
    method: options.method ?? 'GET',
    headers,
    credentials: 'include',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })

  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const message =
      (payload && (payload.error?.message || payload.detail)) || `请求失败（HTTP ${response.status}）`
    throw new ApiError(String(message), response.status)
  }
  return payload as T
}

export async function checkSession() {
  return call<{ authenticated?: boolean; csrf_token?: string }>('/session')
}

export async function login(apiKey: string) {
  return call<{ authenticated?: boolean; csrf_token?: string }>('/session', {
    method: 'POST',
    body: { api_key: apiKey },
  })
}

export async function logout() {
  await call('/session', { method: 'DELETE' }).catch(() => undefined)
}
