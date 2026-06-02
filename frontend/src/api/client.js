import axios from 'axios'
const BASE = import.meta.env.VITE_API_URL || ''
const api  = axios.create({ baseURL: BASE })

export const uploadDocument  = (file, docType = '') => {
  const f = new FormData()
  f.append('file', file)
  if (docType) f.append('doc_type', docType)
  return api.post('/api/documents/upload', f)
}
export const listDocuments   = ()     => api.get('/api/documents/')
export const deleteDocument  = (id)   => api.delete(`/api/documents/${id}`)
export const getPageUrl      = (docId, page) => `${BASE}/pages/${docId}_page_${page}.png`

/**
 * Query documents with optional visual mode.
 *
 * visual=true → backend passes retrieved page PNGs to Gemini Vision so it can
 * actually *see* the drawing alongside the extracted text.  Citations in the
 * response will include an image_url for inline preview.
 */
export const queryDocuments  = (question, doc_ids = null, top_k = 5, visual = false) =>
  api.post('/api/query/', { question, doc_ids, top_k, visual })

export const detectConflicts = (doc_id_a, doc_id_b, filename_a = '', filename_b = '') =>
  api.post('/api/conflicts/detect', { doc_id_a, doc_id_b, filename_a, filename_b })

/**
 * Generate RFIs by comparing a blueprint against a specification.
 * visual=true (default) → blueprint page images sent to Gemini so it reads
 * the drawing directly, not just extracted text.
 */
export const generateRFIs = (blueprint_doc_id, spec_doc_id, blueprint_filename = '', spec_filename = '', visual = true) =>
  api.post('/api/rfi/generate', { blueprint_doc_id, spec_doc_id, blueprint_filename, spec_filename, visual })