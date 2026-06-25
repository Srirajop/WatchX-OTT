import re
import os

filepath = r"d:\Downloads\OTTWatchX\subtitleai-v2\subtitleai-v2\frontend\src\App.jsx"
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Let's fix the white text on light backgrounds
# We need to manually fix things that were not properly transformed or were overwritten incorrectly

fixes = {
    # Buttons and text colors
    "color: '#ffffff'": "color: 'white'",
    "color:'#ffffff'": "color:'white'",
    "color: '#0f172a'": "color: '#1e293b'",
    "background:'#4338ca20'": "background:'#eef2ff'",
    "background: '#e2e8f0'": "background: '#f8fafc'",
    "background:'#f1f5f9'": "background:'#f8fafc'",
    
    # Progress bars
    "background: '#e2e8f0', borderRadius: 10, border: '1px solid #4338ca20'": "background: '#ffffff', borderRadius: 10, border: '1px solid #e2e8f0'",
    "background: '#e2e8f0', borderRadius: 10, overflow: 'hidden'": "background: '#f1f5f9', borderRadius: 10, overflow: 'hidden'",
    "background: 'linear-gradient(90deg, #4338ca, #4338ca)'": "background: 'linear-gradient(90deg, #6366f1, #4f46e5)'",
    
    # The empty/blank states
    "background:'#ffffff', border:'1px solid #e2e8f0', borderRadius:12": "background:'#f8fafc', border:'1px dashed #cbd5e1', borderRadius:12",
    "color:'#ffffff',marginBottom:12": "color:'#0f172a',marginBottom:12",
    "color:'#ffffff',marginBottom:2": "color:'#0f172a',marginBottom:2",

    # Gradients
    "background:'linear-gradient(135deg,#4338ca,#4338ca)'": "background:'linear-gradient(135deg, #6366f1, #4f46e5)'",

    # Table styles etc.
    "background:'#f1f5f9',border:'1px solid #e2e8f0',borderRadius:6": "background:'#f8fafc',border:'1px solid #e2e8f0',borderRadius:6",
    
    # Text in cards
    "color:'#ffffff'": "color:'#0f172a'",
}

for old, new in fixes.items():
    content = content.replace(old, new)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Colors fixed for light theme!")
