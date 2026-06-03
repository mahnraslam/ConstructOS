import { useState, useEffect } from 'react'
import { getProjectConflicts, detectProjectConflicts } from '../api/client'

const SEV_COLOR = { high: '#7f1d1d', medium: '#78350f', low: '#1e3a5f' }
const SEV_TEXT  = { high: '#fca5a5', medium: '#fcd34d', low: '#93c5fd' }

const S = {
  wrap:    { flex: 1, overflowY: 'auto', padding: 24 },
  header:  { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 },
  h2:      { fontSize: 16, color: '#e2e8f0', margin: 0 },
  btn:     { padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12,
             fontWeight: 600, background: '#1d4ed8', color: '#fff' },
  empty:   { color: '#6b7a99', fontSize: 14, marginTop: 40 },
  table:   { width: '100%', borderCollapse: 'collapse' },
  th:      { textAlign: 'left', padding: '8px 12px', background: '#0f1b2d',
             color: '#6b7a99', fontSize: 11, fontWeight: 600, borderBottom: '1px solid #1e3a5f' },
  tr:      (sev) => ({ borderBottom: '1px solid #0f1b2d', background: 'transparent' }),
  td:      { padding: '10px 12px', fontSize: 12, color: '#e2e8f0', verticalAlign: 'top' },
  field:   { fontWeight: 600, color: '#60a5fa', textTransform: 'capitalize' },
  bpVal:   { color: '#93c5fd' },
  spVal:   { color: '#6ee7b7' },
  sevBadge:(sev) => ({
    padding: '2px 8px', borderRadius: 8, fontSize: 10, fontWeight: 700,
    background: SEV_COLOR[sev] || SEV_COLOR.low,
    color:      SEV_TEXT[sev]  || SEV_TEXT.low,
  }),
  ref:     { fontSize: 10, color: '#6b7a99', marginTop: 2 },
}

export default function ConflictDashboard({ projectId, initialConflicts }) {
  const [conflicts, setConflicts] = useState(initialConflicts?.conflicts ?? null)
  const [loading,   setLoading]   = useState(false)

  useEffect(() => {
    if (!conflicts) {
      getProjectConflicts(projectId).then(r => setConflicts(r.data.conflicts)).catch(() => setConflicts([]))
    }
  }, [projectId])

  // When parent re-runs detection, sync
  useEffect(() => {
    if (initialConflicts?.conflicts) setConflicts(initialConflicts.conflicts)
  }, [initialConflicts])

  const reDetect = async () => {
    setLoading(true)
    try {
      const r = await detectProjectConflicts(projectId)
      setConflicts(r.data.conflicts)
    } finally { setLoading(false) }
  }

  return (
    <div style={S.wrap}>
      <div style={S.header}>
        <h2 style={S.h2}>Conflict Dashboard</h2>
        {conflicts !== null && (
          <span style={{ fontSize: 12, color: '#6b7a99' }}>
            {conflicts.length} conflict{conflicts.length !== 1 ? 's' : ''} detected
          </span>
        )}
        <button style={S.btn} onClick={reDetect} disabled={loading}>
          {loading ? 'Detecting…' : '⚡ Re-Detect'}
        </button>
      </div>

      {conflicts === null ? (
        <div style={S.empty}>Loading conflicts…</div>
      ) : conflicts.length === 0 ? (
        <div style={S.empty}>
          No conflicts detected.<br />
          <span style={{ fontSize: 12, marginTop: 8, display: 'block' }}>
            Make sure you have at least one blueprint and one specification in the project,
            then run "Extract Facts &amp; Detect Conflicts".
          </span>
        </div>
      ) : (
        <table style={S.table}>
          <thead>
            <tr>
              <th style={S.th}>Field</th>
              <th style={S.th}>📐 Blueprint Value</th>
              <th style={S.th}>📋 Specification Value</th>
              <th style={S.th}>Severity</th>
              <th style={S.th}>Status</th>
            </tr>
          </thead>
          <tbody>
            {conflicts.map((c, i) => (
              <tr key={i} style={S.tr(c.severity)}>
                <td style={{ ...S.td, ...S.field }}>
                  {c.field.replace(/_/g, ' ')}
                </td>
                <td style={{ ...S.td }}>
                  <span style={S.bpVal}>{c.blueprint_value}</span>
                  {(c.blueprint_sheet || c.blueprint_page > 0) && (
                    <div style={S.ref}>
                      {c.blueprint_sheet && `Sheet ${c.blueprint_sheet}`}
                      {c.blueprint_page > 0 && ` · p.${c.blueprint_page}`}
                    </div>
                  )}
                </td>
                <td style={{ ...S.td }}>
                  <span style={S.spVal}>{c.spec_value}</span>
                  {(c.spec_section || c.spec_page > 0) && (
                    <div style={S.ref}>
                      {c.spec_section && c.spec_section}
                      {c.spec_page > 0 && ` · p.${c.spec_page}`}
                    </div>
                  )}
                </td>
                <td style={S.td}>
                  <span style={S.sevBadge(c.severity)}>{c.severity}</span>
                </td>
                <td style={S.td}>
                  <span style={{ color: '#f87171', fontSize: 11 }}>⚠ {c.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
