/** 统一 HTTP 客户端：token 注入、401 跳登录、错误 ElMessage。 */

const TOKEN_KEY = 'itops_token'

export function getToken(): string {

  return localStorage.getItem(TOKEN_KEY) || ''

}

export function setToken(token: string) {

  localStorage.setItem(TOKEN_KEY, token)

}

export function clearToken() {

  localStorage.removeItem(TOKEN_KEY)

}

export class ApiError extends Error {

  status: number

  constructor(status: number, message: string) {

    super(message)

    this.status = status

  }

}

export async function http<T = any>(method: string, path: string, body?: any): Promise<T> {

  const headers: Record<string, string> = { 'Content-Type': 'application/json' }

  const token = getToken()

  if (token) headers['Authorization'] = `Bearer ${token}`

  let resp: Response

  try {

    resp = await fetch(path, {

      method,

      headers,

      body: body !== undefined ? JSON.stringify(body) : undefined,

    })

  } catch {

    throw new ApiError(0, '网络错误，请检查服务是否已启动')

  }

  // 登录接口的 401 是「凭据错误」而非会话过期：保留后端 detail，不清 token 不跳转

  if (resp.status === 401 && !path.includes('/api/auth/login')) {

    clearToken()

    if (!location.pathname.startsWith('/login')) location.href = '/login'

    throw new ApiError(401, '登录已过期')

  }

  const data = await resp.json().catch(() => ({}))

  if (!resp.ok) {

    throw new ApiError(resp.status, (data as any).detail || `请求失败 (${resp.status})`)

  }

  return data as T

}

export const get = <T = any>(path: string) => http<T>('GET', path)

export const post = <T = any>(path: string, body?: any) => http<T>('POST', path, body)

export const put = <T = any>(path: string, body?: any) => http<T>('PUT', path, body)

export const patch = <T = any>(path: string, body?: any) => http<T>('PATCH', path, body)

export const del = <T = any>(path: string) => http<T>('DELETE', path)

/** 文件上传（multipart），由浏览器自动设置 boundary。 */

export async function upload<T = any>(path: string, file: File): Promise<T> {

  const headers: Record<string, string> = {}

  const token = getToken()

  if (token) headers['Authorization'] = `Bearer ${token}`

  const fd = new FormData()

  fd.append('file', file)

  const resp = await fetch(path, { method: 'POST', headers, body: fd })

  if (resp.status === 401) {

    clearToken()

    location.href = '/login'

    throw new ApiError(401, '登录已过期')

  }

  const data = await resp.json().catch(() => ({}))

  if (!resp.ok) throw new ApiError(resp.status, (data as any).detail || `上传失败 (${resp.status})`)

  return data as T

}

/** 下载文件（带认证），返回 Blob 供前端保存。 */

export async function download(path: string, filename: string): Promise<void> {

  const headers: Record<string, string> = {}

  const token = getToken()

  if (token) headers['Authorization'] = `Bearer ${token}`

  const resp = await fetch(path, { headers })

  if (!resp.ok) throw new ApiError(resp.status, '下载失败')

  const blob = await resp.blob()

  const url = URL.createObjectURL(blob)

  const a = document.createElement('a')

  a.href = url

  a.download = filename

  a.click()

  URL.revokeObjectURL(url)

}

/** 带认证拉取文件为 Blob URL（附件在线预览：图片缩略图/大图、PDF iframe）。 */

export async function fetchBlobUrl(path: string): Promise<string> {

  const headers: Record<string, string> = {}

  const token = getToken()

  if (token) headers['Authorization'] = `Bearer ${token}`

  const resp = await fetch(path, { headers })

  if (!resp.ok) throw new ApiError(resp.status, '预览失败')

  return URL.createObjectURL(await resp.blob())

}
