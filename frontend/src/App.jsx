import { useState, useEffect, useRef } from 'react'
import axios from 'axios'

const API = '/api'

const SEVERITY_COLOR = { critical: '#ef4444', error: '#f59e0b', warning: '#a78bfa' }
const SEVERITY_BG = { critical: '#2a0f0f', error: '#2a1f0f', warning: '#1a1535' }

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

  // Transcribe tab
  const [audioFile, setAudioFile] = useState(null)
  const [recording, setRecording] = useState(false)
  const [mediaRecorder, setMediaRecorder] = useState(null)
  const [transcribing, setTranscribing] = useState(false)
  const [transcribeError, setTranscribeError] = useState('')

  useEffect(() => { loadPlatforms() }, [])

  async function loadPlatforms() {
    try {
      const r = await axios.get(`${API}/platforms`)
      setPlatforms(r.data.platforms || {})
    } catch {}
  }

  // ── CLEAN ──────────────────────────────────────────────────────

  async function handleExtract() {
    if (!file) { setCleanError('Please upload a file first'); return }
    setExtracting(true); setCleanError(''); setCleanStats(null); setSubtitles([]); setCleanProgress(0)
    setCleanText('Extracting file...')
    const fd = new FormData()
    fd.append('file', file)
    try {
      const response = await axios.post(`${API}/extract`, fd)
      setSubtitles(response.data.subtitles || [])
      setCleanStats(response.data.stats || null)
      setCleanProgress(100)
      setCleanText('Extraction complete!')
    } catch (e) {
      setCleanError(e.response?.data?.detail || 'Extraction failed')
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

      // If a separate file uploaded for QC — use /extract (returns JSON, not SSE)
      if (qcFile) {
        const fd = new FormData()
        fd.append('file', qcFile)
        fd.append('platform', platform)
        const extractR = await axios.post(`${API}/extract`, fd)
        subs = extractR.data.subtitles || []
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
      if (r.data.subtitles?.length && !qcFile) setSubtitles(r.data.subtitles)
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

  async function handleTranscribe() {
    if (!audioFile) { setTranscribeError('Please upload or record audio first'); return }
    setTranscribing(true); setTranscribeError(''); setSubtitles([]); setCleanStats(null);
    const fd = new FormData()
    fd.append('file', audioFile)
    try {
      const response = await axios.post(`${API}/transcribe`, fd)
      setSubtitles(response.data.subtitles || [])
      setCleanStats(response.data.stats || null)
      setTab('clean') // Auto-switch to view the extracted subtitles
    } catch (e) {
      setTranscribeError(e.response?.data?.detail || 'Transcription failed')
    } finally { setTranscribing(false) }
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
          {[['clean','🧹 Clean'],['transcribe','🎙️ Transcribe'],['quality','✅ Quality Check'],['platforms','⚙️ Platforms']].map(([id,label]) => (
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
                          onBlur={e=>{const u=[...subtitles];u[i]={...u[i],text:e.target.textContent};setSubtitles(u)}}>
                          {sub.text}
                        </div>
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
          <div style={{maxWidth:600, margin:'0 auto'}}>
            <div style={S.card}>
              <div style={{fontSize:18, fontWeight:700, marginBottom:20, textAlign:'center'}}>🎙️ AI Audio / Video Transcription</div>
              <div style={{fontSize:12, color:'#a78bfa', marginBottom:20, textAlign:'center'}}>Powered by Groq Whisper-Large-v3. Automatically generates frame-accurate SRT.</div>
              
              <div style={{display:'flex', gap:10, marginBottom:20}}>
                <div style={{flex:1, ...S.uploadZone}} onClick={()=>document.getElementById('audio-upload').click()}>
                  <div style={{fontSize:24, marginBottom:6}}>📁</div>
                  <div style={S.uploadTitle}>Upload Audio/Video</div>
                  <div style={S.uploadSub}>MP3, MP4, M4A, WAV, WEBM</div>
                  <input id="audio-upload" type="file" hidden accept="audio/*,video/*" onChange={e=>{if(e.target.files[0])setAudioFile(e.target.files[0])}}/>
                </div>
                
                <div style={{flex:1, ...S.uploadZone, borderColor: recording ? '#ef4444' : '#2a2a3e', background: recording ? '#2a0f0f' : '#08080f'}} 
                     onClick={recording ? stopRecording : startRecording}>
                  <div style={{fontSize:24, marginBottom:6}}>{recording ? '🛑' : '🎤'}</div>
                  <div style={S.uploadTitle}>{recording ? 'Stop Recording' : 'Live Record'}</div>
                  <div style={S.uploadSub}>{recording ? 'Recording in progress...' : 'Use your microphone'}</div>
                </div>
              </div>

              {audioFile && (
                <div style={{...S.fileChip, marginBottom:20}}>
                  <span style={{fontSize:18}}>🎵</span>
                  <div style={{flex:1}}>
                    <div style={{fontSize:13,color:'#c8c6d4'}}>{audioFile.name}</div>
                    <div style={{fontSize:10,color:'#5a5870'}}>{(audioFile.size/1024/1024).toFixed(2)} MB</div>
                  </div>
                  <button style={S.btnX} onClick={()=>setAudioFile(null)}>✕</button>
                </div>
              )}

              <button style={{...S.btnPrimary, ...(transcribing || !audioFile ? S.btnOff : {})}} onClick={handleTranscribe} disabled={transcribing || !audioFile}>
                {transcribing ? '⏳ Transcribing...' : '✨ Transcribe to SRT'}
              </button>

              {transcribeError && <div style={{...S.errBox, marginTop:20}}><div style={{fontSize:12,color:'#fca5a5'}}>{transcribeError}</div></div>}
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
                  <div style={S.label}>Result</div>
                  <div style={S.statsGrid}>
                    {[
                      ['Total Lines', qcResult.total_lines, '#a78bfa'],
                      ['Defects Found', qcResult.total_defects, qcResult.total_defects===0?'#34d399':'#ef4444'],
                      ['Lines Affected', qcResult.defect_lines, qcResult.defect_lines===0?'#34d399':'#fbbf24'],
                      ['Clean Lines', qcResult.clean_lines, '#34d399'],
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
                    {qcResult.is_ready_for_delivery ? '✅ File is ready for delivery to OTT platform' : '❌ File has defects — fix before delivery'}
                  </div>
                </div>
              )}
            </div>

            <div style={S.right}>
              {qcResult?.defects?.length > 0 ? (
                <div style={S.card}>
                  <div style={{fontSize:14,fontWeight:700,color:'#fff',marginBottom:12}}>Defects Found — Fix Before Delivery</div>
                  <div style={{maxHeight:600,overflowY:'auto'}}>
                    {qcResult.defects.map((d,i) => (
                      <div key={i} style={{background:SEVERITY_BG[d.severity]||'#13131f',border:`1px solid ${SEVERITY_COLOR[d.severity]||'#2a2a3e'}30`,borderRadius:8,padding:'10px 14px',marginBottom:8,borderLeft:`3px solid ${SEVERITY_COLOR[d.severity]||'#7c3aed'}`}}>
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
                    <div key={k} style={{background:'#13131f',border:'1px solid #1e1e2e',borderRadius:8,padding:'12px 14px',marginBottom:8,display:'flex',alignItems:'flex-start',gap:10}}>
                      <div style={{flex:1}}>
                        <div style={{fontSize:13,fontWeight:700,color:'#fff',marginBottom:2}}>{p.name||k}</div>
                        <div style={{fontSize:11,color:'#5a5870'}}>{p.max_chars_per_line} chars/line · {p.max_lines} lines · {(p.rules||[]).length} rules</div>
                      </div>
                      <button style={{background:'none',border:'none',cursor:'pointer',fontSize:16,color:'#5a5870'}} onClick={()=>handleDeletePlatform(k)}>🗑</button>
                    </div>
                  ))}
                </div>
              )}

              <div style={S.card}>
                <div style={S.label}>Built-in Platforms (from OTT Clients Protocol)</div>
                <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
                  {builtinPlatforms.map(([k,p]) => (
                    <div key={k} style={{background:'#13131f',border:'1px solid #1e1e2e',borderRadius:8,padding:'10px 12px'}}>
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
