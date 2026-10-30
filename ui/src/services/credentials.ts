/** 凭证管理数据服务。 */
import { call } from '../api'

export interface CredentialRow {
  platform: string
  label: string
  present: boolean
  path?: string | null
  desktop_path?: string | null
  source?: string | null
  account?: string | null
  fingerprint?: string | null
  error?: string | null
  can_login: boolean
  login_state: string
}

export interface LoginState {
  state: 'idle' | 'waiting' | 'success' | 'failed' | 'manual'
  message?: string
  auth_url?: string
  token_fingerprint?: string | null
  started_at?: number | null
  finished_at?: number | null
}

export async function loadCredentials(): Promise<{ platforms: CredentialRow[] }> {
  return call<{ platforms: CredentialRow[] }>('/credentials')
}

export async function startLogin(platform: string): Promise<LoginState> {
  return call<LoginState>(`/credentials/${platform}/login`, { method: 'POST' })
}

export async function loginStatus(): Promise<LoginState> {
  return call<LoginState>('/credentials/qwenwork/login/status')
}

export async function reloadSession(platform: string) {
  return call(`/${platform}/session/reload`, { method: 'POST' })
}
