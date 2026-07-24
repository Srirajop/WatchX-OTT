import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  componentDidCatch(error, info) {
    console.error('Editor crashed:', error, info)
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 16,
          padding: 24, color: '#991b1b', fontSize: 13, lineHeight: 1.7 }}>
          <div style={{ fontWeight: 800, fontSize: 15, marginBottom: 8 }}>⚠️ Subtitle Editor hit an error</div>
          <div style={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', background: '#fff',
            border: '1px solid #fecaca', borderRadius: 8, padding: 10, marginBottom: 10 }}>
            {String(this.state.error && this.state.error.stack || this.state.error)}
          </div>
          <button onClick={() => this.setState({ error: null })}
            style={{ padding: '8px 14px', background: '#dc2626', color: '#fff', border: 'none',
              borderRadius: 8, fontWeight: 700, cursor: 'pointer' }}>
            Reload Editor
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
