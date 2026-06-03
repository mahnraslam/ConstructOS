import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { listProjects, createProject, deleteProject, uploadDocument, listProjectDocs, removeDocFromProject } from '../api/client'

const DOC_TYPES = ['blueprint', 'specification', 'boq', 'method_statement', 'other']

const S = {
  wrap:    { display: 'flex', height: '100vh', background: '#0a1628', color: '#e2e8f0', fontFamily: 'system-ui, sans-serif' },
  sidebar: { width: 280, borderRight: '1px solid #1e3a5f', padding: 16, overflowY: 'auto', flexShrink: 0 },
  main:    { flex: 1, padding: 24, overflowY: 'auto' },
  h1:      { fontSize: 18, fontWeight: 700, color: '#60a5fa', margin: '0 0 4px' },
  sub:     { fontSize: 12, color: '#6b7a99', margin: '0 0 20px' },
  h2:      { fontSize: 14, fontWeight: 600, color: '#94a3b8', margin: '0 0 12px' },
  btn:     (variant = 'primary') => ({
    padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600,
    background: variant === 'primary' ? '#2563eb' : variant === 'danger' ? '#7f1d1d' : '#1e3a5f',
    color: variant === 'danger' ? '#fca5a5' : '#e2e8f0',
  }),
  input:   { background: '#111e30', border: '1px solid #1e3a5f', borderRadius: 6, padding: '7px 10px',
             color: '#e2e8f0', fontSize: 13, width: '100%', boxSizing: 'border-box' },
  card:    (active) => ({
    padding: '10px 12px', borderRadius: 8, marginBottom: 8, cursor: 'pointer',
    background: active ? '#1e3a5f' : '#111e30',
    border: `1px solid ${active ? '#2563eb' : '#1e3a5f'}`,
  }),
  row:     { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 },
  badge:   (type) => {
    const colors = { blueprint: '#1d4ed8', specification: '#065f46', boq: '#78350f', method_statement: '#581c87', other: '#374151' }
    return { padding: '2px 7px', borderRadius: 10, fontSize: 10, fontWeight: 600, background: colors[type] || colors.other, color: '#e2e8f0' }
  },
  docRow:  { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px',
             background: '#111e30', borderRadius: 6, marginBottom: 6, border: '1px solid #1e3a5f' },
  label:   { fontSize: 11, color: '#6b7a99', marginBottom: 4 },
  divider: { borderTop: '1px solid #1e3a5f', margin: '16px 0' },
  select:  { background: '#111e30', border: '1px solid #1e3a5f', borderRadius: 6, padding: '7px 10px',
             color: '#e2e8f0', fontSize: 12 },
  uploading: { fontSize: 11, color: '#60a5fa', marginTop: 4 },
  error:   { fontSize: 11, color: '#f87171', marginTop: 4 },
}

