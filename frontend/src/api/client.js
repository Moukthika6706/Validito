// Thin fetch wrapper: attaches the JWT, unwraps FastAPI error bodies, and signals 401s so
// the auth context can log the user out.

const BASE = import.meta.env.VITE_API_URL || ''
const TOKEN_KEY = 'validito.token'

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

export class ApiError extends Error {
  constructor(status, detail, body) {
    super(typeof detail === 'string' ? detail : 'Request failed')
    this.status = status
    this.detail = detail
    this.body = body
  }
}

const unauthorizedListeners = new Set()
export const onUnauthorized = (fn) => {
  unauthorizedListeners.add(fn)
  return () => unauthorizedListeners.delete(fn)
}

function formatDetail(body) {
  if (!body) return null
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) {
    // Pydantic validation errors
    return body.detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ')
  }
  return null
}

export async function request(path, { method = 'GET', body, form, params, headers = {} } = {}) {
  const url = new URL(BASE + path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
    })
  }
  const token = tokenStore.get()
  const init = { method, headers: { ...headers } }
  if (token) init.headers.Authorization = `Bearer ${token}`
  if (form) {
    init.body = form // FormData or URLSearchParams; browser sets content-type
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }

  let res
  try {
    res = await fetch(url, init)
  } catch (e) {
    throw new ApiError(0, 'Cannot reach the server. Is the API running?')
  }
  const text = await res.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (res.status === 401) {
    unauthorizedListeners.forEach((fn) => fn())
  }
  if (!res.ok) {
    throw new ApiError(res.status, formatDetail(data) || `${res.status} ${res.statusText}`, data)
  }
  return data
}

export const api = {
  get: (path, params) => request(path, { params }),
  post: (path, body) => request(path, { method: 'POST', body }),
  postForm: (path, form) => request(path, { method: 'POST', form }),
  put: (path, body) => request(path, { method: 'PUT', body }),
  patch: (path, body) => request(path, { method: 'PATCH', body }),
}
