import { useState } from 'react'

const TYPE_COLOR = {
  blueprint:        '#1d4ed8',
  specification:    '#065f46',
  boq:              '#78350f',
  method_statement: '#581c87',
  other:            '#374151',
}

const S = {
  card: (score) => ({
    background: '#111e30',
    borderLeft: `3px solid ${score > 0.7 ? '#2563eb' : score > 0.4 ? '#7c3aed' : '#374151'}`,
    borderRadius: '0 6px 6px 0', padding: '10px 12px', margin: '6px 0',
    cursor: 'pointer', transition: 'background 0.15s',
  }),
  header: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' },
  typeBadge: (type) => ({
    padding: '2px 7px', borderRadius: 8, fontSize: 10, fontWeight: 700,
    background: TYPE_COLOR[type] || TYPE_COLOR.other, color: '#e2e8f0',
  }),
  docName:  { fontSize: 12, fontWeight: 600, color: '#60a5fa', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  pageBtn:  { fontSize: 11, color: '#93c5fd', background: '#1e3a5f', padding: '2px 8px',
              borderRadius: 10, cursor: 'pointer', border: '1px solid #2563eb', fontWeight: 600, whiteSpace: 'nowrap' },
  meta:     { display: 'flex', gap: 8, marginBottom: 6, flexWrap: 'wrap' },
  metaItem: { fontSize: 11, color: '#6b7a99', background: '#0f1b2d', padding: '2px 7px', borderRadius: 4 },
  quote:    { fontSize: 11, color: '#94a3b8', fontStyle: 'italic', lineHeight: 1.6,
              borderLeft: '2px solid #1e3a5f', paddingLeft: 8, margin: '4px 0 0' },
  thumbWrap:{ marginTop: 8, borderRadius: 4, overflow: 'hidden', border: '1px solid #1e3a5f',
              background: '#0a1628', position: 'relative' },
  thumb:    { width: '100%', display: 'block', maxHeight: 180, objectFit: 'contain', background: '#0a1628' },
  thumbBadge:{ position: 'absolute', top: 4, right: 4, background: 'rgba(15,27,45,0.85)',
               borderRadius: 4, padding: '2px 6px', fontSize: 10, color: '#60a5fa', fontWeight: 600 },
  previewBtn:{ marginTop: 5, fontSize: 10, color: '#2563eb', cursor: 'pointer',
               textDecoration: 'underline', background: 'none', border: 'none', padding: 0 },
}

/**
 * CitationCard — renders either a structured Reference or a legacy Citation.
 *
 * Props:
 *   citation  — legacy Citation object (doc_id, filename, page_num, chunk_text, …)
 *   reference — structured Reference object (document_name, document_type, page, sheet, section, quote, image_url)
 *   onJumpToPage(pageNum, docId?)
 */
export default function CitationCard({ citation, reference, onJumpToPage }) {
  const [showThumb, setShowThumb]   = useState(false)
  const [thumbError, setThumbError] = useState(false)

  // Normalise to a unified display object
  const name    = reference?.document_name ?? citation?.filename ?? ''
  const type    = reference?.document_type ?? citation?.doc_type ?? 'other'
  const page    = reference?.page          ?? citation?.page_num  ?? 0
  const sheet   = reference?.sheet         ?? citation?.sheet     ?? ''
  const section = reference?.section       ?? citation?.section   ?? ''
  const quote   = reference?.quote         ?? citation?.chunk_text ?? ''
  const imgUrl  = reference?.image_url     ?? citation?.image_url ?? null
  const score   = citation?.relevance_score ?? 0
  const docId   = citation?.doc_id         ?? null

  const handleJump = (e) => {
    e.stopPropagation()
    if (page) onJumpToPage?.(page, docId)
  }

  return (
    <div style={S.card(score)} onClick={handleJump}>
      {/* Header row */}
      <div style={S.header}>
        <span style={S.typeBadge(type)}>{type}</span>
        <span style={S.docName} title={name}>{name}</span>
        {page > 0 && (
          <span style={S.pageBtn} title="Jump to this page in Blueprint viewer">
            Page {page}
          </span>
        )}
      </div>

      {/* Meta row: sheet + section */}
      {(sheet || section) && (
        <div style={S.meta}>
          {sheet   && <span style={S.metaItem}>📐 Sheet {sheet}</span>}
          {section && <span style={S.metaItem}>📋 {section}</span>}
        </div>
      )}

      {/* Quote */}
      {quote && (
        <div style={S.quote}>
          &ldquo;{quote.slice(0, 200)}{quote.length > 200 ? '…' : ''}&rdquo;
        </div>
      )}

      {/* Preview toggle */}
      {imgUrl && !thumbError && (
        <>
          <button style={S.previewBtn} onClick={(e) => { e.stopPropagation(); setShowThumb(v => !v) }}>
            {showThumb ? 'Hide preview' : '🖼 Preview page'}
          </button>
          {showThumb && (
            <div style={S.thumbWrap}>
              <img src={imgUrl} alt={`Page ${page} preview`} style={S.thumb}
                   onError={() => { setThumbError(true); setShowThumb(false) }} />
              <div style={S.thumbBadge}>Page {page}</div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
