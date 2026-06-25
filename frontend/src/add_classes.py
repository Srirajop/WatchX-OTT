import re

filepath = r"d:\Downloads\OTTWatchX\subtitleai-v2\subtitleai-v2\frontend\src\App.jsx"
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Add classes to match the CSS hover effects
content = content.replace("style={S.card}", "className='card' style={S.card}")
content = content.replace("style={{...S.card,", "className='card' style={{...S.card,")
content = content.replace("style={{...S.uploadZone", "className='uploadZone' style={{...S.uploadZone")
content = content.replace("style={S.btnX}", "className='btn-x-hover icon-spin' style={S.btnX}")

# Improve header gradient for light mode
content = content.replace("background:'linear-gradient(135deg,#ffffff,#f1f5f9)'", "background:'#ffffff'")
# Update primary button gradient
content = content.replace("background:'linear-gradient(135deg,#4f46e5,#4338ca)'", "background:'linear-gradient(135deg, #6366f1, #4f46e5)'")

# Make tabs look more professional
content = content.replace("border:'1.5px solid #cbd5e1'", "border:'1px solid #e2e8f0'")

# Add some box shadows to S definition
# We will do this by replacing 'S = {' with 'S = {'
shadows = """
  card: { background:'#ffffff', border:'1px solid #e2e8f0', borderRadius:16, padding:24, boxShadow:'0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03)' },
"""
content = re.sub(r"card: \{[^\}]+\},", shadows, content)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Classes and shadows added!")
