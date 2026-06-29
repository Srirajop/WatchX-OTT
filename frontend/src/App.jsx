import { useState, useEffect, useRef } from 'react'
import axios from 'axios'

const API = '/api'

const SEVERITY_COLOR = { critical: '#dc2626', error: '#d97706', warning: '#6366f1', info: '#2563eb' }
const SEVERITY_BG = { critical: '#fee2e2', error: '#fef3c7', warning: '#eef2ff', info: '#eff6ff' }

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

  // Platform Search
  const [searchKeyword, setSearchKeyword] = useState('')
  const [searchPlatformFilter, setSearchPlatformFilter] = useState('')

  // Add/Generate Platform
  const [uniPlatform, setUniPlatform] = useState('')
  const [uniFile, setUniFile] = useState(null)
  const [uniText, setUniText] = useState('')
  const [uniProcessing, setUniProcessing] = useState(false)
  const [uniMsg, setUniMsg] = useState('')
  const [uniErr, setUniErr] = useState('')
  const [platform, setPlatform] = useState('discovery_max')
  const [managementView, setManagementView] = useState('platforms')

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
  const [qcPlatform, setQcPlatform] = useState('discovery_max')
  const [qcSubtitles, setQcSubtitles] = useState([])
  const qcFileRef = useRef()

  // Platforms tab
  const [editingPlatform, setEditingPlatform] = useState(null)
  const [editRulesText, setEditRulesText] = useState('')
  const [editPlatformMsg, setEditPlatformMsg] = useState('')
  const [editPlatformErr, setEditPlatformErr] = useState('')

  // Transcribe tab
  const [audioFile, setAudioFile] = useState(null)
  const [scriptFile, setScriptFile] = useState(null)  // optional script for alignment (Case 2)
  const [whisperSubs, setWhisperSubs] = useState([])  // raw whisper output
  const [recording, setRecording] = useState(false)
  const [screenRecording, setScreenRecording] = useState(false)
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

  // Track Changes (on-screen view, before PDF download)
  const [trackChangesOpen, setTrackChangesOpen] = useState(false)
  const [trackChangesData, setTrackChangesData] = useState(null)
  const [trackChangesLoading, setTrackChangesLoading] = useState(false)
  const [trackChangesErr, setTrackChangesErr] = useState('')

  // Timecode Adjuster
  const [tcMode, setTcMode] = useState('offset')   // 'offset' | 'edit_single'
  const [tcValue, setTcValue] = useState('')         // offset OR new start TC
  const [tcEndValue, setTcEndValue] = useState('')   // new end TC (edit_single only)
  const [tcTargetId, setTcTargetId] = useState('')   // subtitle ID (edit_single only)
  const [tcRangeEndId, setTcRangeEndId] = useState('') // last subtitle ID the fix applies up to (range mode only)
  const [tcShiftMode, setTcShiftMode] = useState('ripple') // 'ripple' | 'only_this' | 'range'
  const [tcAdjusting, setTcAdjusting] = useState(false)
  const [tcError, setTcError] = useState('')
  const [tcSuccess, setTcSuccess] = useState('')
  const [tcCollision, setTcCollision] = useState(null) // null | collision detail string
  const [tcFile, setTcFile] = useState(null)
  const [tcSubtitles, setTcSubtitles] = useState([])
  const [tcLoading, setTcLoading] = useState(false)
  const tcFileRef = useRef()

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
      setMovieErr('')
    } catch(e) {
      console.error('Failed to load movies:', e)
      setMovieErr(e.response?.data?.detail || 'Could not load Movie Hub. Check the backend and database connection.')
    }
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

      const contentType = response.headers.get('content-type')
      if (contentType && contentType.includes('application/json')) {
        const data = await response.json()
        setSubtitles(data.subtitles || [])
        setCleanStats(data.stats || null)
        setCleanProgress(100)
        setCleanText('Extraction complete!')
        setExtracting(false)
        return
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

  async function exportTrackChangesPDF() {
    const r = await axios.post(`${API}/export/track-changes-pdf`, { subtitles, filename: file?.name, platform_key: platform }, { responseType: 'blob' })
    const url = URL.createObjectURL(r.data)
    const a = document.createElement('a'); a.href = url
    a.download = `${file?.name || 'subtitles'}_track_changes.pdf`; a.click(); URL.revokeObjectURL(url)
  }

  async function loadTrackChanges() {
    setTrackChangesErr(''); setTrackChangesLoading(true)
    try {
      const r = await axios.post(`${API}/track-changes`, { subtitles, platform_key: platform })
      setTrackChangesData(r.data)
      setTrackChangesOpen(true)
    } catch (e) {
      setTrackChangesErr(e.response?.data?.detail || 'Could not load track changes')
    } finally {
      setTrackChangesLoading(false)
    }
  }

  // ── QUALITY CHECK ──────────────────────────────────────────────

  function selectQcFile(fileToCheck) {
    if (!fileToCheck) return
    setQcFile(fileToCheck); setQcSubtitles([]); setQcResult(null); setQcError('')
  }

  async function exportQcSRT() {
    const output = qcResult?.subtitles || qcSubtitles
    const name = qcFile?.name || file?.name || 'quality-check.srt'
    const r = await axios.post(`${API}/export/srt`, { subtitles: output, filename: name, platform_key: qcPlatform }, { responseType: 'blob' })
    const url = URL.createObjectURL(r.data)
    const a = document.createElement('a'); a.href = url
    a.download = `${name.replace(/\.[^/.]+$/, '')}_quality_checked.srt`; a.click(); URL.revokeObjectURL(url)
  }

  async function exportQcTXT() {
    const output = qcResult?.subtitles || qcSubtitles
    const name = qcFile?.name || file?.name || 'quality-check.txt'
    const r = await axios.post(`${API}/export/txt`, { subtitles: output, filename: name }, { responseType: 'blob' })
    const url = URL.createObjectURL(r.data)
    const a = document.createElement('a'); a.href = url
    a.download = `${name.replace(/\.[^/.]+$/, '')}_quality_checked.txt`; a.click(); URL.revokeObjectURL(url)
  }

  async function exportAdjustedSRT() {
    const name = tcFile?.name || file?.name || 'adjusted.srt'
    const r = await axios.post(`${API}/export/srt`, { subtitles: activeTcSubtitles, filename: name, platform_key: 'generic', preserve_exact: true }, { responseType: 'blob' })
    const url = URL.createObjectURL(r.data)
    const a = document.createElement('a'); a.href = url
    a.download = `${name.replace(/\.[^/.]+$/, '')}_timecode_adjusted.srt`; a.click(); URL.revokeObjectURL(url)
  }

  function clearQcFile() {
    setQcFile(null); setQcSubtitles([]); setQcResult(null); setQcError('')
    if (qcFileRef.current) qcFileRef.current.value = ''
  }

  async function handleQualityCheck() {
    if (!qcFile && qcSubtitles.length === 0 && subtitles.length === 0) { setQcError('Upload a subtitle file or clean a file first'); return }

    setChecking(true); setQcError(''); setQcResult(null)

    try {
      let subs = qcSubtitles.length ? qcSubtitles : subtitles

      if (qcFile) {
        setQcError('Extracting file for quality check...')
        const fd = new FormData()
        fd.append('file', qcFile)
        fd.append('platform', qcPlatform)
        const response = await fetch(`${API}/extract`, { method: 'POST', body: fd })
        if (!response.ok) throw new Error(`Server error: ${response.status}`)
        
        const contentType = response.headers.get('content-type')
        if (contentType && contentType.includes('application/json')) {
          const data = await response.json()
          subs = data.subtitles || []
        } else {
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
        }
        setQcError('') // Clear extraction message
        setQcSubtitles(subs)
      }

      if (!subs.length) {
        setQcError('No dialogue lines found in file')
        return
      }

      const r = await axios.post(`${API}/quality-check`, {
        subtitles: subs,
        platform_key: qcPlatform,
        filename: qcFile?.name || file?.name || 'subtitles.srt'
      })
      // Quality Check owns its result; do not silently replace Clean/Adjust data.
      if (r.data.subtitles?.length) setQcSubtitles(r.data.subtitles)
      setQcResult(r.data)
    } catch (e) {
      setQcError(e.response?.data?.detail || 'Quality check failed — is backend running?')
    } finally { setChecking(false) }
  }

  // ── PLATFORMS ──────────────────────────────────────────────────

  async function handleUnifiedProcess() {
    setUniErr(''); setUniMsg('')
    if (!uniPlatform.trim()) {
      setUniErr('Platform Name is required.')
      return
    }
    if (!uniFile && !uniText.trim()) {
      setUniErr('Upload a guidelines file or paste the guideline text.')
      return
    }

    setUniProcessing(true)
    try {
      const fdRules = new FormData()
      fdRules.append('platform_name', uniPlatform)
      if (uniFile) fdRules.append('guidelines_file', uniFile)
      if (uniText.trim()) fdRules.append('guidelines_text', uniText.trim())
      const rRules = await axios.post(`/api/platforms/add`, fdRules)
      setUniMsg(rRules.data.message || 'Platform rules generated.')
      await loadPlatforms()

      setUniFile(null); setUniText('')
    } catch (e) {
      setUniErr(e.response?.data?.detail || 'Processing failed.')
    } finally {
      setUniProcessing(false)
    }
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

  async function startScreenRecording() {
    try {
      const displayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true }).catch(() => null)
      if (!displayStream) return // User cancelled
      
      const recorder = new MediaRecorder(displayStream)
      const chunks = []
      recorder.ondataavailable = e => chunks.push(e.data)
      recorder.onstop = () => {
        const blob = new Blob(chunks, { type: 'video/webm' })
        const f = new File([blob], 'screen_recording.webm', { type: 'video/webm' })
        setAudioFile(f)
      }
      
      recorder.__originalStreams = [displayStream]
      
      displayStream.getVideoTracks()[0].onended = () => {
        if (recorder.state !== 'inactive') {
          recorder.stop()
          recorder.__originalStreams.forEach(s => s.getTracks().forEach(t => t.stop()))
          setScreenRecording(false)
        }
      }

      recorder.start()
      setMediaRecorder(recorder)
      setScreenRecording(true)
      setTranscribeError('')
    } catch (e) {
      setTranscribeError('Screen recording failed: ' + e.message)
    }
  }

  function stopScreenRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop()
      mediaRecorder.stream.getTracks().forEach(t => t.stop())
      if (mediaRecorder.__originalStreams) {
        mediaRecorder.__originalStreams.forEach(s => s.getTracks().forEach(t => t.stop()))
      }
      setScreenRecording(false)
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
    setTcRangeEndId('')
    setTcSuccess(''); setTcError(''); setTcCollision(null)
    if (val.trim()) {
      const found = activeTcSubtitles.find(s => s.id === parseInt(val, 10))
      if (found) {
        setTcValue(found.start_time || '')
        setTcEndValue(found.end_time || '')
      }
    }
  }

  async function handleTcFile(fileToLoad) {
    if (!fileToLoad) return
    setTcFile(fileToLoad); setTcLoading(true); setTcError(''); setTcSuccess(''); setTcCollision(null)
    try {
      const fd = new FormData()
      fd.append('file', fileToLoad)
      const r = await axios.post(`${API}/extract`, fd)
      const extracted = r.data?.subtitles || []
      const timed = extracted.filter(s => s.start_time && s.end_time)
      if (!timed.length) throw new Error('This file has no readable timecodes. Upload an SRT/VTT or a timed DOC/DOCX/PDF script.')
      setTcSubtitles(timed)
      setTcSuccess(`Loaded ${timed.length} timed subtitles from ${fileToLoad.name}.`)
    } catch (e) {
      setTcFile(null); setTcSubtitles([])
      setTcError(e.response?.data?.detail || e.message || 'Could not extract timed subtitles from this file.')
    } finally { setTcLoading(false) }
  }

  function clearTcFile() {
    setTcFile(null); setTcSubtitles([]); setTcError(''); setTcSuccess(''); setTcCollision(null)
    setTcTargetId(''); setTcRangeEndId(''); setTcValue(''); setTcEndValue('')
    if (tcFileRef.current) tcFileRef.current.value = ''
  }

  async function handleAdjustTimecodes() {
    if (!activeTcSubtitles.length) { setTcError('Upload a timed subtitle file here, or load one in Clean/Transcribe.'); return }
    setTcAdjusting(true); setTcError(''); setTcSuccess(''); setTcCollision(null)
    try {
      let payload, r
      if (tcMode === 'offset') {
        if (!tcValue.trim()) { setTcError('Enter an offset value.'); setTcAdjusting(false); return }
        payload = { subtitles: activeTcSubtitles, mode: 'offset', value: tcValue.trim() }
        r = await axios.post(`${API}/adjust-timecodes`, payload)
        if (tcFile) setTcSubtitles(r.data.subtitles || []); else setSubtitles(r.data.subtitles || [])
        setTcSuccess(`✅ All ${r.data.total} subtitles shifted by ${r.data.value}.`)
        setTcValue('')
      } else {
        // edit_single
        if (!tcTargetId.trim()) { setTcError('Enter the subtitle ID to edit.'); setTcAdjusting(false); return }
        if (!tcValue.trim()) { setTcError('Enter the new start timecode.'); setTcAdjusting(false); return }
        if (tcShiftMode === 'only_this') {
          if (!tcEndValue.trim()) { setTcError('Enter the new end timecode.'); setTcAdjusting(false); return }
          payload = { subtitles: activeTcSubtitles, mode: 'shift_only_this', target_id: parseInt(tcTargetId, 10), new_start: tcValue.trim(), new_end: tcEndValue.trim() }
          r = await axios.post(`${API}/adjust-timecodes`, payload)
          if (tcFile) setTcSubtitles(r.data.subtitles || []); else setSubtitles(r.data.subtitles || [])
          if (r.data.collision) {
            setTcCollision(r.data.collision_detail)
            setTcSuccess(`⚠️ Subtitle #${tcTargetId} updated — but collision detected! Check warning below.`)
          } else {
            setTcSuccess(`✅ Subtitle #${tcTargetId} timecode updated. No collision.`)
          }
        } else if (tcShiftMode === 'range') {
          if (!tcRangeEndId.trim()) { setTcError('Enter the last subtitle ID the fix should apply up to.'); setTcAdjusting(false); return }
          payload = { subtitles: activeTcSubtitles, mode: 'fix_range', target_id: parseInt(tcTargetId, 10), range_end_id: parseInt(tcRangeEndId, 10), value: tcValue.trim() }
          r = await axios.post(`${API}/adjust-timecodes`, payload)
          if (tcFile) setTcSubtitles(r.data.subtitles || []); else setSubtitles(r.data.subtitles || [])
          if (r.data.warning) {
            setTcError(r.data.warning)
          } else {
            setTcSuccess(`✅ Subtitles #${tcTargetId} through #${tcRangeEndId} shifted (${r.data.touched_ids.length} line${r.data.touched_ids.length===1?'':'s'}). Everything outside that range is untouched.`)
          }
        } else {
          // ripple — to the end of the file
          payload = { subtitles: activeTcSubtitles, mode: 'fix_from_index', target_id: parseInt(tcTargetId, 10), value: tcValue.trim() }
          r = await axios.post(`${API}/adjust-timecodes`, payload)
          if (tcFile) setTcSubtitles(r.data.subtitles || []); else setSubtitles(r.data.subtitles || [])
          setTcSuccess(`✅ Subtitle #${tcTargetId} + all ${r.data.total} subsequent subtitles shifted.`)
        }
      }
    } catch (e) {
      setTcError(e.response?.data?.detail || 'Adjustment failed')
    } finally { setTcAdjusting(false) }
  }

  const flaggedCount = subtitles.filter(s => s.flagged).length
  const activeTcSubtitles = tcFile ? tcSubtitles : subtitles
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
            <button key={id} style={{...S.tab,...(tab===id?S.tabActive:{})}} onClick={()=>setTab(id)}>{id === 'platforms' ? 'Rules & Guidelines' : label}</button>
          ))}
        </div>
      </div>

      <div style={S.body}>

        {/* ══ CLEAN TAB ══ */}
        {tab === 'clean' && (
          <div style={S.twoCol}>
            <div style={S.left}>

              <div className='card' style={S.card}>
                <div style={S.label}>Step 1 — Select OTT Platform</div>
                <select style={S.select} value={platform} onChange={e=>setPlatform(e.target.value)}>
                  <optgroup label="Built-in Platforms">
                    {builtinPlatforms.length > 0 ? (
                      builtinPlatforms.map(([k,p]) => <option key={k} value={k}>{p.name || k}</option>)
                    ) : (
                      <option disabled>Loading platforms (or Backend Down)...</option>
                    )}
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

              <div className='card' style={S.card}>
                <div style={S.label}>Step 2 — Upload OTT Script File</div>
                {!file ? (
                  <div className='uploadZone' style={{...S.uploadZone,...(dragOver?S.uploadDrag:{})}}
                    onDragOver={e=>{e.preventDefault();setDragOver(true)}}
                    onDragLeave={()=>setDragOver(false)}
                    onDrop={e=>{e.preventDefault();setDragOver(false);e.dataTransfer.files[0]&&setFile(e.dataTransfer.files[0])}}
                    onClick={()=>fileRef.current.click()}>
                    <div style={{fontSize:32,marginBottom:8}}>📁</div>
                    <div style={S.uploadTitle}>Drag & drop any OTT script file</div>
                    <div style={S.uploadSub}>DOC · DOCX · PDF · SRT · VTT · XML · TTML · RTF · XLSX · CSV · TXT</div>
                    <div style={{...S.uploadSub,marginTop:4,color:'#94a3b8'}}>Tables · Paragraphs · CCSL Spotting Lists · Already cleaned scripts</div>
                    <input ref={fileRef} type="file" hidden
                      accept=".doc,.docx,.pdf,.srt,.vtt,.webvtt,.xml,.ttml,.dfxp,.rtf,.xlsx,.xls,.csv,.txt,.json"
                      onChange={e=>e.target.files[0]&&setFile(e.target.files[0])}/>
                  </div>
                ) : (
                  <div style={S.fileChip}>
                    <span style={{fontSize:18}}>📄</span>
                    <div style={{flex:1}}>
                      <div style={{fontSize:13,color:'#334155'}}>{file.name}</div>
                      <div style={{fontSize:10,color:'#64748b'}}>{(file.size/1024).toFixed(1)} KB</div>
                    </div>
                    <button className='btn-x-hover icon-spin' style={S.btnX} onClick={()=>{setFile(null);setSubtitles([]);setCleanStats(null);setCleanError('')}}>✕</button>
                  </div>
                )}
              </div>

              <div style={{display:'flex',gap:10}}>
                <button style={{...S.btnOutline,flex:1,...(extracting||cleaning||!file?S.btnOff:{})}} onClick={handleExtract} disabled={extracting||cleaning||!file}>
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

              {cleanError && <div style={S.errBox}><div style={{fontSize:20,marginBottom:6}}>❌</div><div style={{fontSize:12,color:'#dc2626',lineHeight:1.6}}>{cleanError}</div></div>}

              {cleanStats && (
                <div style={S.statsGrid}>
                  {[
                    ['Total Lines', cleanStats.total_lines, '#6366f1'],
                    ['Lines Changed', cleanStats.changed_lines ?? '—', '#0ea5e9'],
                    ['Auto-approved', cleanStats.total_lines - cleanStats.flagged_lines, '#059669'],
                    ['Flagged', cleanStats.flagged_lines, cleanStats.flagged_lines > 0 ? '#d97706' : '#059669'],
                  ].map(([label,val,color]) => (
                    <div key={label} style={S.statItem}>
                      <div style={{...S.statNum,color}}>{val}</div>
                      <div style={S.statLabel}>{label}</div>
                    </div>
                  ))}
                  <div style={S.statItem}>
                    <div style={{fontSize:11,fontWeight:700,color:'#4338ca',marginBottom:2}}>{STRUCTURE_LABELS[cleanStats.detected_structure]||cleanStats.detected_structure}</div>
                    <div style={S.statLabel}>Detected Format</div>
                  </div>
                </div>
              )}
            </div>

            <div style={S.right}>
              {subtitles.length > 0 ? (
                <div className='card' style={S.card}>
                  <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:10}}>
                    <div style={{fontSize:14,fontWeight:700,color: '#0f172a'}}>Cleaned Subtitles</div>
                    <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
                      <button style={{...S.btnSm,background:'#eef2ff',borderColor:'#6366f1',color:'#4338ca'}}
                        onClick={loadTrackChanges} disabled={trackChangesLoading}>
                        {trackChangesLoading ? 'Loading...' : '👁️ View Track Changes'}
                      </button>
                      <button style={S.btnSm} onClick={exportSRT}>⬇️ SRT</button>
                      <button style={S.btnSm} onClick={exportTXT}>⬇️ TXT</button>
                      <button style={S.btnSm} onClick={exportDOCX}>⬇️ DOCX</button>
                      <button style={S.btnSm} onClick={exportPDF}>⬇️ PDF</button>
                      <button style={{...S.btnSm,background:'#059669',borderColor:'#059669',color: 'white'}}
                        onClick={()=>setTab('quality')}>✅ Quality Check →</button>
                    </div>
                  </div>
                  {trackChangesErr && <div style={{...S.errBox, marginBottom:12}}>{trackChangesErr}</div>}
                  {flaggedCount > 0 && (
                    <div style={{background:'#fef2f2',border:'1px solid #dc262630',borderRadius:8,padding:'8px 12px',fontSize:11,color:'#dc2626',marginBottom:10}}>
                      ⚠️ {flaggedCount} lines flagged for review — shown in red below. Edit directly in the box.
                    </div>
                  )}
                  <div style={S.subList}>
                    {subtitles.map((sub,i) => (
                      <div key={i} style={{...S.subRow,...(sub.flagged?S.subFlagged:{})}}>
                        {(sub.start_time || sub.end_time) && (
                          <div style={S.timecode}>{`${sub.start_time} --> ${sub.end_time}`}</div>
                        )}
                        <div style={{...S.subText,...(sub.flagged?{color:'#dc2626'}:{})}}
                          contentEditable suppressContentEditableWarning
                          onBlur={e=>{const u=[...subtitles];u[i]={...u[i],text:e.target.innerHTML};setSubtitles(u)}}
                          dangerouslySetInnerHTML={{ __html: (sub.text || '').replace(/&lt;/g, '<').replace(/&gt;/g, '>') }}
                        />
                        {sub.flagged&&sub.flag_reason&&<div style={{fontSize:10,color:'#dc2626',marginTop:4}}>⚠ {sub.flag_reason}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div style={S.empty}>
                  <div style={{fontSize:48,marginBottom:14}}>🎬</div>
                  <div style={{fontSize:17,fontWeight:700,color:'#334155',marginBottom:8}}>Upload a file to get started</div>
                  <div style={{fontSize:12,color:'#64748b',marginBottom:20}}>Supports all OTT subtitle and script formats</div>
                  <div style={{display:'flex',flexWrap:'wrap',gap:8,justifyContent:'center'}}>
                    {['Table with Timecodes (FBoy Island style)','Plain Paragraph Script (Everybody Loves Raymond)','SRT / VTT Subtitle Files','XML / TTML / DFXP','CCSL Spotting List (Juno style)','Excel Spotting Lists','Already Cleaned Scripts','Double Dialogue Scripts'].map(f=>(
                      <div key={f} style={{background:'#f8fafc',border:'1px solid #cbd5e1',borderRadius:6,padding:'5px 10px',fontSize:11,color:'#64748b'}}>{f}</div>
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
            <div className='card' style={S.card}>
              <div style={{fontSize:18, fontWeight:700, marginBottom:6, textAlign:'center'}}>🎙️ AI Audio / Video Transcription</div>
              <div style={{fontSize:11, color:'#6366f1', marginBottom:20, textAlign:'center'}}>Powered by local Faster-Whisper. Runs entirely on your machine. Auto-generates frame-accurate SRT.</div>

              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:8, marginBottom:16}}>
                <div style={{background:'#ffffff', border:'1px solid #4338ca30', borderRadius:8, padding:'10px 12px', fontSize:11}}>
                  <div style={{color:'#6366f1', fontWeight:700, marginBottom:4}}>📄 Case 1 — No Script</div>
                  <div style={{color:'#64748b'}}>Upload audio/video only. Whisper generates a full SRT from scratch.</div>
                </div>
                <div style={{background:'#ffffff', border:'1px solid #05966940', borderRadius:8, padding:'10px 12px', fontSize:11}}>
                  <div style={{color:'#059669', fontWeight:700, marginBottom:4}}>📋 Case 2 — Script + Audio</div>
                  <div style={{color:'#64748b'}}>Upload audio + a <strong style={{color:'#059669'}}>fully-timed</strong> cleaned script. Whisper timecodes get mapped to the correct script text.</div>
                </div>
                <div style={{background:'#ffffff', border:'1px solid #d9770640', borderRadius:8, padding:'10px 12px', fontSize:11}}>
                  <div style={{color:'#d97706', fontWeight:700, marginBottom:4}}>📋 Case 2B — Partial-Timestamp Script</div>
                  <div style={{color:'#64748b'}}>Script has only <em>some</em> timecodes (e.g. scene headings only)? Upload it! Whisper transcribes audio separately, then its timecodes are aligned onto your original script text — best of both worlds.</div>
                </div>
              </div>

              <div style={{display:'flex', gap:10, marginBottom:14}}>
                <div style={{flex:1, ...S.uploadZone}} onClick={()=>document.getElementById('audio-upload').click()}>
                  <div style={{fontSize:22, marginBottom:4}}>📁</div>
                  <div style={S.uploadTitle}>Upload Audio/Video</div>
                  <div style={S.uploadSub}>MP3, MP4, M4A, WAV, WEBM</div>
                  <input id="audio-upload" type="file" hidden accept="audio/*,video/*" onChange={e=>{if(e.target.files[0])setAudioFile(e.target.files[0])}}/>
                </div>
                <div style={{flex:1, ...S.uploadZone, borderColor: recording ? '#dc2626' : '#cbd5e1', background: recording ? '#fee2e2' : '#f8fafc', opacity: screenRecording ? 0.5 : 1, pointerEvents: screenRecording ? 'none' : 'auto'}}
                     onClick={recording ? stopRecording : startRecording}>
                  <div style={{fontSize:22, marginBottom:4}}>{recording ? '🛑' : '🎤'}</div>
                  <div style={S.uploadTitle}>{recording ? 'Stop Recording' : 'Live Record'}</div>
                  <div style={S.uploadSub}>{recording ? 'Recording in progress...' : 'Use your microphone'}</div>
                </div>
                <div style={{flex:1, ...S.uploadZone, borderColor: screenRecording ? '#dc2626' : '#cbd5e1', background: screenRecording ? '#fee2e2' : '#f8fafc', opacity: recording ? 0.5 : 1, pointerEvents: recording ? 'none' : 'auto'}}
                     onClick={screenRecording ? stopScreenRecording : startScreenRecording}>
                  <div style={{fontSize:22, marginBottom:4}}>{screenRecording ? '🛑' : '🖥️'}</div>
                  <div style={S.uploadTitle}>{screenRecording ? 'Stop Screen' : 'Record Screen'}</div>
                  <div style={S.uploadSub}>{screenRecording ? 'Recording in progress...' : 'Record screen & system audio'}</div>
                </div>
              </div>

              {audioFile && (
                <div style={{...S.fileChip, marginBottom:10}}>
                  <span style={{fontSize:16}}>🎵</span>
                  <div style={{flex:1}}>
                    <div style={{fontSize:12,color:'#334155'}}>{audioFile.name}</div>
                    <div style={{fontSize:10,color:'#64748b'}}>{(audioFile.size/1024/1024).toFixed(2)} MB</div>
                  </div>
                  <button className='btn-x-hover icon-spin' style={S.btnX} onClick={()=>setAudioFile(null)}>✕</button>
                </div>
              )}

              <div style={{marginBottom:14}}>
                <div style={{fontSize:11, fontWeight:700, color:'#d97706', marginBottom:6}}>📋 Optional: Upload Script for Alignment (Case 2 / 2B)</div>
                <div style={{fontSize:10, color:'#64748b', marginBottom:8}}>
                  Provide your OTT client's script file (even if it only has scene-level timestamps or none at all).
                  Whisper will transcribe the audio separately, then its timecodes are aligned onto <em style={{color:'#d97706'}}>your script's correct dialogue text</em>.
                  This prevents Whisper hallucinations — the final output uses <strong style={{color:'#d97706'}}>your script's words</strong> with <strong style={{color:'#d97706'}}>Whisper's timecodes</strong>.
                </div>
                {!scriptFile ? (
                  <div className='uploadZone' style={{...S.uploadZone, padding:12, borderColor:'#05966940'}} onClick={()=>scriptFileRef.current.click()}>
                    <div style={{fontSize:11, color:'#059669'}}>Click to upload script file (DOC, DOCX, PDF, SRT, TXT)</div>
                    <input ref={scriptFileRef} type="file" hidden accept=".doc,.docx,.pdf,.srt,.txt,.vtt"
                      onChange={e=>scriptFileRef.current.files[0]&&setScriptFile(scriptFileRef.current.files[0])}/>
                  </div>
                ) : (
                  <div style={{...S.fileChip, borderColor:'#05966940'}}>
                    <span style={{fontSize:14}}>📄</span>
                    <div style={{flex:1}}><div style={{fontSize:12,color:'#059669'}}>{scriptFile.name}</div></div>
                    <button className='btn-x-hover icon-spin' style={S.btnX} onClick={()=>setScriptFile(null)}>✕</button>
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
                <div style={{marginTop:12, background:'#ecfdf5', border:'1px solid #05966930', borderRadius:8, padding:'10px 14px', fontSize:11, color:'#059669'}}>
                  ✅ Alignment complete — {alignStats.matched} / {alignStats.total} lines matched to script.
                  {alignStats.total - alignStats.matched > 0 && <span style={{color:'#d97706'}}> {alignStats.total - alignStats.matched} lines interpolated (flagged for review).</span>}
                </div>
              )}

              {transcribeError && <div style={{...S.errBox, marginTop:14}}><div style={{fontSize:12,color:'#dc2626'}}>{transcribeError}</div></div>}
            </div>
          </div>
        )}

        {/* ══ ADJUST TIMECODES TAB ══ */}
        {tab === 'adjust' && (
          <div style={{maxWidth:1080, margin:'0 auto', display:'grid', gridTemplateColumns:'1fr 320px', gap:20, alignItems:'start'}}>
            <div className='card' style={S.card}>
              <div style={{fontSize:18, fontWeight:700, marginBottom:4}}>⏱️ Timecode Adjuster</div>
              <div style={{fontSize:11, color:'#6366f1', marginBottom:18}}>
                Fix subtitles that are slightly off from the video. Upload a timed file here, or use subtitles already loaded elsewhere.
              </div>

              <div style={{marginBottom:18}}>
                <div style={{fontSize:11,fontWeight:700,color:'#334155',marginBottom:7}}>Timed subtitle file (optional)</div>
                {!tcFile ? (
                  <div className='uploadZone' style={{...S.uploadZone,padding:14}} onClick={()=>tcFileRef.current?.click()}>
                    <div style={{fontSize:22,marginBottom:5}}>Upload</div>
                    <div style={S.uploadTitle}>{tcLoading ? 'Reading timecodes...' : 'Upload directly for timestamp adjustment'}</div>
                    <div style={S.uploadSub}>SRT / VTT / DOC / DOCX / PDF / XML / TTML</div>
                    <input ref={tcFileRef} type='file' hidden accept='.srt,.vtt,.doc,.docx,.pdf,.xml,.ttml,.dfxp,.txt'
                      onChange={e=>handleTcFile(e.target.files?.[0])}/>
                  </div>
                ) : (
                  <div style={S.fileChip}>
                    <span style={{fontSize:18}}>TC</span>
                    <div style={{flex:1}}>
                      <div style={{fontSize:13,color:'#334155'}}>{tcFile.name}</div>
                      <div style={{fontSize:10,color:'#059669'}}>{tcSubtitles.length} timed subtitles loaded independently</div>
                    </div>
                    <button className='btn-x-hover icon-spin' style={S.btnX} onClick={clearTcFile}>X</button>
                  </div>
                )}
                {!tcFile && subtitles.length > 0 && (
                  <div style={{fontSize:10,color:'#059669',marginTop:7}}>Using {subtitles.length} subtitles already loaded in Clean/Transcribe.</div>
                )}
              </div>

              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, marginBottom:20}}>
                <div style={{background:'#ffffff', border:`2px solid ${tcMode==='offset'?'#4338ca':'#e2e8f0'}`, borderRadius:10, padding:'14px 16px', cursor:'pointer'}}
                  onClick={()=>{setTcMode('offset');setTcValue('');setTcEndValue('');setTcTargetId('');setTcRangeEndId('');setTcSuccess('');setTcError('');setTcCollision(null)}}>
                  <div style={{fontSize:13, fontWeight:700, color:tcMode==='offset'?'#6366f1':'#334155', marginBottom:4}}>± Shift All Subtitles</div>
                  <div style={{fontSize:10, color:'#64748b', lineHeight:1.5}}>
                    Move <strong style={{color:'#64748b'}}>every</strong> subtitle forward (+) or backward (−) by the same amount.
                    <br/>e.g. <span style={{color:'#6366f1', fontFamily:'monospace'}}>+2.5</span> seconds, <span style={{color:'#6366f1', fontFamily:'monospace'}}>-00:00:01:12</span> (frames)
                  </div>
                </div>
                <div style={{background:'#ffffff', border:`2px solid ${tcMode==='edit_single'?'#d97706':'#e2e8f0'}`, borderRadius:10, padding:'14px 16px', cursor:'pointer'}}
                  onClick={()=>{setTcMode('edit_single');setTcValue('');setTcEndValue('');setTcTargetId('');setTcRangeEndId('');setTcSuccess('');setTcError('');setTcCollision(null)}}>
                  <div style={{fontSize:13, fontWeight:700, color:tcMode==='edit_single'?'#d97706':'#334155', marginBottom:4}}>✏️ Edit Specific Subtitle</div>
                  <div style={{fontSize:10, color:'#64748b', lineHeight:1.5}}>
                    Pick a subtitle by its # number. Its current timecodes auto-fill. Choose how far the fix should reach — see the three options below.
                  </div>
                </div>
              </div>

              {tcMode === 'offset' && (
                <div style={{marginBottom:14}}>
                  <div style={{fontSize:11, color:'#64748b', marginBottom:8}}>
                    Enter offset — positive pushes subtitles later, negative pulls them earlier:
                  </div>
                  <input style={{...S.input, fontFamily:'monospace', fontSize:15, letterSpacing:1, marginBottom:0, borderColor:'#4338ca'}}
                    placeholder='+2.5  or  -00:00:01:12  or  +00:00:02,500'
                    value={tcValue}
                    onChange={e=>{setTcValue(e.target.value);setTcSuccess('');setTcError('')}}
                    onKeyDown={e=>e.key==='Enter'&&handleAdjustTimecodes()}
                  />
                  <div style={{fontSize:10, color:'#64748b', marginTop:6}}>
                    Formats: plain seconds (+2.5), HH:MM:SS:FF frame TC (+00:00:02:12), SRT (+00:00:02,500)
                  </div>
                </div>
              )}

              {tcMode === 'edit_single' && (
                <>
                  <div style={{marginBottom:12}}>
                    <div style={{fontSize:11, color:'#64748b', marginBottom:6}}>
                      Subtitle # — type an ID and both timecodes below auto-fill:
                    </div>
                    <input style={{...S.input, fontFamily:'monospace', fontSize:15, marginBottom:0, borderColor: tcTargetId ? '#d97706' : '#cbd5e1', width:130}}
                      placeholder='e.g. 42'
                      type='number' min='1'
                      value={tcTargetId}
                      onChange={e=>handleTcTargetIdChange(e.target.value)}
                    />
                    {tcTargetId && (() => {
                      const found = activeTcSubtitles.find(s=>s.id===parseInt(tcTargetId,10))
                      return found ? (
                        <div style={{marginTop:6, padding:'8px 12px', background:'#fef3c7', border:'1px solid #d9770630', borderRadius:6, fontSize:11, fontFamily:'monospace', color:'#d97706', lineHeight:1.6}}>
                          <span style={{color:'#64748b'}}>#{found.id}</span>{'  '}
                          {found.start_time} → {found.end_time}
                          {'  '}<span style={{color:'#a08050', fontFamily:'inherit'}}>"{found.text?.substring(0,55)}{found.text?.length>55?'...':''}"</span>
                        </div>
                      ) : tcTargetId ? (
                        <div style={{marginTop:4, fontSize:10, color:'#dc2626'}}>Subtitle #{tcTargetId} not found</div>
                      ) : null
                    })()}
                  </div>

                  <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:14}}>
                    <div>
                      <div style={{fontSize:10, color:'#64748b', marginBottom:5, fontWeight:700, textTransform:'uppercase', letterSpacing:0.6}}>In Timecode (start)</div>
                      <input style={{...S.input, fontFamily:'monospace', fontSize:13, marginBottom:0, borderColor:'#d97706'}}
                        placeholder='00:01:05,000'
                        value={tcValue}
                        onChange={e=>{setTcValue(e.target.value);setTcSuccess('');setTcError('');setTcCollision(null)}}
                      />
                    </div>
                    <div>
                      <div style={{fontSize:10, color:'#64748b', marginBottom:5, fontWeight:700, textTransform:'uppercase', letterSpacing:0.6}}>
                        Out Timecode (end) {tcShiftMode!=='only_this' && <span style={{color:'#64748b', fontStyle:'italic', fontWeight:400}}> — auto-adjusted</span>}
                      </div>
                      <input style={{...S.input, fontFamily:'monospace', fontSize:13, marginBottom:0,
                        borderColor: tcShiftMode==='only_this' ? '#dc2626' : '#e2e8f0',
                        opacity: tcShiftMode!=='only_this' ? 0.45 : 1,
                        cursor: tcShiftMode!=='only_this' ? 'not-allowed' : 'text'}}
                        placeholder='00:01:07,500'
                        value={tcEndValue}
                        onChange={e=>{setTcEndValue(e.target.value);setTcSuccess('');setTcError('');setTcCollision(null)}}
                        readOnly={tcShiftMode!=='only_this'}
                      />
                    </div>
                  </div>

                  <div style={{fontSize:10, color:'#64748b', marginBottom:6, fontWeight:700, textTransform:'uppercase', letterSpacing:0.6}}>How far should this fix reach?</div>
                  <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:8, marginBottom:14}}>
                    <div style={{background:'#ffffff', border:`2px solid ${tcShiftMode==='ripple'?'#d97706':'#e2e8f0'}`, borderRadius:8, padding:'10px 12px', cursor:'pointer'}}
                      onClick={()=>setTcShiftMode('ripple')}>
                      <div style={{fontSize:11, fontWeight:700, color:tcShiftMode==='ripple'?'#d97706':'#334155', marginBottom:3}}>🔁 Ripple to End</div>
                      <div style={{fontSize:10, color:'#64748b'}}>Shifts this line and every line AFTER it, all the way to the end of the file. Use when the drift never gets corrected again later in the file.</div>
                    </div>
                    <div style={{background:'#ffffff', border:`2px solid ${tcShiftMode==='range'?'#0ea5e9':'#e2e8f0'}`, borderRadius:8, padding:'10px 12px', cursor:'pointer'}}
                      onClick={()=>setTcShiftMode('range')}>
                      <div style={{fontSize:11, fontWeight:700, color:tcShiftMode==='range'?'#0ea5e9':'#334155', marginBottom:3}}>📐 Ripple to a Stopping Point</div>
                      <div style={{fontSize:10, color:'#64748b'}}>Shifts this line and the lines after it, but ONLY up to a subtitle # you choose. Use when the drift fixes itself again partway through the file — e.g. lines 50–80 are off, but 81 onward is already correct.</div>
                    </div>
                    <div style={{background:'#ffffff', border:`2px solid ${tcShiftMode==='only_this'?'#dc2626':'#e2e8f0'}`, borderRadius:8, padding:'10px 12px', cursor:'pointer'}}
                      onClick={()=>setTcShiftMode('only_this')}>
                      <div style={{fontSize:11, fontWeight:700, color:tcShiftMode==='only_this'?'#dc2626':'#334155', marginBottom:3}}>📌 This Line Only</div>
                      <div style={{fontSize:10, color:'#64748b'}}>Changes IN and OUT for just this one line. No other line moves. Will warn if the new timecodes overlap a neighbor.</div>
                    </div>
                  </div>

                  {tcShiftMode === 'range' && (
                    <div style={{marginBottom:14}}>
                      <div style={{fontSize:10, color:'#64748b', marginBottom:6, fontWeight:700, textTransform:'uppercase', letterSpacing:0.6}}>
                        Stop the ripple at subtitle # (inclusive)
                      </div>
                      <input style={{...S.input, fontFamily:'monospace', fontSize:15, marginBottom:0, borderColor:'#0ea5e9', width:130}}
                        placeholder='e.g. 80'
                        type='number' min={tcTargetId || 1}
                        value={tcRangeEndId}
                        onChange={e=>{setTcRangeEndId(e.target.value);setTcSuccess('');setTcError('')}}
                      />
                      <div style={{fontSize:10, color:'#64748b', marginTop:6}}>
                        Everything from #{tcTargetId || '?'} up to and including #{tcRangeEndId || '?'} will shift by the same amount. Subtitle #{tcRangeEndId ? parseInt(tcRangeEndId,10)+1 : '(end+1)'} onward stays exactly where it is.
                      </div>
                    </div>
                  )}

                  {tcTargetId && activeTcSubtitles.find(s=>s.id===parseInt(tcTargetId,10)) && (
                    <div style={{marginBottom:14}}>
                      <div style={{fontSize:10, color:'#64748b', marginBottom:6, textTransform:'uppercase', letterSpacing:0.8}}>Context — surrounding subtitles</div>
                      {activeTcSubtitles.filter(s=>s.id>=Math.max(1,parseInt(tcTargetId,10)-1)&&s.id<=parseInt(tcTargetId,10)+1).map((s,i)=>(
                        <div key={i} style={{
                          background: s.id===parseInt(tcTargetId,10) ? '#fef3c7' : '#ffffff',
                          border: s.id===parseInt(tcTargetId,10) ? '1px solid #d9770640' : '1px solid #e2e8f0',
                          borderRadius:6, padding:'7px 11px', marginBottom:5, display:'flex', gap:10, alignItems:'center'
                        }}>
                          <span style={{fontFamily:'monospace', fontSize:10, color: s.id===parseInt(tcTargetId,10)?'#d97706':'#94a3b8', minWidth:30}}>#{s.id}</span>
                          <span style={{fontFamily:'monospace', fontSize:10, color: s.id===parseInt(tcTargetId,10)?'#d97706':'#4338ca', minWidth:210}}>
                            {s.start_time} → {s.end_time}
                          </span>
                          <span style={{fontSize:10, color: s.id===parseInt(tcTargetId,10)?'#b45309':'#64748b', flex:1}}>{s.text?.substring(0,60)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}

              {activeTcSubtitles.length > 0 && (
                <div style={{background:'#e0e7ff', border:'1px solid #4338ca30', borderRadius:8, padding:'8px 14px', fontSize:11, color:'#6366f1', marginBottom:12}}>
                  📊 {activeTcSubtitles.length} subtitles · First: <span style={{fontFamily:'monospace'}}>{activeTcSubtitles.find(s=>s.start_time)?.start_time||'—'}</span> · Last: <span style={{fontFamily:'monospace'}}>{[...activeTcSubtitles].reverse().find(s=>s.end_time)?.end_time||'—'}</span>
                </div>
              )}
              {!activeTcSubtitles.length && (
                <div style={{background:'#eef2ff', border:'1px solid #4338ca30', borderRadius:8, padding:'10px 14px', fontSize:11, color:'#64748b', marginBottom:12}}>
                  ⚠️ No subtitles loaded. Go to <strong style={{color:'#6366f1'}}>Clean</strong> or <strong style={{color:'#6366f1'}}>Transcribe</strong> tab first.
                </div>
              )}

              {(() => {
                const disabled = tcAdjusting || !activeTcSubtitles.length ||
                  (tcMode==='offset' && !tcValue.trim()) ||
                  (tcMode==='edit_single' && (
                    !tcTargetId.trim() || !tcValue.trim() ||
                    (tcShiftMode==='only_this' && !tcEndValue.trim()) ||
                    (tcShiftMode==='range' && !tcRangeEndId.trim())
                  ))
                const label = tcAdjusting ? 'Applying...'
                  : tcMode==='offset' ? '⏱️ Shift All Subtitles'
                  : tcShiftMode==='ripple' ? '🔁 Apply Ripple Shift'
                  : tcShiftMode==='range' ? '📐 Apply Ripple to Stopping Point'
                  : '📌 Update This Line Only'
                return (
                  <button style={{...S.btnPrimary, ...(disabled?S.btnOff:{})}} onClick={handleAdjustTimecodes} disabled={disabled}>
                    {label}
                  </button>
                )
              })()}

              {tcSuccess && <div style={{marginTop:12, background: tcCollision?'#fef3c7':'#ecfdf5', border:`1px solid ${tcCollision?'#d9770630':'#05966930'}`, borderRadius:8, padding:'10px 14px', fontSize:12, color: tcCollision?'#d97706':'#059669'}}>{tcSuccess}</div>}
              {tcSuccess && activeTcSubtitles.length > 0 && (
                <button style={{...S.btnOutline,marginTop:8,width:'100%'}} onClick={exportAdjustedSRT}>Download adjusted SRT</button>
              )}
              {tcCollision && (
                <div style={{marginTop:8, background:'#fef2f2', border:'1px solid #dc262640', borderRadius:8, padding:'10px 14px', fontSize:11, color:'#dc2626'}}>
                  ⚠️ <strong>Collision Warning:</strong> {tcCollision}
                  <div style={{marginTop:6, color:'#64748b', fontSize:10}}>The subtitle was updated anyway. Use Ripple Shift to avoid collisions, or manually adjust the neighboring subtitle.</div>
                </div>
              )}
              {tcError && <div style={{...S.errBox, marginTop:12}}><div style={{fontSize:12,color:'#dc2626'}}>{tcError}</div></div>}
            </div>

            <div className='card' style={{...S.card, background:'#fafbff', position:'sticky', top:20}}>
              <div style={{fontSize:13, fontWeight:700, marginBottom:10, color:'#334155'}}>ℹ️ What does this section do?</div>
              <div style={{fontSize:11, color:'#475569', lineHeight:1.7, marginBottom:14}}>
                Sometimes a subtitle's timecode doesn't quite line up with the actual video — the line shows a second too early, or a whole stretch of dialogue drifts out of sync because the original script was timed against a slightly different cut of the footage. This tool lets you correct those timecodes by hand, directly on the text, without needing to touch the video file at all.
              </div>

              <div style={{fontSize:11, fontWeight:700, color:'#334155', marginBottom:6}}>The three ways to fix a line:</div>
              <div style={{fontSize:11, color:'#475569', lineHeight:1.6, marginBottom:10}}>
                <span style={{color:'#d97706', fontWeight:700}}>🔁 Ripple to End</span> — one line is wrong, and so is everything after it. Fixing line 50 also fixes 51, 52, 53... all the way to the last line, by the same amount.
              </div>
              <div style={{fontSize:11, color:'#475569', lineHeight:1.6, marginBottom:10}}>
                <span style={{color:'#0ea5e9', fontWeight:700}}>📐 Ripple to a Stopping Point</span> — only a <em>section</em> drifted, and it goes back to being correct later on. For example lines 50 through 80 are off, but 81 onward already lines up fine. Fixing line 50 with a stopping point of 80 corrects exactly that stretch and leaves 81+ exactly as it was.
              </div>
              <div style={{fontSize:11, color:'#475569', lineHeight:1.6, marginBottom:14}}>
                <span style={{color:'#dc2626', fontWeight:700}}>📌 This Line Only</span> — just one single line is wrong, a one-off mistake, not a sign that anything after it drifted too. Nothing else in the file changes.
              </div>

              <div style={{fontSize:11, fontWeight:700, color:'#334155', marginBottom:6}}>± Shift All Subtitles</div>
              <div style={{fontSize:11, color:'#475569', lineHeight:1.6, marginBottom:14}}>
                Use this instead of the three options above when the <em>entire file</em> is off by the same amount from the very first line — e.g. the whole thing is consistently 2 seconds early. One offset value moves every single subtitle by the same amount.
              </div>

              <div style={{borderTop:'1px solid #e2e8f0', paddingTop:12}}>
                <div style={{fontSize:10, color:'#94a3b8', lineHeight:1.6}}>
                  <strong>Tip:</strong> "Subtitle #" refers to the line number shown next to each subtitle, not a video timestamp. Type that number in and the current timecodes for that line load automatically, so you can see exactly what you're changing before you apply it.
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ══ QUALITY CHECK TAB ══ */}
        {tab === 'movie_hub' && (
          <div style={S.twoCol}>
            <div style={S.left}>
              <div className='card' style={S.card}>
                <div style={{fontSize:18,fontWeight:700,color:'#0f172a',marginBottom:5}}>Movie Hub</div>
                <div style={{fontSize:11,color:'#64748b',lineHeight:1.6,marginBottom:18}}>
                  Keep shared screening and reference links in one place for the subtitle team.
                </div>
                <div style={S.label}>Add a movie or reference</div>
                <input style={{...S.input,marginBottom:10}} placeholder='Title' value={newMovie.title}
                  onChange={e=>setNewMovie({...newMovie,title:e.target.value})}/>
                <input style={{...S.input,marginBottom:10}} placeholder='https://example.com/movie' value={newMovie.url}
                  onChange={e=>setNewMovie({...newMovie,url:e.target.value})}/>
                <input style={{...S.input,marginBottom:12}} placeholder='Added by (optional)' value={newMovie.added_by}
                  onChange={e=>setNewMovie({...newMovie,added_by:e.target.value})}/>
                <button style={S.btnPrimary} onClick={handleAddMovie}>Add to Movie Hub</button>
                {movieMsg && <div style={{marginTop:12,padding:'9px 12px',background:'#ecfdf5',border:'1px solid #05966930',borderRadius:8,fontSize:12,color:'#059669'}}>{movieMsg}</div>}
                {movieErr && <div style={{...S.errBox,marginTop:12}}>{movieErr}</div>}
              </div>
            </div>

            <div style={S.right}>
              <div className='card' style={S.card}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:14}}>
                  <div style={S.label}>Shared links ({movies.length})</div>
                  <button style={S.btnSm} onClick={loadMovies}>Refresh</button>
                </div>
                {movies.length === 0 ? (
                  <div style={{...S.empty,padding:32}}>
                    <div style={{fontSize:16,fontWeight:700,color:'#334155',marginBottom:6}}>No movies added yet</div>
                    <div style={{fontSize:11,color:'#64748b'}}>Use the form to add the first shared link.</div>
                  </div>
                ) : movies.map(movie => (
                  <a key={movie.id || `${movie.title}-${movie.url}`} href={/^https?:\/\//i.test(movie.url || '') ? movie.url : '#'} target='_blank' rel='noreferrer'
                    style={{display:'block',textDecoration:'none',border:'1px solid #e2e8f0',borderRadius:10,padding:'12px 14px',marginBottom:9,background:'#f8fafc'}}>
                    <div style={{fontSize:13,fontWeight:700,color:'#0f172a',marginBottom:4}}>{movie.title}</div>
                    <div style={{fontSize:10,color:'#6366f1',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{movie.url}</div>
                    <div style={{fontSize:10,color:'#94a3b8',marginTop:6}}>Added by {movie.added_by || 'Anonymous'}</div>
                  </a>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === 'quality' && (
          <div style={S.twoCol}>
            <div style={S.left}>
              <div className='card' style={S.card}>
                <div style={S.label}>Platform to Check Against</div>
                <select style={S.select} value={qcPlatform} onChange={e=>{setQcPlatform(e.target.value);setQcResult(null);setQcError('')}}>
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

              <div className='card' style={S.card}>
                <div style={S.label}>Upload File to Check (or use cleaned file from Clean tab)</div>
                {(qcSubtitles.length > 0 || subtitles.length > 0) && !qcFile && (
                  <div style={{background:'#ecfdf5',border:'1px solid #05966930',borderRadius:8,padding:'10px 14px',fontSize:12,color:'#059669',marginBottom:12}}>
                    ✅ Will use {qcSubtitles.length || subtitles.length} loaded lines
                  </div>
                )}
                {!qcFile ? (
                  <div className='uploadZone' style={{...S.uploadZone,...(qcDragOver?S.uploadDrag:{})}}
                    onDragOver={e=>{e.preventDefault();setQcDragOver(true)}}
                    onDragLeave={()=>setQcDragOver(false)}
                    onDrop={e=>{e.preventDefault();setQcDragOver(false);selectQcFile(e.dataTransfer.files[0])}}
                    onClick={()=>qcFileRef.current.click()}>
                    <div style={{fontSize:24,marginBottom:6}}>📋</div>
                    <div style={S.uploadTitle}>Upload a different file to check</div>
                    <div style={S.uploadSub}>SRT · TXT · DOC · any format</div>
                    <input ref={qcFileRef} type="file" hidden
                      accept=".srt,.vtt,.txt,.doc,.docx,.pdf,.rtf,.xml,.ttml,.dfxp,.xlsx,.xls,.csv,.json"
                      onChange={e=>qcFileRef.current.files[0]&&selectQcFile(qcFileRef.current.files[0])}/>
                  </div>
                ) : (
                  <div style={S.fileChip}>
                    <span style={{fontSize:18}}>📄</span>
                    <div style={{flex:1}}><div style={{fontSize:13,color:'#334155'}}>{qcFile.name}</div></div>
                    <button className='btn-x-hover icon-spin' style={S.btnX} onClick={clearQcFile}>✕</button>
                  </div>
                )}
              </div>

              <button style={{...S.btnPrimary,...(checking?S.btnOff:{})}} onClick={handleQualityCheck} disabled={checking}>
                {checking ? 'Running quality check...' : '✅ Run Quality Check'}
              </button>

              {qcError && <div style={S.errBox}><div style={{fontSize:12,color:'#dc2626'}}>{qcError}</div></div>}

              {qcResult && (
                <div className='card' style={S.card}>
                  <div style={S.label}>Result — Auto-fixes applied</div>
                  <div style={S.statsGrid}>
                    {[
                      ['Total Lines', qcResult.total_lines, '#6366f1'],
                      ['Errors', qcResult.error_count ?? qcResult.total_defects, (qcResult.error_count||0)===0?'#059669':'#dc2626'],
                      ['Warnings', qcResult.warning_count ?? 0, (qcResult.warning_count||0)===0?'#059669':'#6366f1'],
                      ['Info', qcResult.info_count ?? 0, '#2563eb'],
                    ].map(([l,v,c]) => (
                      <div key={l} style={S.statItem}>
                        <div style={{...S.statNum,color:c}}>{v}</div>
                        <div style={S.statLabel}>{l}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{marginTop:12,padding:'10px 14px',borderRadius:8,
                    background: qcResult.is_ready_for_delivery ? '#ecfdf5' : '#fef2f2',
                    border: `1px solid ${qcResult.is_ready_for_delivery ? '#05966930' : '#dc262630'}`,
                    fontSize:13,fontWeight:700,
                    color: qcResult.is_ready_for_delivery ? '#059669' : '#dc2626'
                  }}>
                    {qcResult.is_ready_for_delivery
                      ? '✅ File is ready for delivery — all critical issues auto-fixed'
                      : `❌ ${qcResult.error_count || qcResult.total_defects} error(s) need manual review before delivery`}
                  </div>
                  {qcResult.warning_count > 0 && (
                    <div style={{marginTop:8,padding:'8px 12px',borderRadius:8,background:'#eef2ff',border:'1px solid #6366f120',fontSize:11,color:'#6366f1'}}>
                      ⚠️ {qcResult.warning_count} warning(s) — acceptable for delivery but review when possible
                    </div>
                  )}
                  {qcResult.info_count > 0 && (
                    <div style={{marginTop:6,padding:'8px 12px',borderRadius:8,background:'#eff6ff',border:'1px solid #2563eb20',fontSize:11,color:'#2563eb'}}>
                      ℹ️ {qcResult.info_count} info note(s) — reading speed slightly above target, review if timing allows
                    </div>
                  )}
                  {qcResult.is_ready_for_delivery && qcSubtitles.length > 0 && (
                    <div style={{marginTop:10,display:'flex',gap:8}}>
                      <button style={{...S.btnPrimary,flex:1,fontSize:12,padding:'8px 12px'}} onClick={exportQcSRT}>⬇ Export SRT</button>
                      <button style={{...S.btnSecondary,flex:1,fontSize:12,padding:'8px 12px'}} onClick={exportQcTXT}>⬇ Export TXT</button>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div style={S.right}>
              {qcResult?.defects?.length > 0 ? (
                <div className='card' style={S.card}>
                  <div style={{fontSize:14,fontWeight:700,color: '#0f172a',marginBottom:12}}>
                    {(qcResult.error_count||0) > 0
                      ? `❌ ${qcResult.error_count} Error(s) — Must Fix Before Delivery`
                      : `⚠️ Warnings & Notes — File is Deliverable`}
                  </div>
                  <div style={{maxHeight:600,overflowY:'auto'}}>
                    {/* Errors first */}
                    {qcResult.defects.filter(d=>['critical','error'].includes(d.severity)).map((d,i) => (
                      <div key={`e${i}`} style={{background:SEVERITY_BG[d.severity]||'#f1f5f9',border:`1px solid ${SEVERITY_COLOR[d.severity]||'#cbd5e1'}30`,borderRadius:8,padding:'10px 14px',marginBottom:8,borderLeft:`3px solid ${SEVERITY_COLOR[d.severity]||'#4338ca'}`}}>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
                          <span style={{fontSize:10,fontWeight:700,padding:'2px 7px',borderRadius:20,background:SEVERITY_COLOR[d.severity]||'#4338ca',color: 'white'}}>{d.severity?.toUpperCase()}</span>
                          <span style={{fontSize:11,fontWeight:700,color:'#334155'}}>{d.type?.replace(/_/g,' ')}</span>
                          {d.line_id&&<span style={{fontSize:10,color:'#64748b',marginLeft:'auto'}}>Line {d.line_id}</span>}
                        </div>
                        <div style={{fontSize:12,color:'#334155',marginBottom:4,lineHeight:1.5}}>{d.description}</div>
                        {d.suggestion&&<div style={{fontSize:11,color:'#64748b',fontStyle:'italic'}}>→ {d.suggestion}</div>}
                        {d.text&&<div style={{marginTop:6,padding:'6px 10px',background:'#f8fafc',borderRadius:6,fontSize:11,color:'#64748b',fontFamily:'monospace'}}>{d.text.substring(0,100)}{d.text.length>100?'...':''}</div>}
                      </div>
                    ))}
                    {/* Warnings */}
                    {qcResult.defects.filter(d=>d.severity==='warning').length > 0 && (
                      <div style={{fontSize:11,fontWeight:700,color:'#6366f1',margin:'12px 0 8px',textTransform:'uppercase',letterSpacing:0.8}}>⚠ Warnings (acceptable for delivery)</div>
                    )}
                    {qcResult.defects.filter(d=>d.severity==='warning').map((d,i) => (
                      <div key={`w${i}`} style={{background:'#eef2ff',border:'1px solid #6366f120',borderRadius:8,padding:'8px 12px',marginBottom:6,borderLeft:'3px solid #6366f1'}}>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:3}}>
                          <span style={{fontSize:10,fontWeight:700,padding:'2px 6px',borderRadius:20,background:'#4338ca80',color:'#4338ca'}}>WARN</span>
                          <span style={{fontSize:10,color:'#334155'}}>{d.type?.replace(/_/g,' ')}</span>
                          {d.line_id&&<span style={{fontSize:10,color:'#64748b',marginLeft:'auto'}}>Line {d.line_id}</span>}
                        </div>
                        <div style={{fontSize:11,color:'#475569',lineHeight:1.4}}>{d.description}</div>
                      </div>
                    ))}
                    {/* Info */}
                    {qcResult.defects.filter(d=>d.severity==='info').length > 0 && (
                      <div style={{fontSize:11,fontWeight:700,color:'#2563eb',margin:'12px 0 8px',textTransform:'uppercase',letterSpacing:0.8}}>ℹ Info (no action needed)</div>
                    )}
                    {qcResult.defects.filter(d=>d.severity==='info').map((d,i) => (
                      <div key={`i${i}`} style={{background:'#eff6ff',border:'1px solid #2563eb15',borderRadius:8,padding:'8px 12px',marginBottom:6,borderLeft:'3px solid #2563eb40'}}>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:3}}>
                          <span style={{fontSize:10,color:'#2563eb'}}>{d.type?.replace(/_/g,' ')}</span>
                          {d.line_id&&<span style={{fontSize:10,color:'#64748b',marginLeft:'auto'}}>Line {d.line_id}</span>}
                        </div>
                        <div style={{fontSize:11,color:'#1e40af',lineHeight:1.4}}>{d.description}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : qcResult?.is_ready_for_delivery ? (
                <div style={{...S.empty,border:'1px solid #05966930',background:'#ecfdf5'}}>
                  <div style={{fontSize:48,marginBottom:14}}>🎉</div>
                  <div style={{fontSize:17,fontWeight:700,color:'#059669',marginBottom:8}}>No defects found!</div>
                  <div style={{fontSize:12,color:'#059669'}}>File is ready for delivery to {platforms[qcPlatform]?.name || qcPlatform}</div>
                </div>
              ) : (
                <div style={S.empty}>
                  <div style={{fontSize:48,marginBottom:14}}>🔍</div>
                  <div style={{fontSize:17,fontWeight:700,color:'#334155',marginBottom:8}}>Quality Check</div>
                  <div style={{fontSize:12,color:'#64748b',marginBottom:20}}>Checks your file against real OTT platform rules</div>
                  <div style={{textAlign:'left',maxWidth:360}}>
                    {['File naming convention (EHD_123456E_ENG.PAC)','Zero subtitle format and fields','Character limit per line per platform','Duration min/max per platform','Reading speed (CPS)','HOH and EMT element removal','Profanity replacement (fxxx, cxxx etc.)','Spacing and punctuation defects','Double spaces, trailing spaces','ALL CAPS usage'].map(c=>(
                      <div key={c} style={{fontSize:12,color:'#64748b',padding:'4px 0',borderBottom:'1px solid #e2e8f0'}}>✓ {c}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ══ PLATFORMS & GUIDELINES TAB ══ */}
        {tab === 'platforms' && (
          <div style={S.twoCol}>
            <div style={S.left}>
              <div className='card' style={S.card}>
                <div style={S.label}>🔎 Search Platform Rules</div>
                <div style={{fontSize:12,color:'#64748b',marginBottom:14}}>
                  Search across all platform rules, or filter by a specific platform.
                </div>
                <input
                  type='text' placeholder='Search a keyword, e.g. "duration" or "frame gap"'
                  value={searchKeyword} onChange={e=>setSearchKeyword(e.target.value)}
                  style={{...S.input, marginBottom:10}}
                />
                <select style={{...S.select, marginBottom:10}} value={searchPlatformFilter} onChange={e=>setSearchPlatformFilter(e.target.value)}>
                  <option value=''>All Platforms</option>
                  {Object.entries(platforms).map(([k,p]) => <option key={k} value={k}>{p.name||k}</option>)}
                </select>
                <div style={{display:'flex',gap:8, marginBottom: 16}}>
                  <button style={S.btnOutline} onClick={() => { setSearchKeyword(''); setSearchPlatformFilter(''); }}>Clear Filters</button>
                </div>
              </div>

              <div className='card' style={S.card}>
                <div style={S.label}>➕ Add Custom Platform</div>
                <div style={{fontSize:11,color:'#64748b',marginBottom:14}}>
                  Upload a document to extract quality check rules automatically.
                </div>
                <input style={S.input} placeholder="Platform Name (e.g. Netflix)" value={uniPlatform} onChange={e=>setUniPlatform(e.target.value)}/>
                <div style={{fontSize:11,color:'#64748b',marginBottom:6}}>Upload guidelines document</div>
                {!uniFile ? (
                  <div className='uploadZone' style={{...S.uploadZone,padding:14}} onClick={()=>document.getElementById('unified-gl-in').click()}>
                    <div style={{fontSize:11,color:'#64748b',marginBottom:6}}>PDF · DOC · TXT · XLSX</div>
                    <button style={S.btnOutline}>Upload Document</button>
                    <input id="unified-gl-in" type="file" hidden accept=".doc,.docx,.pdf,.txt,.rtf,.xls,.xlsx" onChange={e=>e.target.files[0]&&setUniFile(e.target.files[0])}/>
                  </div>
                ) : (
                  <div style={{...S.fileChip,marginBottom:10}}>
                    <span>📄</span><span style={{flex:1,fontSize:12}}>{uniFile.name}</span>
                    <button className='btn-x-hover icon-spin' style={S.btnX} onClick={()=>setUniFile(null)}>✕</button>
                  </div>
                )}
                
                <div style={{fontSize:11,color:'#64748b',marginBottom:6,marginTop:10}}>Or paste guidelines text</div>
                <textarea style={{...S.textarea, marginBottom:12}} placeholder="Paste guidelines text here..." value={uniText} onChange={e=>setUniText(e.target.value)} rows={4}/>

                <button style={{...S.btnPrimary,...(uniProcessing?S.btnOff:{})}} onClick={handleUnifiedProcess} disabled={uniProcessing}>
                  {uniProcessing ? 'AI Processing...' : '🚀 Generate QC Rules'}
                </button>
                {uniMsg&&<div style={{background:'#ecfdf5',border:'1px solid #05966930',borderRadius:8,padding:'10px 14px',fontSize:12,color:'#059669',marginTop:10}}>✅ {uniMsg}</div>}
                {uniErr&&<div style={{...S.errBox, marginTop: 10}}><div style={{fontSize:12,color:'#dc2626'}}>{uniErr}</div></div>}
              </div>
            </div>

            <div style={S.right}>
              <div className='card' style={S.card}>
                <div style={S.label}>Platform Rules</div>
                <div style={{fontSize:12,color:'#64748b',marginBottom:14}}>
                  Click any platform to edit its rules.
                </div>
                
                <div style={{display:'flex', flexDirection:'column', gap:10}}>
                  {Object.entries(platforms)
                    .filter(([k, p]) => {
                      if (searchPlatformFilter && k !== searchPlatformFilter) return false;
                      if (searchKeyword.trim()) {
                        const kw = searchKeyword.toLowerCase();
                        if ((p.name || k).toLowerCase().includes(kw)) return true;
                        if ((p.rules || []).some(r => r.toLowerCase().includes(kw))) return true;
                        return false;
                      }
                      return true;
                    })
                    .map(([k,p]) => {
                      const isCustom = k.startsWith('custom_');
                      const matchingRules = searchKeyword.trim() ? (p.rules || []).filter(r => r.toLowerCase().includes(searchKeyword.toLowerCase())) : [];
                      
                      return (
                        <div key={k} style={{background:'#f8fafc',border:'1px solid #cbd5e1',borderRadius:8,padding:'12px 14px',display:'flex',flexDirection:'column',gap:10,cursor:'pointer'}} onClick={()=>{setEditingPlatform({...p, platform_key: k});setEditRulesText((p.rules||[]).join('\n'))}}>
                          <div style={{display:'flex',alignItems:'flex-start',gap:10}}>
                            <div style={{flex:1}}>
                              <div style={{fontSize:13,fontWeight:700,color: '#0f172a',marginBottom:2}}>
                                {p.name||k} 
                                <span style={{fontSize:10,fontWeight:400,color:'#64748b',background:'#e2e8f0',padding:'2px 6px',borderRadius:4,marginLeft:6}}>{isCustom ? 'CUSTOM' : 'BUILT-IN'}</span>
                                {isCustom && p.created_at && <span style={{fontSize:10,fontWeight:400,color:'#94a3b8',marginLeft:6}}>{new Date(p.created_at).toLocaleDateString()}</span>}
                              </div>
                              <div style={{fontSize:11,color:'#64748b'}}>{p.max_chars_per_line} chars/line · {p.max_lines} lines · {(p.rules||[]).length} rules</div>
                            </div>
                            {isCustom && <button style={{background:'none',border:'none',cursor:'pointer',fontSize:16,color:'#64748b'}} onClick={(e)=>{e.stopPropagation();handleDeletePlatform(k)}}>🗑</button>}
                          </div>
                          {searchKeyword.trim() && matchingRules.length > 0 && (
                            <div style={{background:'#ffffff', border:'1px solid #e2e8f0', borderRadius: 6, padding: '8px 10px'}}>
                              <div style={{fontSize: 10, fontWeight: 700, color: '#6366f1', marginBottom: 4}}>Matching Rules:</div>
                              {matchingRules.slice(0, 3).map((r, i) => (
                                <div key={i} style={{fontSize: 11, color: '#334155', marginBottom: 2}}>• {r}</div>
                              ))}
                              {matchingRules.length > 3 && <div style={{fontSize: 10, color: '#64748b', marginTop: 2}}>+ {matchingRules.length - 3} more...</div>}
                            </div>
                          )}
                        </div>
                      );
                    })}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>


      {/* ══ EDIT PLATFORM MODAL ══ */}
      {editingPlatform && (
        <div style={{position:'fixed',top:0,left:0,right:0,bottom:0,background:'rgba(0,0,0,0.8)',display:'flex',alignItems:'center',justifyContent:'center',zIndex:999}} onClick={(e)=>{if(e.target===e.currentTarget)setEditingPlatform(null)}}>
          <div style={{background:'#ffffff',border:'1px solid #4338ca',borderRadius:12,padding:24,width:600,maxWidth:'90%',maxHeight:'90vh',display:'flex',flexDirection:'column'}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
              <div style={{fontSize:18,fontWeight:700}}>📝 Rules: {editingPlatform.name} <span style={{fontSize:11,fontWeight:400,color:'#64748b',background:'#f8fafc',padding:'2px 6px',borderRadius:4,marginLeft:8}}>{editingPlatform.is_custom?'CUSTOM':'BUILT-IN'}</span></div>
              <button style={{background:'none',border:'none',color:'#64748b',fontSize:20,cursor:'pointer'}} onClick={()=>setEditingPlatform(null)}>✕</button>
            </div>
            <div style={{fontSize:12,color:'#6366f1',marginBottom:16,lineHeight:1.4}}>
              Edit the exact rules used by the AI Quality Checker below. Each line is evaluated as a separate formatting rule. Changes apply immediately to future checks.
            </div>
            <textarea 
              style={{...S.textarea, flex:1, minHeight:350, fontFamily:'monospace', fontSize:13, lineHeight:1.6, borderColor:'#cbd5e1', background:'#ffffff'}} 
              value={editRulesText} 
              onChange={e=>setEditRulesText(e.target.value)} 
              spellCheck="false"
            />
            <div style={{display:'flex',alignItems:'center',gap:12,marginTop:16}}>
              <button style={{...S.btnPrimary, flex:1}} onClick={handleSaveRules}>💾 Save Rules</button>
            </div>
            {editPlatformMsg && <div style={{marginTop:12,background:'#ecfdf5',border:'1px solid #05966930',borderRadius:8,padding:'8px',color:'#059669',fontSize:12,textAlign:'center'}}>✅ {editPlatformMsg}</div>}
            {editPlatformErr && <div style={{marginTop:12,background:'#fef2f2',border:'1px solid #dc262630',borderRadius:8,padding:'8px',color:'#dc2626',fontSize:12,textAlign:'center'}}>❌ {editPlatformErr}</div>}
          </div>
        </div>
      )}

    </div>
  )
}

// ─── STYLES ──────────────────────────────────────────────────────

const S = {
  badge: { fontSize:11, fontWeight:600, padding:'2px 9px', borderRadius:20, background:'#dbeafe', color:'#1e40af' },
  root: { minHeight:'100vh', background:'#f8fafc', backgroundImage:'radial-gradient(circle at 50% -20%, #eef2ff 0%, #f8fafc 60%)', color:'#0f172a', fontFamily:"'Inter',system-ui,sans-serif", paddingBottom: 40 },
  header: { background:'rgba(255, 255, 255, 0.85)', backdropFilter:'blur(12px)', WebkitBackdropFilter:'blur(12px)', borderBottom:'1px solid rgba(226, 232, 240, 0.8)', padding:'16px 32px', display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', gap:10, position:'sticky', top:0, zIndex:100 },
  headerLeft: { display:'flex', alignItems:'center', gap:16 },
  logo: { width:46, height:46, background:'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)', borderRadius:12, display:'flex', alignItems:'center', justifyContent:'center', fontWeight:800, fontSize:22, color: 'white', boxShadow: '0 4px 14px 0 rgba(99,102,241,0.39)' },
  logoTitle: { fontSize:19, fontWeight:800, color: '#0f172a', letterSpacing: '-0.03em' },
  logoSub: { fontSize:12, color:'#64748b', marginTop:2, fontWeight:500, letterSpacing: '-0.01em' },
  tabs: { display:'flex', gap:6, flexWrap:'wrap', background:'#f1f5f9', padding:6, borderRadius:14, border:'1px solid #e2e8f0' },
  tab: { padding:'8px 16px', background:'transparent', border:'none', borderRadius:10, color:'#64748b', fontSize:13, fontWeight:600, cursor:'pointer', transition: 'all 0.2s ease' },
  tabActive: { background:'#ffffff', color:'#4f46e5', boxShadow:'0 2px 6px rgba(0,0,0,0.05)' },
  body: { padding:'32px 32px', maxWidth:1400, margin:'0 auto' },
  twoCol: { display:'grid', gridTemplateColumns:'400px 1fr', gap:32 },
  left: { display:'flex', flexDirection:'column', gap:24 },
  right: { display:'flex', flexDirection:'column', gap:24 },
  
  card: { background:'#ffffff', border:'1px solid rgba(226, 232, 240, 0.8)', borderRadius:20, padding:32, boxShadow:'0 10px 25px -5px rgba(0, 0, 0, 0.02), 0 8px 10px -6px rgba(0, 0, 0, 0.01)', transition: 'transform 0.3s ease, box-shadow 0.3s ease' },

  label: { fontSize:12, fontWeight:800, color:'#4f46e5', textTransform:'uppercase', letterSpacing:1.2, marginBottom:16, display: 'flex', alignItems: 'center', gap: 6 },
  select: { width:'100%', padding:'14px 16px', background:'#f8fafc', border:'1.5px solid #e2e8f0', borderRadius:12, color:'#0f172a', fontSize:14, fontWeight:600, cursor:'pointer', transition: 'all 0.2s ease', appearance: 'none', backgroundImage: 'url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 24 24\' fill=\'none\' stroke=\'%2364748b\' stroke-width=\'2\' stroke-linecap=\'round\' stroke-linejoin=\'round\'%3e%3cpolyline points=\'6 9 12 15 18 9\'%3e%3c/polyline%3e%3c/svg%3e")', backgroundRepeat: 'no-repeat', backgroundPosition: 'right 16px center', backgroundSize: '16px' },
  platformMeta: { display:'flex', gap:10, marginTop:16, fontSize:12, color:'#64748b', flexWrap:'wrap', background:'#f8fafc', padding:'12px 16px', borderRadius:10, border:'1px solid #e2e8f0', fontWeight: 500 },
  uploadZone: { border:'2px dashed #cbd5e1', borderRadius:16, padding:32, textAlign:'center', cursor:'pointer', background:'#f8fafc', transition:'all 0.3s ease', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', minHeight: 200 },
  uploadDrag: { borderColor:'#6366f1', background:'#eef2ff', transform:'scale(1.02)' },
  uploadTitle: { fontSize:16, fontWeight:700, color:'#1e293b', marginBottom:8, marginTop:16 },
  uploadSub: { fontSize:13, color:'#64748b', marginBottom:12, lineHeight: 1.5, maxWidth: '80%' },
  fileChip: { display:'flex', alignItems:'center', gap:16, background:'#ffffff', border:'1px solid #e2e8f0', borderRadius:14, padding:'16px 20px', boxShadow:'0 4px 12px rgba(0,0,0,0.03)' },
  btnX: { background:'#f1f5f9', border:'none', color:'#64748b', cursor:'pointer', fontSize:14, width:32, height:32, borderRadius:'50%', display:'flex', alignItems:'center', justifyContent:'center', transition:'all 0.2s ease' },
  btnPrimary: { width:'100%', padding:'14px 24px', background:'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)', border:'none', borderRadius:12, color: 'white', fontSize:15, fontWeight:700, cursor:'pointer', boxShadow:'0 4px 14px rgba(99, 102, 241, 0.25)', transition:'all 0.3s ease', display:'flex', alignItems:'center', justifyContent:'center', gap:8, letterSpacing: '0.01em' },
  btnOff: { opacity:0.6, cursor:'not-allowed', filter:'grayscale(0.6)', transform: 'none !important', boxShadow: 'none !important' },
  btnSm: { padding:'8px 16px', background:'#ffffff', border:'1px solid #e2e8f0', borderRadius:8, color:'#334155', fontSize:13, fontWeight:600, cursor:'pointer', transition:'all 0.2s ease', boxShadow:'0 1px 2px rgba(0,0,0,0.02)' },
  btnOutline: { padding:'14px 24px', background:'#ffffff', border:'1.5px solid #e2e8f0', borderRadius:12, color:'#475569', fontSize:15, fontWeight:700, cursor:'pointer', transition:'all 0.2s ease', display:'flex', alignItems:'center', justifyContent:'center', gap:8 },
  errBox: { background:'#fef2f2', border:'1px solid #fca5a5', borderRadius:12, padding:'16px 20px', display:'flex', alignItems:'flex-start', gap:12 },
  statsGrid: { background:'#f8fafc', border:'1px solid #e2e8f0', borderRadius:14, padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 },
  statItem: { background:'#ffffff', padding:'16px', borderRadius:10, boxShadow:'0 2px 6px rgba(0,0,0,0.02)', border:'1px solid #f1f5f9', textAlign:'center', display:'flex', flexDirection:'column', justifyContent:'center' },
  statNum: { fontSize:28, fontWeight:800, color:'#6366f1', marginBottom:6, letterSpacing:'-0.03em' },
  statLabel: { fontSize:11, color:'#64748b', textTransform:'uppercase', letterSpacing:0.8, fontWeight:700 },
  subList: { maxHeight:600, overflowY:'auto', border:'1px solid #e2e8f0', borderRadius:14, background:'#f8fafc', padding: 10 },
  subRow: { padding:'24px 32px', background:'#ffffff', border:'1px solid #e2e8f0', borderRadius:12, marginBottom:10, boxShadow:'0 1px 3px rgba(0,0,0,0.02)', transition: 'border-color 0.2s ease' },
  subFlagged: { background:'#fff1f2', border:'1px solid #fda4af' },
  timecode: { fontSize:13, color:'#6366f1', fontFamily:"'JetBrains Mono', Consolas, monospace", marginBottom:10, fontWeight:600, display:'inline-block', background:'#eef2ff', padding:'6px 10px', borderRadius:8 },
  subText: { fontSize:16, color:'#1e293b', lineHeight:1.7, outline:'none', padding:'8px 0', fontWeight: 400 },
  empty: { display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', minHeight:380, textAlign:'center', padding:40, background:'#ffffff', border:'2px dashed #cbd5e1', borderRadius:20, boxShadow:'0 4px 6px rgba(0,0,0,0.01)' },
  input: { width:'100%', padding:'14px 16px', background:'#ffffff', border:'1.5px solid #e2e8f0', borderRadius:12, color:'#0f172a', fontSize:14, marginBottom:12, outline:'none', transition:'all 0.2s ease', boxShadow:'0 1px 2px rgba(0,0,0,0.01)', fontWeight: 500 },
  textarea: { width:'100%', padding:'16px', background:'#ffffff', border:'1.5px solid #e2e8f0', borderRadius:12, color:'#0f172a', fontSize:14, resize:'vertical', fontFamily:"'JetBrains Mono', Consolas, monospace", outline:'none', transition:'all 0.2s ease', lineHeight:1.6 },
  progressContainer: { marginTop: 16, padding: 24, background: '#ffffff', borderRadius: 16, border: '1px solid #e2e8f0', boxShadow:'0 10px 15px -3px rgba(0,0,0,0.03)' },
  progressBarOuter: { width: '100%', height: 10, background: '#f1f5f9', borderRadius: 10, overflow: 'hidden', marginBottom: 16 },
  progressBarInner: { height: '100%', background: 'linear-gradient(90deg, #6366f1 0%, #a855f7 100%)', transition: 'width 0.4s cubic-bezier(0.4, 0, 0.2, 1)', borderRadius:10 },
  progressMeta: { display: 'flex', justifyContent: 'space-between', fontSize: 14, color: '#6366f1', fontWeight: 600 },
  progressMsg: { color: '#475569' },
  progressPct: { fontWeight: 800, color: '#4f46e5' },
}
