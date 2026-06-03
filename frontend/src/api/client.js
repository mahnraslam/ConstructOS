import axios from 'axios'
const BASE = import.meta.env.VITE_API_URL || ''
const api  = axios.create({ baseURL: BASE })

// ── Documents ─────────────────────────────────────────────────────────────
export const uploadDocument = (file, docType = '', projectId = '') => {
  const f = new FormData()
  f.append('file', file)
  if (docType)   f.append('doc_type', docType)
  if (projectId) f.append('project_id', projectId)
  return api.post('/api/documents/upload', f)
}
export const listDocuments  = ()    => api.get('/api/documents/')
export const deleteDocument = (id)  => api.delete(`/api/documents/${id}`)
export const getPageUrl     = (docId, page) => `${BASE}/pages/${docId}_page_${page}.png`

// ── Query ─────────────────────────────────────────────────────────────────
export const queryDocuments = (question, doc_ids = null, top_k = 5, visual = false, project_id = null) =>
  api.post('/api/query/', { question, doc_ids, top_k, visual, project_id })

// ── Conflicts ─────────────────────────────────────────────────────────────
export const detectConflicts = (doc_id_a, doc_id_b, filename_a = '', filename_b = '') =>
  api.post('/api/conflicts/detect', { doc_id_a, doc_id_b, filename_a, filename_b })

export const detectProjectConflicts = (projectId) =>
  api.post(`/api/conflicts/project/${projectId}/detect`)

export const getProjectConflicts = (projectId) =>
  api.get(`/api/conflicts/project/${projectId}`)

// ── RFIs ──────────────────────────────────────────────────────────────────
export const generateProjectRFIs = (projectId) =>
  api.post('/api/rfi/project/generate', { project_id: projectId })

export const getProjectRFIs = (projectId) =>
  api.get(`/api/rfi/project/${projectId}`)

// ── Projects ─────────────────────────────────────────────────────────────
export const listProjects     = ()                             => api.get('/api/projects/')
export const getProject       = (id)                          => api.get(`/api/projects/${id}`)
export const createProject    = (name, description = '')      => api.post('/api/projects/', { name, description })
export const deleteProject    = (id)                          => api.delete(`/api/projects/${id}`)

export const addDocToProject  = (projectId, doc) =>
  api.post(`/api/projects/${projectId}/documents`, doc)
export const listProjectDocs  = (projectId) =>
  api.get(`/api/projects/${projectId}/documents`)
export const removeDocFromProject = (projectId, docId) =>
  api.delete(`/api/projects/${projectId}/documents/${docId}`)

// ── Facts ─────────────────────────────────────────────────────────────────
export const extractFacts     = (projectId, docId) =>
  api.post('/api/facts/extract', { project_id: projectId, doc_id: docId })
export const getProjectFacts  = (projectId) =>
  api.get(`/api/facts/project/${projectId}`)
