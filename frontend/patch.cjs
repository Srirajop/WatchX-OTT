const fs = require('fs');
let code = fs.readFileSync('src/App.jsx', 'utf8');

// Replace bulk import state
code = code.replace(
    /\/\/ Bulk import \(digitize a whole guidelines document\)[\s\S]*?const \[platform, setPlatform\]/,
    `// Unified Platform & Guidelines Form
  const [uniClient, setUniClient] = useState('')
  const [uniPlatform, setUniPlatform] = useState('')
  const [uniYear, setUniYear] = useState(new Date().getFullYear())
  const [uniFile, setUniFile] = useState(null)
  const [uniText, setUniText] = useState('')
  const [uniDoRules, setUniDoRules] = useState(true)
  const [uniDoLib, setUniDoLib] = useState(true)
  const [uniProcessing, setUniProcessing] = useState(false)
  const [uniMsg, setUniMsg] = useState('')
  const [uniErr, setUniErr] = useState('')
  const [platform, setPlatform]`
);

// Replace old platform state
code = code.replace(
    /\/\/ Platforms tab[\s\S]*?const \[editingPlatform, setEditingPlatform\] = useState\(null\)/,
    `// Platforms tab
  const [editingPlatform, setEditingPlatform] = useState(null)`
);

// Replace handleAddPlatform with handleUnifiedProcess
code = code.replace(
    /async function handleAddPlatform\(\) \{[\s\S]*?finally \{ setAdding\(false\) \}\r?\n  \}/,
    `async function handleUnifiedProcess() {
    setUniErr(''); setUniMsg('')
    if (!uniPlatform.trim()) {
      setUniErr('OTT Platform Name is required.')
      return
    }
    if (uniDoLib && !uniClient.trim()) {
      setUniErr('Client is required to add to the Guideline Library.')
      return
    }
    if (!uniFile && !uniText.trim()) {
      setUniErr('Upload a guidelines file or paste the guideline text.')
      return
    }
    if (!uniDoRules && !uniDoLib) {
      setUniErr('Please select at least one action (Generate Rules or Add to Library).')
      return
    }

    setUniProcessing(true)
    try {
      let rulesMsg = '';
      let libMsg = '';
      
      if (uniDoRules) {
        const fdRules = new FormData()
        fdRules.append('platform_name', uniPlatform)
        if (uniFile) fdRules.append('guidelines_file', uniFile)
        if (uniText.trim()) fdRules.append('guidelines_text', uniText.trim())
        const rRules = await axios.post(\`/api/platforms/add\`, fdRules)
        rulesMsg = rRules.data.message || 'Platform rules generated.'
        await loadPlatforms()
      }

      if (uniDoLib) {
        const fdLib = new FormData()
        fdLib.append('client', uniClient)
        fdLib.append('ott_platform', uniPlatform)
        fdLib.append('year', uniYear)
        if (uniFile) fdLib.append('guidelines_file', uniFile)
        if (uniText.trim()) fdLib.append('guidelines_text', uniText.trim())
        const rLib = await axios.post(\`/api/guidelines/bulk-import\`, fdLib)
        libMsg = \`Digitized \${rLib.data.entries_added} library entries.\`
        await loadGuidelineFilters()
        searchGuidelines()
      }

      setUniMsg([rulesMsg, libMsg].filter(Boolean).join(' | '))
      setUniFile(null); setUniText('')
    } catch (e) {
      setUniErr(e.response?.data?.detail || 'Processing failed.')
    } finally {
      setUniProcessing(false)
    }
  }`
);

// Replace runBulkImport
code = code.replace(
    /async function runBulkImport\(\) \{[\s\S]*?finally \{ setGlImporting\(false\) \}\r?\n  \}/,
    ''
);

