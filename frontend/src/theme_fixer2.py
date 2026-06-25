import re
import os

filepath = r"d:\Downloads\OTTWatchX\subtitleai-v2\subtitleai-v2\frontend\src\App.jsx"
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

new_s = """const S = {
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
  select: { width:'100%', padding:'14px 16px', background:'#f8fafc', border:'1.5px solid #e2e8f0', borderRadius:12, color:'#0f172a', fontSize:14, fontWeight:600, cursor:'pointer', transition: 'all 0.2s ease', appearance: 'none', backgroundImage: 'url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 24 24\\' fill=\\'none\\' stroke=\\'%2364748b\\' stroke-width=\\'2\\' stroke-linecap=\\'round\\' stroke-linejoin=\\'round\\'%3e%3cpolyline points=\\'6 9 12 15 18 9\\'%3e%3c/polyline%3e%3c/svg%3e")', backgroundRepeat: 'no-repeat', backgroundPosition: 'right 16px center', backgroundSize: '16px' },
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
}"""

content = re.sub(r'const S = \{.*?\n\}', new_s, content, flags=re.DOTALL)

# Fix the manual inline style overrides in App.jsx
content = content.replace(
    "style={{...S.btnOutline,flex:1,...(extracting||cleaning||!file?S.btnOff:{}),borderColor:'#4338ca',color:'#6366f1'}}",
    "style={{...S.btnOutline,flex:1,...(extracting||cleaning||!file?S.btnOff:{})}}"
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated beautifully.")
