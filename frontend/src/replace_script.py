import sys

with open('App.jsx', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. scriptFileRef
content = content.replace(
    '<div style={{fontSize:11, color:\'#059669\'}}>Click to upload script file (DOC, DOCX, PDF, SRT, TXT)</div>\n                    <input ref={scriptFileRef} type="file" hidden accept=".doc,.docx,.pdf,.srt,.txt,.vtt"',
    '<div style={{fontSize:11, color:\'#059669\'}}>Click to upload script file (PMW, DOC, DOCX, PDF, SRT, TXT)</div>\n                    <input ref={scriptFileRef} type="file" hidden accept=".pmw,.doc,.docx,.pdf,.srt,.txt,.vtt"'
)

# 2. tcFileRef
content = content.replace(
    '<div style={S.uploadSub}>SRT / VTT / DOC / DOCX / PDF / XML / TTML</div>\n                    <input ref={tcFileRef} type=\'file\' hidden accept=\'.srt,.vtt,.doc,.docx,.pdf,.xml,.ttml,.dfxp,.txt\'',
    '<div style={S.uploadSub}>PMW / SRT / VTT / DOC / DOCX / PDF / XML / TTML</div>\n                    <input ref={tcFileRef} type=\'file\' hidden accept=\'.pmw,.srt,.vtt,.doc,.docx,.pdf,.xml,.ttml,.dfxp,.txt\''
)

# 3. qcFileRef
content = content.replace(
    '<div style={S.uploadSub}>SRT · TXT · DOC · any format</div>\n                    <input ref={qcFileRef} type="file" hidden\n                      accept=".srt,.vtt,.txt,.doc,.docx,.pdf,.rtf,.xml,.ttml,.dfxp,.xlsx,.xls,.csv,.json"',
    '<div style={S.uploadSub}>PMW · SRT · TXT · DOC · any format</div>\n                    <input ref={qcFileRef} type="file" hidden\n                      accept=".pmw,.srt,.vtt,.txt,.doc,.docx,.pdf,.rtf,.xml,.ttml,.dfxp,.xlsx,.xls,.csv,.json"'
)

with open('App.jsx', 'w', encoding='utf-8') as f:
    f.write(content)

print('Replacements done.')
