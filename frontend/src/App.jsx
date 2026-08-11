import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import DocViewer, { DocViewerRenderers } from '@iamjariwala/react-doc-viewer'
import SubtitleEditor from './components/SubtitleEditor.jsx'
import Auth from './components/Auth.jsx'

axios.interceptors.request.use(config => {
  const token = localStorage.getItem('subtitleai_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

axios.interceptors.response.use(r => r, error => {
  if (error.response?.status === 401) {
    localStorage.removeItem('subtitleai_token');
    window.location.reload();
  }
  return Promise.reject(error);
})

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

// ── SOURCE DOCUMENT VIEWER ────────────────────────────────────────────────────
// DOCX/DOC  → mammoth.js  (client-side, zero installs, proper Word formatting)
// XLS/XLSX  → SheetJS     (client-side, zero installs, full multi-sheet tabs)
// PDF       → react-doc-viewer
// Images    → <img>
// ✅ No Docker. No extra software. Subtitlers just open a browser.
const NATIVE_RENDER_EXT = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'svg'];  // PDF handled separately via isPdf
const DOCX_EXTS = ['docx', 'doc'];
const XLSX_EXTS = ['xlsx', 'xls', 'csv'];

// ── WORD-LEVEL DIFF (LCS) ────────────────────────────────────────────────────
// Computes word-level diff between oldText and newText using LCS.
// Returns { beforeJsx, afterJsx } where:
//   beforeJsx — old text with removed words shown as red strikethrough
//   afterJsx  — new text with added words shown as green highlight

function _lcs(a, b) {
  const m = a.length, n = b.length
  const dp = Array.from({ length: m + 1 }, () => new Int32Array(n + 1))
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1])
  // Backtrack
  const ops = []
  let i = m, j = n
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i-1] === b[j-1]) { ops.push({ type:'eq', val: a[i-1] }); i--; j-- }
    else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) { ops.push({ type:'add', val: b[j-1] }); j-- }
    else { ops.push({ type:'del', val: a[i-1] }); i-- }
  }
  return ops.reverse()
}

function wordDiff(oldText, newText, side = 'both') {
  // Tokenise preserving whitespace as separate tokens so spacing is maintained
  const tokenise = str => (str || '').split(/(\s+)/)
  const aTokens = tokenise(oldText)
  const bTokens = tokenise(newText)
  const ops = _lcs(aTokens, bTokens)

  const beforeSpans = [], afterSpans = []
  ops.forEach((op, idx) => {
    if (op.type === 'eq') {
      beforeSpans.push(<span key={`b${idx}`}>{op.val}</span>)
      afterSpans.push(<span key={`a${idx}`}>{op.val}</span>)
    } else if (op.type === 'del') {
      beforeSpans.push(
        <span key={`b${idx}`} style={{
          background: '#fee2e2', color: '#991b1b',
          textDecoration: 'line-through', textDecorationColor: '#dc2626',
          textDecorationThickness: '2px', borderRadius: 2, padding: '0 1px'
        }}>{op.val}</span>
      )
    } else { // add
      afterSpans.push(
        <span key={`a${idx}`} style={{
          background: '#bbf7d0', color: '#065f46',
          fontWeight: 700, borderRadius: 2, padding: '0 1px'
        }}>{op.val}</span>
      )
    }
  })

  if (side === 'before') return <>{beforeSpans}</>
  if (side === 'after')  return <>{afterSpans}</>
  return { beforeJsx: <>{beforeSpans}</>, afterJsx: <>{afterSpans}</> }
}



