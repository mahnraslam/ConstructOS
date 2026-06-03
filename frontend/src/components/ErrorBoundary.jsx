import { Component } from 'react'

/**
 * ErrorBoundary — catches React component errors to prevent full UI crash
 * Production safety feature
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          background: '#0a1628',
          color: '#e2e8f0',
          padding: 32,
          textAlign: 'center',
        }}>
          <div style={{ fontSize: 32, marginBottom: 16 }}>⚠️</div>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
            Something went wrong
          </div>
          <div style={{ fontSize: 13, color: '#6b7a99', maxWidth: 400, lineHeight: 1.6 }}>
            {this.state.error?.message || 'An unexpected error occurred. Please try refreshing the page.'}
          </div>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: 16,
              padding: '8px 16px',
              borderRadius: 6,
              border: 'none',
              background: '#2563eb',
              color: '#fff',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            Refresh
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
