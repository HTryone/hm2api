/** 登录态服务。 */
import { checkSession, login, logout, setCsrf } from '../api'

export interface AuthState {
  status: 'checking' | 'anonymous' | 'ready'
  error: string
}

export async function restore(): Promise<AuthState> {
  try {
    const data = await checkSession()
    if (data.authenticated === true && typeof data.csrf_token === 'string') {
      setCsrf(data.csrf_token)
      return { status: 'ready', error: '' }
    }
    setCsrf(null)
    return { status: 'anonymous', error: '' }
  } catch {
    setCsrf(null)
    return { status: 'anonymous', error: '' }
  }
}

export async function signIn(apiKey: string): Promise<AuthState> {
  try {
    const data = await login(apiKey)
    if (data.authenticated === true && typeof data.csrf_token === 'string') {
      setCsrf(data.csrf_token)
      return { status: 'ready', error: '' }
    }
    return { status: 'anonymous', error: '密钥不正确' }
  } catch (error) {
    return { status: 'anonymous', error: (error as Error).message || '登录失败' }
  }
}

export async function signOut(): Promise<AuthState> {
  await logout()
  setCsrf(null)
  return { status: 'anonymous', error: '' }
}
