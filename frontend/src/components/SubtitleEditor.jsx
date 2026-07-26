import { useState, useRef, useEffect, Component } from 'react'
import axios from 'axios'

const API = '/api'

// ─── time helpers ──────────────────────────────────────────────────
function tcToSec(tc) {
  if (!tc) return 0
  const m = String(tc).trim().match(/(\d+):(\d{2}):(\d{2})[,.](\d{1,3})/)
  if (!m) return 0
  const h = +m[1], mn = +m[2], s = +m[3], ms = +m[4].padEnd(3, '0')
  return h * 3600 + mn * 60 + s + ms / 1000
}
function secToTc(sec) {
  sec = Math.max(0, sec)
  const h = Math.floor(sec / 3600)
  const mn = Math.floor((sec % 3600) / 60)
  const s = Math.floor(sec % 60)
  const ms = Math.round((sec - Math.floor(sec)) * 1000)
  return `${String(h).padStart(2, '0')}:${String(mn).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms).padStart(3, '0')}`
}
function sameId(a, b) {
  return String(a) === String(b)
}
function normalizeSubs(list) {
  return (list || []).map((s, i) => ({
    ...s,
    id: Number.isFinite(Number(s.id)) ? Number(s.id) : i + 1,
    start_time: s.start_time || '',
    end_time: s.end_time || '',
    text: s.text || '',
  }))
}
function fmtClock(sec) {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const SUB_EXT = ['srt', 'vtt', 'ass', 'ssa', 'sub', 'sbv', 'lrc', 'ttml', 'xml', 'csv', 'json', 'txt']
const LANGUAGES = ['English', 'Spanish', 'French', 'German', 'Italian', 'Portuguese',
  'Russian', 'Arabic', 'Hindi', 'Chinese (Simplified)', 'Japanese', 'Korean',
  'Turkish', 'Dutch', 'Polish', 'Ukrainian']

// Fallback provider list (backend /editor/translate/providers overrides this).
// Mirrors Subtitle Edit's multi-engine auto-translate
const PROVIDERS_FALLBACK = [
  { value: 'google', name: 'Google Translate (free, no key)', needsKey: false, customEndpoint: false, models: [], default_model: '', default_base_url: '' },
  { value: 'openai', name: 'ChatGPT / OpenAI', needsKey: true, customEndpoint: false, models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-5-mini'], default_model: 'gpt-4o-mini', default_base_url: 'https://api.openai.com/v1' },
  { value: 'anthropic', name: 'Claude (Anthropic)', needsKey: true, customEndpoint: false, models: ['claude-3-5-haiku-latest', 'claude-3-7-sonnet-latest', 'claude-sonnet-4-0'], default_model: 'claude-3-5-haiku-latest', default_base_url: 'https://api.anthropic.com/v1' },
  { value: 'gemini', name: 'Google Gemini', needsKey: true, customEndpoint: false, models: ['gemini-2.0-flash', 'gemini-2.5-flash', 'gemini-2.5-pro'], default_model: 'gemini-2.0-flash', default_base_url: '' },
  { value: 'deepl', name: 'DeepL', needsKey: true, customEndpoint: true, models: [], default_model: '', default_base_url: 'https://api-free.deepl.com/v2' },
  { value: 'deepseek', name: 'DeepSeek', needsKey: true, customEndpoint: false, models: ['deepseek-chat', 'deepseek-reasoner'], default_model: 'deepseek-chat', default_base_url: 'https://api.deepseek.com/v1' },
  { value: 'groq', name: 'Groq', needsKey: true, customEndpoint: false, models: ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant'], default_model: 'llama-3.3-70b-versatile', default_base_url: 'https://api.groq.com/openai/v1' },
  { value: 'mistral', name: 'Mistral AI', needsKey: true, customEndpoint: false, models: ['mistral-small-latest', 'mistral-large-latest'], default_model: 'mistral-small-latest', default_base_url: 'https://api.mistral.ai/v1' },
  { value: 'openrouter', name: 'OpenRouter', needsKey: true, customEndpoint: false, models: ['openai/gpt-4o-mini', 'anthropic/claude-3.5-haiku'], default_model: 'openai/gpt-4o-mini', default_base_url: 'https://openrouter.ai/api/v1' },
  { value: 'perplexity', name: 'Perplexity', needsKey: true, customEndpoint: false, models: ['sonar', 'sonar-pro'], default_model: 'sonar', default_base_url: 'https://api.perplexity.ai' },
  { value: 'openai-compatible', name: 'OpenAI-Compatible API (custom)', needsKey: false, customEndpoint: true, models: [], default_model: '', default_base_url: '' },
  { value: 'ollama', name: 'Ollama (local)', needsKey: false, customEndpoint: true, models: ['llama3', 'mistral', 'gemma2'], default_model: 'llama3', default_base_url: 'http://localhost:11434/v1' },
  { value: 'libretranslate', name: 'LibreTranslate (local / hosted)', needsKey: false, customEndpoint: true, models: [], default_model: '', default_base_url: 'http://localhost:5000' },
  { value: 'microsoft', name: 'Microsoft Azure Translator', needsKey: true, customEndpoint: true, models: [], default_model: '', default_base_url: '' },
]

const TRANSLATE_CFG_KEY = 'subtitleai_translate_config'

// ─── styles (Subtitle-Edit flavoured: dense, dark video side, light grid) ──
const st = {
  wrap: { display: 'flex', flexDirection: 'column', gap: 12, position: 'relative' },
  toolbar: { background: 'linear-gradient(180deg,#1e293b,#0f172a)', border: '1px solid #1e293b',
    borderRadius: 12, padding: '10px 14px', display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' },
  brand: { color: '#fff', fontWeight: 800, fontSize: 14, marginRight: 6, letterSpacing: 0.3 },
  fileBtn: { background: '#334155', border: '1px solid #475569', color: '#e2e8f0', padding: '8px 13px',
    borderRadius: 8, cursor: 'pointer', fontWeight: 700, fontSize: 12.5 },
  urlInput: { padding: '8px 11px', border: '1px solid #475569', borderRadius: 8, fontSize: 12.5,
    minWidth: 200, background: '#0f172a', color: '#e2e8f0', outline: 'none' },
  smallBtn: { padding: '8px 12px', background: '#fff', border: '1px solid #cbd5e1', borderRadius: 8,
    fontSize: 12.5, fontWeight: 700, cursor: 'pointer', color: '#334155' },
  primBtn: { padding: '8px 14px', background: 'linear-gradient(135deg,#6366f1,#4f46e5)', border: 'none',
    borderRadius: 8, color: '#fff', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' },
  mainGrid: { display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 460px', gap: 12, alignItems: 'stretch' },
  videoCard: { background: '#000', borderRadius: 12, overflow: 'hidden', display: 'flex', flexDirection: 'column', border: '1px solid #1e293b' },
  videoShell: { position: 'relative', background: '#000' },
  video: { width: '100%', display: 'block', background: '#000', maxHeight: 460 },
  // transport bar
  transportBar: { background: '#0f172a', borderTop: '1px solid #1e293b', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 },
  ctrlRowMain: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' },
  ctrlGroup: { display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' },
  playBtn: { background: 'linear-gradient(135deg,#6366f1,#4f46e5)', border: 'none', color: '#fff', width: 34, height: 34, borderRadius: 8, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, fontWeight: 'bold', boxShadow: '0 2px 6px rgba(99,102,241,0.4)' },
  transportBtn: { background: '#1e293b', border: '1px solid #334155', color: '#e2e8f0', padding: '6px 9px', borderRadius: 7, cursor: 'pointer', fontSize: 11.5, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 3 },
  transportBtnActive: { background: '#312e81', borderColor: '#6366f1', color: '#a5b4fc' },
  fpsSelect: { background: '#1e293b', border: '1px solid #334155', color: '#e2e8f0', padding: '5px 7px', borderRadius: 7, fontSize: 11, fontFamily: 'monospace', outline: 'none', cursor: 'pointer' },
  emptyVideo: { display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#64748b',
    height: 300, fontSize: 13, textAlign: 'center', padding: 20 },
  overlay: { position: 'absolute', bottom: 54, left: 0, right: 0, textAlign: 'center', padding: '0 20px',
    zIndex: 5,
    pointerEvents: 'none', textShadow: '0 2px 6px rgba(0,0,0,0.95)' },
  overlayText: { display: 'inline-block', background: 'rgba(0,0,0,0.7)', color: '#fff', fontSize: 19,
    lineHeight: 1.35, padding: '5px 14px', borderRadius: 8, whiteSpace: 'pre-wrap', maxWidth: '85%' },
  // timeline / waveform
  ruler: { position: 'relative', height: 20, background: '#0b1220', borderTop: '1px solid #1e293b',
    fontSize: 10, color: '#64748b', fontFamily: 'monospace', userSelect: 'none' },
  tick: { position: 'absolute', top: 0, bottom: 0, borderLeft: '1px solid #1e293b', paddingLeft: 3 },
  timeline: { position: 'relative', height: 64, background: '#0f172a', cursor: 'pointer', overflow: 'hidden', borderTop: '1px solid #1e293b' },
  block: { position: 'absolute', top: 10, height: 44, background: 'linear-gradient(180deg,#6366f1,#4f46e5)',
    borderRadius: 3, opacity: 0.9, border: '1px solid #a5b4fc', boxSizing: 'border-box', minWidth: 2,
    display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', fontSize: 9, color: '#e0e7ff' },
  blockActive: { background: 'linear-gradient(180deg,#f59e0b,#d97706)', borderColor: '#fde68a', opacity: 1 },
  playhead: { position: 'absolute', top: 0, bottom: 0, width: 2, background: '#ef4444', zIndex: 6, pointerEvents: 'none' },
  // subtitle list
  listCard: { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, display: 'flex', flexDirection: 'column', overflow: 'hidden', height: '72vh' },
  listHead: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px',
    borderBottom: '1px solid #e2e8f0', background: '#f8fafc' },
  listTitle: { fontSize: 13, fontWeight: 800, color: '#0f172a', textTransform: 'uppercase', letterSpacing: 0.6 },
  list: { overflowY: 'auto', padding: 8, background: '#f8fafc', flex: 1, minHeight: 0 },
  subRow: { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: 8, marginBottom: 6, cursor: 'pointer', transition: 'border-color .15s' },
  subRowActive: { borderColor: '#f59e0b', boxShadow: '0 0 0 2px #fde68a' },
  tcInline: { display: 'flex', gap: 5, marginBottom: 5, alignItems: 'center' },
  tcField: { flex: 1, padding: '4px 7px', border: '1px solid #e2e8f0', borderRadius: 6, fontSize: 11.5, fontFamily: 'monospace', outline: 'none', boxSizing: 'border-box' },
  txtArea: { width: '100%', minHeight: 42, border: '1px solid #e2e8f0', borderRadius: 7, padding: '7px 9px',
    fontSize: 13.5, fontFamily: 'inherit', resize: 'vertical', outline: 'none', boxSizing: 'border-box', lineHeight: 1.45 },
  delBtn: { background: '#fee2e2', border: 'none', color: '#dc2626', borderRadius: 6, padding: '3px 8px', cursor: 'pointer', fontSize: 11, fontWeight: 700 },
  // controls
  controls: { display: 'grid', gridTemplateColumns: '360px 1fr', gap: 12, alignItems: 'start' },
  panel: { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16 },
  panelTitle: { fontSize: 12.5, fontWeight: 800, color: '#4f46e5', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 12 },
  subTitle: { fontSize: 12, fontWeight: 700, color: '#334155', margin: '12px 0 7px' },
  input: { width: '100%', padding: '8px 10px', border: '1.5px solid #e2e8f0', borderRadius: 8, fontSize: 12.5, outline: 'none', boxSizing: 'border-box' },
  row: { display: 'flex', gap: 7, marginBottom: 7 },
  msg: { fontSize: 12, padding: '8px 10px', borderRadius: 8, marginBottom: 8 },
  msgOk: { background: '#ecfdf5', color: '#059669', border: '1px solid #a7f3d0' },
  msgErr: { background: '#fef2f2', color: '#dc2626', border: '1px solid #fca5a5' },
  // drag overlay
  dropOverlay: { position: 'fixed', inset: 0, background: 'rgba(79,70,229,0.92)', zIndex: 100001,
    display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 22,
    fontWeight: 800, flexDirection: 'column', gap: 10, pointerEvents: 'none' },
  // toolbar buttons (open popups)
  tbBtn: { background: '#334155', border: '1px solid #475569', color: '#e2e8f0', padding: '9px 14px',
    borderRadius: 8, cursor: 'pointer', fontWeight: 700, fontSize: 12.5 },
  fieldLabel: { fontSize: 12, fontWeight: 700, color: '#334155', textTransform: 'uppercase',
    letterSpacing: 0.6, marginBottom: 8 },
  modalFileBtn: { display: 'block', background: '#eef2ff', border: '1px solid #c7d2fe', color: '#4338ca',
    padding: '14px', borderRadius: 10, cursor: 'pointer', fontWeight: 700, fontSize: 13, textAlign: 'center' },
  modalOverlay: { position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.65)', zIndex: 100000,
    display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 },
  modalBox: { background: '#fff', borderRadius: 16, width: '100%', maxWidth: 520, maxHeight: '90vh',
    overflow: 'auto', boxShadow: '0 20px 50px rgba(0,0,0,0.35)' },
  modalHead: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 18px',
    borderBottom: '1px solid #e2e8f0', position: 'sticky', top: 0, background: '#fff',
    borderTopLeftRadius: 16, borderTopRightRadius: 16 },
  modalTitle: { fontSize: 15, fontWeight: 800, color: '#0f172a' },
  modalBody: { padding: 18 },
  modalClose: { background: '#f1f5f9', border: 'none', color: '#64748b', cursor: 'pointer',
    width: 30, height: 30, borderRadius: '50%', fontSize: 14 },
  vsyncTime: { fontSize: 13, color: '#334155', marginBottom: 8, fontFamily: 'monospace' },
  vsyncList: { maxHeight: 220, overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: 10,
    padding: 6, background: '#f8fafc', marginBottom: 10 },
  vsyncRow: { display: 'flex', gap: 8, alignItems: 'flex-start', padding: '7px 9px', borderRadius: 7,
    cursor: 'pointer', border: '1px solid transparent' },
  vsyncRowActive: { background: '#fff7ed', borderColor: '#fdba74' },
  vsyncNum: { fontSize: 11, fontWeight: 800, color: '#94a3b8', minWidth: 28 },
  vsyncTxt: { fontSize: 12.5, color: '#334155', lineHeight: 1.4, whiteSpace: 'nowrap',
    overflow: 'hidden', textOverflow: 'ellipsis' },
  vsyncPreviewHead: { fontSize: 12, fontWeight: 800, color: '#0f172a', margin: '12px 0 6px' },
  vsyncVideo: { width: '100%', borderRadius: 10, background: '#000', maxHeight: 220, display: 'block' },
  // detailed timeline (waveform + ruler + draggable blocks)
  tlToolbar: { display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', background: '#1e293b', fontSize: 12, color: '#cbd5e1' },
  tlBtn: { background: '#334155', border: '1px solid #475569', color: '#e2e8f0', borderRadius: 6,
    width: 26, height: 24, cursor: 'pointer', fontWeight: 800, fontSize: 14, lineHeight: 1 },
  timelineWrap: { overflowX: 'auto', overflowY: 'hidden', background: '#0f172a', borderTop: '1px solid #1e293b' },
  timelineInner: { position: 'relative', height: 120, minWidth: '100%' },
  waveCanvas: { position: 'absolute', top: 0, left: 0, height: 56, width: '100%', display: 'block', pointerEvents: 'none' },
  tlRuler: { position: 'absolute', top: 56, left: 0, right: 0, height: 18, fontSize: 10, color: '#64748b',
    fontFamily: 'monospace', userSelect: 'none' },
  tlTick: { position: 'absolute', top: 0, height: 18, borderLeft: '1px solid #1e293b', paddingLeft: 3 },
  tlBlock: { position: 'absolute', top: 80, height: 36, background: 'linear-gradient(180deg,#6366f1,#4f46e5)',
    borderRadius: 4, border: '1px solid #a5b4fc', boxSizing: 'border-box', display: 'flex', alignItems: 'center',
    overflow: 'hidden', cursor: 'grab', userSelect: 'none' },
  tlBlockActive: { background: 'linear-gradient(180deg,#f59e0b,#d97706)', borderColor: '#fde68a' },
  tlBlockText: { flex: 1, fontSize: 10.5, color: '#e0e7ff', padding: '0 4px', whiteSpace: 'nowrap',
    overflow: 'hidden', textOverflow: 'ellipsis', pointerEvents: 'none', minWidth: 0 },
  tlHandle: { width: 6, alignSelf: 'stretch', cursor: 'ew-resize', background: 'rgba(255,255,255,0.25)', flex: '0 0 auto' },
  progOuter: { width: '100%', height: 12, background: '#f1f5f9', borderRadius: 10, overflow: 'hidden', marginTop: 12 },
  progInner: { height: '100%', background: 'linear-gradient(90deg,#6366f1,#a855f7)', borderRadius: 10, transition: 'width .2s ease' },
  progCount: { fontSize: 14, fontWeight: 700, color: '#4f46e5', marginBottom: 4 },
  progLog: { marginTop: 14, maxHeight: 260, overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: 10, background: '#f8fafc' },
  progRow: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, padding: '8px 10px', borderBottom: '1px solid #eef2f7', fontSize: 12, lineHeight: 1.45 },
  progOrig: { color: '#64748b', whiteSpace: 'pre-wrap', wordBreak: 'break-word' },
  progTrans: { color: '#0f172a', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontWeight: 600 },
  progHead: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, padding: '6px 10px', fontSize: 10.5,
    fontWeight: 800, textTransform: 'uppercase', letterSpacing: 0.6, color: '#94a3b8', borderBottom: '2px solid #e2e8f0' },
}

// Mini Waveform & Subtitle Block Timeline Scrubber for Visual Sync previews
function SyncTimelinePreview({ curTime, dur, fps, activeSubId, onSeek, accentColor = '#38bdf8', peaks, subs }) {
  const containerRef = useRef(null)
  const canvasRef = useRef(null)

  const safeDur = dur > 0 ? dur : 60
  const playheadPct = Math.min(100, Math.max(0, (curTime / safeDur) * 100))

  useEffect(() => {
    const c = canvasRef.current
    if (!c) return
    const w = c.width, h = c.height, mid = h / 2
    if (!w || !h) return
    const ctx = c.getContext('2d')
    ctx.clearRect(0, 0, w, h)
    ctx.fillStyle = '#0f172a'
    ctx.fillRect(0, 0, w, h)
    if (peaks && peaks.N) {
      ctx.strokeStyle = '#475569'
      ctx.lineWidth = 1
      ctx.beginPath()
      for (let x = 0; x < w; x++) {
        const idx = Math.min(peaks.N - 1, Math.floor((x / w) * peaks.N))
        const maxVal = Number.isFinite(peaks.maxs?.[idx]) ? peaks.maxs[idx] : 0
        const minVal = Number.isFinite(peaks.mins?.[idx]) ? peaks.mins[idx] : 0
        const y1 = mid - maxVal * (mid - 2)
        const y2 = mid - minVal * (mid - 2)
        ctx.moveTo(x + 0.5, y1)
        ctx.lineTo(x + 0.5, y2)
      }
      ctx.stroke()
    }
  }, [peaks, safeDur])

  function handleClick(e) {
    if (!containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const clickX = e.clientX - rect.left
    const pct = Math.max(0, Math.min(1, clickX / rect.width))
    onSeek(pct * safeDur)
  }

  return (
    <div ref={containerRef} onClick={handleClick}
      style={{
        position: 'relative',
        height: 64,
        background: '#0b1220',
        borderRadius: 8,
        overflow: 'hidden',
        cursor: 'pointer',
        border: '1px solid #1e293b',
        userSelect: 'none'
      }}>
      {/* Waveform Canvas */}
      <canvas ref={canvasRef} width={440} height={38} style={{ width: '100%', height: 38, display: 'block' }} />

      {/* Subtitle Block Markers overlay */}
      <div style={{ position: 'absolute', top: 38, left: 0, right: 0, bottom: 0, background: '#020617', borderTop: '1px solid #1e293b' }}>
        {subs.map(s => {
          const startSec = tcToSec(s.start_time)
          const endSec = tcToSec(s.end_time) || startSec + 2
          const leftPct = (startSec / safeDur) * 100
          const widthPct = Math.max(0.6, ((endSec - startSec) / safeDur) * 100)
          const isSelected = String(s.id) === String(activeSubId)

          return (
            <div key={s.id} title={`#${s.id} ${s.start_time} - ${s.text}`}
              style={{
                position: 'absolute',
                left: `${leftPct}%`,
                width: `${widthPct}%`,
                top: 2,
                height: 20,
                background: isSelected ? accentColor : '#334155',
                borderRadius: 3,
                fontSize: 9.5,
                fontWeight: 700,
                color: isSelected ? '#000' : '#cbd5e1',
                padding: '1px 3px',
                overflow: 'hidden',
                whiteSpace: 'nowrap',
                textOverflow: 'ellipsis',
                boxShadow: isSelected ? `0 0 8px ${accentColor}` : 'none',
                zIndex: isSelected ? 2 : 1
              }}>
              #{s.id} {s.text.split('\n')[0]}
            </div>
          )
        })}
      </div>

      {/* Red Playhead Line */}
      <div style={{
        position: 'absolute',
        top: 0,
        bottom: 0,
        left: `${playheadPct}%`,
        width: 2,
        background: '#ef4444',
        boxShadow: '0 0 6px #ef4444',
        pointerEvents: 'none',
        zIndex: 5
      }} />
    </div>
  )
}

// Lightweight popup used by the toolbar buttons (Subtitle-Edit style)
function Modal({ title, onClose, maxWidth = 520, children }) {
  return (
    <div style={st.modalOverlay} onClick={onClose}>
      <div style={{ ...st.modalBox, maxWidth }} onClick={e => e.stopPropagation()}>
        <div style={st.modalHead}>
          <span style={st.modalTitle}>{title}</span>
          <button style={st.modalClose} onClick={onClose}>✕</button>
        </div>
        <div style={st.modalBody}>{children}</div>
      </div>
    </div>
  )
}

function SubtitleEditor() {
  const [videoSrc, setVideoSrc] = useState(null)
  const [videoUrl, setVideoUrl] = useState('')
  const [duration, setDuration] = useState(0)
  const [activeId, setActiveId] = useState(null)
  const [subs, setSubs] = useState([])
  const [filename, setFilename] = useState('subtitles')
  const [formats, setFormats] = useState({ import: [], export: [] })

  const [msg, setMsg] = useState(null)
  const [exportFmt, setExportFmt] = useState('srt')
  const [busy, setBusy] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [modal, setModal] = useState(null)   // 'video' | 'subs' | 'sync' | 'translate' | 'export'
  const [pxPerSec, setPxPerSec] = useState(80)   // timeline zoom (pixels per second)
  const [translating, setTranslating] = useState(false)
  const [translateProgress, setTranslateProgress] = useState({ done: 0, total: 0 })
  const [translateLog, setTranslateLog] = useState([])

  // video transport & workspace fullscreen state
  const [isPlaying, setIsPlaying] = useState(false)
  const [fps, setFps] = useState(25)
  const [showFrames, setShowFrames] = useState(true)
  const [playbackRate, setPlaybackRate] = useState(1)
  const [audioScrub, setAudioScrub] = useState(true)
  const [isEditorFullscreen, setIsEditorFullscreen] = useState(false)
  const [isVideoFullscreen, setIsVideoFullscreen] = useState(false)

  const isPlayingRef = useRef(false)
  const scrubTimerRef = useRef(null)

  useEffect(() => { isPlayingRef.current = isPlaying }, [isPlaying])

  const wrapRef = useRef(null)
  const fpsRef = useRef(25)
  const tcDisplayRef = useRef(null)
  const frameDisplayRef = useRef(null)

  useEffect(() => { fpsRef.current = fps }, [fps])

  function toggleEditorFullscreen() {
    setIsEditorFullscreen(prev => {
      const next = !prev
      if (next) {
        if (wrapRef.current?.requestFullscreen) wrapRef.current.requestFullscreen().catch(() => {})
      } else {
        if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {})
      }
      return next
    })
  }

  function toggleVideoFullscreen() {
    const v = videoRef.current
    if (!v) {
      flash('err', 'Please open a video first')
      return
    }

    const currentFullscreen =
      document.fullscreenElement ||
      document.webkitFullscreenElement ||
      document.mozFullScreenElement ||
      document.msFullscreenElement

    const requestVideoFullscreen = () => {
      const shell = videoShellRef.current
      if (shell?.requestFullscreen) {
        shell.requestFullscreen().catch(() => {})
      } else if (shell?.webkitRequestFullscreen) {
        shell.webkitRequestFullscreen()
      } else if (v.requestFullscreen) {
        v.requestFullscreen().catch(() => {})
      } else if (v.webkitRequestFullscreen) {
        v.webkitRequestFullscreen()
      } else if (v.webkitEnterFullscreen) {
        v.webkitEnterFullscreen()
      } else if (v.mozRequestFullScreen) {
        v.mozRequestFullScreen()
      } else if (v.msRequestFullscreen) {
        v.msRequestFullscreen()
      }
    }

    if (currentFullscreen === videoShellRef.current || currentFullscreen === v) {
      if (document.exitFullscreen) {
        document.exitFullscreen().catch(() => {})
      } else if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen()
      }
    } else if (currentFullscreen) {
      const exitPromise = document.exitFullscreen ? document.exitFullscreen() : Promise.resolve()
      exitPromise.finally(requestVideoFullscreen)
    } else {
      requestVideoFullscreen()
    }
  }

  useEffect(() => {
    function handleEsc(e) {
      if (e.key === 'Escape' && isEditorFullscreen && !modal && !translating) {
        if (document.fullscreenElement && document.exitFullscreen) {
          document.exitFullscreen().catch(() => {})
        }
        setIsEditorFullscreen(false)
      }
    }
    function handleFsChange() {
      const fsEl =
        document.fullscreenElement ||
        document.webkitFullscreenElement ||
        document.mozFullScreenElement ||
        document.msFullscreenElement

      const isVidFs = fsEl === videoShellRef.current || fsEl === videoRef.current
      setIsVideoFullscreen(Boolean(isVidFs))
      if (!fsEl) {
        setIsEditorFullscreen(false)
      }
    }

    window.addEventListener('keydown', handleEsc)
    document.addEventListener('fullscreenchange', handleFsChange)
    document.addEventListener('webkitfullscreenchange', handleFsChange)
    document.addEventListener('mozfullscreenchange', handleFsChange)
    document.addEventListener('MSFullscreenChange', handleFsChange)
    return () => {
      window.removeEventListener('keydown', handleEsc)
      document.removeEventListener('fullscreenchange', handleFsChange)
      document.removeEventListener('webkitfullscreenchange', handleFsChange)
      document.removeEventListener('mozfullscreenchange', handleFsChange)
      document.removeEventListener('MSFullscreenChange', handleFsChange)
    }
  }, [isEditorFullscreen, modal, translating])

  // sync state & visual preview helpers
  const [offsetVal, setOffsetVal] = useState('')
  const [scaleVal, setScaleVal] = useState('')
  const [fpsWorking, setFpsWorking] = useState('24')
  const [fpsTarget, setFpsTarget] = useState('25')
  const [durWorking, setDurWorking] = useState('')
  const [durTarget, setDurTarget] = useState('')
  const [pointId, setPointId] = useState('')
  const [pointStart, setPointStart] = useState('')
  const [pointId2, setPointId2] = useState('')
  const [pointStart2, setPointStart2] = useState('')
  const [syncRangeStart, setSyncRangeStart] = useState('')
  const [syncRangeEnd, setSyncRangeEnd] = useState('')

  const [vsStartTime, setVsStartTime] = useState(0)
  const [vsEndTime, setVsEndTime] = useState(0)
  const [vsStartPlaying, setVsStartPlaying] = useState(false)
  const [vsEndPlaying, setVsEndPlaying] = useState(false)

  function onVsStartUpdate() {
    if (vsStartRef.current) setVsStartTime(vsStartRef.current.currentTime || 0)
  }
  function onVsEndUpdate() {
    if (vsEndRef.current) setVsEndTime(vsEndRef.current.currentTime || 0)
  }
  function toggleVsPlay(v) {
    if (!v) return
    if (v.paused) v.play()
    else v.pause()
    if (v === vsStartRef.current) setVsStartPlaying(!v.paused)
    if (v === vsEndRef.current) setVsEndPlaying(!v.paused)
  }
  function nudgeVs(v, frames) {
    if (!v) return
    v.pause()
    const step = 1 / (fpsRef.current || 25)
    const newTime = Math.max(0, Math.min(durRef.current, v.currentTime + frames * step))
    v.currentTime = newTime
    if (v === vsStartRef.current) { setVsStartTime(newTime); setVsStartPlaying(false) }
    if (v === vsEndRef.current) { setVsEndTime(newTime); setVsEndPlaying(false) }
    if (audioScrub) triggerAudioScrubBurst(newTime, 100, v)
  }
  function seekVs(v, sec) {
    if (!v) return
    const newTime = Math.max(0, Math.min(durRef.current, sec))
    v.currentTime = newTime
    if (v === vsStartRef.current) setVsStartTime(newTime)
    if (v === vsEndRef.current) setVsEndTime(newTime)
    if (audioScrub) triggerAudioScrubBurst(newTime, 120, v)
  }

  // point-via-other
  const [refSubs, setRefSubs] = useState([])
  const [refName, setRefName] = useState('')
  const [mainIdx, setMainIdx] = useState('')
  const [refIdx, setRefIdx] = useState('')
  const [mainIdx2, setMainIdx2] = useState('')
  const [refIdx2, setRefIdx2] = useState('')

  // translate
  const [targetLang, setTargetLang] = useState('Spanish')
  const [sourceLang, setSourceLang] = useState('')
  const [providers, setProviders] = useState(PROVIDERS_FALLBACK)
  const [translateProvider, setTranslateProvider] = useState('google')
  const [translateApiKey, setTranslateApiKey] = useState('')
  const [translateModel, setTranslateModel] = useState('')
  const [translateEndpoint, setTranslateEndpoint] = useState('')
  const [translatePrompt, setTranslatePrompt] = useState('')
  const [showAdvTranslate, setShowAdvTranslate] = useState(false)

  const videoRef = useRef(null)
  const videoShellRef = useRef(null)
  const fileVideoRef = useRef(null)
  const fileSubRef = useRef(null)
  const fileRefRef = useRef(null)
  const timelineRef = useRef(null)
  const listRef = useRef(null)
  const rowRefs = useRef({})
  const playheadRef = useRef(null)
  const clockRef = useRef(null)
  const rafRef = useRef(null)
  const trackRef = useRef(null)
  const vttUrlRef = useRef(null)
  const translateClientRef = useRef('')   // id for an in-flight translate job (for Stop)
  const [stopping, setStopping] = useState(false)
  const vsyncTimeRef = useRef(null)
  const vsStartRef = useRef(null)
  const vsEndRef = useRef(null)
  const timelineWrapRef = useRef(null)
  const timelineInnerRef = useRef(null)
  const waveCanvasRef = useRef(null)
  const pxPerSecRef = useRef(80)
  useEffect(() => { pxPerSecRef.current = pxPerSec }, [pxPerSec])
  const audioBufferRef = useRef(null)
  const audioCtxRef = useRef(null)
  const peaksRef = useRef(null)   // [min,max] columns for the waveform
  const dragRef = useRef(null)
  const movedRef = useRef(false)
  const subsRef = useRef([])
  const durRef = useRef(60)

  const flash = (type, text) => { setMsg({ type, text }); setTimeout(() => setMsg(null), 4000) }

  const dur = duration || (subs.length ? tcToSec(subs[subs.length - 1].end_time) + 5 : 60)
  useEffect(() => { 
    subsRef.current = subs.map(s => ({
      ...s,
      _startSec: tcToSec(s.start_time),
      _endSec: tcToSec(s.end_time) || tcToSec(s.start_time) + 0.001
    }))
  }, [subs])
  useEffect(() => { durRef.current = dur }, [dur])

  // Which subtitle is "on screen" at time t (reads the live ref)
  function activeIdAt(t) {
    const list = subsRef.current
    for (const s of list) {
      if (t >= s._startSec && t < s._endSec) return s.id
    }
    return null
  }

  // rAF loop: moves the playhead + clock through DOM refs (smooth, no full
  // re-render every frame) and only flips the `activeId` state when the
  // current subtitle line actually changes — that drives the highlight +
  // auto-scroll of the synced side-by-side list.
  function paintPlayhead(t) {
    const d = durRef.current || 1
    const f = fpsRef.current || 25
    const curFrame = Math.floor(t * f)
    const totFrames = Math.floor(d * f)
    if (playheadRef.current) playheadRef.current.style.left = `${Math.min(100, (t / d) * 100)}%`
    if (clockRef.current) clockRef.current.textContent = `${fmtClock(t)} / ${fmtClock(d)}`
    if (vsyncTimeRef.current) vsyncTimeRef.current.textContent = fmtClock(t)
    if (tcDisplayRef.current) tcDisplayRef.current.textContent = secToTc(t)
    if (frameDisplayRef.current) frameDisplayRef.current.textContent = `#${curFrame.toLocaleString()} / #${totFrames.toLocaleString()}`

    // Auto-scroll timeline window to keep the red playhead centered in view
    const wrap = timelineWrapRef.current
    if (wrap && !dragRef.current) {
      const playheadPx = t * (pxPerSecRef.current || 80)
      const wrapW = wrap.clientWidth || 600
      const targetScroll = Math.max(0, playheadPx - wrapW / 2)
      if (Math.abs(wrap.scrollLeft - targetScroll) > 2) {
        wrap.scrollLeft = targetScroll
      }
    }
  }
  function tick() {
    const v = videoRef.current
    if (!v) return
    const t = v.currentTime
    paintPlayhead(t)
    const id = activeIdAt(t)
    setActiveId(prev => (prev === id ? prev : id))
    rafRef.current = requestAnimationFrame(tick)
  }
  function startRaf() { if (rafRef.current == null) rafRef.current = requestAnimationFrame(tick) }
  function stopRaf() { if (rafRef.current != null) { cancelAnimationFrame(rafRef.current); rafRef.current = null } }
  function updateOnce() {
    const v = videoRef.current
    if (!v) return
    paintPlayhead(v.currentTime)
    const id = activeIdAt(v.currentTime)
    setActiveId(prev => (prev === id ? prev : id))
  }

  function triggerAudioScrubBurst(timeSec, durationMs = 100, targetVideo = null) {
    if (!audioScrub) return
    const audioBuf = audioBufferRef.current

    if (audioBuf) {
      try {
        const AC = window.AudioContext || window.webkitAudioContext
        if (!audioCtxRef.current) audioCtxRef.current = new AC()
        const ac = audioCtxRef.current
        if (ac.state === 'suspended') ac.resume().catch(() => {})

        const source = ac.createBufferSource()
        source.buffer = audioBuf
        source.connect(ac.destination)

        const startOffset = Math.max(0, Math.min(audioBuf.duration - 0.05, timeSec))
        const durationSec = durationMs / 1000
        source.start(0, startOffset, durationSec)
        return
      } catch {
        /* fallback to video element audio */
      }
    }

    const v = targetVideo || videoRef.current
    if (!v) return
    try {
      if (scrubTimerRef.current) clearTimeout(scrubTimerRef.current)
      v.currentTime = timeSec
      const playPromise = v.play()
      if (playPromise !== undefined) {
        playPromise.then(() => {
          scrubTimerRef.current = setTimeout(() => {
            v.pause()
          }, durationMs)
        }).catch(() => {})
      }
    } catch {
      /* ignore audio errors */
    }
  }

  function togglePlayPause() {
    const v = videoRef.current
    if (!v) return
    if (v.paused) v.play()
    else v.pause()
  }

  function seekDelta(seconds) {
    const v = videoRef.current
    if (!v) return
    const wasPaused = v.paused
    const newTime = Math.max(0, Math.min(durRef.current, v.currentTime + seconds))
    v.currentTime = newTime
    updateOnce()
    if (wasPaused && audioScrub) triggerAudioScrubBurst(newTime, 120)
  }

  function stepFrame(frames) {
    const v = videoRef.current
    if (!v) return
    const wasPaused = v.paused
    const step = 1 / (fpsRef.current || 25)
    const newTime = Math.max(0, Math.min(durRef.current, v.currentTime + frames * step))
    v.currentTime = newTime
    updateOnce()
    if (wasPaused && audioScrub) triggerAudioScrubBurst(newTime, 100)
  }

  function playActiveSub() {
    const v = videoRef.current
    if (!v || activeId == null) return
    const sub = subs.find(s => sameId(s.id, activeId))
    if (!sub) return
    const start = tcToSec(sub.start_time)
    v.currentTime = start
    v.play()
  }

  useEffect(() => {
    function handleKeyDown(e) {
      const activeEl = document.activeElement
      const isInput = activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable)
      if (isInput) return

      if (e.code === 'Space') {
        e.preventDefault()
        togglePlayPause()
      } else if (e.code === 'ArrowLeft') {
        e.preventDefault()
        if (e.altKey) stepFrame(-1)
        else if (e.ctrlKey || e.metaKey) stepFrame(-5)
        else seekDelta(-1)
      } else if (e.code === 'ArrowRight') {
        e.preventDefault()
        if (e.altKey) stepFrame(1)
        else if (e.ctrlKey || e.metaKey) stepFrame(5)
        else seekDelta(1)
      } else if ((e.ctrlKey || e.metaKey) && e.code === 'KeyF') {
        e.preventDefault()
        toggleEditorFullscreen()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [activeId, isEditorFullscreen])

  useEffect(() => {
    axios.get(`${API}/editor/formats`).then(r => setFormats(r.data)).catch(() => {})
    return () => { if (videoSrc) URL.revokeObjectURL(videoSrc) }
  }, [videoSrc])

  // Load available translation providers + restore saved translate settings
  // (API key, model, endpoint) from localStorage so subtitlers don't re-paste.
  useEffect(() => {
    axios.get(`${API}/editor/translate/providers`).then(r => {
      if (r.data?.providers?.length) setProviders(r.data.providers)
    }).catch(() => {})
    try {
      const saved = JSON.parse(localStorage.getItem(TRANSLATE_CFG_KEY) || '{}')
      if (saved.provider) setTranslateProvider(saved.provider)
      if (saved.apiKey != null) setTranslateApiKey(saved.apiKey)
      if (saved.model != null) setTranslateModel(saved.model)
      if (saved.endpoint != null) setTranslateEndpoint(saved.endpoint)
      if (saved.prompt != null) setTranslatePrompt(saved.prompt)
      if (saved.targetLang) setTargetLang(saved.targetLang)
      if (saved.sourceLang != null) setSourceLang(saved.sourceLang)
    } catch { /* ignore corrupt storage */ }
  }, [])

  // Persist translate settings whenever they change.
  useEffect(() => {
    try {
      localStorage.setItem(TRANSLATE_CFG_KEY, JSON.stringify({
        provider: translateProvider, apiKey: translateApiKey, model: translateModel,
        endpoint: translateEndpoint, prompt: translatePrompt,
        targetLang, sourceLang,
      }))
    } catch { /* storage may be full / disabled */ }
  }, [translateProvider, translateApiKey, translateModel, translateEndpoint, translatePrompt, targetLang, sourceLang])

  // When the provider changes, prefill model + endpoint from its defaults
  // (unless the user already overrode them for that provider previously).
  function onProviderChange(val) {
    setTranslateProvider(val)
    const p = providers.find(x => x.value === val)
    if (!p) return
    // Only auto-fill if the current model/endpoint don't look custom/used.
    setTranslateModel(prev => (prev && translateProvider === val) ? prev : (p.default_model || ''))
    setTranslateEndpoint(prev => (prev && translateProvider === val) ? prev : (p.default_base_url || ''))
  }

  const activeProvider = providers.find(p => p.value === translateProvider) || providers[0]

  // cancel the rAF loop on unmount
  useEffect(() => () => stopRaf(), [])

  // Keep a VTT blob available for browser subtitle tooling, while the visible
  // preview is rendered from React state so it updates immediately after edits.
  function buildVtt(list) {
    const lines = ['WEBVTT', '']
    for (const s of list) {
      if (!s.text.trim()) continue
      const start = (s.start_time || '').replace(',', '.')
      const end = (s.end_time || '').replace(',', '.')
      if (!start || !end) continue
      lines.push(`${start} --> ${end}`)
      lines.push(s.text)
      lines.push('')
    }
    return lines.join('\n')
  }
  useEffect(() => {
    const track = trackRef.current
    if (!track) return
    const vtt = buildVtt(subs)
    const url = URL.createObjectURL(new Blob([vtt], { type: 'text/vtt' }))
    if (vttUrlRef.current) URL.revokeObjectURL(vttUrlRef.current)
    vttUrlRef.current = url
    track.src = url
  }, [subs])

  // show the track once it (re)loads
  function onTrackLoad() {
    const t = trackRef.current
    if (t && t.track) t.track.mode = 'hidden'
  }

  // auto-scroll ONLY the inner list container (instant scroll, no smooth animation lock)
  useEffect(() => {
    const list = listRef.current
    const row = activeId != null ? rowRefs.current[activeId] : null
    if (!list || !row) return
    const targetTop = row.offsetTop - (list.clientHeight / 2) + (row.offsetHeight / 2)
    list.scrollTop = Math.max(0, targetTop)
  }, [activeId])

  // redraw the waveform when zoom / duration / fullscreen mode changes (canvas width follows zoom)
  useEffect(() => {
    const c = waveCanvasRef.current
    if (!c) return
    const w = Math.min(8000, Math.max(600, Math.ceil(dur * pxPerSec)))
    const h = isEditorFullscreen ? 120 : 56
    c.width = w
    c.height = h
    drawWaveform()
  }, [pxPerSec, dur, isEditorFullscreen])

  // ── video ─────────────────────────────────────────────
  function loadVideoFromFile(f) {
    if (videoSrc) URL.revokeObjectURL(videoSrc)
    setVideoSrc(URL.createObjectURL(f))
    setVideoUrl('')
  }
  function onPickVideo(e) { const f = e.target.files?.[0]; if (f) loadVideoFromFile(f) }
  function loadUrl() { if (videoUrl.trim()) { if (videoSrc) URL.revokeObjectURL(videoSrc); setVideoSrc(videoUrl.trim()) } }
  function onMeta() {
    if (videoRef.current) setDuration(videoRef.current.duration || 0)
    updateOnce()
    startRaf()
    generateWaveform()
  }
  function seekTo(sec) {
    if (videoRef.current) { videoRef.current.currentTime = sec; updateOnce() }
  }
  function seekFromEvent(e) {
    const inner = timelineInnerRef.current
    if (!inner) return
    const rect = inner.getBoundingClientRect()
    const x = e.clientX - rect.left
    seekTo(Math.max(0, Math.min(dur, x / pxPerSec)))
  }

  // ── timeline waveform (Subtitle-Edit style) ───────────
  async function generateWaveform() {
    if (!videoSrc) return
    try {
      const AC = window.AudioContext || window.webkitAudioContext
      if (!audioCtxRef.current) audioCtxRef.current = new AC()
      const ac = audioCtxRef.current
      const buf = await (await fetch(videoSrc)).arrayBuffer()
      const audio = await ac.decodeAudioData(buf)
      audioBufferRef.current = audio
      const data = audio.getChannelData(0)
      const N = 4000
      const step = Math.max(1, Math.floor(data.length / N))
      const mins = new Float32Array(N), maxs = new Float32Array(N)
      for (let i = 0; i < N; i++) {
        let mn = 1, mx = -1
        const start = i * step
        for (let j = 0; j < step; j++) {
          const v = data[start + j] || 0
          if (v < mn) mn = v
          if (v > mx) mx = v
        }
        mins[i] = mn; maxs[i] = mx
      }
      peaksRef.current = { mins, maxs, N }
      drawWaveform()
    } catch (e) {
      console.warn('Waveform generation skipped:', e)
    }
  }
  function drawWaveform() {
    const c = waveCanvasRef.current
    const peaks = peaksRef.current
    if (!c) return
    const w = c.width, h = c.height, mid = h / 2
    if (!w || !h || !Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return
    const ctx = c.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, w, h)
    if (!peaks || !peaks.N) return
    ctx.fillStyle = '#0f172a'
    ctx.fillRect(0, 0, w, h)
    ctx.strokeStyle = '#64748b'
    ctx.lineWidth = 1
    ctx.beginPath()
    for (let x = 0; x < w; x++) {
      const idx = Math.min(peaks.N - 1, Math.floor((x / w) * peaks.N))
      const maxVal = Number.isFinite(peaks.maxs?.[idx]) ? peaks.maxs[idx] : 0
      const minVal = Number.isFinite(peaks.mins?.[idx]) ? peaks.mins[idx] : 0
      const y1 = mid - maxVal * (mid - 2)
      const y2 = mid - minVal * (mid - 2)
      ctx.moveTo(x + 0.5, y1)
      ctx.lineTo(x + 0.5, y2)
    }
    ctx.stroke()
  }

  // ── timeline block drag / resize ──────────────────────
  function onBlockPointerDown(e, s, mode) {
    e.stopPropagation()
    e.preventDefault()
    movedRef.current = false
    dragRef.current = {
      id: s.id, mode, startX: e.clientX,
      origStart: tcToSec(s.start_time), origEnd: tcToSec(s.end_time),
    }
    window.addEventListener('pointermove', onDragMove)
    window.addEventListener('pointerup', onDragUp)
  }
  function onDragMove(e) {
    const d = dragRef.current
    if (!d) return
    if (Math.abs(e.clientX - d.startX) > 3) movedRef.current = true
    const delta = (e.clientX - d.startX) / pxPerSec
    setSubs(prev => prev.map(s => {
      if (!sameId(s.id, d.id)) return s
      if (d.mode === 'move') {
        const len = d.origEnd - d.origStart
        const ns = Math.max(0, d.origStart + delta)
        return { ...s, start_time: secToTc(ns), end_time: secToTc(ns + len) }
      } else if (d.mode === 'left') {
        const ns = Math.max(0, Math.min(d.origEnd - 0.1, d.origStart + delta))
        return { ...s, start_time: secToTc(ns) }
      } else {
        const ne = Math.max(d.origStart + 0.1, d.origEnd + delta)
        return { ...s, end_time: secToTc(ne) }
      }
    }))
  }
  function onDragUp() {
    dragRef.current = null
    window.removeEventListener('pointermove', onDragMove)
    window.removeEventListener('pointerup', onDragUp)
  }


  // ── import (file / drag-drop) ─────────────────────────
  async function importSubsFromFile(f, setRef = false) {
    if (!f) return
    setBusy(true)
    try {
      const fd = new FormData(); fd.append('file', f)
      const r = await axios.post(`${API}/editor/import`, fd)
      const loaded = normalizeSubs(r.data.subtitles || [])
      if (setRef) { setRefSubs(loaded); setRefName(f.name); setRefIdx(''); setRefIdx2('') }
      else { setSubs(loaded); setFilename(f.name.replace(/\.[^/.]+$/, '')) }
      flash('ok', `Imported ${loaded.length} subtitles (${r.data.format.toUpperCase()})`)
    } catch (e) { flash('err', e.response?.data?.detail || 'Import failed') }
    finally { setBusy(false) }
  }

  function handleDrop(e) {
    e.preventDefault(); setDragOver(false)
    const f = e.dataTransfer.files?.[0]
    if (!f) return
    const isVideo = f.type.startsWith('video') || /\.(mp4|mkv|webm|mov|avi|mpg|mpeg|m4v|ogg)$/i.test(f.name)
    if (isVideo) loadVideoFromFile(f)
    else if (SUB_EXT.some(ext => f.name.toLowerCase().endsWith('.' + ext))) importSubsFromFile(f)
    else flash('err', 'Unsupported file — drop a video or a subtitle file.')
  }

  // ── export / sync / translate (unchanged logic) ───────
  async function exportSubs() {
    if (!subs.length) return flash('err', 'No subtitles to export')
    try {
      const r = await axios.post(`${API}/editor/export`, { subtitles: subs, format: exportFmt, filename }, { responseType: 'blob' })
      const url = URL.createObjectURL(r.data); const a = document.createElement('a')
      a.href = url; a.download = `${filename}_edited.${exportFmt}`; a.click(); URL.revokeObjectURL(url)
    } catch (e) { flash('err', 'Export failed') }
  }
  async function doSync(payload) {
    if (!subs.length) return flash('err', 'Open subtitles first')
    setBusy(true)
    try {
      const r = await axios.post(`${API}/editor/sync`, { subtitles: normalizeSubs(subs), ...payload })
      setSubs(normalizeSubs(r.data.subtitles)); flash('ok', 'Synchronization applied')
    } catch (e) { flash('err', e.response?.data?.detail || 'Sync failed') }
    finally { setBusy(false) }
  }
  function syncRangePayload() {
    return {
      range_start_id: syncRangeStart === '' ? null : parseInt(syncRangeStart, 10),
      range_end_id: syncRangeEnd === '' ? null : parseInt(syncRangeEnd, 10),
    }
  }
  function applyOffset() {
    const v = parseFloat(offsetVal); if (isNaN(v)) return flash('err', 'Enter a numeric offset in seconds')
    doSync({ mode: 'offset', seconds: v, ...syncRangePayload() })
  }
  function applyScale() {
    const v = parseFloat(scaleVal); if (isNaN(v) || v <= 0) return flash('err', 'Enter a positive scale factor')
    doSync({ mode: 'scale', factor: v, ...syncRangePayload() })
  }
  function applyFpsConversion() {
    const w = parseFloat(fpsWorking)
    const t = parseFloat(fpsTarget)
    if (isNaN(w) || isNaN(t) || w <= 0 || t <= 0) return flash('err', 'Enter valid FPS numbers')
    const factor = w / t
    doSync({ mode: 'scale', factor: factor, ...syncRangePayload() })
    setModal(null)
  }
  function applyDurationConversion() {
    function parseToSec(str) {
      if (!str) return NaN;
      const parts = str.split(':').map(Number);
      if (parts.length === 2) return parts[0] * 60 + parts[1];
      if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
      return parseFloat(str);
    }
    const w = parseToSec(durWorking)
    const t = parseToSec(durTarget)
    if (isNaN(w) || isNaN(t) || w <= 0 || t <= 0) return flash('err', 'Enter valid durations (e.g. 44:54)')
    const factor = t / w
    doSync({ mode: 'scale', factor: factor, ...syncRangePayload() })
    setModal(null)
  }
  function nudgeSelected(delta) {
    if (!pointId) return flash('err', 'Select a subtitle first')
    const id = parseInt(pointId, 10)
    setSubs(prev => prev.map(s => sameId(s.id, id) ? {
      ...s, start_time: secToTc(tcToSec(s.start_time) + delta), end_time: secToTc(tcToSec(s.end_time) + delta)
    } : s))
  }
  function setPreviewTime(which) {
    const ref = which === 2 ? vsEndRef : vsStartRef
    const tc = secToTc(ref.current?.currentTime || 0)
    if (which === 2) setPointStart2(tc)
    else setPointStart(tc)
  }
  function applyPoint() {
    if (!pointId) return flash('err', 'Select the first visual sync subtitle')
    if (!pointStart.trim()) return flash('err', 'Set the first video time')
    doSync({
      mode: 'visual', anchor_id: parseInt(pointId, 10), new_start: pointStart,
      anchor_id2: pointId2 ? parseInt(pointId2, 10) : null, new_start2: pointStart2 || null,
      ...syncRangePayload(),
    })
  }
  function applyPointViaOther() {
    if (!refSubs.length) return flash('err', 'Upload a reference subtitle file first')
    if (mainIdx === '' || refIdx === '') return flash('err', 'Pick a matched line in both files')
    doSync({
      mode: 'point_via_other', reference_subtitles: refSubs,
      sub_index: parseInt(mainIdx, 10), ref_index: parseInt(refIdx, 10),
      sub_index2: mainIdx2 === '' ? null : parseInt(mainIdx2, 10),
      ref_index2: refIdx2 === '' ? null : parseInt(refIdx2, 10),
    })
  }
  async function translate() {
    if (!subs.length) return flash('err', 'Open subtitles first')
    setBusy(true)
    setTranslating(true)
    setStopping(false)
    setTranslateProgress({ done: 0, total: subs.length })
    setTranslateLog([])
    setModal(null)   // close the language picker; show the live progress popup
    translateClientRef.current = (crypto.randomUUID ? crypto.randomUUID()
      : 'c' + Date.now() + Math.random().toString(16).slice(2))
    let finalSubs = null
    let wasStopped = false
    let stoppedAction = 'apply'
    try {
      const resp = await fetch(`${API}/editor/translate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subtitles: subs,
          target_language: targetLang,
          source_language: sourceLang,
          provider: translateProvider,
          api_key: translateApiKey,
          model: translateModel,
          base_url: translateEndpoint,
          custom_prompt: translatePrompt,
          client_id: translateClientRef.current,
        }),
      })
      if (!resp.ok) throw new Error('Translation request failed')
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() || ''
        for (const line of lines) {
          const t = line.trim()
          if (!t.startsWith('data: ')) continue
          let ev = null
          try { ev = JSON.parse(t.substring(6)) } catch { continue }
          if (ev.type === 'line') {
            setTranslateProgress({ done: ev.done, total: ev.total })
            setTranslateLog(prev => {
              const next = [...prev, { original: ev.original, translated: ev.translated }]
              return next.length > 200 ? next.slice(-200) : next
            })
          } else if (ev.type === 'done') { finalSubs = ev.subtitles }
          else if (ev.type === 'stopped') {
            finalSubs = ev.subtitles
            wasStopped = true
            stoppedAction = ev.action || 'apply'
          }
        }
      }
      if (finalSubs) {
        setSubs(finalSubs)
        if (wasStopped && stoppedAction === 'remove')
          flash('ok', `Reverted — translation changes discarded (${finalSubs.length} original lines kept)`)
        else if (wasStopped)
          flash('ok', `Stopped — ${finalSubs.filter(s => s.text).length} lines translated & applied`)
        else
          flash('ok', `Translated to ${targetLang}`)
      } else flash('err', 'Translation produced no result')
    } catch (e) {
      flash('err', e.message || 'Translation failed')
    } finally {
      setBusy(false)
      setTranslating(false)
      setStopping(false)
    }
  }

  async function stopTranslate(action) {
    if (!translateClientRef.current) return
    setStopping(true)
    try {
      await fetch(`${API}/editor/translate/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: translateClientRef.current, action }),
      })
    } catch { /* backend will stop regardless once event is set; ignore network errors */ }
  }

  function updateSub(id, field, value) { setSubs(subs.map(s => sameId(s.id, id) ? { ...s, [field]: value } : s)) }
  function addSub() {
    const last = subs[subs.length - 1]
    const start = last ? secToTc(tcToSec(last.end_time || last.start_time) + 0.2) : '00:00:00,000'
    const nextId = subs.length ? Math.max(...subs.map(s => s.id)) + 1 : 1
    setSubs([...subs, { id: nextId, start_time: start, end_time: secToTc(tcToSec(start) + 2), text: '' }])
  }
  function removeSub(id) { setSubs(subs.filter(s => !sameId(s.id, id))) }
  function clearSubs() {
    setSubs([]); setRefSubs([])
    setPointId(''); setPointId2(''); setPointStart(''); setPointStart2(''); setMainIdx(''); setRefIdx(''); setMainIdx2(''); setRefIdx2('')
    flash('ok', 'All subtitles cleared')
  }
  function removeVideo() {
    stopRaf()
    if (videoSrc) URL.revokeObjectURL(videoSrc)
    setVideoSrc(null); setDuration(0); setActiveId(null)
    if (vsStartRef.current) vsStartRef.current.removeAttribute('src')
    if (vsEndRef.current) vsEndRef.current.removeAttribute('src')
    flash('ok', 'Video removed')
  }

  // timeline ruler ticks (spacing adapts to zoom - safe against NaN infinite loop)
  const safeDur = Number.isFinite(dur) && dur > 0 ? dur : 60
  const safePx = Number.isFinite(pxPerSec) && pxPerSec > 0 ? pxPerSec : 80
  const innerW = Math.max(600, Math.ceil(safeDur * safePx))
  const tickStep = Math.max(1, Math.round(80 / safePx))
  const activeSub = activeId != null ? subs.find(s => sameId(s.id, activeId)) : null
  const ticks = []
  if (tickStep > 0 && safeDur < 86400) {
    for (let t = 0; t <= safeDur; t += tickStep) ticks.push(t)
  }

  return (
    <div ref={wrapRef}
      style={isEditorFullscreen ? {
        ...st.wrap,
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 9999,
        background: '#0b1220',
        padding: 12,
        boxSizing: 'border-box',
        height: '100vh',
        width: '100vw',
        overflow: 'auto',
        display: 'flex',
        flexDirection: 'column',
      } : st.wrap}
      onDragOver={e => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={e => { if (e.currentTarget === e.target) setDragOver(false) }}
      onDrop={handleDrop}>

      {dragOver && <div style={st.dropOverlay}>⬇ Drop a video or subtitle file to load it</div>}

      {/* TOOLBAR — buttons open popups (Subtitle-Edit style) */}
      <div style={st.toolbar}>
        <span style={st.brand}>✏️ Subtitle Edit</span>
        <button style={st.tbBtn} onClick={() => setModal('video')}>🎬 Open Video</button>
        <button style={st.tbBtn} onClick={() => setModal('subs')}>📄 Open Subtitles</button>
        <button style={{ ...st.tbBtn, background: '#7f1d1d', borderColor: '#991b1b' }} onClick={clearSubs} disabled={!subs.length}>🗑 Clear Subs</button>
        <button style={st.tbBtn} onClick={() => setModal('sync')}>⏱ Synchronize</button>
        <button style={{ ...st.tbBtn, background: '#0f766e', borderColor: '#115e59', color: '#ccfbf1' }} onClick={() => setModal('fps')}>🎞 FPS Converter</button>
        <button style={st.tbBtn} onClick={() => setModal('translate')}>🌐 Auto-Translate</button>
        <button style={st.tbBtn} onClick={() => setModal('export')}>⬇ Export</button>
        <div style={{ flex: 1 }} />
        {videoSrc && <button style={{ ...st.tbBtn, background: '#7f1d1d', borderColor: '#991b1b' }} onClick={removeVideo}>✕ Remove Video</button>}
        <button style={st.tbBtn} onClick={addSub}>+ Add line</button>
        <button
          style={{
            ...st.tbBtn,
            background: isEditorFullscreen ? 'linear-gradient(135deg,#6366f1,#4f46e5)' : '#334155',
            borderColor: isEditorFullscreen ? '#818cf8' : '#475569',
            color: '#fff',
            fontWeight: 800,
          }}
          onClick={toggleEditorFullscreen}
          title="Toggle Fullscreen Workspace for Video, Audio Waveform & Side Subtitles (Ctrl+F)"
        >
          {isEditorFullscreen ? '✕ Exit Fullscreen' : '🖥 Fullscreen Editor'}
        </button>
        <button
          style={{
            ...st.tbBtn,
            background: videoSrc ? (isVideoFullscreen ? 'linear-gradient(135deg,#6366f1,#4f46e5)' : '#334155') : '#1e293b',
            borderColor: videoSrc ? (isVideoFullscreen ? '#818cf8' : '#475569') : '#334155',
            color: videoSrc ? '#e2e8f0' : '#64748b',
          }}
          onClick={toggleVideoFullscreen}
          title={videoSrc ? "Fullscreen Video Player (or double-click video)" : "Open a video to enable Fullscreen Video"}
        >
          {isVideoFullscreen ? '✕ Exit Video Fullscreen' : '🎬 Fullscreen Video'}
        </button>
      </div>

      {msg && <div style={{ ...st.msg, ...(msg.type === 'ok' ? st.msgOk : st.msgErr) }}>{msg.text}</div>}

      {/* LIVE TRANSLATION PROGRESS POPUP (Subtitle-Edit style) */}
      {translating && (
        <div style={st.modalOverlay}>
          <div style={st.modalBox}>
            <div style={st.modalHead}>
              <span style={st.modalTitle}>🌐 Translating…</span>
            </div>
            <div style={st.modalBody}>
              <div style={st.progCount}>
                Translating {translateProgress.done} / {translateProgress.total} lines
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 4, marginBottom: 10 }}>
                <button style={{ ...st.primBtn, background: '#b91c1c', borderColor: '#991b1b' }}
                  onClick={() => stopTranslate('apply')} disabled={stopping}>
                  {stopping ? 'Stopping…' : '⏹ Stop & Apply'}
                </button>
                <button style={{ ...st.primBtn, background: '#475569', borderColor: '#334155' }}
                  onClick={() => stopTranslate('remove')} disabled={stopping}>
                  {stopping ? 'Stopping…' : '↩ Stop & Revert'}
                </button>
              </div>
              <div style={st.progOuter}>
                <div style={{ ...st.progInner,
                  width: `${translateProgress.total ? (translateProgress.done / translateProgress.total) * 100 : 0}%` }} />
              </div>
              <div style={st.progHead}><span>Original</span><span>Translated</span></div>
              <div style={st.progLog}>
                {[...translateLog].reverse().map((row, i) => (
                  <div key={i} style={st.progRow}>
                    <div style={st.progOrig}>{row.original}</div>
                    <div style={st.progTrans}>{row.translated}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SIDE-BY-SIDE: video + synced subtitle list */}
      <div style={isEditorFullscreen ? { ...st.mainGrid, flex: 1, minHeight: 450 } : st.mainGrid}>
        {/* LEFT: video + detailed timeline (waveform + ruler + draggable blocks) */}
        <div style={isEditorFullscreen ? { ...st.videoCard, height: '100%', display: 'flex', flexDirection: 'column', minHeight: 450 } : st.videoCard}>
          {videoSrc ? (
            <div ref={videoShellRef}
              style={isVideoFullscreen ? {
                position: 'relative',
                background: '#000',
                width: '100vw',
                height: '100vh',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                overflow: 'hidden',
              } : st.videoShell}
              onDoubleClick={toggleVideoFullscreen}>
              <video ref={videoRef}
                style={isVideoFullscreen ? {
                  width: '100%',
                  height: '100%',
                  maxWidth: '100vw',
                  maxHeight: '100vh',
                  objectFit: 'contain',
                  display: 'block',
                  background: '#000',
                } : (isEditorFullscreen ? { ...st.video, maxHeight: '340px', objectFit: 'contain' } : st.video)}
                src={videoSrc}
                onLoadedMetadata={onMeta} onTimeUpdate={updateOnce}
                onPlay={() => { setIsPlaying(true); startRaf() }}
                onPause={() => { setIsPlaying(false); stopRaf() }}
                onEnded={() => { setIsPlaying(false); stopRaf() }}
                onSeeked={updateOnce}>
                <track ref={trackRef} kind="subtitles" srcLang="en" label="Subtitles"
                  onLoad={onTrackLoad} />
              </video>
              {activeSub && activeSub.text?.trim() && (
                <div style={isVideoFullscreen ? { ...st.overlay, bottom: '6%', zIndex: 10 } : st.overlay}>
                  <span style={isVideoFullscreen ? {
                    ...st.overlayText,
                    fontSize: 'clamp(22px, 3vw, 44px)',
                    padding: '8px 20px',
                    borderRadius: 10,
                    maxWidth: '90%',
                  } : st.overlayText}>{activeSub.text}</span>
                </div>
              )}
            </div>
          ) : (
            <div style={st.emptyVideo}>🎬 Open a video file (or drop one here) to start editing</div>
          )}

          {/* Subtitle Editor Transport Controls Bar */}
          <div style={st.transportBar}>
            <div style={st.ctrlRowMain}>
              {/* Play / Pause & Rewind / Forward transport buttons */}
              <div style={st.ctrlGroup}>
                <button style={st.playBtn} onClick={togglePlayPause} title={isPlaying ? "Pause (Space)" : "Play (Space)"}>
                  {isPlaying ? '⏸' : '▶'}
                </button>
                <button style={st.transportBtn} onClick={() => seekDelta(-5)} title="Rewind 5s (Ctrl+←)">⏪ -5s</button>
                <button style={st.transportBtn} onClick={() => seekDelta(-1)} title="Rewind 1s (←)">◀ -1s</button>
                <button style={st.transportBtn} onClick={() => stepFrame(-1)} title="Previous Frame (Alt+←)">⏮ -1f</button>
                <button style={st.transportBtn} onClick={() => stepFrame(1)} title="Next Frame (Alt+→)">⏭ +1f</button>
                <button style={st.transportBtn} onClick={() => seekDelta(1)} title="Forward 1s (→)">▶ +1s</button>
                <button style={st.transportBtn} onClick={() => seekDelta(5)} title="Forward 5s (Ctrl+→)">⏩ +5s</button>
                {activeSub && (
                  <button style={{ ...st.transportBtn, background: '#312e81', borderColor: '#6366f1', color: '#e0e7ff' }}
                    onClick={playActiveSub} title="Play current subtitle block">
                    ⏯ Play Line
                  </button>
                )}
              </div>

              {/* Frames & Audio Scrub option Controls */}
              <div style={st.ctrlGroup}>
                {/* Audio Scrubbing Toggle */}
                <button style={{ ...st.transportBtn, ...(audioScrub ? st.transportBtnActive : {}) }}
                  onClick={() => setAudioScrub(v => !v)} title="Toggle Audio Scrubbing on frame step and seek">
                  {audioScrub ? '🔊 Scrub: ON' : '🔇 Scrub: OFF'}
                </button>

                {/* Frame Display Option Toggle */}
                <button style={{ ...st.transportBtn, ...(showFrames ? st.transportBtnActive : {}) }}
                  onClick={() => setShowFrames(v => !v)} title="Toggle Frame Counter display">
                  🎞 Frames: {showFrames ? 'ON' : 'OFF'}
                </button>

                {/* FPS Selector */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11.5, color: '#94a3b8' }}>
                  <span>FPS:</span>
                  <select style={st.fpsSelect} value={fps} onChange={e => setFps(parseFloat(e.target.value))}>
                    <option value={23.976}>23.976 fps</option>
                    <option value={24}>24 fps (Film)</option>
                    <option value={25}>25 fps (PAL)</option>
                    <option value={29.97}>29.97 fps (NTSC)</option>
                    <option value={30}>30 fps</option>
                    <option value={50}>50 fps</option>
                    <option value={60}>60 fps</option>
                  </select>
                </div>

                {/* Speed Selector */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11.5, color: '#94a3b8' }}>
                  <span>Speed:</span>
                  <select style={st.fpsSelect} value={playbackRate} onChange={e => {
                    const r = parseFloat(e.target.value)
                    setPlaybackRate(r)
                    if (videoRef.current) videoRef.current.playbackRate = r
                  }}>
                    <option value={0.5}>0.5x</option>
                    <option value={0.75}>0.75x</option>
                    <option value={1.0}>1.0x (Normal)</option>
                    <option value={1.25}>1.25x</option>
                    <option value={1.5}>1.5x</option>
                    <option value={2.0}>2.0x</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Readout Row: Timecode + Frame Counter */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12, color: '#94a3b8', borderTop: '1px solid #1e293b', paddingTop: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ color: '#cbd5e1', fontWeight: 600 }}>Time:</span>
                <span ref={tcDisplayRef} style={{ fontFamily: 'monospace', color: '#38bdf8', fontWeight: 700 }}>
                  {secToTc(videoRef.current?.currentTime || 0)}
                </span>
                {showFrames && (
                  <>
                    <span style={{ color: '#cbd5e1', fontWeight: 600, marginLeft: 8 }}>Frame:</span>
                    <span ref={frameDisplayRef} style={{ fontFamily: 'monospace', color: '#f59e0b', fontWeight: 700 }}>
                      #{Math.floor((videoRef.current?.currentTime || 0) * fps).toLocaleString()} / #{Math.floor(dur * fps).toLocaleString()}
                    </span>
                  </>
                )}
              </div>
              <span style={{ fontSize: 10.5, color: '#64748b' }}>
                Shortcuts: Space=Play/Pause · Alt+←/→=±1f · Ctrl+←/→=±5f · ←/→=±1s
              </span>
            </div>
          </div>
          {/* timeline toolbar: zoom + hints */}
          <div style={st.tlToolbar}>
            <span style={{ fontWeight: 700 }}>🎞 Timeline</span>
            <button style={st.tlBtn} onClick={() => setPxPerSec(p => Math.max(20, p - 20))}>−</button>
            <span style={{ minWidth: 52, textAlign: 'center' }}>{pxPerSec} px/s</span>
            <button style={st.tlBtn} onClick={() => setPxPerSec(p => Math.min(400, p + 20))}>+</button>
            <div style={{ flex: 1 }} />
            <span style={{ fontSize: 11, color: '#94a3b8' }}>drag block = move · drag edges = trim · click = seek</span>
          </div>

          {/* zoomable, scrollable timeline (auto-scrolls with playhead) */}
          <div ref={timelineWrapRef}
            style={{
              ...st.timelineWrap,
              ...(isEditorFullscreen ? { flex: 1, display: 'flex', flexDirection: 'column', minHeight: 180, overflowY: 'auto' } : {})
            }}>
            <div ref={timelineInnerRef}
              style={{
                ...st.timelineInner,
                width: innerW,
                height: isEditorFullscreen ? '100%' : 120,
                minHeight: isEditorFullscreen ? 180 : 120,
              }}
              onClick={seekFromEvent}>
              <canvas ref={waveCanvasRef}
                style={{ ...st.waveCanvas, height: isEditorFullscreen ? 120 : 56 }} />
              <div style={{ ...st.tlRuler, top: isEditorFullscreen ? 120 : 56 }}>
                {ticks.map(t => (
                  <div key={t} style={{ ...st.tlTick, left: `${(t / dur) * 100}%` }}>{fmtClock(t)}</div>
                ))}
              </div>

              {subs.map(s => {
                const a = tcToSec(s.start_time), b = tcToSec(s.end_time) || a + 2
                const left = a * pxPerSec
                const width = Math.max(3, (b - a) * pxPerSec)
                const active = sameId(s.id, activeId)
                return (
                  <div key={s.id} title={`#${s.id}  ${s.start_time} → ${s.end_time}`}
                    style={{
                      ...st.tlBlock,
                      ...(active ? st.tlBlockActive : {}),
                      left,
                      width,
                      top: isEditorFullscreen ? 148 : 80,
                      height: isEditorFullscreen ? 44 : 36,
                    }}
                    onClick={e => { e.stopPropagation(); if (!movedRef.current) seekTo(a) }}>
                    <div style={st.tlHandle} onPointerDown={e => onBlockPointerDown(e, s, 'left')} />
                    <div style={st.tlBlockText} onPointerDown={e => onBlockPointerDown(e, s, 'move')}>
                      {s.text.split('\n')[0] || '(empty)'}
                    </div>
                    <div style={st.tlHandle} onPointerDown={e => onBlockPointerDown(e, s, 'right')} />
                  </div>
                )
              })}

              <div ref={playheadRef} style={{ ...st.playhead, left: '0%' }} />
            </div>
          </div>
        </div>

        {/* RIGHT: subtitle list (synced with video) */}
        <div style={isEditorFullscreen ? { ...st.listCard, height: '100%' } : st.listCard}>
          <div style={st.listHead}>
            <span style={st.listTitle}>🗂 Subtitles ({subs.length})</span>
            <span ref={clockRef} style={{ fontSize: 11, color: '#64748b', fontFamily: 'monospace' }}>00:00 / 00:00</span>
          </div>
          <div style={st.list} ref={listRef}>
            {subs.length === 0 ? (
              <div style={{ fontSize: 13, color: '#64748b', padding: 24, textAlign: 'center' }}>
                No subtitles loaded.<br />Click “Open Subtitles” or drop a subtitle file anywhere.
              </div>
            ) : subs.map(s => (
              <div key={s.id} ref={el => (rowRefs.current[s.id] = el)}
                style={{ ...st.subRow, ...(sameId(s.id, activeId) ? st.subRowActive : {}) }}
                onClick={() => seekTo(tcToSec(s.start_time))}>
                <div style={st.tcInline}>
                  <span style={{ fontSize: 11, fontWeight: 800, color: '#94a3b8', minWidth: 26 }}>#{s.id}</span>
                  <input className="tc" style={st.tcField} value={s.start_time}
                    onChange={e => updateSub(s.id, 'start_time', e.target.value)} onClick={e => e.stopPropagation()} />
                  <span style={{ color: '#64748b' }}>→</span>
                  <input className="tc" style={st.tcField} value={s.end_time}
                    onChange={e => updateSub(s.id, 'end_time', e.target.value)} onClick={e => e.stopPropagation()} />
                  <button style={st.delBtn} onClick={e => { e.stopPropagation(); removeSub(s.id) }}>✕</button>
                </div>
                <textarea style={st.txtArea} value={s.text}
                  onChange={e => updateSub(s.id, 'text', e.target.value)}
                  onClick={e => e.stopPropagation()} />
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* POPUP MODALS — toolbar buttons open these (Subtitle-Edit style) */}
      {modal === 'video' && (
        <Modal title="🎬 Open Video" onClose={() => setModal(null)}>
          <div style={st.fieldLabel}>From your computer</div>
          <label style={st.modalFileBtn}>Choose video file…
            <input ref={fileVideoRef} type="file" accept="video/*" hidden onChange={e => { onPickVideo(e); setModal(null) }} />
          </label>
          <div style={{ ...st.fieldLabel, marginTop: 18 }}>From a URL</div>
          <div style={st.row}>
            <input style={st.input} placeholder="https://…/video.mp4" value={videoUrl} onChange={e => setVideoUrl(e.target.value)} />
            <button style={st.primBtn} onClick={() => { loadUrl(); setModal(null) }}>Load</button>
          </div>
          <div style={{ fontSize: 11.5, color: '#64748b', marginTop: 12, lineHeight: 1.6 }}>
            Tip: you can also drag &amp; drop a video file anywhere on this page.
          </div>
        </Modal>
      )}

      {modal === 'subs' && (
        <Modal title="📄 Open Subtitles" onClose={() => setModal(null)}>
          <div style={st.fieldLabel}>Import a subtitle file</div>
          <label style={st.modalFileBtn}>Choose subtitle file…
            <input ref={fileSubRef} type="file" hidden onChange={e => { importSubsFromFile(e.target.files?.[0]); setModal(null) }} />
          </label>
          <div style={{ fontSize: 11.5, color: '#64748b', marginTop: 12, lineHeight: 1.6 }}>
            Supported: {SUB_EXT.map(f => f.toUpperCase()).join(', ')}
          </div>
        </Modal>
      )}

      {modal === 'fps' && (
        <Modal title="🎞 Auto-Stretch & FPS Converter" onClose={() => setModal(null)}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a', marginBottom: 8 }}>1. Scale by Exact Duration (Recommended)</div>
          <div style={{ fontSize: 12.5, color: '#64748b', marginBottom: 12, lineHeight: 1.5 }}>
            If your video content is identical but plays at a completely different speed, type the exact duration (HH:MM:SS or MM:SS) of both files.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
            <div>
              <div style={st.fieldLabel}>Working Duration (Pirated)</div>
              <input style={{ ...st.input, width: '100%' }} value={durWorking} onChange={e => setDurWorking(e.target.value)} placeholder="e.g. 1:44:54 or 44:54" />
            </div>
            <div>
              <div style={st.fieldLabel}>Target Duration (GTS Pro)</div>
              <input style={{ ...st.input, width: '100%' }} value={durTarget} onChange={e => setDurTarget(e.target.value)} placeholder="e.g. 1:37:12 or 37:12" />
            </div>
          </div>
          <button style={{ ...st.primBtn, width: '100%', padding: 10, fontSize: 13, background: '#0f766e', marginBottom: 24 }} onClick={applyDurationConversion} disabled={busy}>
            {busy ? 'Converting...' : 'Match Durations'}
          </button>

          <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a', marginBottom: 8 }}>2. Scale by Exact FPS</div>
            <div style={{ fontSize: 12.5, color: '#64748b', marginBottom: 12, lineHeight: 1.5 }}>
              Use this for known PAL speedups (e.g., converting 24fps to 25fps).
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
              <div>
                <div style={st.fieldLabel}>Your Video FPS (Pirated)</div>
                <input style={{ ...st.input, width: '100%' }} value={fpsWorking} onChange={e => setFpsWorking(e.target.value)} placeholder="e.g. 24" />
              </div>
              <div>
                <div style={st.fieldLabel}>Client's Video FPS (GTS Pro)</div>
                <input style={{ ...st.input, width: '100%' }} value={fpsTarget} onChange={e => setFpsTarget(e.target.value)} placeholder="e.g. 25" />
              </div>
            </div>
            <button style={{ ...st.smallBtn, width: '100%', padding: 10, fontSize: 13 }} onClick={applyFpsConversion} disabled={busy}>
              {busy ? 'Converting...' : 'Convert FPS'}
            </button>
          </div>

          <div style={{ marginTop: 16, padding: 12, background: '#f1f5f9', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 11.5, color: '#475569', lineHeight: 1.5 }}>
            <strong>💡 Tip: How to find FPS?</strong><br/>
            <strong>Pirated Video:</strong> Open the video in VLC Media Player and press <code>Ctrl + J</code> to see the exact Frame Rate.<br/>
            <strong>Client Video:</strong> Check the GTS Pro project settings. If unknown, you can often guess based on the region (US TV/Movies = 23.976 or 24, Europe/India/Australia TV = 25).
          </div>
        </Modal>
      )}

      {modal === 'sync' && (
        <Modal title="⏱ Visual Synchronization & Point Alignment" onClose={() => setModal(null)} maxWidth={1200}>
          {/* Global Offset & Speed adjustment bar */}
          <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: 12, marginBottom: 14 }}>
            <div style={st.fieldLabel}>⚡ Quick Shift / Speed Scale</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div style={st.row}>
                <input style={st.input} placeholder="Offset sec (e.g. -2.5)" value={offsetVal} onChange={e => setOffsetVal(e.target.value)} />
                <button style={st.smallBtn} onClick={applyOffset} disabled={busy}>+/− Shift</button>
              </div>
              <div style={st.row}>
                <input style={st.input} placeholder="Speed factor (e.g. 1.04)" value={scaleVal} onChange={e => setScaleVal(e.target.value)} />
                <button style={st.smallBtn} onClick={applyScale} disabled={busy}>Scale</button>
              </div>
            </div>
          </div>

          {/* Visual Sync Header instructions */}
          <div style={{ ...st.fieldLabel, marginBottom: 4 }}>🎯 Visual Point Sync (Side-by-Side)</div>
          <div style={{ fontSize: 12, color: '#64748b', lineHeight: 1.5, marginBottom: 12 }}>
            Select a subtitle line, play/step the video to the exact speech frame, and click <strong>"Set Time"</strong>. Optionally set a 2nd point near the end to automatically stretch/compress timing across drift!
          </div>

          {/* Range selectors */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: '#475569', marginBottom: 4, display: 'block' }}>Apply From:</label>
              <select style={st.input} value={syncRangeStart} onChange={e => setSyncRangeStart(e.target.value)}>
                <option value="">Apply from first line</option>
                {subs.map(s => <option key={s.id} value={s.id}>From #{s.id} ({(s.text.split('\n')[0] || '').slice(0, 24)})</option>)}
              </select>
            </div>
            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: '#475569', marginBottom: 4, display: 'block' }}>Apply Through:</label>
              <select style={st.input} value={syncRangeEnd} onChange={e => setSyncRangeEnd(e.target.value)}>
                <option value="">Apply through last line</option>
                {subs.map(s => <option key={s.id} value={s.id}>Through #{s.id} ({(s.text.split('\n')[0] || '').slice(0, 24)})</option>)}
              </select>
            </div>
          </div>

          {/* LEFT AND RIGHT SIDE-BY-SIDE VISUAL SYNC COLUMNS */}
          {videoSrc ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
              
              {/* LEFT COLUMN: POINT 1 (START SYNC POINT) */}
              <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 12, fontWeight: 800, color: '#38bdf8' }}>📍 POINT 1 (Start Sync)</span>
                  <span style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace' }}>
                    {secToTc(vsStartTime)}
                  </span>
                </div>

                <select style={{ ...st.input, background: '#1e293b', color: '#fff', borderColor: '#334155' }} value={pointId} onChange={e => setPointId(e.target.value)}>
                  <option value="">Select 1st Subtitle Line…</option>
                  {subs.map(s => <option key={s.id} value={s.id}>#{s.id} [{s.start_time}] {(s.text.split('\n')[0] || '').slice(0, 28)}</option>)}
                </select>

                <div style={{ position: 'relative', width: '100%', background: '#000', borderRadius: 8, overflow: 'hidden' }}>
                  <video ref={vsStartRef} src={videoSrc} style={{ width: '100%', maxHeight: 320, display: 'block' }}
                    onTimeUpdate={onVsStartUpdate} onLoadedMetadata={onVsStartUpdate} />
                  {pointId && (
                    <div style={{ position: 'absolute', bottom: '10%', width: '100%', textAlign: 'center', pointerEvents: 'none', padding: '0 10%' }}>
                      <span style={{ background: 'rgba(0,0,0,0.7)', color: 'white', padding: '4px 8px', borderRadius: 4, fontSize: 16, textShadow: '1px 1px 2px black', whiteSpace: 'pre-wrap' }}>
                        {subs.find(s => s.id == pointId)?.text || ''}
                      </span>
                    </div>
                  )}
                </div>

                {/* Point 1 Transport Controls */}
                <div style={{ background: '#1e293b', borderRadius: 8, padding: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                    <button style={st.playBtn} onClick={() => toggleVsPlay(vsStartRef.current)}>
                      {vsStartPlaying ? '⏸' : '▶'}
                    </button>
                    <button style={st.transportBtn} onClick={() => nudgeVs(vsStartRef.current, -1)}>⏮ -1f</button>
                    <button style={st.transportBtn} onClick={() => nudgeVs(vsStartRef.current, 1)}>⏭ +1f</button>
                    <button style={st.transportBtn} onClick={() => nudgeVs(vsStartRef.current, -25)}>◀ -1s</button>
                    <button style={st.transportBtn} onClick={() => nudgeVs(vsStartRef.current, 25)}>▶ +1s</button>
                    <button style={{ ...st.primBtn, padding: '8px 14px', fontSize: 12, fontWeight: 800, marginLeft: 'auto', background: '#0ea5e9' }} onClick={() => setPreviewTime(1)}>
                      📍 SET TIME ({pointStart || '00:00:00,000'})
                    </button>
                  </div>
                  {/* Mini Waveform & Subtitle Block Timeline Scrubber */}
                  <SyncTimelinePreview
                    curTime={vsStartTime}
                    dur={dur}
                    fps={fps}
                    activeSubId={pointId}
                    onSeek={t => seekVs(vsStartRef.current, t)}
                    accentColor="#38bdf8"
                    peaks={peaksRef.current}
                    subs={subs}
                  />
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: '#94a3b8', fontFamily: 'monospace' }}>
                    <span>Time: {secToTc(vsStartTime)}</span>
                    <span>Frame #{Math.floor(vsStartTime * fps).toLocaleString()}</span>
                  </div>
                </div>
              </div>

              {/* RIGHT COLUMN: POINT 2 (END / DRIFT SYNC POINT) */}
              <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 12, fontWeight: 800, color: '#f59e0b' }}>📍 POINT 2 (End / Drift Sync)</span>
                  <span style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace' }}>
                    {secToTc(vsEndTime)}
                  </span>
                </div>

                <select style={{ ...st.input, background: '#1e293b', color: '#fff', borderColor: '#334155' }} value={pointId2} onChange={e => setPointId2(e.target.value)}>
                  <option value="">Select 2nd Subtitle Line (Optional)…</option>
                  {subs.map(s => <option key={s.id} value={s.id}>#{s.id} [{s.start_time}] {(s.text.split('\n')[0] || '').slice(0, 28)}</option>)}
                </select>

                <div style={{ position: 'relative', width: '100%', background: '#000', borderRadius: 8, overflow: 'hidden' }}>
                  <video ref={vsEndRef} src={videoSrc} style={{ width: '100%', maxHeight: 320, display: 'block' }}
                    onTimeUpdate={onVsEndUpdate} onLoadedMetadata={onVsEndUpdate} />
                  {pointId2 && (
                    <div style={{ position: 'absolute', bottom: '10%', width: '100%', textAlign: 'center', pointerEvents: 'none', padding: '0 10%' }}>
                      <span style={{ background: 'rgba(0,0,0,0.7)', color: 'white', padding: '4px 8px', borderRadius: 4, fontSize: 16, textShadow: '1px 1px 2px black', whiteSpace: 'pre-wrap' }}>
                        {subs.find(s => s.id == pointId2)?.text || ''}
                      </span>
                    </div>
                  )}
                </div>

                {/* Point 2 Transport Controls */}
                <div style={{ background: '#1e293b', borderRadius: 8, padding: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                    <button style={st.playBtn} onClick={() => toggleVsPlay(vsEndRef.current)}>
                      {vsEndPlaying ? '⏸' : '▶'}
                    </button>
                    <button style={st.transportBtn} onClick={() => nudgeVs(vsEndRef.current, -1)}>⏮ -1f</button>
                    <button style={st.transportBtn} onClick={() => nudgeVs(vsEndRef.current, 1)}>⏭ +1f</button>
                    <button style={st.transportBtn} onClick={() => nudgeVs(vsEndRef.current, -25)}>◀ -1s</button>
                    <button style={st.transportBtn} onClick={() => nudgeVs(vsEndRef.current, 25)}>▶ +1s</button>
                    <button style={{ ...st.primBtn, padding: '8px 14px', fontSize: 12, fontWeight: 800, background: '#d97706', borderColor: '#b45309', marginLeft: 'auto' }} onClick={() => setPreviewTime(2)}>
                      📍 SET TIME ({pointStart2 || '00:00:00,000'})
                    </button>
                  </div>
                  {/* Mini Waveform & Subtitle Block Timeline Scrubber */}
                  <SyncTimelinePreview
                    curTime={vsEndTime}
                    dur={dur}
                    fps={fps}
                    activeSubId={pointId2}
                    onSeek={t => seekVs(vsEndRef.current, t)}
                    accentColor="#f59e0b"
                    peaks={peaksRef.current}
                    subs={subs}
                  />
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: '#94a3b8', fontFamily: 'monospace' }}>
                    <span>Time: {secToTc(vsEndTime)}</span>
                    <span>Frame #{Math.floor(vsEndTime * fps).toLocaleString()}</span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div style={{ fontSize: 12.5, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 10, padding: 16, textAlign: 'center', marginBottom: 14 }}>
              🎬 Open a video first to use visual side-by-side sync previews.
            </div>
          )}

          <button style={{ ...st.primBtn, width: '100%', padding: 12, fontSize: 14, fontWeight: 800 }} onClick={applyPoint} disabled={busy}>
            ⏱ Apply Visual Point Synchronization
          </button>

          <div style={{ ...st.fieldLabel, marginTop: 16 }}>Point sync via other subtitle</div>
          <label style={{ ...st.modalFileBtn, display: 'inline-block', fontSize: 12, marginBottom: 8 }}>
            📑 Load reference subtitles
            <input ref={fileRefRef} type="file" hidden onChange={e => importSubsFromFile(e.target.files?.[0], true)} />
          </label>
          {refSubs.length > 0 && <div style={{ fontSize: 11, color: '#059669', marginBottom: 8 }}>{refName}: {refSubs.length} lines</div>}
          <div style={st.row}>
            <select style={st.input} value={mainIdx} onChange={e => setMainIdx(e.target.value)}>
              <option value="">This line #</option>
              {subs.map((s, i) => <option key={s.id} value={i}>#{s.id} {(s.text.split('\n')[0] || '').slice(0, 30)}</option>)}
            </select>
            <select style={st.input} value={refIdx} onChange={e => setRefIdx(e.target.value)} disabled={!refSubs.length}>
              <option value="">Ref line #</option>
              {refSubs.map((s, i) => <option key={i} value={i}>#{s.id} {(s.text.split('\n')[0] || '').slice(0, 30)}</option>)}
            </select>
          </div>
          <div style={st.row}>
            <select style={st.input} value={mainIdx2} onChange={e => setMainIdx2(e.target.value)}>
              <option value="">2nd this line (opt)</option>
              {subs.map((s, i) => <option key={s.id} value={i}>#{s.id} {(s.text.split('\n')[0] || '').slice(0, 30)}</option>)}
            </select>
            <select style={st.input} value={refIdx2} onChange={e => setRefIdx2(e.target.value)} disabled={!refSubs.length}>
              <option value="">2nd ref line</option>
              {refSubs.map((s, i) => <option key={i} value={i}>#{s.id} {(s.text.split('\n')[0] || '').slice(0, 30)}</option>)}
            </select>
          </div>
          <button style={{ ...st.primBtn, width: '100%', marginTop: 8 }} onClick={applyPointViaOther} disabled={busy}>Sync against reference</button>
        </Modal>
      )}

      {modal === 'translate' && (
        <Modal title="🌐 Auto-Translate" onClose={() => setModal(null)}>
          <div style={st.fieldLabel}>Translation engine</div>
          <select style={st.input} value={translateProvider} onChange={e => onProviderChange(e.target.value)}>
            {providers.map(p => <option key={p.value} value={p.value}>{p.name}</option>)}
          </select>

          {activeProvider?.needsKey && (
            <>
              <div style={st.fieldLabel}>API key</div>
              <input style={st.input} type="password" placeholder="Paste your API key"
                value={translateApiKey} onChange={e => setTranslateApiKey(e.target.value)} />
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
                Saved in your browser only (localStorage) — never sent anywhere except the engine you choose.
              </div>
            </>
          )}

          {activeProvider?.models?.length > 0 && (
            <>
              <div style={st.fieldLabel}>Model</div>
              <input style={st.input} list="model-suggestions" placeholder={activeProvider.default_model || 'model name'}
                value={translateModel} onChange={e => setTranslateModel(e.target.value)} />
              <datalist id="model-suggestions">
                {activeProvider.models.map(m => <option key={m} value={m} />)}
              </datalist>
            </>
          )}

          {activeProvider?.customEndpoint && (
            <>
              <div style={st.fieldLabel}>Endpoint (base URL)</div>
              <input style={st.input} placeholder={activeProvider.default_base_url || 'https://…/v1'}
                value={translateEndpoint} onChange={e => setTranslateEndpoint(e.target.value)} />
            </>
          )}

          <div style={st.fieldLabel}>Languages</div>
          <div style={st.row}>
            <select style={st.input} value={targetLang} onChange={e => setTargetLang(e.target.value)}>
              {LANGUAGES.map(l => <option key={l} value={l}>{l}</option>)}
            </select>
            <input style={st.input} placeholder="Source lang (opt)" value={sourceLang} onChange={e => setSourceLang(e.target.value)} />
          </div>

          <div style={{ marginTop: 10 }}>
            <button style={{ ...st.smallBtn, fontSize: 11.5 }} onClick={() => setShowAdvTranslate(v => !v)}>
              {showAdvTranslate ? '▾ Hide advanced' : '▸ Advanced (custom prompt)'}
            </button>
          </div>
          {showAdvTranslate && (
            <textarea style={{ ...st.txtArea, marginTop: 8 }} rows={4}
              placeholder="Optional custom translation instruction. Leave blank for the default subtitle prompt."
              value={translatePrompt} onChange={e => setTranslatePrompt(e.target.value)} />
          )}

          <button style={{ ...st.primBtn, width: '100%', marginTop: 14 }} onClick={translate} disabled={busy}>
            🌐 Translate to {targetLang}
          </button>

          <div style={{ fontSize: 11.5, color: '#64748b', marginTop: 10, lineHeight: 1.6 }}>
            {activeProvider?.note || 'Translates every line. Speaker labels and <i>/<b> tags are preserved.'}
          </div>
        </Modal>
      )}

      {modal === 'export' && (
        <Modal title="⬇ Export Subtitles" onClose={() => setModal(null)}>
          <div style={st.fieldLabel}>Choose a format</div>
          <select style={st.input} value={exportFmt} onChange={e => setExportFmt(e.target.value)}>
            {(formats.export.length ? formats.export : SUB_EXT).map(f => <option key={f} value={f}>{f.toUpperCase()}</option>)}
          </select>
          <button style={{ ...st.primBtn, width: '100%', marginTop: 14 }} onClick={() => { exportSubs(); setModal(null) }} disabled={busy}>
            Download ({exportFmt.toUpperCase()})
          </button>
          <div style={{ fontSize: 11.5, color: '#64748b', marginTop: 10, lineHeight: 1.6 }}>
            Your current subtitle list is exported exactly as shown in the editor.
          </div>
        </Modal>
      )}
    </div>
  )
}

class SubtitleEditorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  componentDidCatch(error, info) {
    console.error('SubtitleEditor Error Boundary:', error, info)
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 24, background: '#0f172a', color: '#e2e8f0', borderRadius: 12, textAlign: 'center', border: '1px solid #1e293b', margin: 20 }}>
          <h3 style={{ fontSize: 16, marginBottom: 8, color: '#f87171' }}>⚠️ Subtitle Editor Error</h3>
          <p style={{ fontSize: 12, color: '#94a3b8', marginBottom: 16 }}>{String(this.state.error?.message || 'An unexpected error occurred in Subtitle Editor')}</p>
          <button style={{ padding: '8px 16px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer', fontWeight: 700 }}
            onClick={() => this.setState({ hasError: false })}>
            🔄 Reload Subtitle Editor
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

export default function SubtitleEditorWrapped(props) {
  return (
    <SubtitleEditorBoundary>
      <SubtitleEditor {...props} />
    </SubtitleEditorBoundary>
  )
}
