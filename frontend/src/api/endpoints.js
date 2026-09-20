import { api } from './client'

const V1 = '/api/v1'

export const auth = {
  login: (email, password) => {
    const form = new URLSearchParams({ username: email, password })
    return api.postForm(`${V1}/auth/login`, form)
  },
  register: (payload) => api.post(`${V1}/auth/register`, payload),
  me: () => api.get(`${V1}/auth/me`),
}

export const documents = {
  list: (params) => api.get(`${V1}/documents`, params),
  get: (id) => api.get(`${V1}/documents/${id}`),
  text: (id) => api.get(`${V1}/documents/${id}/text`),
  flags: (id, params) => api.get(`${V1}/documents/${id}/flags`, params),
  runs: (id) => api.get(`${V1}/documents/${id}/runs`),
  upload: ({ file, doc_type, rule_pack_key, related_document_id }) => {
    const form = new FormData()
    form.append('file', file)
    form.append('doc_type', doc_type)
    if (rule_pack_key) form.append('rule_pack_key', rule_pack_key)
    if (related_document_id) form.append('related_document_id', related_document_id)
    return api.postForm(`${V1}/documents`, form)
  },
  reprocess: (id) => api.post(`${V1}/documents/${id}/reprocess`),
  revalidate: (id) => api.post(`${V1}/documents/${id}/validate`),
  link: (id, related_document_id) => api.put(`${V1}/documents/${id}/link`, { related_document_id }),
}

export const validation = {
  run: (runId) => api.get(`${V1}/validation/runs/${runId}`),
  flag: (flagId) => api.get(`${V1}/flags/${flagId}`),
}

export const review = {
  queue: (params) => api.get(`${V1}/review/queue`, params),
  act: (flagId, payload) => api.post(`${V1}/review/flags/${flagId}/actions`, payload),
  complete: (documentId, payload) => api.post(`${V1}/review/documents/${documentId}/complete`, payload),
}

export const audit = {
  query: (params) => api.get(`${V1}/audit`, params),
  forDocument: (id, params) => api.get(`${V1}/audit/documents/${id}`, params),
  eventTypes: () => api.get(`${V1}/audit/event-types`),
  verify: () => api.get(`${V1}/audit/verify`),
}

export const rulePacks = {
  list: (params) => api.get(`${V1}/rule-packs`, params),
  get: (key) => api.get(`${V1}/rule-packs/${key}`),
  checks: () => api.get(`${V1}/rule-packs/checks`),
  patchRule: (key, ruleId, payload) => api.patch(`${V1}/rule-packs/${key}/rules/${ruleId}`, payload),
  activate: (packId) => api.post(`${V1}/rule-packs/versions/${packId}/activate`),
  create: (config, activate = true) => api.post(`${V1}/rule-packs?activate=${activate}`, { config }),
}

export const metrics = {
  summary: (params) => api.get(`${V1}/metrics/summary`, params),
}

export const users = {
  list: () => api.get(`${V1}/users`),
  create: (payload) => api.post(`${V1}/users`, payload),
  update: (id, payload) => api.patch(`${V1}/users/${id}`, payload),
}
