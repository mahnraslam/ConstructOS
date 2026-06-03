import { useState, useEffect } from 'react'
import { getProjectFacts } from '../api/client'

const CAT_COLOR = { structural: '#1d4ed8', architectural: '#065f46', mep: '#78350f' }

const S = {
  wrap:    { flex: 1, overflowY: 'auto', padding: 24 },
  header:  { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 },
  h2:      { fontSize: 16, color: '#e2e8f0', margin: 0 },
  empty:   { color: '#6b7a99', fontSize: 14, marginTop: 40 },
  filterRow:{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' },
  filterBtn:(active, cat) => ({
    padding: '4px 12px', borderRadius: 12, border: 'none', cursor: 'pointer', fontSize: 11, fontWeight: 600,
    background: active ? (CAT_COLOR[cat] || '#1e3a5f') : '#0f1b2d',
    color: '#e2e8f0', opacity: active ? 1 : 0.6,
  }),
  grid:    { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 },
  card:    (cat) => ({
    background: '#111e30', border: `1px solid ${CAT_COLOR[cat] || '#1e3a5f'}20`,
    borderLeft: `3px solid ${CAT_COLOR[cat] || '#1e3a5f'}`,
    borderRadius: '0 8px 8px 0', padding: 12,
  }),
  catBadge:(cat) => ({
    padding: '2px 7px', borderRadius: 8, fontSize: 10, fontWeight: 700,
    background: CAT_COLOR[cat] || '#374151', color: '#e2e8f0', marginBottom: 6, display: 'inline-block',
  }),
  field:   { fontSize: 12, fontWeight: 600, color: '#94a3b8', textTransform: 'capitalize', marginBottom: 2 },
  value:   { fontSize: 16, fontWeight: 700, color: '#60a5fa', marginBottom: 6 },
  meta:    { fontSize: 11, color: '#6b7a99', display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 4 },
  metaItem:{ background: '#0f1b2d', padding: '2px 6px', borderRadius: 4 },
  quote:   { fontSize: 11, color: '#64748b', fontStyle: 'italic', marginTop: 6,
             borderTop: '1px solid #1e3a5f', paddingTop: 6 },
  docName: { fontSize: 11, color: '#475569', marginTop: 4 },
}

export default function FactViewer({ projectId }) {
  const [facts,       setFacts]       = useState(null)
  const [activeFilter, setFilter]     = useState('all')
  const [error,       setError]       = useState('')

  useEffect(() => {
    getProjectFacts(projectId).then(r => setFacts(r.data)).catch(e => {
      setError('Failed to load facts: ' + (e.response?.data?.detail || e.message))
      setFacts([])
    })
  }, [projectId])

  if (facts === null) return <div style={{ padding: 24, color: '#6b7a99' }}>Loading facts…</div>

  const categories = ['all', ...new Set(facts.map(f => f.category))]
  const filtered   = activeFilter === 'all' ? facts : facts.filter(f => f.category === activeFilter)

  // Group by category for display
  const grouped = filtered.reduce((acc, f) => {
    acc[f.category] = acc[f.category] || []
    acc[f.category].push(f)
    return acc
  }, {})

  return (
    <div style={S.wrap}>
      <div style={S.header}>
        <h2 style={S.h2}>Extracted Facts</h2>
        <span style={{ fontSize: 12, color: '#6b7a99' }}>{facts.length} facts</span>
      </div>

      {error && (
        <div style={{ padding: 12, background: '#7f1d1d', border: '1px solid #fca5a5',
                      borderRadius: 6, color: '#fca5a5', fontSize: 12, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {facts.length === 0 ? (
        <div style={S.empty}>
          No facts extracted yet.<br />
          <span style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
            Click "Extract Facts &amp; Detect Conflicts" in the sidebar.
          </span>
        </div>
      ) : (
        <>
          {/* Category filter */}
          <div style={S.filterRow}>
            {categories.map(cat => (
              <button key={cat} style={S.filterBtn(activeFilter === cat, cat)}
                      onClick={() => setFilter(cat)}>
                {cat === 'all' ? `All (${facts.length})` : `${cat} (${facts.filter(f => f.category === cat).length})`}
              </button>
            ))}
          </div>

          {/* Cards grouped by category */}
          {Object.entries(grouped).map(([cat, catFacts]) => (
            <div key={cat} style={{ marginBottom: 24 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7a99', marginBottom: 8,
                            textTransform: 'uppercase', letterSpacing: 1 }}>
                {cat}
              </div>
              <div style={S.grid}>
                {catFacts.map(f => (
                  <div key={f.id} style={S.card(f.category)}>
                    <span style={S.catBadge(f.category)}>{f.category}</span>
                    <div style={S.field}>{f.field.replace(/_/g, ' ')}</div>
                    <div style={S.value}>{f.value}{f.unit ? ` ${f.unit}` : ''}</div>
                    <div style={S.meta}>
                      {f.page > 0    && <span style={S.metaItem}>p.{f.page}</span>}
                      {f.sheet       && <span style={S.metaItem}>Sheet {f.sheet}</span>}
                      {f.section     && <span style={S.metaItem}>{f.section}</span>}
                    </div>
                    {f.quote && (
                      <div style={S.quote}>&ldquo;{f.quote.slice(0,120)}&rdquo;</div>
                    )}
                    <div style={S.docName}>{f.filename}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  )
}
