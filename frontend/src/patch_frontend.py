import re

with open(r"d:\Downloads\OTTWatchX\subtitleai-v2\subtitleai-v2\frontend\src\App.jsx", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Add states
states_str = """  const [trackChangesOpen, setTrackChangesOpen] = useState(false)
  const [trackChangesData, setTrackChangesData] = useState(null)
  const [trackChangesLoading, setTrackChangesLoading] = useState(false)
  const [trackChangesErr, setTrackChangesErr] = useState('')"""
if "setTrackChangesOpen" not in code:
    code = code.replace("const [platform, setPlatform] = useState('discovery_max')", "const [platform, setPlatform] = useState('discovery_max')\n" + states_str)

# 2. Add loadTrackChanges
load_func = """  async function loadTrackChanges() {
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

"""
if "loadTrackChanges" not in code:
    code = code.replace("async function exportTrackChangesPDF() {", load_func + "  async function exportTrackChangesPDF() {")

# 3. Add Export Buttons & View button
export_btn_target = """                    <div style={{display:'flex',gap:8,flexWrap:'wrap',marginTop:8}}>
                      <button style={S.btnSm} onClick={exportSRT}>⬇️ SRT</button>
                      <button style={S.btnSm} onClick={exportTXT}>⬇️ TXT</button>
                      <button style={S.btnSm} onClick={exportPDF}>⬇️ PDF</button>
                      <button style={S.btnSm} onClick={exportTrackChangesPDF}>📝 Track Changes PDF</button>
                    </div>"""
new_export = """                    <div style={{display:'flex',gap:8,flexWrap:'wrap',marginTop:8}}>
                      <button style={{...S.btnSm,background:'#eef2ff',borderColor:'#6366f1',color:'#4338ca'}}
                        onClick={loadTrackChanges} disabled={trackChangesLoading}>
                        {trackChangesLoading ? 'Loading...' : '👁️ View Track Changes'}
                      </button>
                      <button style={S.btnSm} onClick={exportSRT}>⬇️ SRT</button>
                      <button style={S.btnSm} onClick={exportTXT}>⬇️ TXT</button>
                      <button style={S.btnSm} onClick={exportPDF}>⬇️ PDF</button>
                      <button style={S.btnSm} onClick={exportTrackChangesPDF}>📝 Track Changes PDF</button>
                    </div>
                    {trackChangesErr && <div style={{...S.errBox, marginTop:8}}>{trackChangesErr}</div>}"""
if "👁️ View Track Changes" not in code:
    code = code.replace(export_btn_target, new_export)

# 4. Add the modal UI before Movie Hub
modal_ui = """      {/* ══ TRACK CHANGES MODAL — on-screen view, see before you download ══ */}
      {trackChangesOpen && trackChangesData && (
        <div style={{position:'fixed',top:0,left:0,right:0,bottom:0,background:'rgba(0,0,0,0.8)',display:'flex',alignItems:'center',justifyContent:'center',zIndex:999}}
          onClick={(e)=>{if(e.target===e.currentTarget) setTrackChangesOpen(false)}}>
          <div style={{background:'#ffffff',border:'1px solid #4338ca',borderRadius:12,padding:24,width:760,maxWidth:'92%',maxHeight:'88vh',display:'flex',flexDirection:'column'}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:6}}>
              <div style={{fontSize:18,fontWeight:700}}>📝 Track Changes — {trackChangesData.platform}</div>
              <button style={{background:'none',border:'none',color:'#64748b',fontSize:20,cursor:'pointer'}} onClick={()=>setTrackChangesOpen(false)}>✕</button>
            </div>
            <div style={{fontSize:12,color:'#64748b',marginBottom:16}}>
              {trackChangesData.changed_lines} of {trackChangesData.total_lines} lines were changed during cleaning · {trackChangesData.unchanged_lines} needed no changes
            </div>

            <div style={{overflowY:'auto',flex:1,paddingRight:6}}>
              {trackChangesData.changes.length === 0 ? (
                <div style={{textAlign:'center',color:'#64748b',padding:40}}>
                  No changes were made — every line was already clean.
                </div>
              ) : (
                trackChangesData.changes.map(c => (
                  <div key={c.id} style={{border:'1px solid #e2e8f0',borderRadius:10,padding:14,marginBottom:10,
                    background: c.flagged ? '#fff1f2' : '#f8fafc'}}>
                    <div style={{fontSize:11,color:'#94a3b8',marginBottom:6,fontWeight:600}}>Line {c.id}</div>
                    <div style={{fontSize:13,color:'#d97706',marginBottom:4}}>
                      <b>Previously:</b> {c.original_text}
                    </div>
                    <div style={{fontSize:14,color:'#059669',marginBottom:8}}>
                      <b>Cleaned:</b> {c.new_text}
                    </div>
                    <div style={{fontSize:11,color:'#64748b'}}>
                      {c.rules_applied.map((r,i) => <div key={i}>• {r}</div>)}
                    </div>
                    {c.flagged && (
                      <div style={{fontSize:11,color:'#dc2626',marginTop:6,fontWeight:600}}>⚠ {c.flag_reason}</div>
                    )}
                  </div>
                ))
              )}
            </div>

            <div style={{display:'flex',gap:10,marginTop:16}}>
              <button style={{...S.btnPrimary, flex:1}} onClick={exportTrackChangesPDF}>⬇️ Download Full Report (PDF)</button>
              <button style={{...S.btnOutline}} onClick={()=>setTrackChangesOpen(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
"""
if "TRACK CHANGES MODAL" not in code:
    code = code.replace("{/* ══ MOVIE HUB TAB ══ */}", modal_ui + "\n      {/* ══ MOVIE HUB TAB ══ */}")

with open(r"d:\Downloads\OTTWatchX\subtitleai-v2\subtitleai-v2\frontend\src\App.jsx", "w", encoding="utf-8") as f:
    f.write(code)

print("Frontend patched.")