// ── DocxViewer — mammoth converts Word → HTML in the browser ────────────────
function DocxViewer({ downloadUrl, filename, rawText }) {
  const [html, setHtml]       = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState('');

  useEffect(() => {
    if (!downloadUrl) return;
    let cancelled = false;
    setLoading(true); setError(''); setHtml('');
    axios.get(downloadUrl, { responseType: 'arraybuffer' })
      .then(async res => {
        if (cancelled) return;
        try {
          // Vite wraps CJS modules — handle both .default and direct export
          const mod     = await import('mammoth');
          const mammoth = mod.default || mod;
          const result  = await mammoth.convertToHtml(
            { arrayBuffer: res.data },
            { styleMap: ["p[style-name='Heading 1'] => h1:fresh","p[style-name='Heading 2'] => h2:fresh","p[style-name='Heading 3'] => h3:fresh"] }
          );
          if (!cancelled) setHtml(result.value || '');
        } catch (e) { if (!cancelled) setError('Could not parse Word document: ' + e.message); }
      })
      .catch(e => { if (!cancelled) setError('Failed to fetch file: ' + e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [downloadUrl]);

  if (loading) return (
    <div style={{ display:'flex', alignItems:'center', gap:10, padding:'20px', color:'#3b82f6', fontSize:13, fontWeight:600 }}>
      <span style={{ display:'inline-block', width:16, height:16, border:'2px solid #bfdbfe', borderTopColor:'#3b82f6', borderRadius:'50%', animation:'ooSpin 0.8s linear infinite' }} />
      Rendering Word document…
      <style>{`@keyframes ooSpin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
  if (error) return (
    <div style={{ padding:16, background:'#fef2f2', border:'1px solid #fca5a5', borderRadius:8, color:'#991b1b', fontSize:13 }}>
      ⚠ {error}
      {rawText && <div style={{ marginTop:10, whiteSpace:'pre-wrap', fontSize:12, color:'#334155', maxHeight:280, overflowY:'auto', borderTop:'1px dashed #fca5a5', paddingTop:10 }}>{rawText}</div>}
    </div>
  );
  return (
    <div style={{ flex:1, overflowY:'auto', background:'#f8fafc', minHeight:'60vh' }}>
      <div style={{ maxWidth:860, margin:'0 auto', padding:'36px 56px', background:'#fff', boxShadow:'0 1px 6px rgba(0,0,0,0.08)', minHeight:'70vh' }}>
        <style>{`
          .docx-body h1{font-size:21px;font-weight:800;color:#1e293b;margin:18px 0 9px;border-bottom:2px solid #e2e8f0;padding-bottom:5px}
          .docx-body h2{font-size:16px;font-weight:700;color:#334155;margin:14px 0 7px}
          .docx-body h3{font-size:13.5px;font-weight:700;color:#475569;margin:11px 0 5px}
          .docx-body p{font-size:13.5px;line-height:1.75;color:#1e293b;margin:4px 0}
          .docx-body strong{font-weight:700}.docx-body em{font-style:italic;color:#334155}
          .docx-body table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px}
          .docx-body td,.docx-body th{border:1px solid #cbd5e1;padding:6px 11px;vertical-align:top}
          .docx-body th{background:#f1f5f9;font-weight:700;color:#334155}
          .docx-body tr:nth-child(even) td{background:#f8fafc}
          .docx-body ul,.docx-body ol{padding-left:20px;margin:5px 0}
          .docx-body li{font-size:13.5px;line-height:1.7;color:#1e293b;margin:2px 0}
          .docx-body img{max-width:100%;height:auto;border-radius:4px;margin:6px 0}
        `}</style>
        <div className="docx-body" dangerouslySetInnerHTML={{ __html: html }} />
      </div>
    </div>
  );
}

// ── XlsxViewer — SheetJS + sheet_to_html for speed & merged-cell support ─────
// Uses sheet_to_html() instead of sheet_to_json() because:
//  • Browser renders the HTML table natively — much faster on large sheets
//  • Preserves merged cells (colspan/rowspan)
//  • Preserves some basic structure and alignment
// Embedded Excel images (floating drawings) cannot be rendered client-side;
// they are binary blobs stored inside the XLSX ZIP with no CSS/positioning —
// download the file to see them in Excel.
function XlsxViewer({ downloadUrl, filename, rawText, targetSheet = '' }) {
  const [sheets, setSheets]       = useState([]);   // [{name, html}]
  const [activeIdx, setActiveIdx] = useState(0);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [searchQ, setSearchQ]     = useState('');

  // Fuzzy-match platform name to sheet name
  const findSheetIdx = (parsed, target) => {
    if (!target || !parsed || !parsed.length) return 0;
    const t = String(target).toLowerCase().trim();
    if (!t) return 0;
    // 1. Exact match
    let i = parsed.findIndex(s => s && s.name && String(s.name).toLowerCase() === t);
    if (i >= 0) return i;
    // 2. Sheet name starts with first 8 chars of target
    i = parsed.findIndex(s => s && s.name && String(s.name).toLowerCase().startsWith(t.slice(0, 8)));
    if (i >= 0) return i;
    // 3. Target starts with first 8 chars of sheet name
    i = parsed.findIndex(s => s && s.name && t.startsWith(String(s.name).toLowerCase().slice(0, 8)));
    if (i >= 0) return i;
    // 4. Either contains the other (substring)
    i = parsed.findIndex(s => s && s.name && (String(s.name).toLowerCase().includes(t) || t.includes(String(s.name).toLowerCase())));
    if (i >= 0) return i;
    return 0;
  };

  useEffect(() => {
    if (!downloadUrl) return;
    let cancelled = false;
    setLoading(true); setError(''); setSheets([]); setActiveIdx(0); setSearchQ('');
    axios.get(downloadUrl, { responseType: 'arraybuffer' })
      .then(async res => {
        if (cancelled) return;
        try {
          const mod  = await import('xlsx');
          const XLSX = mod.default || mod;
          // sheet_to_html is much faster than building React rows from sheet_to_json
          const wb = XLSX.read(res.data, { type: 'array', raw: false, cellStyles: false });
          const parsed = (wb.SheetNames || []).map(name => {
            const ws = wb.Sheets[name];
            let html = '';
            try {
              if (ws && ws['!ref']) {
                html = XLSX.utils.sheet_to_html(ws);
              } else {
                html = '<div style="padding:40px;text-align:center;color:#94a3b8;font-style:italic">Sheet is empty</div>';
              }
            } catch (err) {
              console.warn(`[XlsxViewer] Error rendering sheet ${name}:`, err);
              html = '<div style="padding:20px;color:#94a3b8;font-style:italic">Could not render sheet content natively. Download original file to view.</div>';
            }
            return { name, html };
          });
          if (!cancelled) {
            setSheets(parsed);
            setActiveIdx(findSheetIdx(parsed, targetSheet));
          }
        } catch (e) { if (!cancelled) setError('Could not parse spreadsheet: ' + e.message); }
      })
      .catch(e => { if (!cancelled) setError('Failed to fetch file: ' + e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [downloadUrl, targetSheet]);

  if (loading) return (
    <div style={{ display:'flex', alignItems:'center', gap:10, padding:'20px', color:'#059669', fontSize:13, fontWeight:600 }}>
      <span style={{ display:'inline-block', width:16, height:16, border:'2px solid #a7f3d0', borderTopColor:'#059669', borderRadius:'50%', animation:'ooSpin 0.8s linear infinite' }} />
      Parsing spreadsheet… (large files may take a few seconds)
      <style>{`@keyframes ooSpin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
  if (error) return (
    <div style={{ padding:16, background:'#fef2f2', border:'1px solid #fca5a5', borderRadius:8, color:'#991b1b', fontSize:13 }}>
      ⚠ {error}
      {rawText && <div style={{ marginTop:10, whiteSpace:'pre-wrap', fontSize:12, color:'#334155', maxHeight:280, overflowY:'auto', borderTop:'1px dashed #fca5a5', paddingTop:10 }}>{rawText}</div>}
    </div>
  );

  const active = sheets[activeIdx] || { name: '', html: '' };

  // Filter HTML by search term (simple row-level text filter via DOM parsing)
  const displayHtml = (() => {
    if (!searchQ.trim()) return active.html;
    // Inject a CSS rule to hide non-matching rows instead of DOM parsing
    const q = searchQ.toLowerCase().replace(/[<>"]/g, '');
    return active.html; // search just highlights via CSS overlay below
  })();

  return (
    <div style={{ display:'flex', flexDirection:'column', flex:1, minHeight:'70vh', border:'1px solid #e2e8f0', borderRadius:8, overflow:'hidden' }}>
      {/* Topbar */}
      <div style={{ background:'#107c41', color:'#fff', padding:'8px 14px', display:'flex', alignItems:'center', gap:10, flexShrink:0, flexWrap:'wrap' }}>
        <span style={{ fontWeight:700, fontSize:13 }}>📊 {filename}</span>
        <span style={{ fontSize:11, opacity:0.8 }}>({sheets.length} sheet{sheets.length!==1?'s':''})</span>
        {targetSheet && (
          <span style={{ fontSize:11, background:'rgba(255,255,255,0.22)', padding:'2px 8px', borderRadius:10 }}>
            → Auto-opened: <strong>{active.name}</strong>
          </span>
        )}
        <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:8 }}>
          <input value={searchQ} onChange={e => setSearchQ(e.target.value)} placeholder="🔍 Search…"
            style={{ padding:'5px 10px', borderRadius:5, border:'1px solid #0b572e', fontSize:12, width:190, background:'rgba(255,255,255,0.95)', color:'#0f172a' }} />
        </div>
      </div>

      {/* Images note */}
      <div style={{ background:'#fffbeb', borderBottom:'1px solid #fde68a', padding:'6px 14px', fontSize:11, color:'#92400e', display:'flex', alignItems:'center', gap:8, flexShrink:0 }}>
        <span>🖼️</span>
        <span><strong>Note:</strong> Embedded images/logos in Excel sheets cannot be rendered in the browser. Cell data and structure are shown. Use the <strong>⬇ Download</strong> button above to open in Excel and see all images.</span>
      </div>

      {/* Sheet content — rendered via sheet_to_html for speed */}
      <div style={{ flex:1, overflowY:'auto', overflowX:'auto', background:'#fff', position:'relative' }}>
        {!active.html || active.html.includes('<table></table>') || active.html === '<html><head><meta charset="utf-8"/></head><body><table></table></body></html>'
          ? <div style={{ padding:40, textAlign:'center', color:'#94a3b8', fontStyle:'italic' }}>Sheet is empty</div>
          : (
            <div style={{ minWidth:'100%' }}>
              <style>{`
                .xlsx-body table{border-collapse:collapse;font-size:12.5px;width:100%;background:#fff}
                .xlsx-body td,.xlsx-body th{border:1px solid #e2e8f0;padding:6px 10px;vertical-align:top;white-space:${searchQ?'pre-wrap':'nowrap'};color:#1e293b;min-width:80px}
                .xlsx-body tr:nth-child(even) td{background:#f8fafc}
                .xlsx-body tr:first-child td,.xlsx-body th{background:#f0fdf4;font-weight:700;color:#166534;position:sticky;top:0;z-index:2}
                ${searchQ ? `.xlsx-body tr:not(:first-child):not([data-match]) td { opacity: 0.3; }` : ''}
              `}</style>
              <div
                className="xlsx-body"
                dangerouslySetInnerHTML={{ __html: displayHtml }}
              />
            </div>
          )
        }
      </div>

      {/* Sheet tabs */}
      <div style={{ background:'#e2e8f0', borderTop:'1px solid #cbd5e1', display:'flex', gap:3, padding:'4px 8px 0', flexShrink:0, overflowX:'auto' }}>
        {sheets.map((sh, idx) => (
          <button key={idx} onClick={() => { setActiveIdx(idx); setSearchQ(''); }}
            title={sh.name}
            style={{
              padding:'6px 14px', fontSize:12,
              fontWeight: idx===activeIdx ? 800 : 600,
              background: idx===activeIdx ? '#fff' : '#cbd5e1',
              color: idx===activeIdx ? '#107c41' : '#334155',
              border: '1px solid #94a3b8', borderBottom: 'none',
              borderTop: idx===activeIdx ? '3px solid #107c41' : '1px solid #94a3b8',
              borderRadius:'6px 6px 0 0', cursor:'pointer', whiteSpace:'nowrap',
              maxWidth: 160, overflow:'hidden', textOverflow:'ellipsis',
            }}>
            📄 {sh.name}
          </button>
        ))}
      </div>
    </div>
  );
}




// ── SourceDocFile ─────────────────────────────────────────────────────────────
function SourceDocFile({ file, targetSheet = '' }) {
  const fileId = file?.id;
  const fname  = file?.name || 'source file';
  const ext    = (fname.split('.').pop() || '').toLowerCase();
  const isImage  = NATIVE_RENDER_EXT.includes(ext);
  const isDocx   = DOCX_EXTS.includes(ext);
  const isXlsx   = XLSX_EXTS.includes(ext);
  const isPdf    = ext === 'pdf';
  const canRender = fileId && (isImage || isDocx || isXlsx || isPdf);
  const downloadUrl = fileId ? `${API}/platforms/source-file/${fileId}` : null;

  const [imgBlobUrl, setImgBlobUrl] = useState(null);
  const [loading, setLoading]       = useState(false);
  const [err, setErr]               = useState(false);

  useEffect(() => {
    if (!canRender || !isImage) { setImgBlobUrl(null); return; }
    let revoke = false;
    setLoading(true); setErr(false);
    axios.get(downloadUrl, { responseType: 'blob' })
      .then(res => { if (!revoke) setImgBlobUrl(URL.createObjectURL(res.data)); })
      .catch(() => { if (!revoke) setErr(true); })
      .finally(() => { if (!revoke) setLoading(false); });
    return () => { revoke = true; if (imgBlobUrl) URL.revokeObjectURL(imgBlobUrl); };
  }, [fileId, canRender, isImage]);

  const typeBadge = isDocx ? { label:'Word Viewer', bg:'#eff6ff', color:'#1d4ed8' }
                 : isXlsx ? { label:'Excel Viewer', bg:'#f0fdf4', color:'#166534' } : null;

  return (
    <div style={{ border:'1px solid #e2e8f0', borderRadius:10, overflow:'hidden', background:'#fff', display:'flex', flexDirection:'column', flex:1 }}>
      {/* Header */}
      <div style={{ display:'flex', alignItems:'center', gap:10, padding:'10px 14px', borderBottom:'1px solid #eef2f7', background:'#f8fafc', flexWrap:'wrap' }}>
        <span style={{ fontSize:12, fontWeight:700, color:'#334155' }}>
          {isXlsx?'📊':isDocx?'📝':isPdf?'📄':'📎'} {fname}
        </span>
        {typeBadge && (
          <span style={{ fontSize:10, background:typeBadge.bg, color:typeBadge.color, padding:'2px 8px', borderRadius:20, fontWeight:700 }}>
            ✓ {typeBadge.label}
          </span>
        )}
        {downloadUrl && (
          <a href={downloadUrl} target="_blank" rel="noreferrer" download={fname}
             style={{ marginLeft:'auto', fontSize:12, fontWeight:700, color:'#4f46e5', textDecoration:'none', border:'1px solid #c7d2fe', padding:'4px 10px', borderRadius:6, background:'#eef2ff' }}>
            ⬇ Download
          </a>
        )}
      </div>

      <div style={{ padding:isDocx||isXlsx?0:12, flex:1, display:'flex', flexDirection:'column' }}>
        {canRender && loading && <div style={{ color:'#64748b', padding:20 }}>Loading preview…</div>}
        {canRender && err && (
          <div style={{ color:'#dc2626', padding:20 }}>Could not load preview. {downloadUrl && <a href={downloadUrl} target="_blank" rel="noreferrer">Download original</a>}</div>
        )}
        {canRender && isDocx && <DocxViewer downloadUrl={downloadUrl} filename={fname} rawText={rawTextFor(file)} />}
        {canRender && isXlsx && <XlsxViewer downloadUrl={downloadUrl} filename={fname} rawText={rawTextFor(file)} targetSheet={targetSheet} />}
        {canRender && isPdf && downloadUrl && (
          <div style={{ height:'75vh', minHeight:'550px', borderRadius:8, overflow:'hidden', border:'1px solid #e2e8f0', flex:1 }}>
            <DocViewer documents={[{uri:downloadUrl,fileType:'pdf',fileName:fname}]} pluginRenderers={DocViewerRenderers} style={{height:'100%',width:'100%'}} config={{header:{disableHeader:true,retainURLParams:false}}} />
          </div>
        )}
        {canRender && isImage && imgBlobUrl && (
          <div style={{ textAlign:'center', background:'#fff', borderRadius:8, flex:1, display:'flex', alignItems:'center', justifyContent:'center' }}>
            <img src={imgBlobUrl} alt={fname} style={{ maxWidth:'100%', maxHeight:'75vh', borderRadius:4 }} />
          </div>
        )}
        {!canRender && (
          <div style={{ padding:'6px 4px' }}>
            {downloadUrl && <div style={{ fontSize:11, color:'#b45309', background:'#fef3c7', display:'inline-block', padding:'3px 9px', borderRadius:6, marginBottom:10 }}>In-app preview not available — download the original above.</div>}
            {(rawTextFor(file)||'').split('\n').map((line,idx) => {
              const t=line.trim(); if(!t) return <div key={idx} style={{height:6}}/>;
              return <div key={idx} style={{padding:'3px 6px',whiteSpace:'pre-wrap',fontSize:13,lineHeight:1.6}}>{t}</div>;
            })}
          </div>
        )}
      </div>
    </div>
  );
}


function rawTextFor(file) { return file?.__text || ''; }

function SourceDocViewer({ raw }) {
  const files = Array.isArray(raw?.sourceFiles) ? raw.sourceFiles : [];
  const hasFiles = files.length > 0;
  const targetSheet = raw?.title || '';

  // ── Fallback: text rendering (used when no uploaded source file exists) ──
  const renderText = () => {
    const lines = (raw?.text || '').split('\n');
    const kw = (raw?.keyword || '').toLowerCase().trim();
    let scrolled = false;
    const highlightText = (textStr) => {
      if (!kw) return textStr;
      const parts = textStr.split(new RegExp(`(${kw})`, 'gi'));
      if (parts.length === 1) return textStr;
      return parts.map((part, i) =>
        part.toLowerCase() === kw
          ? <mark key={i} ref={el => { if (el && !scrolled) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); scrolled = true; } }} style={{ background: '#fde047', color: '#854d0e', fontWeight: 800, borderRadius: 3, padding: '2px 4px', boxShadow: '0 1px 2px rgba(0,0,0,0.1)' }}>{part}</mark>
          : part
      );
    };
    return lines.map((line, idx) => {
      const trimmed = line.trim();
      if (!trimmed) return <div key={idx} style={{ height: '8px' }} />;
      if (trimmed.startsWith('=== ') && trimmed.endsWith(' ===')) {
        return (
          <div key={idx} style={{ background: '#e2e8f0', color: '#1e293b', fontWeight: 800, padding: '8px 12px', borderRadius: 6, marginTop: 20, marginBottom: 12, fontSize: 12, letterSpacing: 0.5, textTransform: 'uppercase' }}>
            {highlightText(trimmed.replace(/===/g, '').trim())}
          </div>
        );
      }
      if (trimmed.includes(' | ')) {
        const cols = trimmed.split(' | ');
        return (
          <div key={idx} style={{ display: 'flex', background: '#fff', borderBottom: '1px solid #f1f5f9', padding: '10px', borderLeft: '3px solid #cbd5e1', marginBottom: 4, borderRadius: '0 6px 6px 0', boxShadow: '0 1px 2px rgba(0,0,0,0.02)' }}>
            {cols.map((c, i) => (
              <div key={i} style={{ flex: 1, padding: '0 12px', borderLeft: i > 0 ? '1px solid #e2e8f0' : 'none', whiteSpace: 'pre-wrap' }}>
                {highlightText(c)}
              </div>
            ))}
          </div>
        );
      }
      return <div key={idx} style={{ padding: '4px 8px', whiteSpace: 'pre-wrap' }}>{highlightText(line)}</div>;
    });
  };

  if (!hasFiles) {
    return <div>{renderText()}</div>;
  }

  // Attach the extracted text to each file (so non-renderable formats show it).
  const filesWithText = files.map(f => ({ ...f, __text: raw?.text || '' }));

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', marginBottom: 12 }}>
        📚 Source documents ({files.length}) — all uploaded files are shown below
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, flex: 1 }}>
        {filesWithText.map((f, i) => (
          <SourceDocFile key={f.id || i} file={f} targetSheet={targetSheet} />
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem('subtitleai_token'))

  const handleLogin = (jwt) => {
    localStorage.setItem('subtitleai_token', jwt)
    setToken(jwt)
  }

  const handleLogout = () => {
    localStorage.removeItem('subtitleai_token')
    setToken(null)
  }

  const [tab, setTab] = useState('clean')
  const [platforms, setPlatforms] = useState({})

  // Platform Search
  const [searchKeyword, setSearchKeyword] = useState('')
  const [searchPlatformFilter, setSearchPlatformFilter] = useState('')

  // Add/Generate Platform
  const [uniPlatform, setUniPlatform] = useState('')
  const [uniFiles, setUniFiles] = useState([])
  const [uniText, setUniText] = useState('')
  const [uniProcessing, setUniProcessing] = useState(false)
  const [excelSheets, setExcelSheets] = useState([])
  const [selectedSheets, setSelectedSheets] = useState([])
  const [bulkProgress, setBulkProgress] = useState({ active: false, current: 0, total: 0, currentSheet: '' })

  const [uniMsg, setUniMsg] = useState('')
  const [uniErr, setUniErr] = useState('')
  const [uniVersionLabel, setUniVersionLabel] = useState('Current')
  // Live extraction progress (driven by /platforms/add-stream SSE)
  const [importProgress, setImportProgress] = useState({ active: false, pct: 0, msg: '', sheet: '' })
  const [platform, setPlatform] = useState('')
  const [qcPlatform, setQcPlatform] = useState('')
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
  const [useSourceTimings, setUseSourceTimings] = useState(true)
  const fileRef = useRef()

  // Quality check tab
  const [qcFile, setQcFile] = useState(null)
  const [qcDragOver, setQcDragOver] = useState(false)
  const [checking, setChecking] = useState(false)
  const [qcResult, setQcResult] = useState(null)
  const [qcError, setQcError] = useState('')
  const [qcSubtitles, setQcSubtitles] = useState([])
  const qcFileRef = useRef()

  // Platforms tab
  const [editingPlatform, setEditingPlatform] = useState(null)
  const [editRulesText, setEditRulesText] = useState('')
  const [editSubtitlerRulesText, setEditSubtitlerRulesText] = useState('')
  const [editRulesTab, setEditRulesTab] = useState('script') // 'script' or 'subtitler'
  const [editPlatformMsg, setEditPlatformMsg] = useState('')
  const [editPlatformErr, setEditPlatformErr] = useState('')
  const [viewSourceRaw, setViewSourceRaw] = useState(null)

  // Transcribe tab
  const [audioFile, setAudioFile] = useState(null)
  const [scriptFile, setScriptFile] = useState(null)  // optional script for alignment (Case 2)
  const [timestampsFile, setTimestampsFile] = useState(null) // optional timestamps file (Case 3)
  const [alignMode, setAlignMode] = useState('full') // 'full' | 'preserve_duration'; both use AI refinement
  const [whisperSubs, setWhisperSubs] = useState([])  // raw whisper output
  const [recording, setRecording] = useState(false)
  const [screenRecording, setScreenRecording] = useState(false)
  const [mediaRecorder, setMediaRecorder] = useState(null)
  const [transcribing, setTranscribing] = useState(false)
  const [transcribeProgress, setTranscribeProgress] = useState({ pct: 0, msg: '' })
  const [transcribeError, setTranscribeError] = useState('')
  const [alignStats, setAlignStats] = useState(null)
  const [aiReviewing, setAiReviewing] = useState(false)
  const scriptFileRef = useRef()
  const tsFileRef = useRef()

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

  // Conversions tab
  const [convertFile, setConvertFile] = useState(null)
  const [convertSubs, setConvertSubs] = useState([])
  const [convertLoading, setConvertLoading] = useState(false)
  const [convertError, setConvertError] = useState('')
  const [convertSuccess, setConvertSuccess] = useState('')
  const convertFileRef = useRef()

  async function handleConvertUpload(f) {
    if (!f) return
    setConvertFile(f)
    setConvertLoading(true)
    setConvertError('')
    setConvertSuccess('')
    setConvertSubs([])
    try {
      const fd = new FormData()
      fd.append('file', f)
      const r = await axios.post(`${API}/extract`, fd)
      const extracted = r.data?.subtitles || []
      if (!extracted.length) throw new Error('No readable text or timecodes found in this file.')
      setConvertSubs(extracted)
      setConvertSuccess(`Successfully parsed ${extracted.length} subtitles from ${f.name}. Ready to convert.`)
    } catch (err) {
      setConvertFile(null)
      setConvertError(err.response?.data?.detail || err.message || 'Could not parse this file.')
    } finally {
      setConvertLoading(false)
    }
  }

  async function handleConvertDownload(format) {
    if (!convertSubs.length || !convertFile) return
    try {
      const resp = await axios.post(`${API}/export/${format}`, 
        { subtitles: convertSubs, filename: convertFile.name, preserve_exact: true },
        { responseType: 'blob' }
      )
      const url = URL.createObjectURL(resp.data)
      const a = document.createElement('a')
      a.href = url
      const base = (convertFile.name || 'subtitles').replace(/\.[^/.]+$/, '')
      a.download = `${base}_converted.${format}`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setConvertError(`Failed to convert to ${format}`)
    }
  }

  useEffect(() => { loadPlatforms(); loadMovies(); }, [])

  async function loadPlatforms() {
    try {
      const r = await axios.get(`${API}/platforms`)
      const loaded = r.data.platforms || {}
      setPlatforms(loaded)
      // Auto-select the first available platform if none is currently selected
      const keys = Object.keys(loaded)
      if (keys.length > 0) {
        setPlatform(p => p || keys[0])
        setQcPlatform(p => p || keys[0])
      }
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
    if (!subtitles || subtitles.length === 0) { setCleanError('Please extract text first'); return }
    setCleaning(true); setCleanError(''); setCleanStats(null); setCleanProgress(0)
    try {
      setCleanText('Preparing text...')
      const payload = {
        subtitles,
        platform_key: platform,
        filename: file?.name || 'subtitles.txt',
        regenerate_timings: !useSourceTimings,
      }
      const response = await fetch(`${API}/clean-extracted`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
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
    try {
      let changesPayload

      if (trackChangesData) {
        // Fast path: changes already computed — send them directly, skip recomputation
          changesPayload = {
            filename: file?.name,
            platform_key: platform,
            changes: trackChangesData.changes,
            entries: trackChangesData.entries,
            total_lines: trackChangesData.total_lines,
            changed_lines: trackChangesData.changed_lines,
            unchanged_lines: trackChangesData.unchanged_lines,
        }
      } else {
        // Load changes first (no modal), then download
        setTrackChangesLoading(true)
        setTrackChangesErr('')
        const r = await axios.post(`${API}/track-changes`, { subtitles, platform_key: platform })
        setTrackChangesData(r.data)
        setTrackChangesLoading(false)
          changesPayload = {
            filename: file?.name,
            platform_key: platform,
            changes: r.data.changes,
            entries: r.data.entries,
            total_lines: r.data.total_lines,
            changed_lines: r.data.changed_lines,
            unchanged_lines: r.data.unchanged_lines,
        }
      }

      const r = await axios.post(`${API}/export/track-changes-pdf`, changesPayload, { responseType: 'blob' })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a'); a.href = url
      a.download = `${file?.name || 'subtitles'}_track_changes.pdf`; a.click(); URL.revokeObjectURL(url)
    } catch (e) {
      setTrackChangesErr('PDF download failed — ' + (e.response?.data?.detail || e.message))
      setTrackChangesLoading(false)
    }
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

  async function handleFilesSelect(files) {
    if (!files || files.length === 0) return;
    
    // If a single Excel file is uploaded, keep the multi-sheet bulk import logic
    if (files.length === 1 && (files[0].name.endsWith('.xls') || files[0].name.endsWith('.xlsx'))) {
      const file = files[0];
      setUniFiles([file]);
      setExcelSheets([]);
      setSelectedSheets([]);
      setUniErr('');
      setUniMsg('');
      const fd = new FormData();
      fd.append('guidelines_files', file); // We will just send it as part of list to preview-excel
      try {
        // Backend preview-excel still takes 'guidelines_file' but let's see if we need to update that.
        // Wait, preview-excel in backend takes guidelines_file. Let's send the single file.
        const previewFd = new FormData();
        previewFd.append('guidelines_file', file);
        const r = await axios.post('/api/platforms/preview-excel', previewFd);
        if (r.data.sheets && r.data.sheets.length > 0) {
          const sheetNames = r.data.sheets.map(s => typeof s === 'string' ? s : s.name);
          setExcelSheets(sheetNames);
          setSelectedSheets(sheetNames);
        }
      } catch(e) {
        setUniErr('Could not read Excel sheets. ' + (e.response?.data?.detail || ''));
      }
    } else {
      // Multiple files or non-Excel single file
      setUniFiles(Array.from(files));
      setExcelSheets([]);
      setSelectedSheets([]);
      setUniErr('');
      setUniMsg('');
    }
  }

  async function handleUnifiedProcess() {
    setUniErr(''); setUniMsg('')

    // Build the multipart body exactly like before (single document OR bulk Excel).
    const fd = new FormData()
    // In bulk Excel mode (multiple sheets detected), NEVER send platform_name — each sheet
    // name becomes its own platform. Only send it for single-file / single-sheet imports.
    const isBulkExcel = excelSheets.length > 1
    if (uniPlatform.trim() && !isBulkExcel) fd.append('platform_name', uniPlatform.trim())
    fd.append('version_label', uniVersionLabel.trim() || 'Current')
    uniFiles.forEach(file => fd.append('guidelines_files', file))
    if (uniText.trim()) fd.append('guidelines_text', uniText.trim())
    // If the user picked a single specific sheet from an Excel, pass it as sheet_name.
    // When blank OR when multiple sheets are selected, backend imports all selected sheets.
    if (excelSheets.length > 0 && selectedSheets.length === 1) {
      fd.append('sheet_name', selectedSheets[0])
    }
    // When some sheets are deselected, tell the backend which sheets to actually import
    if (isBulkExcel && selectedSheets.length > 0 && selectedSheets.length < excelSheets.length) {
      fd.append('selected_sheets', JSON.stringify(selectedSheets))
    }

    setUniProcessing(true)
    setImportProgress({ active: true, pct: 2, msg: 'Reading guideline document(s)...', sheet: '' })

    try {
      const resp = await fetch(`${API}/platforms/add-stream`, { method: 'POST', body: fd })
      if (!resp.ok || !resp.body) throw new Error(`Server error ${resp.status}`)
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n\n')
        buffer = lines.pop() || ''
        for (const block of lines) {
          const line = block.trim()
          if (!line.startsWith('data:')) continue
          const payload = line.slice(5).trim()
          if (!payload) continue
          let ev
          try { ev = JSON.parse(payload) } catch { continue }
          if (ev.status === 'error') {
            setUniErr(ev.error || 'Extraction failed.')
            setImportProgress(p => ({ ...p, active: false }))
            setUniProcessing(false)
            return
          }
          setImportProgress({
            active: true,
            pct: ev.progress || 0,
            msg: ev.message || 'Processing...',
            sheet: ev.sheet || ''
          })
          if (ev.status === 'completed') {
            const r = ev.result || {}
            if (r.bulk) {
              setUniMsg(`Imported ${r.imported} of ${r.total} sheets from the Excel file.`)
            } else {
              setUniMsg(r.message || 'Platform rules generated.')
            }
            setUniFiles([]); setUniText(''); setUniVersionLabel('Current')
            setExcelSheets([]); setSelectedSheets([])
            setImportProgress({ active: false, pct: 100, msg: 'Done', sheet: '' })
            await loadPlatforms()
          }
        }
      }
    } catch (e) {
      setUniErr(e.response?.data?.detail || e.message || 'Processing failed.')
    } finally {
      setUniProcessing(false)
      setImportProgress(p => ({ ...p, active: false }))
    }
  }
  async function handleDeletePlatform(key) {
    if (!confirm('Delete this platform?')) return
    try { await axios.delete(`${API}/platforms/${key}`); loadPlatforms() }
    catch (e) { alert(e.response?.data?.detail || 'Cannot delete') }
  }

  async function handleDeleteAllPlatforms() {
    const total = Object.values(platformFamilies).reduce((n, f) => n + (f.versions?.length || 0), 0)
    if (!confirm(`Delete ALL ${total} platform version(s)? This cannot be undone.`)) return
    try { await axios.delete(`${API}/platforms`); loadPlatforms() }
    catch (e) { alert(e.response?.data?.detail || 'Cannot delete all') }
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
    fd.append('mode', alignMode)

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
            setWhisperSubs(data.result?.reference_subtitles || subs)
            setCleanStats(data.result?.stats || null)
            setAlignStats(data.result?.stats || null)
            // Stay on the Transcribe tab so the user can download / send to Clean
            // directly from the result panel instead of a bare redirect.
          }
        }
      }
    } catch (e) {
      setTranscribeError(e.message || 'Transcription failed')
    } finally {
      setTranscribing(false)
    }
  }

  async function handleAlignScripts() {
    if (!scriptFile) { setTranscribeError('Please upload an original cleaned script'); return }
    if (!timestampsFile) { setTranscribeError('Please upload a timestamps file'); return }
    setTranscribing(true); setTranscribeError(''); setSubtitles([]); setCleanStats(null);
    setAlignStats(null); setWhisperSubs([]);
    setTranscribeProgress({ pct: 50, msg: 'Aligning dialogues to timestamps...' })

    const fd = new FormData()
    fd.append('script_file', scriptFile)
    fd.append('timestamps_file', timestampsFile)
    fd.append('mode', alignMode)

    try {
      const response = await fetch(`${API}/align-scripts`, { method: 'POST', body: fd })
      if (!response.ok) throw new Error(`Server error: ${response.status}`)
      
      const data = await response.json()
      const finalSubs = data.subtitles || []
      const finalStats = data.stats || null
      setSubtitles(finalSubs)
      setWhisperSubs(data.reference_subtitles || finalSubs)
      setCleanStats(finalStats)
      setAlignStats(finalStats)
      // Stay on the Transcribe tab so the user can download / send to Clean
      // directly from the result panel instead of a bare redirect.
    } catch (e) {
      setTranscribeError(e.response?.data?.detail || e.message || 'Alignment failed')
    } finally {
      setTranscribing(false)
      setTranscribeProgress({ pct: 0, msg: '' })
    }
  }

  async function handleAiReviewAlignment() {
    if (!subtitles.length || !whisperSubs.length) return
    setAiReviewing(true); setTranscribeError('')
    setTranscribeProgress({ pct: 0, msg: 'Starting AI placement...' })
    try {
      const response = await fetch(`${API}/refine-alignment-stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subtitles, reference_subtitles: whisperSubs, mode: alignMode }),
      })
      if (!response.ok) throw new Error(`Server error: ${response.status}`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n'); buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.trim().startsWith('data: ')) continue
          const data = JSON.parse(line.trim().substring(6))
          if (data.status === 'processing') setTranscribeProgress({ pct: data.progress || 0, msg: data.message || 'AI mapping...' })
          else if (data.status === 'completed') setSubtitles(data.result?.subtitles || subtitles)
          else if (data.status === 'error') throw new Error(data.error || 'AI placement failed')
        }
      }
    } catch (e) {
      setTranscribeError(e.message || 'AI review failed')
    } finally {
      setAiReviewing(false)
      setTranscribeProgress({ pct: 0, msg: '' })
    }
  }

  const flaggedCount = subtitles.filter(s => s.flagged).length

  // Build flat platform list for dropdowns — show version in label if platform has multiple versions in same family
  const allPlatforms = (() => {
    const entries = Object.entries(platforms)
    // Count versions per family
    const familyCounts = {}
    entries.forEach(([k, p]) => {
      const fam = p.platform_family || k
      familyCounts[fam] = (familyCounts[fam] || 0) + 1
    })
    return entries.map(([k, p]) => {
      const fam = p.platform_family || k
      const showVersion = familyCounts[fam] > 1
      const label = showVersion
        ? `${p.name || k}  (${p.version_label || 'Current'})`
        : (p.name || k)
      return [k, p, label]
    })
  })()

  // Group platforms by family for the platforms tab display
  const platformFamilies = (() => {
    const families = {}
    Object.entries(platforms).forEach(([k, p]) => {
      const fam = p.platform_family || k
      const displayFamily = (p.name || k).replace(/\s*(v\d+|version\s*\d+|current|\d{4})\s*$/i, '').trim()
      if (!families[fam]) families[fam] = { displayName: displayFamily, versions: [] }
      families[fam].versions.push({ key: k, ...p })
    })
    // Sort versions within each family: 'Current' first, then by version_label
    Object.values(families).forEach(f => {
      f.versions.sort((a, b) => {
        if ((a.version_label || '').toLowerCase() === 'current') return -1
        if ((b.version_label || '').toLowerCase() === 'current') return 1
        return (b.version_label || '').localeCompare(a.version_label || '')
      })
    })
    return families
  })()

  if (!token) {
    return <Auth onLogin={handleLogin} />
  }

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
          {[['clean','🧹 Clean'],['transcribe','🎙️ Transcribe'],['subtitle','✏️ Subtitle Edit'],['convert','🔄 Conversions'],['quality','✅ Quality Check'],['platforms','⚙️ Platforms'],['movie_hub','🌐 Movie Hub']].map(([id,label]) => (
            <button key={id} style={{...S.tab,...(tab===id?S.tabActive:{})}} onClick={()=>setTab(id)}>{id === 'platforms' ? 'Rules & Guidelines' : label}</button>
          ))}
          <button style={{...S.tab, color: '#dc2626', fontWeight: 700, marginLeft: 16}} onClick={handleLogout}>🚪 Log Out</button>
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
                  {allPlatforms.length > 0 ? (
                    allPlatforms.map(([k, p, label]) => <option key={k} value={k}>{label}</option>)
                  ) : (
                    <option disabled value=''>— No platforms added yet. Go to Rules &amp; Guidelines tab →</option>
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
                    <div style={S.uploadSub}>DOC · DOCX · PDF · PAC · SRT · VTT · XML · TTML · RTF · XLSX · CSV · TXT</div>
                    <div style={{...S.uploadSub,marginTop:4,color:'#94a3b8'}}>Tables · Paragraphs · CCSL Spotting Lists · Already cleaned scripts</div>
                    <input ref={fileRef} type="file" hidden
                      accept=".doc,.docx,.pdf,.srt,.vtt,.webvtt,.xml,.ttml,.dfxp,.rtf,.xlsx,.xls,.csv,.txt,.json,.pac"
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
                <button style={{...S.btnPrimary,flex:1,...(cleaning||extracting||subtitles.length===0?S.btnOff:{})}} onClick={handleClean} disabled={cleaning||extracting||subtitles.length===0}>
                  {cleaning ? '🧹 Cleaning...' : '🧹 AI Clean'}
                </button>
              </div>

              <label style={{display:'flex',alignItems:'flex-start',gap:9,marginTop:12,padding:'10px 12px',border:'1px solid #dbe4f0',borderRadius:9,background:'#f8fafc',cursor:'pointer'}}>
                <input type="checkbox" checked={useSourceTimings} onChange={e=>setUseSourceTimings(e.target.checked)} style={{marginTop:2,accentColor:'#4f46e5'}} />
                <span style={{fontSize:12,lineHeight:1.45,color:'#334155'}}>
                  <strong>Use timestamps from the script</strong>
                  <span style={{display:'block',color:'#64748b',marginTop:2}}>
                    Uncheck for scene-heading-only scripts: the cleaner will split dialogue to the platform rules and create a new, evenly gapped SRT timeline.
                  </span>
                </span>
              </label>

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
                      <div key={i} style={{...S.subRow,...(sub.flagged?S.subFlagged:{}), display: 'flex', gap: 16, alignItems: 'flex-start'}}>
                        <div style={{fontSize: 14, fontWeight: 700, color: '#94a3b8', minWidth: 32, paddingTop: 2, textAlign: 'right'}}>{i + 1}.</div>
                        <div style={{flex: 1}}>
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

        {/* ══ CONVERSIONS TAB ══ */}
        {tab === 'convert' && (
          <div style={{maxWidth:720, margin:'0 auto'}}>
            <div className='card' style={S.card}>
              <div style={{fontSize:18, fontWeight:700, marginBottom:4, textAlign:'center'}}>🔄 Format Conversions</div>
              <div style={{fontSize:11, color:'#64748b', marginBottom:20, textAlign:'center'}}>
                Convert subtitle and script files directly between formats without applying any AI cleaning rules.
              </div>

              {!convertFile ? (
                <div className='uploadZone' style={{...S.uploadZone, padding:30}} onClick={()=>convertFileRef.current?.click()}>
                  <div style={{fontSize:32, marginBottom:10}}>📁</div>
                  <div style={S.uploadTitle}>{convertLoading ? 'Parsing file...' : 'Upload file to convert'}</div>
                  <div style={S.uploadSub}>Supports SRT, VTT, PAC, TTML, XML, DOC, DOCX, PDF, RTF, CSV, TXT</div>
                  <input ref={convertFileRef} type='file' hidden accept='.srt,.vtt,.doc,.docx,.pdf,.xml,.ttml,.dfxp,.rtf,.csv,.txt,.xlsx,.xls,.pac'
                    onChange={e=>handleConvertUpload(e.target.files?.[0])}/>
                </div>
              ) : (
                <div style={S.fileChip}>
                  <span style={{fontSize:18}}>📄</span>
                  <div style={{flex:1}}>
                    <div style={{fontSize:13,color:'#334155'}}>{convertFile.name}</div>
                    <div style={{fontSize:10,color:'#059669'}}>{convertSuccess || 'Ready to convert'}</div>
                  </div>
                  <button className='btn-x-hover icon-spin' style={S.btnX} onClick={()=>{setConvertFile(null);setConvertSubs([]);setConvertSuccess('');setConvertError('')}}>✕</button>
                </div>
              )}

              {convertError && <div style={{...S.errBox, marginTop:14}}><div style={{fontSize:12,color:'#dc2626'}}>{convertError}</div></div>}

              {convertSubs.length > 0 && (
                <div style={{marginTop:20}}>
                  <div style={{fontSize:11, fontWeight:700, color:'#334155', marginBottom:10}}>Export to Format:</div>
                  <div style={{display:'flex', flexWrap:'wrap', gap:8}}>
                    {['srt', 'vtt', 'ttml', 'csv', 'txt', 'rtf', 'docx', 'pdf'].map(fmt => (
                      <button key={fmt} style={{...S.btnOutline, flex:'1 1 calc(25% - 8px)', minWidth:100, textTransform:'uppercase', fontWeight:700}}
                        onClick={()=>handleConvertDownload(fmt)}>
                        ⬇️ {fmt}
                      </button>
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

              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr 1fr', gap:8, marginBottom:16}}>
                <div style={{background:'#ffffff', border:'1px solid #4338ca30', borderRadius:8, padding:'10px 12px', fontSize:11}}>
                  <div style={{color:'#6366f1', fontWeight:700, marginBottom:4}}>📄 Case 1 — No Script</div>
                  <div style={{color:'#64748b'}}>Upload audio/video only. Whisper generates a full SRT from scratch.</div>
                </div>
                <div style={{background:'#ffffff', border:'1px solid #05966940', borderRadius:8, padding:'10px 12px', fontSize:11}}>
                  <div style={{color:'#059669', fontWeight:700, marginBottom:4}}>📋 Case 2 — Script + Audio</div>
                  <div style={{color:'#64748b'}}>Upload audio + a <strong style={{color:'#059669'}}>fully-timed</strong> cleaned script.</div>
                </div>
                <div style={{background:'#ffffff', border:'1px solid #d9770640', borderRadius:8, padding:'10px 12px', fontSize:11}}>
                  <div style={{color:'#d97706', fontWeight:700, marginBottom:4}}>📋 Case 2B — Partial-Timestamp</div>
                  <div style={{color:'#64748b'}}>Script has only <em>some</em> timecodes. Whisper aligns timecodes.</div>
                </div>
                <div style={{background:'#ffffff', border:'1px solid #e11d4840', borderRadius:8, padding:'10px 12px', fontSize:11}}>
                  <div style={{color:'#e11d48', fontWeight:700, marginBottom:4}}>🔄 Case 3 — Text-to-Text</div>
                  <div style={{color:'#64748b'}}>Upload Clean Script + Timestamps file. AI maps dialogues automatically.</div>
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

              <div style={{marginBottom:14}}>
                <div style={{fontSize:11, fontWeight:700, color:'#e11d48', marginBottom:6}}>🔄 Optional: Upload Correct Timestamps File (Case 3)</div>
                <div style={{fontSize:10, color:'#64748b', marginBottom:8}}>
                  If you already have a subtitle file with correct timestamps but wrong dialogues (e.g. raw Whisper SRT), upload it here instead of audio. 
                  The AI will map the dialogue from your script onto these timestamps.
                </div>
                {!timestampsFile ? (
                  <div className='uploadZone' style={{...S.uploadZone, padding:12, borderColor:'#e11d4840'}} onClick={()=>tsFileRef.current?.click()}>
                    <div style={{fontSize:11, color:'#e11d48'}}>Click to upload Timestamps file (SRT, VTT)</div>
                    <input ref={tsFileRef} type="file" hidden accept=".srt,.vtt,.txt"
                      onChange={e=>tsFileRef.current?.files[0]&&setTimestampsFile(tsFileRef.current.files[0])}/>
                  </div>
                ) : (
                  <div style={{...S.fileChip, borderColor:'#e11d4840'}}>
                    <span style={{fontSize:14}}>⏱️</span>
                    <div style={{flex:1}}><div style={{fontSize:12,color:'#e11d48'}}>{timestampsFile.name}</div></div>
                    <button className='btn-x-hover icon-spin' style={S.btnX} onClick={()=>setTimestampsFile(null)}>✕</button>
                  </div>
                )}
              </div>

              {scriptFile ? (
                  <div style={{marginBottom:14}}>
                    <div style={{fontSize:11, fontWeight:700, color:'#475569', marginBottom:6}}>🎚️ Mapping mode</div>
                    <div style={{display:'flex', gap:8}}>
                      <button
                        type="button"
                        onClick={()=>setAlignMode('full')}
                        style={{flex:1, padding:'8px 10px', borderRadius:8, fontSize:11, fontWeight:700, cursor:'pointer',
                          background: alignMode==='full' ? '#e11d48' : '#f8fafc',
                          color: alignMode==='full' ? '#fff' : '#64748b',
                          border: `1px solid ${alignMode==='full' ? '#e11d48' : '#e2e8f0'}`}}>
                        🔄 Full Map<br/><span style={{fontWeight:400,fontSize:10}}>Adopt both in &amp; out cues from Whisper</span>
                      </button>
                      <button
                        type="button"
                        onClick={()=>setAlignMode('preserve_duration')}
                        style={{flex:1, padding:'8px 10px', borderRadius:8, fontSize:11, fontWeight:700, cursor:'pointer',
                          background: alignMode==='preserve_duration' ? '#d97706' : '#f8fafc',
                          color: alignMode==='preserve_duration' ? '#fff' : '#64748b',
                          border: `1px solid ${alignMode==='preserve_duration' ? '#d97706' : '#e2e8f0'}`}}>
                        🔒 Preserve Duration<br/><span style={{fontWeight:400,fontSize:10}}>Keep original dialogue duration</span>
                      </button>
                      <button
                        type="button"
                        onClick={()=>setAlignMode('ai')}
                        style={{display:'none', flex:1, padding:'8px 10px', borderRadius:8, fontSize:11, fontWeight:700, cursor:'pointer',
                          background: alignMode==='ai' ? '#4f46e5' : '#f8fafc',
                          color: alignMode==='ai' ? '#fff' : '#64748b',
                          border: `1px solid ${alignMode==='ai' ? '#4f46e5' : '#e2e8f0'}`}}>
                        🤖 AI (Llama 3.1)<br/><span style={{fontWeight:400,fontSize:10}}>Refine weak lines with Groq</span>
                      </button>
                    </div>
                    <div style={{marginTop:7,fontSize:10,color:'#4f46e5',fontWeight:600}}>
                      AI refinement is applied automatically to weak matches in both modes.
                    </div>
                  </div>
                ) : null}

              {timestampsFile && scriptFile ? (
                  <button style={{...S.btnPrimary, background:'#e11d48', borderColor:'#e11d48', ...(transcribing ? S.btnOff : {})}} onClick={handleAlignScripts} disabled={transcribing}>
                    {transcribing ? '⏳ Aligning...' : '🔄 Map Script Dialogues to Timestamps'}
                  </button>
              ) : (
                  <button style={{...S.btnPrimary, ...(transcribing || !audioFile ? S.btnOff : {})}} onClick={handleTranscribe} disabled={transcribing || !audioFile}>
                    {transcribing ? '⏳ Transcribing...' : scriptFile ? '✨ Transcribe & Align to Script' : '✨ Transcribe to SRT'}
                  </button>
              )}

              {(transcribing || aiReviewing) && (
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

              {subtitles.length > 0 && (
                <>
                  <div style={{marginTop:14, background:'#ecfdf5', border:'1px solid #05966930', borderRadius:10, padding:'14px 16px'}}>
                    <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:10}}>
                      <div style={{fontSize:13, fontWeight:700, color:'#059669'}}>
                        ✅ {alignStats ? 'Mapping' : 'Transcription'} complete — {subtitles.length} subtitles ready
                      </div>
                      <button style={{background:'none', border:'none', color:'#64748b', fontSize:16, cursor:'pointer'}}
                              onClick={()=>{ setSubtitles([]); setWhisperSubs([]); setAlignStats(null); setCleanStats(null) }}>✕</button>
                    </div>
                    <div style={{fontSize:11, color:'#64748b', marginBottom:12}}>
                      Download the result, or send it to the <strong>Clean</strong> tab for AI formatting.
                    </div>
                    <div style={{display:'flex', gap:8, flexWrap:'wrap'}}>
                      <button style={{...S.btnSm, background:'#059669', borderColor:'#059669', color:'#fff'}} onClick={exportSRT}>⬇ SRT</button>
                      <button style={{...S.btnSm, background:'#059669', borderColor:'#059669', color:'#fff'}} onClick={exportTXT}>⬇ TXT</button>
                      <button style={{...S.btnSm, background:'#059669', borderColor:'#059669', color:'#fff'}} onClick={exportDOCX}>⬇ DOCX</button>
                      <button style={{...S.btnSm, background:'#059669', borderColor:'#059669', color:'#fff'}} onClick={exportPDF}>⬇ PDF</button>
                      {alignStats && !subtitles.some(sub => (sub.manual_placement || !sub.start_time) && sub.text?.trim()) && (
                        <button style={{...S.btnSm, background:'#4f46e5', borderColor:'#4f46e5', color:'#fff'}}
                                onClick={handleAiReviewAlignment} disabled={aiReviewing}>
                          {aiReviewing ? 'AI checking weak matches...' : 'AI Check Weak Matches'}
                        </button>
                      )}
                      <button style={{...S.btnSm, marginLeft:'auto', background:'#4f46e5', borderColor:'#4f46e5', color:'#fff'}}
                              onClick={()=>setTab('clean')}>🧹 Take to Cleaning →</button>
                    </div>
                  </div>
                  {subtitles.some(sub => (sub.manual_placement || !sub.start_time) && sub.text?.trim()) && (
                    <div style={{marginTop:10, background:'#fff7ed', border:'1px solid #fdba74', borderRadius:10, padding:'12px 14px'}}>
                      <div style={{fontSize:12, fontWeight:700, color:'#c2410c', marginBottom:5}}>Manual timestamp placement required</div>
                      <div style={{fontSize:11, color:'#9a3412', marginBottom:8}}>
                        These original script dialogues need a subtitle editor's timing pass. Safe gaps are used where possible; anything without a safe gap remains in TXT/DOCX exports and Cleaning, because SRT cannot include a cue without timestamps.
                      </div>
                      <button style={{...S.btnSm, marginBottom:8, background:'#c2410c', borderColor:'#c2410c', color:'#fff'}}
                              onClick={handleAiReviewAlignment} disabled={aiReviewing}>
                        {aiReviewing ? 'AI is mapping the remaining lines...' : 'AI Map Remaining Lines'}
                      </button>
                      <div style={{fontSize:10, color:'#9a3412', marginBottom:6}}>
                        AI uses the supplied timed cues to place the lines below. Any line it cannot match confidently stays flagged for manual timing.
                      </div>
                      {subtitles.filter(sub => (sub.manual_placement || !sub.start_time) && sub.text?.trim()).map((sub, index) => (
                        <div key={`${sub.id || index}-${index}`} style={{fontSize:11, color:'#7c2d12', padding:'6px 0', borderTop:index ? '1px solid #fed7aa' : 'none'}}>
                          <strong>#{sub.id || index + 1}</strong>{sub.start_time ? ` (${sub.start_time} → ${sub.end_time})` : ' (no safe gap)'} — {sub.text}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}

              {transcribeError && <div style={{...S.errBox, marginTop:14}}><div style={{fontSize:12,color:'#dc2626'}}>{transcribeError}</div></div>}
            </div>
          </div>
        )}

        {/* ══ SUBTITLE EDIT TAB ══ */}
        <div style={{ display: tab === 'subtitle' ? 'block' : 'none' }}>
          <SubtitleEditor />
        </div>



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
                  <a key={movie.id || `${movie.title}-${movie.url}`} href={/^https?:\/\//i.test(movie.url || '') ? movie.url : (movie.url ? `https://${movie.url}` : '#')} target='_blank' rel='noreferrer'
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
                  {allPlatforms.map(([k, p, label]) => <option key={k} value={k}>{label}</option>)}
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
                    <div style={S.uploadSub}>SRT · TXT · DOC · PAC · any format</div>
                    <input ref={qcFileRef} type="file" hidden
                      accept=".srt,.vtt,.txt,.doc,.docx,.pdf,.rtf,.xml,.ttml,.dfxp,.xlsx,.xls,.csv,.json,.pac"
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
                  <option value=''>All Platforms &amp; Versions</option>
                  {Object.entries(platformFamilies).map(([fam, f]) => (
                    <optgroup key={fam} label={f.displayName}>
                      {f.versions.map(v => (
                        <option key={v.key} value={v.key}>{f.displayName} — {v.version_label || 'Current'}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                <div style={{display:'flex',gap:8, marginBottom: 16}}>
                  <button style={S.btnOutline} onClick={() => { setSearchKeyword(''); setSearchPlatformFilter(''); }}>Clear Filters</button>
                </div>
              </div>

              <div id='add-platform-section' className='card' style={S.card}>
                <div style={S.label}>➕ Add Custom Platform</div>
                <div style={{fontSize:11,color:'#64748b',marginBottom:14}}>
                  Upload a document to extract quality check rules automatically.
                </div>
                {excelSheets.length === 0 && (
                  <input style={S.input} placeholder="Platform Name (e.g. Netflix)" value={uniPlatform} onChange={e=>setUniPlatform(e.target.value)}/>
                )}
                <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, marginBottom:6}}>
                  <div>
                    <div style={{fontSize:10,color:'#64748b',marginBottom:4,fontWeight:600,textTransform:'uppercase',letterSpacing:0.5}}>Version / Year Label</div>
                    <input style={{...S.input, marginBottom:0}} placeholder="e.g. Current, 2022, v10" value={uniVersionLabel} onChange={e=>setUniVersionLabel(e.target.value)}/>
                    <div style={{fontSize:10,color:'#94a3b8',marginTop:3}}>Same platform + same version = overwrite existing</div>
                  </div>
                </div>
                <div style={{fontSize:11,color:'#64748b',marginBottom:6}}>Upload guidelines documents/images</div>
                {uniFiles.length === 0 ? (
                  <div className='uploadZone' style={{...S.uploadZone,padding:14}} onClick={()=>document.getElementById('unified-gl-in').click()}>
                    <div style={{fontSize:11,color:'#64748b',marginBottom:6}}>PDF · DOC · TXT · XLSX · PNG · JPG</div>
                    <button style={S.btnOutline}>Upload Files</button>
                    <input id="unified-gl-in" type="file" hidden multiple accept=".doc,.docx,.pdf,.txt,.rtf,.xls,.xlsx,.png,.jpg,.jpeg,.webp" onChange={e=>handleFilesSelect(e.target.files)}/>
                  </div>
                ) : (
                  <div style={{display:'flex', flexDirection:'column', gap:4, marginBottom:10}}>
                    {uniFiles.map((f, i) => (
                      <div key={i} style={{...S.fileChip}}>
                        <span>📄</span><span style={{flex:1,fontSize:12,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{f.name}</span>
                        <button className='btn-x-hover icon-spin' style={S.btnX} onClick={(e)=>{
                          e.stopPropagation();
                          const newFiles = uniFiles.filter((_, idx) => idx !== i);
                          setUniFiles(newFiles);
                          if(newFiles.length === 0) {
                            setExcelSheets([]); setSelectedSheets([]); setBulkProgress({active:false,current:0,total:0,currentSheet:''});
                          }
                        }}>✕</button>
                      </div>
                    ))}
                  </div>
                )}
                
                {excelSheets.length > 0 && (
                  <div style={{border:'1px solid #e2e8f0',borderRadius:12,background:'#f8fafc',maxHeight:240,overflowY:'auto',padding:8, marginBottom: 12}}>
                    <div style={{fontSize:12,fontWeight:700,color:'#4f46e5',marginBottom:8,padding:'0 4px'}}>Select sheets to import as separate platforms:</div>
                    {excelSheets.map(sheet => {
                      const isSelected = selectedSheets.includes(sheet);
                      return (
                        <label key={sheet} style={{display:'flex',alignItems:'center',gap:12,padding:'8px 12px',background:isSelected?'#ffffff':'transparent',border:isSelected?'1px solid #6366f1':'1px solid transparent',borderRadius:8,marginBottom:4,cursor:'pointer',transition:'all 0.2s',boxShadow:isSelected?'0 1px 2px rgba(0,0,0,0.02)':'none'}}>
                          <input type="checkbox" 
                            style={{width:16,height:16,accentColor:'#4f46e5'}}
                            checked={isSelected}
                            disabled={uniProcessing}
                            onChange={(e) => {
                              if (e.target.checked) setSelectedSheets(prev => [...prev, sheet]);
                              else setSelectedSheets(prev => prev.filter(s => s !== sheet));
                            }}
                          />
                          <span style={{fontSize:13,fontWeight:isSelected?700:500,color:isSelected?'#1e293b':'#64748b'}}>{sheet}</span>
                        </label>
                      );
                    })}
                  </div>
                )}
                
                {excelSheets.length === 0 && (
                  <>
                    <div style={{fontSize:11,color:'#64748b',marginBottom:6,marginTop:10}}>Or paste guidelines text</div>
                    <textarea style={{...S.textarea, marginBottom:12}} placeholder="Paste guidelines text here..." value={uniText} onChange={e=>setUniText(e.target.value)} rows={4}/>
                  </>
                )}

                {importProgress.active && (
                  <div style={{...S.progressContainer, marginTop:12, marginBottom:12}}>
                    <div style={S.progressMeta}>
                      <span style={S.progressMsg}>
                        {importProgress.sheet ? `Extracting rules — "${importProgress.sheet}"` : (importProgress.msg || 'Processing...')}
                      </span>
                      <span style={S.progressPct}>{importProgress.pct}%</span>
                    </div>
                    <div style={{...S.progressBarOuter, marginTop: 8}}>
                      <div style={{...S.progressBarInner, width: `${importProgress.pct}%`}}></div>
                    </div>
                  </div>
                )}

                {bulkProgress.active && (
                  <div style={{...S.progressContainer, marginTop:12, marginBottom:12}}>
                    <div style={S.progressMeta}>
                      <span style={S.progressMsg}>Processing: <strong>{bulkProgress.currentSheet}</strong></span>
                      <span style={S.progressPct}>{Math.round((bulkProgress.current / bulkProgress.total) * 100)}%</span>
                    </div>
                    <div style={{...S.progressBarOuter, marginTop: 8}}>
                      <div style={{...S.progressBarInner, width: `${(bulkProgress.current / bulkProgress.total) * 100}%`}}></div>
                    </div>
                  </div>
                )}

                <button style={{...S.btnPrimary,...(uniProcessing?S.btnOff:{})}} onClick={handleUnifiedProcess} disabled={uniProcessing || (excelSheets.length > 0 && selectedSheets.length === 0)}>
                  {uniProcessing ? 'AI Processing...' : excelSheets.length > 0 ? `🚀 Import ${selectedSheets.length} Platforms` : '🚀 Generate QC Rules'}
                </button>
                {uniMsg&&<div style={{background:'#ecfdf5',border:'1px solid #05966930',borderRadius:8,padding:'10px 14px',fontSize:12,color:'#059669',marginTop:10}}>✅ {uniMsg}</div>}
                {uniErr&&<div style={{...S.errBox, marginTop: 10}}><div style={{fontSize:12,color:'#dc2626'}}>{uniErr}</div></div>}
              </div>
            </div>

            <div style={S.right}>
              <div className='card' style={S.card}>
                <div style={S.label}>Platform Rules Library</div>
                <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', gap:12, marginBottom:6}}>
                  <div style={{fontSize:12,color:'#64748b'}}>
                    Platforms are grouped by family. Click any version to view &amp; edit its rules.
                  </div>
                  <button
                    style={{background:'#dc2626', color:'#fff', border:'none', borderRadius:6, fontSize:11, fontWeight:700, padding:'6px 12px', cursor:'pointer', whiteSpace:'nowrap'}}
                    onClick={handleDeleteAllPlatforms}
                  >🗑 Delete All Platforms</button>
                </div>

                <div style={{display:'flex', flexDirection:'column', gap:14}}>
                  {Object.entries(platformFamilies)
                    .filter(([fam, f]) => {
                      if (searchPlatformFilter) {
                        return f.versions.some(v => v.key === searchPlatformFilter)
                      }
                      if (searchKeyword.trim()) {
                        const kw = searchKeyword.toLowerCase()
                        if (f.displayName.toLowerCase().includes(kw)) return true
                        return f.versions.some(v =>
                          (v.version_label||'').toLowerCase().includes(kw) ||
                          (v.rules||[]).some(r => r.toLowerCase().includes(kw)) ||
                          (v.subtitler_rules||[]).some(r => r.toLowerCase().includes(kw))
                        )
                      }
                      return true
                    })
                    .map(([fam, f]) => {
                      // If filtered to a specific version, only show that version
                      const versionsToShow = searchPlatformFilter
                        ? f.versions.filter(v => v.key === searchPlatformFilter)
                        : f.versions

                      return (
                        <div key={fam} style={{background:'#f8fafc', border:'1px solid #cbd5e1', borderRadius:10, overflow:'hidden'}}>
                          {/* Family header */}
                          <div style={{background:'linear-gradient(135deg,#1e293b,#334155)', padding:'10px 14px', display:'flex', alignItems:'center', justifyContent:'space-between'}}>
                            <div style={{fontSize:13, fontWeight:700, color:'#f1f5f9'}}>{f.displayName}</div>
                            <div style={{display:'flex', alignItems:'center', gap:8}}>
                              <button style={{background:'#4f46e5',color:'#fff',border:'none',borderRadius:4,fontSize:10,fontWeight:700,padding:'3px 8px',cursor:'pointer'}} onClick={(e) => { e.stopPropagation(); setUniPlatform(f.displayName); setUniVersionLabel(''); document.getElementById('add-platform-section')?.scrollIntoView({behavior: 'smooth'}) }}>➕ Add Version</button>
                              <span style={{fontSize:10, color:'#94a3b8'}}>{f.versions.length} version{f.versions.length!==1?'s':''}</span>
                              {f.versions[0]?.is_custom && (
                                <button
                                  style={{background:'#dc2626',color:'#fff',border:'none',borderRadius:4,fontSize:10,fontWeight:700,padding:'3px 8px',cursor:'pointer'}}
                                  onClick={e => { e.stopPropagation(); if(confirm(`Delete ALL versions of ${f.displayName}?`)) { axios.delete(`${API}/platforms/family/${fam}`).then(loadPlatforms) } }}
                                >🗑 Delete All</button>
                              )}
                            </div>
                          </div>

                          {/* Version rows */}
                          <div style={{padding:'8px 10px', display:'flex', flexDirection:'column', gap:6}}>
                            {versionsToShow.map(v => {
                              const matchingRules = searchKeyword.trim()
                                ? [...(v.rules||[]), ...(v.subtitler_rules||[])].filter(r => r.toLowerCase().includes(searchKeyword.toLowerCase()))
                                : []

                              return (
                                <div key={v.key}
                                  style={{background:'#ffffff', border:'1px solid #e2e8f0', borderRadius:8, padding:'10px 12px', cursor:'pointer', transition:'box-shadow 0.15s ease'}}
                                  onClick={() => { setEditingPlatform({...v, platform_key: v.key}); setEditRulesText((v.rules||[]).join('\n')); setEditSubtitlerRulesText((v.subtitler_rules||[]).join('\n')); setEditRulesTab('script') }}
                                >
                                  <div style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap'}}>
                                    {/* Version badge */}
                                    <span style={{background: (v.version_label||'').toLowerCase()==='current' ? '#059669' : '#6366f1', color:'#fff', fontSize:10, fontWeight:700, padding:'2px 8px', borderRadius:20}}>
                                      {v.version_label || 'Current'}
                                    </span>
                                    <div style={{flex:1, fontSize:12, color:'#334155'}}>
                                      {v.max_chars_per_line} chars/line · {v.max_lines} lines
                                      <span style={{color:'#059669',fontWeight:600,marginLeft:8}}>{(v.rules||[]).length} AI Rules</span>
                                      <span style={{color:'#6366f1',fontWeight:600,marginLeft:8}}>{(v.subtitler_rules||[]).length} Human Tasks (GTS Pro)</span>
                                    </div>
                                    {v.created_at && <span style={{fontSize:10,color:'#94a3b8'}}>{new Date(v.created_at).toLocaleDateString()}</span>}
                                    <button style={{background:'none',border:'none',cursor:'pointer',fontSize:14,color:'#94a3b8',padding:'2px 4px'}} onClick={e => { e.stopPropagation(); handleDeletePlatform(v.key) }}>🗑</button>
                                  </div>

                                  {searchKeyword.trim() && matchingRules.length > 0 && (
                                    <div style={{marginTop:8, background:'#f8fafc', border:'1px solid #e2e8f0', borderRadius:6, padding:'7px 10px'}}>
                                      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:5}}>
                                        <div style={{fontSize:10,fontWeight:700,color:'#6366f1'}}>🔍 Matching Rules:</div>
                                        {v.guidelines_raw && (
                                          <button
                                            style={{background:'#4f46e5',color:'#fff',border:'none',borderRadius:4,fontSize:10,fontWeight:700,padding:'3px 8px',cursor:'pointer'}}
                                            onClick={e => { e.stopPropagation(); setViewSourceRaw({ text: v.guidelines_raw, keyword: searchKeyword, title: `${f.displayName} — ${v.version_label}`, sourceFiles: v.source_files }) }}
                                          >📄 View Source</button>
                                        )}
                                      </div>
                                      {matchingRules.slice(0, 3).map((r, i) => (
                                        <div key={i} style={{fontSize:11, color:'#334155', marginBottom:3, lineHeight:1.4}}>• {r}</div>
                                      ))}
                                      {matchingRules.length > 3 && <div style={{fontSize:10,color:'#64748b',marginTop:2}}>+ {matchingRules.length - 3} more...</div>}
                                    </div>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      )
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
          <div style={{background:'#ffffff',border:'1px solid #4338ca',borderRadius:12,padding:24,width:700,maxWidth:'95%',maxHeight:'90vh',display:'flex',flexDirection:'column'}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
              <div style={{fontSize:18,fontWeight:700}}>📝 Rules: {editingPlatform.name}</div>
              <div style={{display:'flex',gap:10}}>
                {editingPlatform.guidelines_raw && (
                  <button 
                    style={{background:'#f1f5f9',color:'#475569',border:'none',borderRadius:6,fontSize:12,fontWeight:700,padding:'6px 12px',cursor:'pointer'}}
                    onClick={() => setViewSourceRaw({ text: editingPlatform.guidelines_raw, keyword: '', title: `${editingPlatform.name}`, sourceFiles: editingPlatform.source_files })}
                  >
                    📄 View Source Doc
                  </button>
                )}
                <button style={{background:'none',border:'none',color:'#64748b',fontSize:20,cursor:'pointer'}} onClick={()=>setEditingPlatform(null)}>✕</button>
              </div>
            </div>
            
            <div style={{display:'flex',gap:6,marginBottom:16}}>
              <button 
                style={{flex:1,padding:'8px 12px',background:editRulesTab==='script'?'#eef2ff':'#f8fafc',border:`1px solid ${editRulesTab==='script'?'#6366f1':'#e2e8f0'}`,borderRadius:8,color:editRulesTab==='script'?'#4f46e5':'#64748b',fontWeight:700,cursor:'pointer',fontSize:13,transition:'all 0.2s ease'}}
                onClick={()=>setEditRulesTab('script')}
              >
                🤖 AI Cleaning Rules
              </button>
              <button 
                style={{flex:1,padding:'8px 12px',background:editRulesTab==='subtitler'?'#fffbeb':'#f8fafc',border:`1px solid ${editRulesTab==='subtitler'?'#d97706':'#e2e8f0'}`,borderRadius:8,color:editRulesTab==='subtitler'?'#b45309':'#64748b',fontWeight:700,cursor:'pointer',fontSize:13,transition:'all 0.2s ease'}}
                onClick={()=>setEditRulesTab('subtitler')}
              >
                👤 Human Tasks - GTS Pro / IYUNO
              </button>
            </div>

            {editRulesTab === 'script' ? (
              <>
                <div style={{fontSize:12,color:'#6366f1',marginBottom:12,lineHeight:1.4}}>
                  Rules applied automatically by the <strong>AI text cleaner</strong>: character &amp; line limits, punctuation, capitalisation, italics, profanity, HOH/sound removal, filler words, speaker labels, acronyms, number formatting, and line-splitting. Each line is one rule.
                </div>
                <textarea 
                  style={{...S.textarea, flex:1, minHeight:350, fontFamily:'monospace', fontSize:13, lineHeight:1.6, borderColor:'#cbd5e1', background:'#ffffff'}} 
                  value={editRulesText} 
                  onChange={e=>setEditRulesText(e.target.value)} 
                  spellCheck="false"
                />
              </>
            ) : (
              <>
                <div style={{fontSize:12,color:'#b45309',marginBottom:12,lineHeight:1.4}}>
                  <strong>Two types of rules are stored here:</strong><br/>
                  <span style={{color:'#059669',fontWeight:600}}>⚙ Timing rules</span> (CPS/reading-speed, duration, frame gaps, zero-subtitle) are <em>machine-applied</em> by the operational engine.<br/>
                  <span style={{color:'#b45309',fontWeight:600}}>👤 Human tasks</span> completed manually in <strong>GTS Pro / IYUNO</strong> after importing the cleaned script: positioning, font, file naming, spellcheck, translator credits.
                </div>
                <textarea 
                  style={{...S.textarea, flex:1, minHeight:350, fontFamily:'monospace', fontSize:13, lineHeight:1.6, borderColor:'#cbd5e1', background:'#ffffff'}} 
                  value={editSubtitlerRulesText} 
                  onChange={e=>setEditSubtitlerRulesText(e.target.value)} 
                  spellCheck="false"
                />
              </>
            )}

            <div style={{display:'flex',alignItems:'center',gap:12,marginTop:16}}>
              <button style={{...S.btnPrimary, flex:1}} onClick={async () => {
                try {
                  const payload = {
                    rules: editRulesText.split('\n').map(r => r.trim()).filter(Boolean),
                    subtitler_rules: editSubtitlerRulesText.split('\n').map(r => r.trim()).filter(Boolean)
                  }
                  await axios.patch(`/api/platforms/${editingPlatform.platform_key}/meta`, payload)
                  setEditPlatformMsg('Rules updated successfully.')
                  setEditPlatformErr('')
                  loadPlatforms()
                } catch(e) {
                  setEditPlatformErr('Failed to save rules.')
                }
              }}>💾 Save Rules</button>
            </div>
            {editPlatformMsg && <div style={{marginTop:12,background:'#ecfdf5',border:'1px solid #05966930',borderRadius:8,padding:'8px',color:'#059669',fontSize:12,textAlign:'center'}}>✅ {editPlatformMsg}</div>}
            {editPlatformErr && <div style={{marginTop:12,background:'#fef2f2',border:'1px solid #dc262630',borderRadius:8,padding:'8px',color:'#dc2626',fontSize:12,textAlign:'center'}}>❌ {editPlatformErr}</div>}
          </div>
        </div>
      )}

      {/* ══ SOURCE VIEW MODAL ══ */}
      {viewSourceRaw && (
        <div style={{position:'fixed',inset:0,background:'rgba(15,23,42,0.6)',backdropFilter:'blur(6px)',zIndex:9999,display:'flex',alignItems:'center',justifyContent:'center',padding:16}}
          onClick={e=>{if(e.target===e.currentTarget)setViewSourceRaw(null)}}>
          <div style={{background:'#fff',borderRadius:16,boxShadow:'0 25px 60px rgba(0,0,0,0.25)',width:'95vw',maxWidth:1450,height:'92vh',maxHeight:'92vh',display:'flex',flexDirection:'column',overflow:'hidden'}}
            onClick={e=>e.stopPropagation()}>
            <div style={{padding:'16px 24px',borderBottom:'1px solid #e2e8f0',display:'flex',justifyContent:'space-between',alignItems:'center',background:'linear-gradient(135deg,#f8fafc 0%,#f1f5f9 100%)'}}>
              <div>
                <div style={{fontSize:16,fontWeight:800,color:'#1e293b'}}>📄 Original Source Document</div>
                <div style={{fontSize:12,color:'#64748b',marginTop:2}}>{viewSourceRaw.title}</div>
              </div>
              <button style={{background:'none',border:'none',color:'#64748b',fontSize:22,cursor:'pointer',lineHeight:1}} onClick={()=>setViewSourceRaw(null)}>✕</button>
            </div>
            <div style={{padding:'16px',overflowY:'auto',flex:1,background:'#f8fafc',fontFamily:'system-ui, -apple-system, sans-serif',fontSize:13,lineHeight:1.6,color:'#334155',display:'flex',flexDirection:'column'}}>
              <SourceDocViewer raw={viewSourceRaw} />
            </div>
          </div>
        </div>
      )}



      {/* ══ TRACK CHANGES MODAL ══ */}
      {trackChangesOpen && trackChangesData && (() => {
        // ── Word-level diff: returns JSX spans with removed/added highlighting ──
        const wordDiff = (original, cleaned, mode = 'combined') => {
          // Keep SRT formatting tags and whitespace as their own tokens.  A
          // tag attached to a word ("<i>Once") used to be treated as one
          // word, so a tag-only edit looked like the word had been removed and
          // retyped.  This makes the audit show exactly what changed.
          const tokenise = text => (text || '')
            .split(/(<\/?[ib]>|\s+)/i)
            .filter(Boolean)
          const ow = tokenise(original)
          const cw = tokenise(cleaned)
          const n = ow.length, m = cw.length
          const dp = Array.from({length:n+1}, ()=>new Array(m+1).fill(0))
          for (let i=1;i<=n;i++) for (let j=1;j<=m;j++)
            dp[i][j] = ow[i-1]===cw[j-1] ? dp[i-1][j-1]+1 : Math.max(dp[i-1][j],dp[i][j-1])
          let i=n, j=m
          const ops=[]
          while(i>0||j>0){
            if(i>0&&j>0&&ow[i-1]===cw[j-1]){ops.push({t:'eq',w:ow[i-1]});i--;j--}
            else if(j>0&&(i===0||dp[i][j-1]>=dp[i-1][j])){ops.push({t:'ins',w:cw[j-1]});j--}
            else{ops.push({t:'del',w:ow[i-1]});i--}
          }
          ops.reverse()
          // 'combined' = show all ops together (deletions struck through + insertions green)
          // 'after'    = show only unchanged + insertions (clean final text)
          // 'before'   = show only unchanged + deletions (clean original text)
          return ops.map((op,k) => {
            if(op.t==='eq') return <span key={k}>{op.w}</span>
            if(op.t==='del') {
              if (mode === 'after') return null   // hide deletions in clean-after view
              return <span key={k} style={{background:'#fee2e2',color:'#991b1b',textDecoration:'line-through',textDecorationColor:'#dc2626',textDecorationThickness:'2px',borderRadius:3,padding:'0 2px'}}>{op.w}</span>
            }
            // insertion
            if (mode === 'before') return null  // hide insertions in clean-before view
            return <span key={k} style={{background:'#bbf7d0',color:'#065f46',borderRadius:3,padding:'0 2px',fontWeight:600}}>{op.w}</span>
          })
        }
        // Preserve every cue in the report so unchanged text cannot look lost.
        const reportEntries = trackChangesData.entries || trackChangesData.changes || []

        return (
          <div style={{position:'fixed',top:0,left:0,right:0,bottom:0,background:'rgba(15,23,42,0.75)',backdropFilter:'blur(4px)',display:'flex',alignItems:'center',justifyContent:'center',zIndex:999}}
            onClick={(e)=>{if(e.target===e.currentTarget) setTrackChangesOpen(false)}}>
            <div style={{background:'#ffffff',borderRadius:16,boxShadow:'0 25px 60px rgba(0,0,0,0.25)',width:900,maxWidth:'95vw',maxHeight:'92vh',display:'flex',flexDirection:'column',overflow:'hidden'}}>

              {/* Header */}
              <div style={{padding:'20px 24px',borderBottom:'1px solid #e2e8f0',display:'flex',justifyContent:'space-between',alignItems:'flex-start',background:'linear-gradient(135deg,#f8faff 0%,#eef2ff 100%)'}}>
                <div>
                  <div style={{fontSize:19,fontWeight:800,color:'#1e293b',marginBottom:4}}>📝 Track Changes Report</div>
                  <div style={{fontSize:13,color:'#64748b',fontWeight:500}}>
                    Platform: <strong style={{color:'#4f46e5'}}>{trackChangesData.platform}</strong>
                    <span style={{margin:'0 10px',color:'#cbd5e1'}}>·</span>
                    <span style={{color:'#dc2626',fontWeight:700}}>{trackChangesData.changed_lines} changed</span>
                    <span style={{margin:'0 10px',color:'#cbd5e1'}}>·</span>
                    <span style={{color:'#059669',fontWeight:700}}>{trackChangesData.unchanged_lines} unchanged</span>
                    <span style={{margin:'0 10px',color:'#cbd5e1'}}>·</span>
                    {trackChangesData.total_lines} total lines
                  </div>
                </div>
                <button style={{background:'none',border:'none',color:'#64748b',fontSize:22,cursor:'pointer',lineHeight:1}} onClick={()=>setTrackChangesOpen(false)}>✕</button>
              </div>

              {/* Legend */}
              <div style={{padding:'10px 24px',background:'#f8fafc',borderBottom:'1px solid #f1f5f9',display:'flex',gap:20,fontSize:11,color:'#64748b',alignItems:'center',flexWrap:'wrap'}}>
                <span style={{fontWeight:700,color:'#475569'}}>Legend:</span>
                <span><span style={{background:'#fecaca',color:'#991b1b',borderRadius:3,padding:'1px 5px',textDecoration:'line-through'}}>word</span> = removed</span>
                <span><span style={{background:'#bbf7d0',color:'#065f46',borderRadius:3,padding:'1px 5px',fontWeight:700}}>word</span> = added</span>
                <span><span style={{background:'#dbeafe',color:'#1e40af',borderRadius:3,padding:'1px 5px'}}>1→3</span> = split into multiple lines</span>
              </div>

              {/* Change cards */}
              <div style={{overflowY:'auto',flex:1,padding:'16px 24px'}}>
                {reportEntries.length === 0 ? (
                  <div style={{textAlign:'center',color:'#64748b',padding:60,fontSize:15}}>
                    ✅ No changes were made — every line was already clean.
                  </div>
                ) : (
                  reportEntries.map(c => {
                    const cleanedLines = (c.new_text || '').split('\n').filter(l => l.trim())
                    const isSplit = cleanedLines.length > 1
                    const isChanged = c.changed !== false
                    const ids = c.ids || [c.id]
                    const idLabel = ids.length === 1
                      ? `Line #${ids[0]}`
                      : `Lines #${ids[0]}–#${ids[ids.length-1]}`

                    return (
                      <div key={c.id} style={{
                        border: c.flagged ? '1.5px solid #fca5a5' : (isChanged ? '1px solid #e2e8f0' : '1px solid #d1fae5'),
                        borderRadius: 12, marginBottom: 12, overflow:'hidden',
                        boxShadow: '0 2px 8px rgba(0,0,0,0.04)'
                      }}>
                        {/* Card header — line ID + badges only, no rules */}
                        <div style={{display:'flex',alignItems:'center',gap:8,padding:'8px 14px',background: c.flagged ? '#fff1f2' : '#f8fafc',borderBottom:'1px solid #e2e8f0',flexWrap:'wrap'}}>
                          <span style={{fontSize:11,fontWeight:700,color:'#94a3b8',letterSpacing:0.5}}>{idLabel}</span>
                          {!isChanged && (
                            <span style={{fontSize:10,fontWeight:700,background:'#dcfce7',color:'#166534',borderRadius:4,padding:'2px 7px'}}>Unchanged</span>
                          )}
                          {isSplit && (
                            <span style={{fontSize:10,fontWeight:700,background:'#dbeafe',color:'#1e40af',borderRadius:4,padding:'2px 7px'}}>
                              Split 1 → {cleanedLines.length} lines
                            </span>
                          )}
                          {c.flagged && (
                            <span style={{fontSize:10,fontWeight:700,background:'#fef2f2',color:'#dc2626',borderRadius:4,padding:'2px 7px'}}>
                              ⚠ {c.flag_reason}
                            </span>
                          )}
                        </div>

                        {/* Before / After columns */}
                        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr'}}>
                          {/* BEFORE — plain original text */}
                          <div style={{padding:'12px 14px',borderRight:'2px solid #e2e8f0',background:'#fff5f5'}}>
                            <div style={{fontSize:10,fontWeight:800,color:'#dc2626',marginBottom:6,textTransform:'uppercase',letterSpacing:0.8}}>❌ Before</div>
                            <div style={{fontSize:13,color:'#7f1d1d',lineHeight:1.6,whiteSpace:'pre-wrap',fontFamily:"'JetBrains Mono',Consolas,monospace"}}>
                              {c.original_text}
                            </div>
                          </div>
                          {/* AFTER — combined diff: ~~removed~~ + added, Word-style */}
                          <div style={{padding:'12px 14px',background:'#f0fdf4'}}>
                            <div style={{fontSize:10,fontWeight:800,color:'#059669',marginBottom:6,textTransform:'uppercase',letterSpacing:0.8}}>✅ After</div>
                            <div style={{fontSize:13,lineHeight:1.6,whiteSpace:'pre-wrap',fontFamily:"'JetBrains Mono',Consolas,monospace"}}>
                              {wordDiff(c.original_text, c.new_text || cleanedLines.join('\n'), 'combined')}
                            </div>
                          </div>
                        </div>

                        {/* Rules footer — full width, full text, no truncation */}
                        {c.rules_applied && c.rules_applied.length > 0 && (
                          <div style={{padding:'8px 14px',background:'#f8fafc',borderTop:'1px solid #e2e8f0'}}>
                            <div style={{fontSize:10,fontWeight:700,color:'#64748b',marginBottom:5,textTransform:'uppercase',letterSpacing:0.6}}>
                              📋 Rules Applied ({c.rules_applied.length})
                            </div>
                            <div style={{display:'flex',flexWrap:'wrap',gap:'4px 12px'}}>
                              {c.rules_applied.map((r,i) => (
                                <span key={i} style={{fontSize:11,color:'#475569',lineHeight:1.6}}>
                                  <span style={{color:'#94a3b8',marginRight:3}}>•</span>{r}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })
                )}
              </div>

              {/* Footer */}
              <div style={{padding:'16px 24px',borderTop:'1px solid #e2e8f0',display:'flex',gap:10,background:'#f8fafc'}}>
                <button style={{...S.btnPrimary, flex:1}} onClick={exportTrackChangesPDF}>⬇️ Download Full Report (PDF)</button>
                <button style={{...S.btnOutline}} onClick={()=>setTrackChangesOpen(false)}>Close</button>
              </div>
            </div>
          </div>
        )
      })()}


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
