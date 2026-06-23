import { useState, useEffect, useRef } from 'react'
import axios from 'axios'

const API = '/api'

const SEVERITY_COLOR = { critical: '#ef4444', error: '#f59e0b', warning: '#a78bfa', info: '#60a5fa' }
const SEVERITY_BG = { critical: '#2a0f0f', error: '#2a1f0f', warning: '#1a1535', info: '#0f1a2e' }

const STRUCTURE_LABELS = {
  srt_timecoded: 'SRT Timecoded',
  srt_format: 'SRT File', vtt_format: 'VTT File',
  table_with_timecodes: 'Table with Timecodes', paragraph_with_speaker: 'Paragraph Script',
  paragraph_without_table: 'Script with Timecodes', ccsl_double_dialogue: 'CCSL Spotting List',
  plain_script: 'Already Clean Script', excel_spotting_list: 'Excel Spotting List', unknown: 'Unknown'
}

export default function App() {
  const [tab, setTab] = useState('clean')
  const [platforms, setPlatforms] = useState({})
  const [platform, setPlatform] = useState('discovery_max')

  // Clean tab
  const [file, setFile] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const [cleaning, setCleaning] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [cleanText, setCleanText] = useState('')
  const [cleanProgress, setCleanProgress] = useState(0)
  const [subtitles, setSubtitles] = useState([])
  const [cleanStats, setCleanStats] = useState(null)
  const [cleanError, setCleanError] = useState('')
  const fileRef = useRef()

  // Quality check tab
  const [qcFile, setQcFile] = useState(null)
  const [qcDragOver, setQcDragOver] = useState(false)
  const [checking, setChecking] = useState(false)
  const [qcResult, setQcResult] = useState(null)
  const [qcError, setQcError] = useState('')
  const qcFileRef = useRef()

  // Platforms tab
  const [newName, setNewName] = useState('')
  const [glFile, setGlFile] = useState(null)
  const [glText, setGlText] = useState('')
  const [adding, setAdding] = useState(false)
  const [addMsg, setAddMsg] = useState('')
  const [addErr, setAddErr] = useState('')
  const [editingPlatform, setEditingPlatform] = useState(null)
  const [editRulesText, setEditRulesText] = useState('')
  const [editPlatformMsg, setEditPlatformMsg] = useState('')
  const [editPlatformErr, setEditPlatformErr] = useState('')

  // Transcribe tab
  const [audioFile, setAudioFile] = useState(null)
  const [scriptFile, setScriptFile] = useState(null)  // optional script for alignment (Case 2)
  const [whisperSubs, setWhisperSubs] = useState([])  // raw whisper output
  const [recording, setRecording] = useState(false)
  const [mediaRecorder, setMediaRecorder] = useState(null)
  const [transcribing, setTranscribing] = useState(false)
  const [transcribeProgress, setTranscribeProgress] = useState({ pct: 0, msg: '' })
  const [transcribeError, setTranscribeError] = useState('')
  const [alignStats, setAlignStats] = useState(null)
  const scriptFileRef = useRef()

  // Movie Hub
  const [movies, setMovies] = useState([])
  const [newMovie, setNewMovie] = useState({ title: '', url: '', added_by: '' })
  const [movieErr, setMovieErr] = useState('')
  const [movieMsg, setMovieMsg] = useState('')

  // Timecode Adjuster
  const [tcMode, setTcMode] = useState('offset')   // 'offset' | 'edit_single'
  const [tcValue, setTcValue] = useState('')         // offset OR new start TC
  const [tcEndValue, setTcEndValue] = useState('')   // new end TC (edit_single only)
  const [tcTargetId, setTcTargetId] = useState('')   // subtitle ID (edit_single only)
  const [tcShiftMode, setTcShiftMode] = useState('ripple') // 'ripple' | 'only_this'
  const [tcAdjusting, setTcAdjusting] = useState(false)
  const [tcError, setTcError] = useState('')
  const [tcSuccess, setTcSuccess] = useState('')
  const [tcCollision, setTcCollision] = useState(null) // null | collision detail string

  useEffect(() => { loadPlatforms(); loadMovies(); }, [])

  async function loadPlatforms() {
    try {
      const r = await axios.get(`${API}/platforms`)
      setPlatforms(r.data.platforms)
    } catch(e) { console.error('Failed to load platforms:', e) }
  }

  async function loadMovies() {
    try {
      const r = await axios.get(`${API}/movies`)
      setMovies(r.data.movies || [])
    } catch(e) { console.error('Failed to load movies:', e) }
  }

  async function handleAddMovie() {
    setMovieErr('')
    setMovieMsg('')
    if (!newMovie.title || !newMovie.url) return setMovieErr('Title and URL are required.')
    try {
      await axios.post(`${API}/movies`, newMovie)
      setMovieMsg('Movie added successfully!')
      setNewMovie({ title: '', url: '', added_by: '' })
      loadMovies()
      setTimeout(() => setMovieMsg(''), 3000)
    } catch (e) {
      setMovieErr(e.response?.data?.detail || 'Failed to add movie.')
    }
  }

  // ── CLEAN ──────────────────────────────────────────────────────

  async function handleExtract() {
    if (!file) { setCleanError('Please upload a file first'); return }
    setExtracting(true); setCleanError(''); setCleanStats(null); setSubtitles([]); setCleanProgress(0)
    setCleanText('Connecting...')
    const fd = new FormData()
    fd.append('file', file)
    try {
      const response = await fetch(`${API}/extract`, {
        method: 'POST',
        body: fd
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}))
        throw new Error(errData.detail || `Server error: ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data: ')) continue

          let data = null
          try {
            data = JSON.parse(trimmed.substring(6))
          } catch (jsonErr) {
            continue
          }

          if (data.status === 'starting' || data.status === 'processing') {
            setCleanText(data.message || 'Extracting...')
            setCleanProgress(data.progress || 0)
          } else if (data.status === 'error') {
            throw new Error(data.error || 'Unknown backend error')
          } else if (data.status === 'completed') {
            setSubtitles(data.result?.subtitles || [])
            setCleanStats(data.result?.stats || null)
            setCleanProgress(100)
            setCleanText('Extraction complete!')
          }
        }
      }
    } catch (e) {
      setCleanError(e.message || 'Extraction failed')
      setCleanText('')
    } finally { setExtracting(false) }
  }

  async function handleClean() {
    if (!file) { setCleanError('Please upload a file first'); return }
    setCleaning(true); setCleanError(''); setCleanStats(null); setSubtitles([]); setCleanProgress(0)
    const fd = new FormData()
    fd.append('file', file)
    fd.append('platform', platform)
    try {
      setCleanText('Preparing file...')
      const response = await fetch(`${API}/clean`, {
        method: 'POST',
        body: fd
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}))
        throw new Error(errData.detail || `Server error: ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data: ')) continue

          // Step 1: parse JSON separately so parse errors don't eat backend errors
          let data = null
          try {
            data = JSON.parse(trimmed.substring(6))
          } catch (jsonErr) {
            console.error('SSE JSON parse error:', jsonErr, '| raw:', trimmed)
            continue
          }

          // Step 2: handle the parsed event (errors thrown here go to outer catch)
          if (data.status === 'starting') {
            setCleanText(data.message || 'Starting...')
            setCleanProgress(0)
          } else if (data.status === 'processing') {
            setCleanText(data.message || 'Processing...')
            setCleanProgress(data.progress || 0)
          } else if (data.status === 'error') {
            throw new Error(data.error || 'Unknown backend error')
          } else if (data.status === 'completed') {
            setSubtitles(data.result?.subtitles || [])
            setCleanStats(data.result?.stats || null)
            setCleanProgress(100)
            setCleanText('')
          }
        }
      }
    } catch (e) {
      setCleanError(e.message || 'Backend error — is the server running on port 8000?')
    } finally { setCleaning(false) }
  }

  async function exportSRT() {
    const r = await axios.post(`${API}/export/srt`, { subtitles, filename: file?.name, platform_key: platform }, { responseType: 'blob' })
    const url = URL.createObjectURL(r.data)
    const a = document.createElement('a'); a.href = url
    const base = (file?.name || 'subtitles').replace(/\.[^/.]+$/, '')
    a.download = `${base}_cleaned.srt`; a.click(); URL.revokeObjectURL(url)
  }

  async function exportTXT() {
    const r = await axios.post(`${API}/export/txt`, { subtitles, filename: file?.name }, { responseType: 'blob' })
    const url = URL.createObjectURL(r.data)
    const a = document.createElement('a'); a.href = url
    a.download = `${file?.name || 'subtitles'}_cleaned.txt`; a.click(); URL.revokeObjectURL(url)
  }

  async function exportDOCX() {
    const r = await axios.post(`${API}/export/docx`, { subtitles, filename: file?.name }, { responseType: 'blob' })
    const url = URL.createObjectURL(r.data)
    const a = document.createElement('a'); a.href = url
    a.download = `${file?.name || 'subtitles'}_cleaned.docx`; a.click(); URL.revokeObjectURL(url)
  }

  async function exportPDF() {
    const r = await axios.post(`${API}/export/pdf`, { subtitles, filename: file?.name }, { responseType: 'blob' })
    const url = URL.createObjectURL(r.data)
    const a = document.createElement('a'); a.href = url
    a.download = `${file?.name || 'subtitles'}_cleaned.pdf`; a.click(); URL.revokeObjectURL(url)
  }

  // ── QUALITY CHECK ──────────────────────────────────────────────

  async function handleQualityCheck() {
    if (!qcFile && subtitles.length === 0) { setQcError('Upload a subtitle file or clean a file first'); return }

    setChecking(true); setQcError(''); setQcResult(null)

    try {
      let subs = subtitles

      if (qcFile) {
        setQcError('Extracting file for quality check...')
        const fd = new FormData()
        fd.append('file', qcFile)
        fd.append('platform', platform)
        const response = await fetch(`${API}/extract`, { method: 'POST', body: fd })
        if (!response.ok) throw new Error(`Server error: ${response.status}`)
        
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          
          for (const line of lines) {
            const trimmed = line.trim()
            if (!trimmed.startsWith('data: ')) continue
            try {
              const data = JSON.parse(trimmed.substring(6))
              if (data.status === 'error') throw new Error(data.error)
              if (data.status === 'completed') subs = data.result?.subtitles || []
            } catch (e) {
              if (e.message !== 'Unexpected end of JSON input') throw e
            }
          }
        }
        setQcError('') // Clear extraction message
      }

      if (!subs.length) {
        setQcError('No dialogue lines found in file')
        return
      }

      const r = await axios.post(`${API}/quality-check`, {
        subtitles: subs,
        platform_key: platform,
        filename: qcFile?.name || file?.name || 'subtitles.srt'
      })
      // Always update the subtitle list with the auto-fixed version from QC
      if (r.data.subtitles?.length) setSubtitles(r.data.subtitles)
      setQcResult(r.data)
    } catch (e) {
      setQcError(e.response?.data?.detail || 'Quality check failed — is backend running?')
    } finally { setChecking(false) }
  }

  // ── PLATFORMS ──────────────────────────────────────────────────

  async function handleAddPlatform() {
    if (!newName.trim()) { setAddErr('Platform name required'); return }
    setAdding(true); setAddErr(''); setAddMsg('')
    const fd = new FormData()
    fd.append('platform_name', newName)
    if (glFile) fd.append('guidelines_file', glFile)
    if (glText) fd.append('guidelines_text', glText)
    try {
      const r = await axios.post(`${API}/platforms/add`, fd)
      setAddMsg(r.data.message)
      setNewName(''); setGlText(''); setGlFile(null)
      loadPlatforms()
    } catch (e) {
      setAddErr(e.response?.data?.detail || 'Failed to add platform')
    } finally { setAdding(false) }
  }

  async function handleDeletePlatform(key) {
    if (!confirm('Delete this platform?')) return
    try { await axios.delete(`${API}/platforms/${key}`); loadPlatforms() }
    catch (e) { alert(e.response?.data?.detail || 'Cannot delete') }
  }

  async function handleSaveRules() {
    if (!editingPlatform) return
    setEditPlatformErr(''); setEditPlatformMsg('Saving...');
    const rulesArray = editRulesText.split('\n').map(r => r.trim()).filter(Boolean)
    try {
      await axios.put(`${API}/platforms/${editingPlatform.platform_key || editingPlatform.name}`, { rules: rulesArray })
      setEditPlatformMsg('Rules saved successfully!')
      loadPlatforms()
      setTimeout(() => {
        setEditingPlatform(null)
        setEditPlatformMsg('')
      }, 1500)
    } catch (e) {
      setEditPlatformMsg('')
      setEditPlatformErr(e.response?.data?.detail || 'Failed to save rules')
    }
  }

  // ── TRANSCRIBE ──────────────────────────────────────────────────

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      const chunks = []
      recorder.ondataavailable = e => chunks.push(e.data)
      recorder.onstop = () => {
        const blob = new Blob(chunks, { type: 'audio/webm' })
        const f = new File([blob], 'recording.webm', { type: 'audio/webm' })
        setAudioFile(f)
      }
      recorder.start()
      setMediaRecorder(recorder)
      setRecording(true)
      setTranscribeError('')
    } catch (e) {
      setTranscribeError('Microphone access denied: ' + e.message)
    }
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop()
      mediaRecorder.stream.getTracks().forEach(t => t.stop())
      setRecording(false)
    }
  }

  // Case 1 (no script) or Case 2 (with script for alignment)
  async function handleTranscribe() {
    if (!audioFile) { setTranscribeError('Please upload or record audio first'); return }
    setTranscribing(true); setTranscribeError(''); setSubtitles([]); setCleanStats(null);
    setAlignStats(null); setWhisperSubs([]);
    setTranscribeProgress({ pct: 0, msg: 'Starting...' })

    // Use /transcribe-and-align (handles both Case 1 and Case 2)
    const fd = new FormData()
    fd.append('audio', audioFile)
    if (scriptFile) fd.append('script', scriptFile)
    fd.append('platform', platform)

    try {
      const response = await fetch(`${API}/transcribe-and-align`, { method: 'POST', body: fd })
      if (!response.ok) throw new Error(`Server error: ${response.status}`)

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data: ')) continue
          let data = null
          try { data = JSON.parse(trimmed.substring(6)) } catch(e) { continue }
          if (data.status === 'processing') {
            setTranscribeProgress({ pct: data.progress || 0, msg: data.message || 'Processing...' })
          } else if (data.status === 'error') {
            throw new Error(data.error || 'Transcription failed')
          } else if (data.status === 'completed') {
            const subs = data.result?.subtitles || []
            setSubtitles(subs)
            setWhisperSubs(subs)
            setCleanStats(data.result?.stats || null)
            setAlignStats(data.result?.stats || null)
            setTab('clean')
          }
        }
      }
    } catch (e) {
      setTranscribeError(e.message || 'Transcription failed')
    } finally {
      setTranscribing(false)
    }
  }

  // ── TIMECODE ADJUSTER (Case 3) ──────────────────────────────────

  // Auto-populate start+end TCs when subtitle ID is entered
  function handleTcTargetIdChange(val) {
    setTcTargetId(val)
    setTcSuccess(''); setTcError(''); setTcCollision(null)
    if (val.trim()) {
      const found = subtitles.find(s => s.id === parseInt(val, 10))
      if (found) {
        setTcValue(found.start_time || '')
        setTcEndValue(found.end_time || '')
      }
    }
  }

  async function handleAdjustTimecodes() {
    if (!subtitles.length) { setTcError('No subtitles loaded. Clean or transcribe a file first.'); return }
    setTcAdjusting(true); setTcError(''); setTcSuccess(''); setTcCollision(null)
    try {
      let payload, r
      if (tcMode === 'offset') {
        if (!tcValue.trim()) { setTcError('Enter an offset value.'); setTcAdjusting(false); return }
        payload = { subtitles, mode: 'offset', value: tcValue.trim() }
        r = await axios.post(`${API}/adjust-timecodes`, payload)
        setSubtitles(r.data.subtitles || [])
        setTcSuccess(`✅ All ${r.data.total} subtitles shifted by ${r.data.value}.`)
        setTcValue('')
      } else {
        // edit_single
        if (!tcTargetId.trim()) { setTcError('Enter the subtitle ID to edit.'); setTcAdjusting(false); return }
        if (!tcValue.trim()) { setTcError('Enter the new start timecode.'); setTcAdjusting(false); return }
        if (tcShiftMode === 'only_this') {
          if (!tcEndValue.trim()) { setTcError('Enter the new end timecode.'); setTcAdjusting(false); return }
          payload = { subtitles, mode: 'shift_only_this', target_id: parseInt(tcTargetId, 10), new_start: tcValue.trim(), new_end: tcEndValue.trim() }
          r = await axios.post(`${API}/adjust-timecodes`, payload)
          setSubtitles(r.data.subtitles || [])
          if (r.data.collision) {
            setTcCollision(r.data.collision_detail)
            setTcSuccess(`⚠️ Subtitle #${tcTargetId} updated — but collision detected! Check warning below.`)
          } else {
            setTcSuccess(`✅ Subtitle #${tcTargetId} timecode updated. No collision.`)
          }
        } else {
          // ripple
          payload = { subtitles, mode: 'fix_from_index', target_id: parseInt(tcTargetId, 10), value: tcValue.trim() }
          r = await axios.post(`${API}/adjust-timecodes`, payload)
          setSubtitles(r.data.subtitles || [])
          setTcSuccess(`✅ Subtitle #${tcTargetId} + all ${r.data.total} subsequent subtitles shifted.`)
        }
      }
    } catch (e) {
      setTcError(e.response?.data?.detail || 'Adjustment failed')
    } finally { setTcAdjusting(false) }
  }

  const flaggedCount = subtitles.filter(s => s.flagged).length
  const builtinPlatforms = Object.entries(platforms).filter(([k]) => !k.startsWith('custom_'))
  const customPlatforms = Object.entries(platforms).filter(([k]) => k.startsWith('custom_'))

  return (
    <div style={S.root}>
      {/* HEADER */}
      <div style={S.header}>
        <div style={S.headerLeft}>
          <div style={S.logo}>S</div>
          <div>
            <div style={S.logoTitle}>SubtitleAI</div>
            <div style={S.logoSub}>Cleaning & Quality Check — v2.0</div>
          </div>
        </div>
        <div style={S.tabs}>
          {[['clean','🧹 Clean'],['transcribe','🎙️ Transcribe'],['adjust','⏱️ Adjust TC'],['quality','✅ Quality Check'],['platforms','⚙️ Platforms'],['movie_hub','🌐 Movie Hub']].map(([id,label]) => (
            <button key={id} style={{...S.tab,...(tab===id?S.tabActive:{})}} onClick={()=>setTab(id)}>{label}</button>
          ))}
        </div>
      </div>

      <div style={S.body}>

        {/* ══ CLEAN TAB ══ */}
        {tab === 'clean' && (
          <div style={S.twoCol}>
            <div style={S.left}>

              <div style={S.card}>
                <div style={S.label}>Step 1 — Select OTT Platform</div>
                <select style={S.select} value={platform} onChange={e=>setPlatform(e.target.value)}>
                  <optgroup label="Built-in Platforms">
                    {builtinPlatforms.map(([k,p]) => <option key={k} value={k}>{p.name || k}</option>)}
                  </optgroup>
                  {customPlatforms.length > 0 && (
                    <optgroup label="Custom Platforms">
                      {customPlatforms.map(([k,p]) => <option key={k} value={k}>{p.name || k}</option>)}
                    </optgroup>
                  )}
                </select>
                {platforms[platform] && (
                  <div style={S.platformMeta}>
                    <span>Max {platforms[platform].max_chars_per_line} chars/line</span>
                    <span>·</span><span>Max {platforms[platform].max_lines} lines</span>
                    <span>·</span><span>{platforms[platform].reading_speed_max_cps || 21} CPS max</span>
                    <span>·</span><span>{platforms[platform].file_format || 'PAC'}</span>
                  </div>
                )}
              </div>

              <div style={S.card}>
                <div style={S.label}>Step 2 — Upload OTT Script File</div>
                {!file ? (
                  <div style={{...S.uploadZone,...(dragOver?S.uploadDrag:{})}}
                    onDragOver={e=>{e.preventDefault();setDragOver(true)}}
                    onDragLeave={()=>setDragOver(false)}
                    onDrop={e=>{e.preventDefault();setDragOver(false);e.dataTransfer.files[0]&&setFile(e.dataTransfer.files[0])}}
                    onClick={()=>fileRef.current.click()}>
                    <div style={{fontSize:32,marginBottom:8}}>📁</div>
                    <div style={S.uploadTitle}>Drag & drop any OTT script file</div>
                    <div style={S.uploadSub}>DOC · DOCX · PDF · SRT · VTT · XML · TTML · RTF · XLSX · CSV · TXT</div>
                    <div style={{...S.uploadSub,marginTop:4,color:'#3a3848'}}>Tables · Paragraphs · CCSL Spotting Lists · Already cleaned scripts</div>
                    <input ref={fileRef} type="file" hidden
                      accept=".doc,.docx,.pdf,.srt,.vtt,.webvtt,.xml,.ttml,.dfxp,.rtf,.xlsx,.xls,.csv,.txt,.json"
                      onChange={e=>e.target.files[0]&&setFile(e.target.files[0])}/>
                  </div>
                ) : (
                  <div style={S.fileChip}>
                    <span style={{fontSize:18}}>📄</span>
                    <div style={{flex:1}}>
                      <div style={{fontSize:13,color:'#c8c6d4'}}>{file.name}</div>
                      <div style={{fontSize:10,color:'#5a5870'}}>{(file.size/1024).toFixed(1)} KB</div>
                    </div>
                    <button style={S.btnX} onClick={()=>{setFile(null);setSubtitles([]);setCleanStats(null);setCleanError('')}}>✕</button>
                  </div>
                )}
              </div>

              <div style={{display:'flex',gap:10}}>
                <button style={{...S.btnOutline,flex:1,...(extracting||cleaning||!file?S.btnOff:{}),borderColor:'#7c3aed',color:'#a78bfa'}} onClick={handleExtract} disabled={extracting||cleaning||!file}>
                  {extracting ? '📄 Extracting...' : '📄 Extract Text'}
                </button>
                <button style={{...S.btnPrimary,flex:1,...(cleaning||extracting||!file?S.btnOff:{})}} onClick={handleClean} disabled={cleaning||extracting||!file}>
                  {cleaning ? '🧹 Cleaning...' : '🧹 AI Clean'}
                </button>
              </div>

              {(cleaning || extracting) && (
                <div style={S.progressContainer}>
                  <div style={S.progressBarOuter}>
                    <div style={{...S.progressBarInner, width: `${cleanProgress}%`}} />
                  </div>
                  <div style={S.progressMeta}>
                    <span style={S.progressMsg}>{cleanText}</span>
                    <span style={S.progressPct}>{cleanProgress}%</span>
                  </div>
                </div>
              )}

              {cleanError && <div style={S.errBox}><div style={{fontSize:20,marginBottom:6}}>❌</div><div style={{fontSize:12,color:'#fca5a5',lineHeight:1.6}}>{cleanError}</div></div>}

              {cleanStats && (
                <div style={S.statsGrid}>
                  {[
                    ['Total Lines', cleanStats.total_lines, '#a78bfa'],
                    ['Auto-approved', cleanStats.total_lines - cleanStats.flagged_lines, '#34d399'],
                    ['Flagged', cleanStats.flagged_lines, cleanStats.flagged_lines > 0 ? '#fbbf24' : '#34d399'],
                  ].map(([label,val,color]) => (
                    <div key={label} style={S.statItem}>
                      <div style={{...S.statNum,color}}>{val}</div>
                      <div style={S.statLabel}>{label}</div>
                    </div>
                  ))}
                  <div style={S.statItem}>
                    <div style={{fontSize:11,fontWeight:700,color:'#7c3aed',marginBottom:2}}>{STRUCTURE_LABELS[cleanStats.detected_structure]||cleanStats.detected_structure}</div>
                    <div style={S.statLabel}>Detected Format</div>
                  </div>
                </div>
              )}
            </div>

            <div style={S.right}>
              {subtitles.length > 0 ? (
                <div style={S.card}>
                  <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:10}}>
                    <div style={{fontSize:14,fontWeight:700,color:'#fff'}}>Cleaned Subtitles</div>
                    <div style={{display:'flex',gap:8}}>
                      <button style={S.btnSm} onClick={exportSRT}>⬇️ SRT</button>
                      <button style={S.btnSm} onClick={exportTXT}>⬇️ TXT</button>
                      <button style={S.btnSm} onClick={exportDOCX}>⬇️ DOCX</button>
                      <button style={S.btnSm} onClick={exportPDF}>⬇️ PDF</button>
                      <button style={{...S.btnSm,background:'#059669',borderColor:'#059669',color:'#fff'}}
                        onClick={()=>setTab('quality')}>✅ Quality Check →</button>
                    </div>
                  </div>
                  {flaggedCount > 0 && (
                    <div style={{background:'#2a1515',border:'1px solid #ef444430',borderRadius:8,padding:'8px 12px',fontSize:11,color:'#fca5a5',marginBottom:10}}>
                      ⚠️ {flaggedCount} lines flagged for review — shown in red below. Edit directly in the box.
                    </div>
                  )}
                  <div style={S.subList}>
                    {subtitles.map((sub,i) => (
                      <div key={i} style={{...S.subRow,...(sub.flagged?S.subFlagged:{})}}>
                        {(sub.start_time || sub.end_time) && (
                          <div style={S.timecode}>{`${sub.start_time} --> ${sub.end_time}`}</div>
                        )}
                        <div style={{...S.subText,...(sub.flagged?{color:'#fca5a5'}:{})}}
                          contentEditable suppressContentEditableWarning
                          onBlur={e=>{const u=[...subtitles];u[i]={...u[i],text:e.target.innerHTML};setSubtitles(u)}}
                          dangerouslySetInnerHTML={{ __html: (sub.text || '').replace(/&lt;/g, '<').replace(/&gt;/g, '>') }}
                        />
                        {sub.flagged&&sub.flag_reason&&<div style={{fontSize:10,color:'#ef4444',marginTop:4}}>⚠ {sub.flag_reason}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div style={S.empty}>
                  <div style={{fontSize:48,marginBottom:14}}>🎬</div>
                  <div style={{fontSize:17,fontWeight:700,color:'#c8c6d4',marginBottom:8}}>Upload a file to get started</div>
                  <div style={{fontSize:12,color:'#5a5870',marginBottom:20}}>Supports all OTT subtitle and script formats</div>
                  <div style={{display:'flex',flexWrap:'wrap',gap:8,justifyContent:'center'}}>
                    {['Table with Timecodes (FBoy Island style)','Plain Paragraph Script (Everybody Loves Raymond)','SRT / VTT Subtitle Files','XML / TTML / DFXP','CCSL Spotting List (Juno style)','Excel Spotting Lists','Already Cleaned Scripts','Double Dialogue Scripts'].map(f=>(
                      <div key={f} style={{background:'#13131f',border:'1px solid #2a2a3e',borderRadius:6,padding:'5px 10px',fontSize:11,color:'#7c7a8a'}}>{f}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ══ TRANSCRIBE TAB ══ */}
        {tab === 'transcribe' && (
          <div style={{maxWidth:640, margin:'0 auto'}}>
            <div style={S.card}>
              <div style={{fontSize:18, fontWeight:700, marginBottom:6, textAlign:'center'}}>🎙️ AI Audio / Video Transcription</div>
              <div style={{fontSize:11, color:'#a78bfa', marginBottom:20, textAlign:'center'}}>Powered by local Faster-Whisper. Runs entirely on your machine. Auto-generates frame-accurate SRT.</div>

              {/* Case 1 & 2 & 2B explanation */}
              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:8, marginBottom:16}}>
                <div style={{background:'#0d0d1a', border:'1px solid #7c3aed30', borderRadius:8, padding:'10px 12px', fontSize:11}}>
                  <div style={{color:'#a78bfa', fontWeight:700, marginBottom:4}}>📄 Case 1 — No Script</div>
                  <div style={{color:'#7c7a8a'}}>Upload audio/video only. Whisper generates a full SRT from scratch.</div>
                </div>
                <div style={{background:'#0d0d1a', border:'1px solid #05966940', borderRadius:8, padding:'10px 12px', fontSize:11}}>
                  <div style={{color:'#34d399', fontWeight:700, marginBottom:4}}>📋 Case 2 — Script + Audio</div>
                  <div style={{color:'#7c7a8a'}}>Upload audio + a <strong style={{color:'#34d399'}}>fully-timed</strong> cleaned script. Whisper timecodes get mapped to the correct script text.</div>
                </div>
                <div style={{background:'#0d0d1a', border:'1px solid #f59e0b40', borderRadius:8, padding:'10px 12px', fontSize:11}}>
                  <div style={{color:'#fbbf24', fontWeight:700, marginBottom:4}}>📋 Case 2B — Partial-Timestamp Script</div>
                  <div style={{color:'#7c7a8a'}}>Script has only <em>some</em> timecodes (e.g. scene headings only)? Upload it! Whisper transcribes audio separately, then its timecodes are aligned onto your original script text — best of both worlds.</div>
                </div>
              </div>

              {/* Audio upload row */}
              <div style={{display:'flex', gap:10, marginBottom:14}}>
                <div style={{flex:1, ...S.uploadZone}} onClick={()=>document.getElementById('audio-upload').click()}>
                  <div style={{fontSize:22, marginBottom:4}}>📁</div>
                  <div style={S.uploadTitle}>Upload Audio/Video</div>
                  <div style={S.uploadSub}>MP3, MP4, M4A, WAV, WEBM</div>
                  <input id="audio-upload" type="file" hidden accept="audio/*,video/*" onChange={e=>{if(e.target.files[0])setAudioFile(e.target.files[0])}}/>
                </div>
                <div style={{flex:1, ...S.uploadZone, borderColor: recording ? '#ef4444' : '#2a2a3e', background: recording ? '#2a0f0f' : '#08080f'}}
                     onClick={recording ? stopRecording : startRecording}>
                  <div style={{fontSize:22, marginBottom:4}}>{recording ? '🛑' : '🎤'}</div>
                  <div style={S.uploadTitle}>{recording ? 'Stop Recording' : 'Live Record'}</div>
                  <div style={S.uploadSub}>{recording ? 'Recording in progress...' : 'Use your microphone'}</div>
                </div>
              </div>

              {audioFile && (
                <div style={{...S.fileChip, marginBottom:10}}>
                  <span style={{fontSize:16}}>🎵</span>
                  <div style={{flex:1}}>
                    <div style={{fontSize:12,color:'#c8c6d4'}}>{audioFile.name}</div>
                    <div style={{fontSize:10,color:'#5a5870'}}>{(audioFile.size/1024/1024).toFixed(2)} MB</div>
                  </div>
                  <button style={S.btnX} onClick={()=>setAudioFile(null)}>✕</button>
                </div>
              )}

              {/* Optional script upload for Case 2 / 2B */}
              <div style={{marginBottom:14}}>
                <div style={{fontSize:11, fontWeight:700, color:'#fbbf24', marginBottom:6}}>📋 Optional: Upload Script for Alignment (Case 2 / 2B)</div>
                <div style={{fontSize:10, color:'#5a5870', marginBottom:8}}>
                  Provide your OTT client's script file (even if it only has scene-level timestamps or none at all).
                  Whisper will transcribe the audio separately, then its timecodes are aligned onto <em style={{color:'#fbbf24'}}>your script's correct dialogue text</em>.
                  This prevents Whisper hallucinations — the final output uses <strong style={{color:'#fbbf24'}}>your script's words</strong> with <strong style={{color:'#fbbf24'}}>Whisper's timecodes</strong>.
                </div>
                {!scriptFile ? (
                  <div style={{...S.uploadZone, padding:12, borderColor:'#05966940'}} onClick={()=>scriptFileRef.current.click()}>
                    <div style={{fontSize:11, color:'#34d399'}}>Click to upload script file (DOC, DOCX, PDF, SRT, TXT)</div>
                    <input ref={scriptFileRef} type="file" hidden accept=".doc,.docx,.pdf,.srt,.txt,.vtt"
                      onChange={e=>e.target.files[0]&&setScriptFile(e.target.files[0])}/>
                  </div>
                ) : (
                  <div style={{...S.fileChip, borderColor:'#05966940'}}>
                    <span style={{fontSize:14}}>📄</span>
                    <div style={{flex:1}}><div style={{fontSize:12,color:'#6ee7b7'}}>{scriptFile.name}</div></div>
                    <button style={S.btnX} onClick={()=>setScriptFile(null)}>✕</button>
                  </div>
                )}
              </div>

              <button style={{...S.btnPrimary, ...(transcribing || !audioFile ? S.btnOff : {})}} onClick={handleTranscribe} disabled={transcribing || !audioFile}>
                {transcribing ? '⏳ Transcribing...' : scriptFile ? '✨ Transcribe & Align to Script' : '✨ Transcribe to SRT'}
              </button>

              {transcribing && (
                <div style={S.progressContainer}>
                  <div style={S.progressBarOuter}><div style={{...S.progressBarInner, width: `${transcribeProgress.pct}%`}} /></div>
                  <div style={S.progressMeta}>
                    <span style={S.progressMsg}>{transcribeProgress.msg}</span>
                    <span style={S.progressPct}>{transcribeProgress.pct}%</span>
                  </div>
                </div>
              )}

              {alignStats && alignStats.mode === 'aligned' && (
                <div style={{marginTop:12, background:'#0f1f15', border:'1px solid #05966930', borderRadius:8, padding:'10px 14px', fontSize:11, color:'#6ee7b7'}}>
                  ✅ Alignment complete — {alignStats.matched} / {alignStats.total} lines matched to script.
                  {alignStats.total - alignStats.matched > 0 && <span style={{color:'#fbbf24'}}> {alignStats.total - alignStats.matched} lines interpolated (flagged for review).</span>}
                </div>
              )}

              {transcribeError && <div style={{...S.errBox, marginTop:14}}><div style={{fontSize:12,color:'#fca5a5'}}>{transcribeError}</div></div>}
            </div>
          </div>
        )}

        {/* ══ ADJUST TIMECODES TAB ══ */}
        {tab === 'adjust' && (
          <div style={{maxWidth:700, margin:'0 auto'}}>
            <div style={S.card}>
              <div style={{fontSize:18, fontWeight:700, marginBottom:4}}>⏱️ Timecode Adjuster</div>
              <div style={{fontSize:11, color:'#a78bfa', marginBottom:18}}>
                Fix subtitles that are slightly off from the video. Load subtitles in the Clean or Transcribe tab first.
              </div>

              {/* Mode selector */}
              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, marginBottom:20}}>
                <div style={{background:'#0d0d1a', border:`2px solid ${tcMode==='offset'?'#7c3aed':'#1e1e2e'}`, borderRadius:10, padding:'14px 16px', cursor:'pointer'}}
                  onClick={()=>{setTcMode('offset');setTcValue('');setTcEndValue('');setTcTargetId('');setTcSuccess('');setTcError('');setTcCollision(null)}}>
                  <div style={{fontSize:13, fontWeight:700, color:tcMode==='offset'?'#a78bfa':'#c8c6d4', marginBottom:4}}>± Shift All Subtitles</div>
                  <div style={{fontSize:10, color:'#5a5870', lineHeight:1.5}}>
                    Move <strong style={{color:'#7c7a8a'}}>every</strong> subtitle forward (+) or backward (−) by the same amount.
                    <br/>e.g. <span style={{color:'#a78bfa', fontFamily:'monospace'}}>+2.5</span> seconds, <span style={{color:'#a78bfa', fontFamily:'monospace'}}>-00:00:01:12</span> (frames)
                  </div>
                </div>
                <div style={{background:'#0d0d1a', border:`2px solid ${tcMode==='edit_single'?'#f59e0b':'#1e1e2e'}`, borderRadius:10, padding:'14px 16px', cursor:'pointer'}}
                  onClick={()=>{setTcMode('edit_single');setTcValue('');setTcEndValue('');setTcTargetId('');setTcSuccess('');setTcError('');setTcCollision(null)}}>
                  <div style={{fontSize:13, fontWeight:700, color:tcMode==='edit_single'?'#fbbf24':'#c8c6d4', marginBottom:4}}>✏️ Edit Specific Subtitle</div>
                  <div style={{fontSize:10, color:'#5a5870', lineHeight:1.5}}>
                    Pick a subtitle by its # number. Its current timecodes auto-fill. Choose:
                    <br/><span style={{color:'#fbbf24'}}>Ripple</span> (shift all after it) or <span style={{color:'#f87171'}}>This Only</span> (collision detected).
                  </div>
                </div>
              </div>

              {/* SHIFT ALL MODE */}
              {tcMode === 'offset' && (
                <div style={{marginBottom:14}}>
                  <div style={{fontSize:11, color:'#7c7a8a', marginBottom:8}}>
                    Enter offset — positive pushes subtitles later, negative pulls them earlier:
                  </div>
                  <input style={{...S.input, fontFamily:'monospace', fontSize:15, letterSpacing:1, marginBottom:0, borderColor:'#7c3aed'}}
                    placeholder='+2.5  or  -00:00:01:12  or  +00:00:02,500'
                    value={tcValue}
                    onChange={e=>{setTcValue(e.target.value);setTcSuccess('');setTcError('')}}
                    onKeyDown={e=>e.key==='Enter'&&handleAdjustTimecodes()}
                  />
                  <div style={{fontSize:10, color:'#5a5870', marginTop:6}}>
                    Formats: plain seconds (+2.5), HH:MM:SS:FF frame TC (+00:00:02:12), SRT (+00:00:02,500)
                  </div>
                </div>
              )}

              {/* EDIT SPECIFIC SUBTITLE MODE */}
              {tcMode === 'edit_single' && (
                <>
                  <div style={{marginBottom:12}}>
                    <div style={{fontSize:11, color:'#7c7a8a', marginBottom:6}}>
                      Subtitle # — type an ID and both timecodes below auto-fill:
                    </div>
                    <input style={{...S.input, fontFamily:'monospace', fontSize:15, marginBottom:0, borderColor: tcTargetId ? '#f59e0b' : '#2a2a3e', width:130}}
                      placeholder='e.g. 42'
                      type='number' min='1'
                      value={tcTargetId}
                      onChange={e=>handleTcTargetIdChange(e.target.value)}
                    />
                    {tcTargetId && (() => {
                      const found = subtitles.find(s=>s.id===parseInt(tcTargetId,10))
                      return found ? (
                        <div style={{marginTop:6, padding:'8px 12px', background:'#0d0d00', border:'1px solid #f59e0b30', borderRadius:6, fontSize:11, fontFamily:'monospace', color:'#fbbf24', lineHeight:1.6}}>
                          <span style={{color:'#5a5870'}}>#{found.id}</span>{'  '}
                          {found.start_time} → {found.end_time}
                          {'  '}<span style={{color:'#a08050', fontFamily:'inherit'}}>"{found.text?.substring(0,55)}{found.text?.length>55?'...':''}"</span>
                        </div>
                      ) : tcTargetId ? (
                        <div style={{marginTop:4, fontSize:10, color:'#ef4444'}}>Subtitle #{tcTargetId} not found</div>
                      ) : null
                    })()}
                  </div>

                  <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:14}}>
                    <div>
                      <div style={{fontSize:10, color:'#7c7a8a', marginBottom:5, fontWeight:700, textTransform:'uppercase', letterSpacing:0.6}}>In Timecode (start)</div>
                      <input style={{...S.input, fontFamily:'monospace', fontSize:13, marginBottom:0, borderColor:'#f59e0b'}}
                        placeholder='00:01:05,000'
                        value={tcValue}
                        onChange={e=>{setTcValue(e.target.value);setTcSuccess('');setTcError('');setTcCollision(null)}}
                      />
                    </div>
                    <div>
                      <div style={{fontSize:10, color:'#7c7a8a', marginBottom:5, fontWeight:700, textTransform:'uppercase', letterSpacing:0.6}}>
                        Out Timecode (end) {tcShiftMode==='ripple' && <span style={{color:'#5a5870', fontStyle:'italic', fontWeight:400}}> — auto-adjusted</span>}
                      </div>
                      <input style={{...S.input, fontFamily:'monospace', fontSize:13, marginBottom:0,
                        borderColor: tcShiftMode==='only_this' ? '#f87171' : '#1e1e2e',
                        opacity: tcShiftMode==='ripple' ? 0.45 : 1,
                        cursor: tcShiftMode==='ripple' ? 'not-allowed' : 'text'}}
                        placeholder='00:01:07,500'
                        value={tcEndValue}
                        onChange={e=>{setTcEndValue(e.target.value);setTcSuccess('');setTcError('');setTcCollision(null)}}
                        readOnly={tcShiftMode==='ripple'}
                      />
                    </div>
                  </div>

                  <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, marginBottom:14}}>
                    <div style={{background:'#0d0d1a', border:`2px solid ${tcShiftMode==='ripple'?'#fbbf24':'#1e1e2e'}`, borderRadius:8, padding:'10px 12px', cursor:'pointer'}}
                      onClick={()=>setTcShiftMode('ripple')}>
                      <div style={{fontSize:11, fontWeight:700, color:tcShiftMode==='ripple'?'#fbbf24':'#c8c6d4', marginBottom:3}}>🔁 Ripple Shift</div>
                      <div style={{fontSize:10, color:'#5a5870'}}>Change IN timecode and shift every subtitle after it by the same delta. Duration is preserved. No collisions possible.</div>
                    </div>
                    <div style={{background:'#0d0d1a', border:`2px solid ${tcShiftMode==='only_this'?'#f87171':'#1e1e2e'}`, borderRadius:8, padding:'10px 12px', cursor:'pointer'}}
                      onClick={()=>setTcShiftMode('only_this')}>
                      <div style={{fontSize:11, fontWeight:700, color:tcShiftMode==='only_this'?'#f87171':'#c8c6d4', marginBottom:3}}>📌 This Subtitle Only</div>
                      <div style={{fontSize:10, color:'#5a5870'}}>Change both IN and OUT for this subtitle only. Others stay untouched. Will warn if new timecodes collide with neighbors.</div>
                    </div>
                  </div>

                  {tcTargetId && subtitles.find(s=>s.id===parseInt(tcTargetId,10)) && (
                    <div style={{marginBottom:14}}>
                      <div style={{fontSize:10, color:'#5a5870', marginBottom:6, textTransform:'uppercase', letterSpacing:0.8}}>Context — surrounding subtitles</div>
                      {subtitles.filter(s=>s.id>=Math.max(1,parseInt(tcTargetId,10)-1)&&s.id<=parseInt(tcTargetId,10)+1).map((s,i)=>(
                        <div key={i} style={{
                          background: s.id===parseInt(tcTargetId,10) ? '#1a1200' : '#09090f',
                          border: s.id===parseInt(tcTargetId,10) ? '1px solid #f59e0b40' : '1px solid #1a1a2a',
                          borderRadius:6, padding:'7px 11px', marginBottom:5, display:'flex', gap:10, alignItems:'center'
                        }}>
                          <span style={{fontFamily:'monospace', fontSize:10, color: s.id===parseInt(tcTargetId,10)?'#fbbf24':'#3a3a6a', minWidth:30}}>#{s.id}</span>
                          <span style={{fontFamily:'monospace', fontSize:10, color: s.id===parseInt(tcTargetId,10)?'#fbbf24':'#4f46e5', minWidth:210}}>
                            {s.start_time} → {s.end_time}
                          </span>
                          <span style={{fontSize:10, color: s.id===parseInt(tcTargetId,10)?'#fde68a':'#5a5870', flex:1}}>{s.text?.substring(0,60)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}

              {subtitles.length > 0 && (
                <div style={{background:'#0f1535', border:'1px solid #4f46e530', borderRadius:8, padding:'8px 14px', fontSize:11, color:'#a78bfa', marginBottom:12}}>
                  📊 {subtitles.length} subtitles · First: <span style={{fontFamily:'monospace'}}>{subtitles.find(s=>s.start_time)?.start_time||'—'}</span> · Last: <span style={{fontFamily:'monospace'}}>{[...subtitles].reverse().find(s=>s.end_time)?.end_time||'—'}</span>
                </div>
              )}
              {!subtitles.length && (
                <div style={{background:'#1a1535', border:'1px solid #7c3aed30', borderRadius:8, padding:'10px 14px', fontSize:11, color:'#7c7a8a', marginBottom:12}}>
                  ⚠️ No subtitles loaded. Go to <strong style={{color:'#a78bfa'}}>Clean</strong> or <strong style={{color:'#a78bfa'}}>Transcribe</strong> tab first.
                </div>
              )}

              {(() => {
                const disabled = tcAdjusting || !subtitles.length ||
                  (tcMode==='offset' && !tcValue.trim()) ||
                  (tcMode==='edit_single' && (!tcTargetId.trim() || !tcValue.trim() || (tcShiftMode==='only_this' && !tcEndValue.trim())))
                return (
                  <button style={{...S.btnPrimary, ...(disabled?S.btnOff:{})}} onClick={handleAdjustTimecodes} disabled={disabled}>
                    {tcAdjusting ? 'Applying...' : tcMode==='offset' ? '⏱️ Shift All Subtitles' : tcShiftMode==='ripple' ? '🔁 Apply Ripple Shift' : '📌 Update This Subtitle Only'}
                  </button>
                )
              })()}

              {tcSuccess && <div style={{marginTop:12, background: tcCollision?'#1a1000':'#0f1f15', border:`1px solid ${tcCollision?'#f59e0b30':'#05966930'}`, borderRadius:8, padding:'10px 14px', fontSize:12, color: tcCollision?'#fbbf24':'#6ee7b7'}}>{tcSuccess}</div>}
              {tcCollision && (
                <div style={{marginTop:8, background:'#1a0a0a', border:'1px solid #ef444440', borderRadius:8, padding:'10px 14px', fontSize:11, color:'#fca5a5'}}>
                  ⚠️ <strong>Collision Warning:</strong> {tcCollision}
                  <div style={{marginTop:6, color:'#7c7a8a', fontSize:10}}>The subtitle was updated anyway. Use Ripple Shift to avoid collisions, or manually adjust the neighboring subtitle.</div>
                </div>
              )}
              {tcError && <div style={{...S.errBox, marginTop:12}}><div style={{fontSize:12,color:'#fca5a5'}}>{tcError}</div></div>}
            </div>
          </div>
        )}

        {/* ══ QUALITY CHECK TAB ══ */}
        {tab === 'quality' && (
          <div style={S.twoCol}>
            <div style={S.left}>
              <div style={S.card}>
                <div style={S.label}>Platform to Check Against</div>
                <select style={S.select} value={platform} onChange={e=>setPlatform(e.target.value)}>
                  <optgroup label="Built-in Platforms">
                    {builtinPlatforms.map(([k,p]) => <option key={k} value={k}>{p.name||k}</option>)}
                  </optgroup>
                  {customPlatforms.length > 0 && (
                    <optgroup label="Custom Platforms">
                      {customPlatforms.map(([k,p]) => <option key={k} value={k}>{p.name||k}</option>)}
                    </optgroup>
                  )}
                </select>
              </div>

              <div style={S.card}>
                <div style={S.label}>Upload File to Check (or use cleaned file from Clean tab)</div>
                {subtitles.length > 0 && !qcFile && (
                  <div style={{background:'#0f1f15',border:'1px solid #05966930',borderRadius:8,padding:'10px 14px',fontSize:12,color:'#6ee7b7',marginBottom:12}}>
                    ✅ Will use {subtitles.length} lines from the Clean tab
                  </div>
                )}
                {!qcFile ? (
                  <div style={{...S.uploadZone,...(qcDragOver?S.uploadDrag:{})}}
                    onDragOver={e=>{e.preventDefault();setQcDragOver(true)}}
                    onDragLeave={()=>setQcDragOver(false)}
                    onDrop={e=>{e.preventDefault();setQcDragOver(false);e.dataTransfer.files[0]&&setQcFile(e.dataTransfer.files[0])}}
                    onClick={()=>qcFileRef.current.click()}>
                    <div style={{fontSize:24,marginBottom:6}}>📋</div>
                    <div style={S.uploadTitle}>Upload a different file to check</div>
                    <div style={S.uploadSub}>SRT · TXT · DOC · any format</div>
                    <input ref={qcFileRef} type="file" hidden
                      accept=".srt,.txt,.doc,.docx,.pdf,.rtf"
                      onChange={e=>e.target.files[0]&&setQcFile(e.target.files[0])}/>
                  </div>
                ) : (
                  <div style={S.fileChip}>
                    <span style={{fontSize:18}}>📄</span>
                    <div style={{flex:1}}><div style={{fontSize:13,color:'#c8c6d4'}}>{qcFile.name}</div></div>
                    <button style={S.btnX} onClick={()=>setQcFile(null)}>✕</button>
                  </div>
                )}
              </div>

              <button style={{...S.btnPrimary,...(checking?S.btnOff:{})}} onClick={handleQualityCheck} disabled={checking}>
                {checking ? 'Running quality check...' : '✅ Run Quality Check'}
              </button>

              {qcError && <div style={S.errBox}><div style={{fontSize:12,color:'#fca5a5'}}>{qcError}</div></div>}

              {qcResult && (
                <div style={S.card}>
                  <div style={S.label}>Result — Auto-fixes applied</div>
                  <div style={S.statsGrid}>
                    {[
                      ['Total Lines', qcResult.total_lines, '#a78bfa'],
                      ['Errors', qcResult.error_count ?? qcResult.total_defects, (qcResult.error_count||0)===0?'#34d399':'#ef4444'],
                      ['Warnings', qcResult.warning_count ?? 0, (qcResult.warning_count||0)===0?'#34d399':'#a78bfa'],
                      ['Info', qcResult.info_count ?? 0, '#60a5fa'],
                    ].map(([l,v,c]) => (
                      <div key={l} style={S.statItem}>
                        <div style={{...S.statNum,color:c}}>{v}</div>
                        <div style={S.statLabel}>{l}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{marginTop:12,padding:'10px 14px',borderRadius:8,
                    background: qcResult.is_ready_for_delivery ? '#0f1f15' : '#2a1515',
                    border: `1px solid ${qcResult.is_ready_for_delivery ? '#05966930' : '#ef444430'}`,
                    fontSize:13,fontWeight:700,
                    color: qcResult.is_ready_for_delivery ? '#34d399' : '#ef4444'
                  }}>
                    {qcResult.is_ready_for_delivery
                      ? '✅ File is ready for delivery — all critical issues auto-fixed'
                      : `❌ ${qcResult.error_count || qcResult.total_defects} error(s) need manual review before delivery`}
                  </div>
                  {qcResult.warning_count > 0 && (
                    <div style={{marginTop:8,padding:'8px 12px',borderRadius:8,background:'#1a1535',border:'1px solid #a78bfa20',fontSize:11,color:'#a78bfa'}}>
                      ⚠️ {qcResult.warning_count} warning(s) — acceptable for delivery but review when possible
                    </div>
                  )}
                  {qcResult.info_count > 0 && (
                    <div style={{marginTop:6,padding:'8px 12px',borderRadius:8,background:'#0f1a2e',border:'1px solid #60a5fa20',fontSize:11,color:'#60a5fa'}}>
                      ℹ️ {qcResult.info_count} info note(s) — reading speed slightly above target, review if timing allows
                    </div>
                  )}
                  {qcResult.is_ready_for_delivery && subtitles.length > 0 && (
                    <div style={{marginTop:10,display:'flex',gap:8}}>
                      <button style={{...S.btnPrimary,flex:1,fontSize:12,padding:'8px 12px'}} onClick={exportSRT}>⬇ Export SRT</button>
                      <button style={{...S.btnSecondary,flex:1,fontSize:12,padding:'8px 12px'}} onClick={exportTXT}>⬇ Export TXT</button>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div style={S.right}>
              {qcResult?.defects?.length > 0 ? (
                <div style={S.card}>
                  <div style={{fontSize:14,fontWeight:700,color:'#fff',marginBottom:12}}>
                    {(qcResult.error_count||0) > 0
                      ? `❌ ${qcResult.error_count} Error(s) — Must Fix Before Delivery`
                      : `⚠️ Warnings & Notes — File is Deliverable`}
                  </div>
                  <div style={{maxHeight:600,overflowY:'auto'}}>
                    {/* Errors first */}
                    {qcResult.defects.filter(d=>['critical','error'].includes(d.severity)).map((d,i) => (
                      <div key={`e${i}`} style={{background:SEVERITY_BG[d.severity]||'#13131f',border:`1px solid ${SEVERITY_COLOR[d.severity]||'#2a2a3e'}30`,borderRadius:8,padding:'10px 14px',marginBottom:8,borderLeft:`3px solid ${SEVERITY_COLOR[d.severity]||'#7c3aed'}`}}>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
                          <span style={{fontSize:10,fontWeight:700,padding:'2px 7px',borderRadius:20,background:SEVERITY_COLOR[d.severity]||'#7c3aed',color:'#fff'}}>{d.severity?.toUpperCase()}</span>
                          <span style={{fontSize:11,fontWeight:700,color:'#c8c6d4'}}>{d.type?.replace(/_/g,' ')}</span>
                          {d.line_id&&<span style={{fontSize:10,color:'#5a5870',marginLeft:'auto'}}>Line {d.line_id}</span>}
                        </div>
                        <div style={{fontSize:12,color:'#c8c6d4',marginBottom:4,lineHeight:1.5}}>{d.description}</div>
                        {d.suggestion&&<div style={{fontSize:11,color:'#7c7a8a',fontStyle:'italic'}}>→ {d.suggestion}</div>}
                        {d.text&&<div style={{marginTop:6,padding:'6px 10px',background:'#08080f',borderRadius:6,fontSize:11,color:'#5a5870',fontFamily:'monospace'}}>{d.text.substring(0,100)}{d.text.length>100?'...':''}</div>}
                      </div>
                    ))}
                    {/* Warnings */}
                    {qcResult.defects.filter(d=>d.severity==='warning').length > 0 && (
                      <div style={{fontSize:11,fontWeight:700,color:'#a78bfa',margin:'12px 0 8px',textTransform:'uppercase',letterSpacing:0.8}}>⚠ Warnings (acceptable for delivery)</div>
                    )}
                    {qcResult.defects.filter(d=>d.severity==='warning').map((d,i) => (
                      <div key={`w${i}`} style={{background:'#1a1535',border:'1px solid #a78bfa20',borderRadius:8,padding:'8px 12px',marginBottom:6,borderLeft:'3px solid #a78bfa'}}>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:3}}>
                          <span style={{fontSize:10,fontWeight:700,padding:'2px 6px',borderRadius:20,background:'#7c3aed80',color:'#e9d5ff'}}>WARN</span>
                          <span style={{fontSize:10,color:'#c8c6d4'}}>{d.type?.replace(/_/g,' ')}</span>
                          {d.line_id&&<span style={{fontSize:10,color:'#5a5870',marginLeft:'auto'}}>Line {d.line_id}</span>}
                        </div>
                        <div style={{fontSize:11,color:'#9c9ab0',lineHeight:1.4}}>{d.description}</div>
                      </div>
                    ))}
                    {/* Info */}
                    {qcResult.defects.filter(d=>d.severity==='info').length > 0 && (
                      <div style={{fontSize:11,fontWeight:700,color:'#60a5fa',margin:'12px 0 8px',textTransform:'uppercase',letterSpacing:0.8}}>ℹ Info (no action needed)</div>
                    )}
                    {qcResult.defects.filter(d=>d.severity==='info').map((d,i) => (
                      <div key={`i${i}`} style={{background:'#0f1a2e',border:'1px solid #60a5fa15',borderRadius:8,padding:'8px 12px',marginBottom:6,borderLeft:'3px solid #60a5fa40'}}>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:3}}>
                          <span style={{fontSize:10,color:'#60a5fa'}}>{d.type?.replace(/_/g,' ')}</span>
                          {d.line_id&&<span style={{fontSize:10,color:'#5a5870',marginLeft:'auto'}}>Line {d.line_id}</span>}
                        </div>
                        <div style={{fontSize:11,color:'#4a7a9b',lineHeight:1.4}}>{d.description}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : qcResult?.is_ready_for_delivery ? (
                <div style={{...S.empty,border:'1px solid #05966930',background:'#0a1a10'}}>
                  <div style={{fontSize:48,marginBottom:14}}>🎉</div>
                  <div style={{fontSize:17,fontWeight:700,color:'#34d399',marginBottom:8}}>No defects found!</div>
                  <div style={{fontSize:12,color:'#6ee7b7'}}>File is ready for delivery to {platforms[platform]?.name || platform}</div>
                </div>
              ) : (
                <div style={S.empty}>
                  <div style={{fontSize:48,marginBottom:14}}>🔍</div>
                  <div style={{fontSize:17,fontWeight:700,color:'#c8c6d4',marginBottom:8}}>Quality Check</div>
                  <div style={{fontSize:12,color:'#5a5870',marginBottom:20}}>Checks your file against real OTT platform rules</div>
                  <div style={{textAlign:'left',maxWidth:360}}>
                    {['File naming convention (EHD_123456E_ENG.PAC)','Zero subtitle format and fields','Character limit per line per platform','Duration min/max per platform','Reading speed (CPS)','HOH and EMT element removal','Profanity replacement (fxxx, cxxx etc.)','Spacing and punctuation defects','Double spaces, trailing spaces','ALL CAPS usage'].map(c=>(
                      <div key={c} style={{fontSize:12,color:'#5a5870',padding:'4px 0',borderBottom:'1px solid #13131f'}}>✓ {c}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ══ PLATFORMS TAB ══ */}
        {tab === 'platforms' && (
          <div style={S.twoCol}>
            <div style={S.left}>
              <div style={S.card}>
                <div style={S.label}>Add New OTT Platform</div>
                <input style={S.input} placeholder="Platform name (e.g. Zee5, SonyLiv, Voot)" value={newName} onChange={e=>setNewName(e.target.value)}/>
                <div style={{fontSize:11,color:'#5a5870',marginBottom:6}}>Upload guidelines document (optional)</div>
                {!glFile ? (
                  <div style={{...S.uploadZone,padding:14}} onClick={()=>document.getElementById('gl-in').click()}>
                    <div style={{fontSize:11,color:'#5a5870',marginBottom:6}}>PDF · DOC · TXT</div>
                    <button style={S.btnOutline}>Upload Guidelines</button>
                    <input id="gl-in" type="file" hidden accept=".doc,.docx,.pdf,.txt,.rtf" onChange={e=>e.target.files[0]&&setGlFile(e.target.files[0])}/>
                  </div>
                ) : (
                  <div style={{...S.fileChip,marginBottom:10}}>
                    <span>📄</span><span style={{flex:1,fontSize:12}}>{glFile.name}</span>
                    <button style={S.btnX} onClick={()=>setGlFile(null)}>✕</button>
                  </div>
                )}
                <div style={{fontSize:11,color:'#5a5870',marginBottom:6,marginTop:10}}>Or paste guidelines text</div>
                <textarea style={S.textarea} placeholder="Paste OTT platform subtitle guidelines here..." value={glText} onChange={e=>setGlText(e.target.value)} rows={5}/>
                <button style={{...S.btnPrimary,marginTop:10,...(adding?S.btnOff:{})}} onClick={handleAddPlatform} disabled={adding}>
                  {adding ? 'AI reading guidelines...' : '➕ Add Platform'}
                </button>
                {addMsg&&<div style={{background:'#0f1f15',border:'1px solid #05966930',borderRadius:8,padding:'10px 14px',fontSize:12,color:'#6ee7b7',marginTop:10}}>✅ {addMsg}</div>}
                {addErr&&<div style={S.errBox}><div style={{fontSize:12,color:'#fca5a5'}}>{addErr}</div></div>}
              </div>
            </div>

            <div style={S.right}>
              {customPlatforms.length > 0 && (
                <div style={S.card}>
                  <div style={S.label}>Your Custom Platforms</div>
                  {customPlatforms.map(([k,p]) => (
                    <div key={k} style={{background:'#1a1a2e',border:'1px solid #2a2a3e',borderRadius:8,padding:'12px 14px',marginBottom:8,display:'flex',alignItems:'flex-start',gap:10,cursor:'pointer'}} onClick={()=>{setEditingPlatform({...p, platform_key: k});setEditRulesText((p.rules||[]).join('\n'))}}>
                      <div style={{flex:1}}>
                        <div style={{fontSize:13,fontWeight:700,color:'#fff',marginBottom:2}}>{p.name||k}</div>
                        <div style={{fontSize:11,color:'#5a5870'}}>{p.max_chars_per_line} chars/line · {p.max_lines} lines · {(p.rules||[]).length} rules</div>
                      </div>
                      <button style={{background:'none',border:'none',cursor:'pointer',fontSize:16,color:'#5a5870'}} onClick={(e)=>{e.stopPropagation();handleDeletePlatform(k)}}>🗑</button>
                    </div>
                  ))}
                </div>
              )}

              <div style={S.card}>
                <div style={S.label}>Built-in Platforms (from OTT Clients Protocol)</div>
                <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
                  {builtinPlatforms.map(([k,p]) => (
                    <div key={k} style={{background:'#1a1a2e',border:'1px solid #2a2a3e',borderRadius:8,padding:'10px 12px',cursor:'pointer'}} onClick={()=>{setEditingPlatform({...p, platform_key: k});setEditRulesText((p.rules||[]).join('\n'))}}>
                      <div style={{fontSize:12,fontWeight:700,color:'#c8c6d4',marginBottom:3}}>{p.name||k}</div>
                      <div style={{fontSize:10,color:'#5a5870'}}>{p.max_chars_per_line} chars · {p.max_lines} lines · {p.file_format||'PAC'}</div>
                      {p.reading_speed_max_cps&&<div style={{fontSize:10,color:'#5a5870'}}>Max {p.reading_speed_max_cps} CPS</div>}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
      {/* ══ MOVIE HUB TAB ══ */}
      {tab === 'movie_hub' && (
        <div style={{display:'flex', gap:20}}>
          {/* Add Movie Form */}
          <div style={{...S.card, width: 350, alignSelf:'flex-start'}}>
            <div style={S.label}>Share a Website</div>
            
            {movieErr && <div style={{...S.errBox, marginBottom:10}}>{movieErr}</div>}
            {movieMsg && <div style={{...S.errBox, background:'#05966933', color:'#34d399', borderColor:'#34d399', padding:'10px', marginBottom:10}}>{movieMsg}</div>}

            <div style={{marginBottom:10}}>
              <div style={{fontSize:12, color:'#c8c6d4', marginBottom:4}}>Site Name</div>
              <input style={S.input} placeholder="e.g. YTS, 1337x, etc." value={newMovie.title} onChange={e=>setNewMovie({...newMovie, title: e.target.value})} />
            </div>
            <div style={{marginBottom:10}}>
              <div style={{fontSize:12, color:'#c8c6d4', marginBottom:4}}>Website URL</div>
              <input style={S.input} placeholder="https://..." value={newMovie.url} onChange={e=>setNewMovie({...newMovie, url: e.target.value})} />
            </div>
            <div style={{marginBottom:15}}>
              <div style={{fontSize:12, color:'#c8c6d4', marginBottom:4}}>Added By (Optional)</div>
              <input style={S.input} placeholder="Your Name" value={newMovie.added_by} onChange={e=>setNewMovie({...newMovie, added_by: e.target.value})} />
            </div>
            
            <button style={S.btnPrimary} onClick={handleAddMovie}>+ Add to Hub</button>
          </div>

          {/* Movie List */}
          <div style={{flex:1, display:'flex', flexDirection:'column', gap:10}}>
            {movies.length === 0 ? (
              <div style={{...S.card, textAlign:'center', color:'#5a5870', padding:40}}>
                <div style={{fontSize:40, marginBottom:10}}>🌐</div>
                No websites shared yet. Be the first!
              </div>
            ) : (
              movies.map(m => (
                <div key={m.id} style={{...S.card, display:'flex', justifyContent:'space-between', alignItems:'center'}}>
                  <div>
                    <div style={{fontSize:16, fontWeight:700, color:'#e8e6df', marginBottom:4}}>{m.title}</div>
                    <div style={{fontSize:12, color:'#5a5870'}}>Added by: <span style={{color:'#a78bfa'}}>{m.added_by}</span> • {new Date(m.created_at).toLocaleDateString()}</div>
                  </div>
                  <a href={m.url.startsWith('http') ? m.url : `https://${m.url}`} target="_blank" rel="noopener noreferrer" style={{...S.btnOutline, textDecoration:'none', display:'inline-block'}}>
                    🔗 Open Link
                  </a>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* ══ EDIT PLATFORM MODAL ══ */}
      {editingPlatform && (
        <div style={{position:'fixed',top:0,left:0,right:0,bottom:0,background:'rgba(0,0,0,0.8)',display:'flex',alignItems:'center',justifyContent:'center',zIndex:999}} onClick={(e)=>{if(e.target===e.currentTarget)setEditingPlatform(null)}}>
          <div style={{background:'#0d0d1a',border:'1px solid #4f46e5',borderRadius:12,padding:24,width:600,maxWidth:'90%',maxHeight:'90vh',display:'flex',flexDirection:'column'}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
              <div style={{fontSize:18,fontWeight:700}}>📝 Rules: {editingPlatform.name} <span style={{fontSize:11,fontWeight:400,color:'#5a5870',background:'#1a1a2e',padding:'2px 6px',borderRadius:4,marginLeft:8}}>{editingPlatform.is_custom?'CUSTOM':'BUILT-IN'}</span></div>
              <button style={{background:'none',border:'none',color:'#5a5870',fontSize:20,cursor:'pointer'}} onClick={()=>setEditingPlatform(null)}>✕</button>
            </div>
            <div style={{fontSize:12,color:'#a78bfa',marginBottom:16,lineHeight:1.4}}>
              Edit the exact rules used by the AI Quality Checker below. Each line is evaluated as a separate formatting rule. Changes apply immediately to future checks.
            </div>
            <textarea 
              style={{...S.textarea, flex:1, minHeight:350, fontFamily:'monospace', fontSize:13, lineHeight:1.6, borderColor:'#2a2a3e', background:'#09090f'}} 
              value={editRulesText} 
              onChange={e=>setEditRulesText(e.target.value)} 
              spellCheck="false"
            />
            <div style={{display:'flex',alignItems:'center',gap:12,marginTop:16}}>
              <button style={{...S.btnPrimary, flex:1}} onClick={handleSaveRules}>💾 Save Rules</button>
            </div>
            {editPlatformMsg && <div style={{marginTop:12,background:'#0f1f15',border:'1px solid #05966930',borderRadius:8,padding:'8px',color:'#6ee7b7',fontSize:12,textAlign:'center'}}>✅ {editPlatformMsg}</div>}
            {editPlatformErr && <div style={{marginTop:12,background:'#2a0a0a',border:'1px solid #ef444430',borderRadius:8,padding:'8px',color:'#fca5a5',fontSize:12,textAlign:'center'}}>❌ {editPlatformErr}</div>}
          </div>
        </div>
      )}

    </div>
  )
}

// ─── STYLES ──────────────────────────────────────────────────────

const S = {
  root: { minHeight:'100vh', background:'#08080f', color:'#e8e6df', fontFamily:"'Segoe UI',system-ui,sans-serif" },
  header: { background:'linear-gradient(135deg,#0d0d1a,#12122a)', borderBottom:'1px solid #1e1e2e', padding:'14px 24px', display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', gap:10 },
  headerLeft: { display:'flex', alignItems:'center', gap:12 },
  logo: { width:38, height:38, background:'linear-gradient(135deg,#7c3aed,#4f46e5)', borderRadius:10, display:'flex', alignItems:'center', justifyContent:'center', fontWeight:800, fontSize:18, color:'white' },
  logoTitle: { fontSize:17, fontWeight:700, color:'#fff' },
  logoSub: { fontSize:10, color:'#5a5870', marginTop:2 },
  tabs: { display:'flex', gap:8, flexWrap:'wrap' },
  tab: { padding:'7px 14px', background:'transparent', border:'1.5px solid #2a2a3e', borderRadius:8, color:'#7c7a8a', fontSize:12, fontWeight:600, cursor:'pointer' },
  tabActive: { background:'#7c3aed20', borderColor:'#7c3aed', color:'#a78bfa' },
  body: { padding:'20px 24px', maxWidth:1400, margin:'0 auto' },
  twoCol: { display:'grid', gridTemplateColumns:'380px 1fr', gap:20 },
  left: { display:'flex', flexDirection:'column', gap:14 },
  right: { display:'flex', flexDirection:'column', gap:14 },
  card: { background:'#0d0d1a', border:'1px solid #1e1e2e', borderRadius:12, padding:18 },
  label: { fontSize:11, fontWeight:700, color:'#7c3aed', textTransform:'uppercase', letterSpacing:0.8, marginBottom:10 },
  select: { width:'100%', padding:'10px 12px', background:'#08080f', border:'1.5px solid #2a2a3e', borderRadius:8, color:'#e8e6df', fontSize:13, cursor:'pointer' },
  platformMeta: { display:'flex', gap:8, marginTop:8, fontSize:11, color:'#5a5870', flexWrap:'wrap' },
  uploadZone: { border:'1.5px dashed #2a2a3e', borderRadius:10, padding:22, textAlign:'center', cursor:'pointer', background:'#08080f' },
  uploadDrag: { borderColor:'#7c3aed', background:'#16132a' },
  uploadTitle: { fontSize:13, fontWeight:600, color:'#c8c6d4', marginBottom:4 },
  uploadSub: { fontSize:11, color:'#5a5870', marginBottom:8 },
  fileChip: { display:'flex', alignItems:'center', gap:10, background:'#13131f', border:'1px solid #7c3aed30', borderRadius:8, padding:'10px 14px' },
  btnX: { background:'none', border:'none', color:'#5a5870', cursor:'pointer', fontSize:14, padding:'2px 5px', borderRadius:4 },
  btnPrimary: { width:'100%', padding:13, background:'linear-gradient(135deg,#7c3aed,#4f46e5)', border:'none', borderRadius:10, color:'white', fontSize:14, fontWeight:700, cursor:'pointer' },
  btnOff: { opacity:0.5, cursor:'not-allowed' },
  btnSm: { padding:'6px 12px', background:'#13131f', border:'1.5px solid #2a2a3e', borderRadius:7, color:'#c8c6d4', fontSize:11, fontWeight:600, cursor:'pointer' },
  btnOutline: { padding:'7px 14px', background:'transparent', border:'1.5px solid #2a2a3e', borderRadius:8, color:'#c8c6d4', fontSize:12, cursor:'pointer' },
  errBox: { background:'#1a0f0f', border:'1px solid #ef444430', borderRadius:10, padding:'14px 16px', textAlign:'center' },
  statsGrid: { background:'#0d0d1a', border:'1px solid #1e1e2e', borderRadius:10, padding:14, display:'grid', gridTemplateColumns:'1fr 1fr', gap:10 },
  statItem: { textAlign:'center' },
  statNum: { fontSize:22, fontWeight:800, color:'#a78bfa', marginBottom:2 },
  statLabel: { fontSize:10, color:'#5a5870', textTransform:'uppercase', letterSpacing:0.5 },
  subList: { maxHeight:560, overflowY:'auto', border:'1px solid #1e1e2e', borderRadius:8 },
  subRow: { padding:'18px 24px', borderBottom:'1px solid #131320', textAlign:'center' },
  subFlagged: { background:'#1a0f0f', borderLeft:'3px solid #ef4444' },
  timecode: { fontSize:11, color:'#a78bfa', fontFamily:'Consolas, monospace', marginBottom:6 },
  subText: { fontSize:13, color:'#e8e6df', lineHeight:1.8, outline:'none' },
  empty: { display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', minHeight:300, textAlign:'center', padding:30, background:'#0d0d1a', border:'1px solid #1e1e2e', borderRadius:12 },
  input: { width:'100%', padding:'10px 12px', background:'#08080f', border:'1.5px solid #2a2a3e', borderRadius:8, color:'#e8e6df', fontSize:13, marginBottom:10, outline:'none' },
  textarea: { width:'100%', padding:'10px 12px', background:'#08080f', border:'1.5px solid #2a2a3e', borderRadius:8, color:'#e8e6df', fontSize:12, resize:'vertical', fontFamily:'inherit', outline:'none' },
  progressContainer: { marginTop: 12, padding: 12, background: '#131320', borderRadius: 10, border: '1px solid #7c3aed20' },
  progressBarOuter: { width: '100%', height: 6, background: '#0a0a10', borderRadius: 10, overflow: 'hidden', marginBottom: 8 },
  progressBarInner: { height: '100%', background: 'linear-gradient(90deg, #7c3aed, #4f46e5)', transition: 'width 0.3s ease' },
  progressMeta: { display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#a78bfa' },
  progressMsg: { color: '#c8c6d4' },
  progressPct: { fontWeight: 700 },
}