export default function ProjectWorkspace() {
  const navigate = useNavigate()
  const [projects,    setProjects]    = useState([])
  const [selected,    setSelected]    = useState(null)
  const [docs,        setDocs]        = useState([])
  const [newName,     setNewName]     = useState('')
  const [newDesc,     setNewDesc]     = useState('')
  const [creating,    setCreating]    = useState(false)
  const [uploading,   setUploading]   = useState(false)
  const [uploadErr,   setUploadErr]   = useState('')
  const [docType,     setDocType]     = useState('blueprint')

  const load = () =>
    listProjects().then(r => setProjects(r.data)).catch(() => {})

  const loadDocs = (pid) =>
    listProjectDocs(pid).then(r => setDocs(r.data)).catch(() => setDocs([]))

  useEffect(() => { load() }, [])
  useEffect(() => { if (selected) loadDocs(selected.id) }, [selected])

  const handleCreate = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      await createProject(newName.trim(), newDesc.trim())
      setNewName(''); setNewDesc('')
      await load()
    } finally { setCreating(false) }
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this project and all its data?')) return
    await deleteProject(id)
    if (selected?.id === id) setSelected(null)
    load()
  }

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file || !selected) return
    setUploading(true); setUploadErr('')
    try {
      await uploadDocument(file, docType, selected.id)
      await loadDocs(selected.id)
    } catch (err) {
      setUploadErr(err.response?.data?.detail || 'Upload failed')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const handleRemoveDoc = async (docId) => {
    await removeDocFromProject(selected.id, docId)
    loadDocs(selected.id)
  }

  return (
    <div style={S.wrap}>
      {/* ── Sidebar: project list ── */}
      <div style={S.sidebar}>
        <div style={S.h1}>🏗 ConstructOS</div>
        <div style={S.sub}>Construction Intelligence Platform</div>

        <div style={S.h2}>Projects</div>
        {projects.map(p => (
          <div key={p.id} style={S.card(selected?.id === p.id)} onClick={() => setSelected(p)}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>{p.name}</span>
              <button style={S.btn('danger')} onClick={(e) => { e.stopPropagation(); handleDelete(p.id) }}>×</button>
            </div>
            <div style={{ fontSize: 11, color: '#6b7a99', marginTop: 2 }}>
              {p.document_count} document{p.document_count !== 1 ? 's' : ''}
            </div>
          </div>
        ))}

        <div style={S.divider} />

        {/* Create new project */}
        <div style={S.h2}>New Project</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <input style={S.input} placeholder="Project name" value={newName}
                 onChange={e => setNewName(e.target.value)}
                 onKeyDown={e => e.key === 'Enter' && handleCreate()} />
          <input style={S.input} placeholder="Description (optional)" value={newDesc}
                 onChange={e => setNewDesc(e.target.value)} />
          <button style={S.btn()} onClick={handleCreate} disabled={creating || !newName.trim()}>
            {creating ? 'Creating…' : '+ Create Project'}
          </button>
        </div>
      </div>

      {/* ── Main panel ── */}
      <div style={S.main}>
        {!selected ? (
          <div style={{ color: '#6b7a99', marginTop: 60, textAlign: 'center', fontSize: 14 }}>
            ← Select or create a project
          </div>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 4 }}>
              <h1 style={{ fontSize: 22, margin: 0, color: '#e2e8f0' }}>{selected.name}</h1>
              <button style={S.btn()} onClick={() => navigate(`/project/${selected.id}`)}>
                Open Project →
              </button>
            </div>
            {selected.description && (
              <div style={{ fontSize: 13, color: '#6b7a99', marginBottom: 16 }}>{selected.description}</div>
            )}

            <div style={S.divider} />
            <div style={S.h2}>Documents ({docs.length})</div>

            {/* Upload */}
            <div style={{ ...S.row, marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
              <select style={S.select} value={docType} onChange={e => setDocType(e.target.value)}>
                {DOC_TYPES.map(t => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
              </select>
              <label style={{ ...S.btn(), cursor: 'pointer', display: 'inline-block' }}>
                {uploading ? 'Uploading…' : '+ Upload PDF'}
                <input type="file" accept=".pdf" style={{ display: 'none' }} onChange={handleUpload} disabled={uploading} />
              </label>
              {uploadErr && <span style={S.error}>{uploadErr}</span>}
            </div>

            {/* Document list */}
            {docs.length === 0 ? (
              <div style={{ color: '#6b7a99', fontSize: 13 }}>No documents yet. Upload a PDF above.</div>
            ) : docs.map(doc => (
              <div key={doc.id} style={S.docRow}>
                <span style={S.badge(doc.document_type)}>{doc.document_type}</span>
                <span style={{ flex: 1, fontSize: 13, color: '#e2e8f0', minWidth: 0,
                               overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {doc.filename}
                </span>
                <span style={{ fontSize: 11, color: '#6b7a99', whiteSpace: 'nowrap' }}>
                  {doc.page_count}p · {doc.chunk_count} chunks
                </span>
                <button style={S.btn('danger')} onClick={() => handleRemoveDoc(doc.id)}>Remove</button>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}
