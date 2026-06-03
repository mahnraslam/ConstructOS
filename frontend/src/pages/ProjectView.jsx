import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getProject, listProjectDocs, extractFacts,
  detectProjectConflicts, generateProjectRFIs, getProjectRFIs, uploadDocument,
} from '../api/client'
import ChatPanel from '../components/ChatPanel'
import BlueprintViewer from '../components/BlueprintViewer'
import ConflictDashboard from '../components/ConflictDashboard'
import FactViewer from '../components/FactViewer'

const TABS = {
  chat:      '💬 Chat',
  viewer:    '📐 Blueprint',
  conflicts: '⚡ Conflicts',
  rfis:      '📋 RFIs',
  facts:     '🔬 Facts',
}

const S = {
  wrap:    { display: 'flex', height: '100vh', background: '#0a1628', color: '#e2e8f0', fontFamily: 'system-ui, sans-serif', overflow: 'hidden' },
  sidebar: { width: 240, borderRight: '1px solid #1e3a5f', display: 'flex', flexDirection: 'column', flexShrink: 0 },
  sideHead:{ padding: '12px 14px', borderBottom: '1px solid #1e3a5f' },
  sideBody:{ flex: 1, overflowY: 'auto', padding: 10 },
  main:    { flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  topbar:  { display: 'flex', alignItems: 'center', gap: 0, padding: '0 16px',
             background: '#0f1b2d', borderBottom: '1px solid #1e3a5f', height: 48, flexShrink: 0 },
  projName:{ fontSize: 13, fontWeight: 600, color: '#94a3b8', borderRight: '1px solid #1e3a5f',
             paddingRight: 16, marginRight: 16, maxWidth: 200, overflow: 'hidden',
             textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  tabs:    { display: 'flex', gap: 4 },
  tab:     (active) => ({
    padding: '6px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600,
    cursor: 'pointer', border: 'none',
    background: active ? '#1e3a5f' : 'transparent',
    color:      active ? '#60a5fa' : '#6b7a99',
  }),
  content: { flex: 1, overflow: 'hidden', display: 'flex' },
  badge:   (type) => {
    const c = { blueprint: '#1d4ed8', specification: '#065f46', boq: '#78350f', method_statement: '#581c87', other: '#374151' }
    return { padding: '2px 6px', borderRadius: 8, fontSize: 10, fontWeight: 600, background: c[type] || c.other, color: '#e2e8f0' }
  },
  docRow:  (selected) => ({
    display: 'flex', alignItems: 'center', gap: 6, padding: '6px 8px', borderRadius: 6,
    marginBottom: 4, cursor: 'pointer',
    background: selected ? '#1e3a5f' : 'transparent',
    border: `1px solid ${selected ? '#2563eb' : 'transparent'}`,
  }),
  actionBtn: { padding: '5px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
               fontSize: 11, fontWeight: 600, background: '#1e3a5f', color: '#60a5fa' },
  status:  { fontSize: 11, color: '#6b7a99', marginTop: 4, minHeight: 16 },
}

export default function ProjectView() {
  const { projectId } = useParams()
  const navigate      = useNavigate()

  const [project,      setProject]      = useState(null)
  const [docs,         setDocs]         = useState([])
  const [selectedDocs, setSelectedDocs] = useState([])
  const [viewerDocId,  setViewerDocId]  = useState(null)
  const [viewPage,     setViewPage]     = useState(1)
  const [tab,          setTab]          = useState('chat')
  const [status,       setStatus]       = useState('')
  const [loading,      setLoading]      = useState(false)
  const [conflicts,    setConflicts]    = useState(null)
  const [rfis,         setRfis]         = useState(null)
  const [error,        setError]        = useState('')
  const [uploading,    setUploading]    = useState(false)
  const [docType,      setDocType]      = useState('blueprint')

  useEffect(() => {
    setError('')
    getProject(projectId)
      .then(r => setProject(r.data))
      .catch(e => setError('Failed to load project: ' + (e.response?.data?.detail || e.message)))
    
    listProjectDocs(projectId)
      .then(r => {
        setDocs(r.data)
        if (r.data.length > 0) {
          setSelectedDocs(r.data.map(d => d.id))
          const bp = r.data.find(d => d.document_type === 'blueprint')
          if (bp) setViewerDocId(bp.id)
        }
      })
      .catch(e => setError('Failed to load documents: ' + (e.response?.data?.detail || e.message)))
  }, [projectId])

  const toggleDoc = (docId) =>
    setSelectedDocs(prev => prev.includes(docId) ? prev.filter(id => id !== docId) : [...prev, docId])

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError('')
    try {
      await uploadDocument(file, docType, projectId)
      // Reload documents after upload
      const r = await listProjectDocs(projectId)
      setDocs(r.data)
      if (r.data.length > 0) {
        setSelectedDocs(r.data.map(d => d.id))
        const bp = r.data.find(d => d.document_type === 'blueprint')
        if (bp) setViewerDocId(bp.id)
      }
      setStatus(`✓ Uploaded ${file.name}`)
    } catch (err) {
      setError('Upload failed: ' + (err.response?.data?.detail || err.message))
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const handleJumpToPage = (pageNum, docId) => {
    if (docId) setViewerDocId(docId)
    setViewPage(pageNum)
    setTab('viewer')
  }

  const runExtract = async () => {
    setLoading(true); setStatus('Extracting facts…')
    try {
      for (const doc of docs) {
        setStatus(`Extracting: ${doc.filename}…`)
        await extractFacts(projectId, doc.id)
      }
      setStatus('Running conflict detection…')
      const r = await detectProjectConflicts(projectId)
      setConflicts(r.data)
      setStatus(`Found ${r.data.total} conflicts.`)
      setTab('conflicts')
    } catch (e) {
      setStatus('Error: ' + (e.response?.data?.detail || e.message))
    } finally { setLoading(false) }
  }

  const runGenerateRFIs = async () => {
    setLoading(true); setStatus('Generating RFIs…')
    try {
      const r = await generateProjectRFIs(projectId)
      setRfis(r.data.rfis)
      setStatus(`Generated ${r.data.total} RFIs.`)
      setTab('rfis')
    } catch (e) {
      setStatus('Error: ' + (e.response?.data?.detail || e.message))
    } finally { setLoading(false) }
  }

  const viewerDoc = docs.find(d => d.id === viewerDocId)

  return (
    <div style={S.wrap}>
      {/* Left sidebar */}
      <div style={S.sidebar}>
        <div style={S.sideHead}>
          <button style={{ background: 'none', border: 'none', color: '#6b7a99', cursor: 'pointer', fontSize: 12, padding: 0, marginBottom: 6 }}
                  onClick={() => navigate('/')}>← Back</button>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#94a3b8' }}>Documents</div>
          <div style={{ fontSize: 11, color: '#6b7a99' }}>☑ = included in chat</div>
        </div>
        <div style={S.sideBody}>
          {error && (
            <div style={{ background: '#7f1d1d', border: '1px solid #fca5a5', borderRadius: 6, padding: 10, marginBottom: 12, fontSize: 11, color: '#fca5a5' }}>
              ⚠ {error}
            </div>
          )}
          {docs.length === 0 ? (
            <div style={{ background: '#111e30', border: '1px dashed #1e3a5f', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 12 }}>No documents yet</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <label style={{ padding: '8px 12px', borderRadius: 6, fontSize: 11, fontWeight: 600,
                               cursor: 'pointer', background: '#1d4ed8', color: '#fff', display: 'block' }}>
                  {uploading ? '⏳ Uploading…' : '📄 Upload PDF'}
                  <input type="file" accept=".pdf" style={{ display: 'none' }} onChange={handleUpload} disabled={uploading} />
                </label>
                <select style={{ padding: '6px 10px', borderRadius: 6, fontSize: 11, background: '#111e30', border: '1px solid #1e3a5f', color: '#e2e8f0' }}
                        value={docType} onChange={e => setDocType(e.target.value)}>
                  <option value="blueprint">Blueprint</option>
                  <option value="specification">Specification</option>
                  <option value="boq">BOQ</option>
                  <option value="method_statement">Method Statement</option>
                  <option value="other">Other</option>
                </select>
              </div>
            </div>
          ) : (
            <>
              {docs.map(doc => (
                <div key={doc.id}>
                  <div style={S.docRow(selectedDocs.includes(doc.id))} onClick={() => toggleDoc(doc.id)}>
                    <input type="checkbox" checked={selectedDocs.includes(doc.id)} onChange={() => {}} style={{ flexShrink: 0 }} />
                    <span style={S.badge(doc.document_type)}>{doc.document_type.slice(0, 4)}</span>
                    <span style={{ fontSize: 11, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {doc.filename}
                    </span>
                  </div>
                  {doc.document_type === 'blueprint' && (
                    <button style={{ ...S.actionBtn, width: '100%', marginBottom: 4, fontSize: 10 }}
                            onClick={() => { setViewerDocId(doc.id); setTab('viewer') }}>
                      View in Blueprint →
                    </button>
                  )}
                </div>
              ))}
              <div style={{ marginTop: 12, padding: '10px 8px', borderTop: '1px solid #1e3a5f' }}>
                <label style={{ padding: '6px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600,
                               cursor: 'pointer', background: '#1e3a5f', color: '#60a5fa', display: 'block', textAlign: 'center' }}>
                  {uploading ? '⏳ Uploading…' : '➕ Add More'}
                  <input type="file" accept=".pdf" style={{ display: 'none' }} onChange={handleUpload} disabled={uploading} />
                </label>
              </div>
            </>
          )}
          {docs.length > 0 && (
            <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <button style={{ ...S.actionBtn, background: '#1d4ed8', color: '#fff' }}
                      onClick={runExtract} disabled={loading}>
                {loading ? '…' : '🔬 Extract Facts & Detect Conflicts'}
              </button>
              <button style={S.actionBtn} onClick={runGenerateRFIs} disabled={loading}>
                📋 Generate RFIs
              </button>
              <div style={S.status}>{status}</div>
            </div>
          )}
        </div>
      </div>

      {/* Main area */}
      <div style={S.main}>
        <div style={S.topbar}>
          <span style={S.projName}>{project?.name ?? 'Loading…'}</span>
          <div style={S.tabs}>
            {Object.entries(TABS).map(([key, label]) => (
              <button key={key} style={S.tab(tab === key)} onClick={() => setTab(key)}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <div style={S.content}>
          {tab === 'chat'      && <ChatPanel docIds={selectedDocs} projectId={projectId} onJumpToPage={handleJumpToPage} />}
          {tab === 'viewer'    && <BlueprintViewer docId={viewerDocId} page={viewPage} pageCount={viewerDoc?.page_count} onPageChange={setViewPage} />}
          {tab === 'conflicts' && <ConflictDashboard projectId={projectId} initialConflicts={conflicts} />}
          {tab === 'rfis'      && <RFIPanel projectId={projectId} initialRfis={rfis} />}
          {tab === 'facts'     && <FactViewer projectId={projectId} />}
        </div>
      </div>
    </div>
  )
}

function RFIPanel({ projectId, initialRfis }) {
  const [rfis,  setRfis]  = useState(initialRfis)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!rfis) {
      getProjectRFIs(projectId)
        .then(r => setRfis(r.data.rfis))
        .catch(e => setError('Failed to load RFIs: ' + (e.response?.data?.detail || e.message)))
    }
  }, [projectId])

  // Sync when parent generates new RFIs
  useEffect(() => { if (initialRfis) setRfis(initialRfis) }, [initialRfis])


  if (!rfis) return <div style={{ padding: 32, color: '#6b7a99', fontSize: 14 }}>Loading RFIs…</div>

  if (!rfis.length) return (
    <div style={{ padding: 32, color: '#6b7a99', fontSize: 14 }}>
      No RFIs yet. Run &quot;Extract Facts &amp; Detect Conflicts&quot; first, then &quot;Generate RFIs&quot;.
    </div>
  )

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
      <h2 style={{ fontSize: 16, color: '#e2e8f0', margin: '0 0 16px' }}>
        Requests for Information ({rfis.length})
      </h2>
      {error && <div style={{ color: '#f87171', fontSize: 12, marginBottom: 12 }}>{error}</div>}
      {rfis.map((rfi, i) => (
        <div key={i} style={{ background: '#111e30', border: '1px solid #1e3a5f', borderRadius: 8, padding: 16, marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#60a5fa' }}>{rfi.number}</span>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{rfi.subject}</span>
            <span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 8, marginLeft: 'auto',
                           background: rfi.priority === 'high' ? '#7f1d1d' : '#1e3a5f',
                           color: rfi.priority === 'high' ? '#fca5a5' : '#93c5fd' }}>
              {rfi.priority}
            </span>
          </div>
          <p style={{ fontSize: 13, color: '#94a3b8', margin: 0, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
            {rfi.body}
          </p>
          {rfi.references?.length > 0 && (
            <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {rfi.references.map((ref, j) => (
                <div key={j} style={{ fontSize: 11, background: '#0f1b2d', border: '1px solid #1e3a5f', borderRadius: 6, padding: '4px 8px', color: '#6b7a99' }}>
                  {ref.document_name}
                  {ref.sheet && ` · ${ref.sheet}`}
                  {ref.page > 0 && ` · p.${ref.page}`}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