// Replace UI
code = code.replace(
    /\{\/\* ══ PLATFORMS TAB ══ \*\/\}[\s\S]*?\{\/\* ══ TRACK CHANGES MODAL — on-screen view, see before you download ══ \*\/\}/,
    `{/* ══ PLATFORMS & GUIDELINES TAB ══ */}
        {tab === 'platforms' && (
          <div style={S.twoCol}>
            <div style={S.left}>
              <div className='card' style={S.card}>
                <div style={S.label}>➕ Add Platform & Digitize Guidelines</div>
                <div style={{fontSize:11,color:'#64748b',marginBottom:14}}>
                  Upload a document to extract quality check rules, populate the searchable guideline library, or both simultaneously.
                </div>
                
                <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10,marginBottom:10}}>
                  <input style={S.input} placeholder="Client (e.g. Deluxe)" value={uniClient} onChange={e=>setUniClient(e.target.value)}/>
                  <input style={S.input} placeholder="OTT Platform (e.g. Netflix)" value={uniPlatform} onChange={e=>setUniPlatform(e.target.value)}/>
                </div>
                <input style={{...S.input,marginBottom:12}} type="number" placeholder="Year" value={uniYear} onChange={e=>setUniYear(e.target.value)}/>

                <div style={{fontSize:11,color:'#64748b',marginBottom:6}}>Upload guidelines document</div>
                {!uniFile ? (
                  <div className='uploadZone' style={{...S.uploadZone,padding:14}} onClick={()=>document.getElementById('unified-gl-in').click()}>
                    <div style={{fontSize:11,color:'#64748b',marginBottom:6}}>PDF · DOC · TXT</div>
                    <button style={S.btnOutline}>Upload Document</button>
                    <input id="unified-gl-in" type="file" hidden accept=".doc,.docx,.pdf,.txt,.rtf" onChange={e=>e.target.files[0]&&setUniFile(e.target.files[0])}/>
                  </div>
                ) : (
                  <div style={{...S.fileChip,marginBottom:10}}>
                    <span>📄</span><span style={{flex:1,fontSize:12}}>{uniFile.name}</span>
                    <button className='btn-x-hover icon-spin' style={S.btnX} onClick={()=>setUniFile(null)}>✕</button>
                  </div>
                )}
                
                <div style={{fontSize:11,color:'#64748b',marginBottom:6,marginTop:10}}>Or paste guidelines text</div>
                <textarea style={{...S.textarea, marginBottom:12}} placeholder="Paste guidelines text here..." value={uniText} onChange={e=>setUniText(e.target.value)} rows={4}/>

                <div style={{display:'flex', gap: 16, marginBottom: 16, padding: '10px 14px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0', flexWrap: 'wrap'}}>
                  <label style={{display:'flex', alignItems:'center', gap:6, fontSize:12, color:'#334155', cursor:'pointer', fontWeight: 600}}>
                    <input type="checkbox" checked={uniDoRules} onChange={e=>setUniDoRules(e.target.checked)} style={{width: 16, height: 16}}/>
                    Generate QC Rules
                  </label>
                  <label style={{display:'flex', alignItems:'center', gap:6, fontSize:12, color:'#334155', cursor:'pointer', fontWeight: 600}}>
                    <input type="checkbox" checked={uniDoLib} onChange={e=>setUniDoLib(e.target.checked)} style={{width: 16, height: 16}}/>
                    Add to Library
                  </label>
                </div>

                <button style={{...S.btnPrimary,...(uniProcessing?S.btnOff:{})}} onClick={handleUnifiedProcess} disabled={uniProcessing}>
                  {uniProcessing ? 'AI Processing...' : '🚀 Process Guidelines'}
                </button>
                {uniMsg&&<div style={{background:'#ecfdf5',border:'1px solid #05966930',borderRadius:8,padding:'10px 14px',fontSize:12,color:'#059669',marginTop:10}}>✅ {uniMsg}</div>}
                {uniErr&&<div style={{...S.errBox, marginTop: 10}}><div style={{fontSize:12,color:'#dc2626'}}>{uniErr}</div></div>}
              </div>

              <div className='card' style={S.card}>
                <div style={S.label}>🔎 Search OTT Guidelines Library</div>
                <div style={{fontSize:12,color:'#64748b',marginBottom:14}}>
                  Search specific rules from previously digitized guidelines.
                </div>

                <input
                  type='text' placeholder='Search a keyword, e.g. "duration" or "frame gap"'
                  value={glKeyword} onChange={e=>setGlKeyword(e.target.value)}
                  onKeyDown={e=>{if(e.key==='Enter') searchGuidelines()}}
                  style={{...S.input, marginBottom:10}}
                />

                <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8,marginBottom:10}}>
                  <select style={S.select} value={glClientFilter} onChange={e=>setGlClientFilter(e.target.value)}>
                    <option value=''>All Clients</option>
                    {glFilterOptions.clients.map(c=> <option key={c} value={c}>{c}</option>)}
                  </select>
                  <select style={S.select} value={glPlatformFilter} onChange={e=>setGlPlatformFilter(e.target.value)}>
                    <option value=''>All Platforms</option>
                    {glFilterOptions.ott_platforms.map(p=> <option key={p} value={p}>{p}</option>)}
                  </select>
                  <select style={S.select} value={glCategoryFilter} onChange={e=>setGlCategoryFilter(e.target.value)}>
                    <option value=''>All Categories</option>
                    {glFilterOptions.categories.map(c=> <option key={c} value={c}>{c}</option>)}
                  </select>
                  <select style={S.select} value={glYearFilter} onChange={e=>setGlYearFilter(e.target.value)}>
                    <option value=''>All Years</option>
                    {glFilterOptions.years.map(y=> <option key={y} value={y}>{y}</option>)}
                  </select>
                </div>

                <div style={{display:'flex',gap:8, marginBottom: 16}}>
                  <button style={{...S.btnPrimary,flex:1}} onClick={searchGuidelines} disabled={glSearching}>
                    {glSearching ? 'Searching...' : '🔎 Search'}
                  </button>
                  <button style={S.btnOutline} onClick={clearGuidelineFilters}>Clear</button>
                </div>

                <button style={{...S.btnOutline, width:'100%'}} onClick={openAddGuidelineForm}>➕ Add Single Guideline Manually</button>

                {glErr && <div style={{...S.errBox, marginTop:12}}>{glErr}</div>}
              </div>
            </div>

            <div style={S.right}>
              <div className='card' style={S.card}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'baseline',marginBottom:12}}>
                  <div style={S.label}>Library Search Results</div>
                  <div style={{fontSize:12,color:'#64748b'}}>{glResults.length} match{glResults.length===1?'':'es'}</div>
                </div>

                {glResults.length === 0 ? (
                  <div style={{textAlign:'center',color:'#94a3b8',padding:40}}>
                    {glSearching ? 'Searching...' : 'No results yet — try a keyword or pick a filter, then click Search.'}
                  </div>
                ) : (
                  <div style={{maxHeight: 500, overflowY: 'auto', paddingRight: 8}}>
                    {glResults.map(row => (
                      <div key={row.id} style={{border:'1px solid #e2e8f0',borderRadius:10,padding:14,marginBottom:10,background:'#f8fafc'}}>
                        <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',gap:8}}>
                          <div style={{flex:1, cursor:'pointer'}} onClick={()=>setGlExpandedId(glExpandedId===row.id ? null : row.id)}>
                            <div style={{display:'flex',gap:8,alignItems:'center',marginBottom:4,flexWrap:'wrap'}}>
                              <span style={S.badge}>{row.client}</span>
                              <span style={{...S.badge,background:'#ede9fe',color:'#5b21b6'}}>{row.ott_platform}</span>
                              <span style={{...S.badge,background:'#fef3c7',color:'#92400e'}}>{row.category}</span>
                              <span style={{fontSize:11,color:'#94a3b8'}}>{row.year} · #{row.spec_no}</span>
                              {row.version_no > 1 && (
                                <span style={{...S.badge,background:'#fee2e2',color:'#991b1b'}}>v{row.version_no}</span>
                              )}
                            </div>
                            <div style={{fontSize:14,fontWeight:700,color:'#0f172a'}}>{row.spec}</div>
                            {row.keywords && <div style={{fontSize:11,color:'#94a3b8',marginTop:2}}>Keywords: {row.keywords}</div>}
                          </div>
                          <div style={{display:'flex',gap:6}}>
                            <button style={S.btnSm} onClick={()=>loadGuidelineHistory(row.id)} title='View version history'>🕓</button>
                            <button style={S.btnSm} onClick={()=>openEditGuidelineForm(row)}>✏️</button>
                            <button style={S.btnSm} onClick={()=>deleteGuideline(row.id)}>🗑</button>
                          </div>
                        </div>

                        {glExpandedId === row.id && (
                          <div style={{marginTop:10,paddingTop:10,borderTop:'1px solid #e2e8f0'}}>
                            <div style={{fontSize:13,color:'#1e293b',lineHeight:1.6,whiteSpace:'pre-wrap'}}>{row.guideline}</div>
                            {row.sub_specific && (
                              <div style={{marginTop:8,fontSize:12,color:'#334155'}}><b>SUB-specific:</b> {row.sub_specific}</div>
                            )}
                            {row.dhoh_specific && (
                              <div style={{marginTop:6,fontSize:12,color:'#334155'}}><b>DHOH/SDH-specific:</b> {row.dhoh_specific}</div>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className='card' style={S.card}>
                <div style={S.label}>QC Platform Rules</div>
                <div style={{fontSize:12,color:'#64748b',marginBottom:14}}>
                  Rules extracted for the Quality Check engine. Custom rules take precedence.
                </div>
                
                {customPlatforms.length > 0 && (
                  <div style={{marginBottom: 20}}>
                    <div style={{fontSize:11, fontWeight:700, color:'#334155', marginBottom:8, textTransform:'uppercase'}}>Custom Platforms</div>
                    {customPlatforms.map(([k,p]) => (
                      <div key={k} style={{background:'#f8fafc',border:'1px solid #cbd5e1',borderRadius:8,padding:'12px 14px',marginBottom:8,display:'flex',alignItems:'flex-start',gap:10,cursor:'pointer'}} onClick={()=>{setEditingPlatform({...p, platform_key: k});setEditRulesText((p.rules||[]).join('\\n'))}}>
                        <div style={{flex:1}}>
                          <div style={{fontSize:13,fontWeight:700,color: '#0f172a',marginBottom:2}}>{p.name||k}</div>
                          <div style={{fontSize:11,color:'#64748b'}}>{p.max_chars_per_line} chars/line · {p.max_lines} lines · {(p.rules||[]).length} rules</div>
                        </div>
                        <button style={{background:'none',border:'none',cursor:'pointer',fontSize:16,color:'#64748b'}} onClick={(e)=>{e.stopPropagation();handleDeletePlatform(k)}}>🗑</button>
                      </div>
                    ))}
                  </div>
                )}

                <div>
                  <div style={{fontSize:11, fontWeight:700, color:'#334155', marginBottom:8, textTransform:'uppercase'}}>Built-in Platforms</div>
                  <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
                    {builtinPlatforms.map(([k,p]) => (
                      <div key={k} style={{background:'#f8fafc',border:'1px solid #cbd5e1',borderRadius:8,padding:'10px 12px',cursor:'pointer'}} onClick={()=>{setEditingPlatform({...p, platform_key: k});setEditRulesText((p.rules||[]).join('\\n'))}}>
                        <div style={{fontSize:12,fontWeight:700,color:'#334155',marginBottom:3}}>{p.name||k}</div>
                        <div style={{fontSize:10,color:'#64748b'}}>{p.max_chars_per_line} chars · {p.max_lines} lines · {p.file_format||'PAC'}</div>
                        {p.reading_speed_max_cps&&<div style={{fontSize:10,color:'#64748b'}}>Max {p.reading_speed_max_cps} CPS</div>}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

      {/* ══ TRACK CHANGES MODAL — on-screen view, see before you download ══ */}`
);

// Replace the Digitize guidelines modal (Bulk Import)
code = code.replace(
    /\{\/\* ══ BULK IMPORT \(DIGITIZE\) GUIDELINES MODAL ══ \*\/\}[\s\S]*?\{\/\* ══ GUIDELINE VERSION HISTORY MODAL ══ \*\/\}/,
    `{/* ══ GUIDELINE VERSION HISTORY MODAL ══ */}`
);

fs.writeFileSync('src/App.jsx', code);
console.log('Patch applied successfully');
