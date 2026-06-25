import re
import os

filepath = r"d:\Downloads\OTTWatchX\subtitleai-v2\subtitleai-v2\frontend\src\App.jsx"
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.content = f.read()

# Make a backup
with open(filepath + ".bak", 'w', encoding='utf-8') as f:
    f.write(content)

color_map = {
    # Backgrounds
    '#08080f': '#f8fafc',
    '#0d0d1a': '#ffffff',
    '#12122a': '#f1f5f9',
    '#13131f': '#f1f5f9',
    '#1a1a2e': '#f8fafc',
    '#131320': '#e2e8f0',
    '#16132a': '#eef2ff',
    '#0a0a10': '#e2e8f0',
    '#09090f': '#ffffff',

    # Borders
    '#1e1e2e': '#e2e8f0',
    '#2a2a3e': '#cbd5e1',
    '#1a1a2a': '#e2e8f0',

    # Texts
    '#e8e6df': '#0f172a',
    '#c8c6d4': '#334155',
    '#5a5870': '#64748b',
    '#7c7a8a': '#64748b',
    '#3a3a6a': '#94a3b8',
    '#3a3848': '#94a3b8',

    # Primary colors (Indigo)
    '#7c3aed': '#4f46e5',
    '#4f46e5': '#4338ca',
    '#a78bfa': '#6366f1',
    '#e9d5ff': '#4338ca',

    # Error/Red
    '#1a0f0f': '#fef2f2',
    '#2a0f0f': '#fee2e2',
    '#1a0a0a': '#fef2f2',
    '#2a1515': '#fef2f2',
    '#ef4444': '#dc2626',
    '#fca5a5': '#dc2626',
    '#f87171': '#ef4444',

    # Success/Green
    '#0f1f15': '#ecfdf5',
    '#0a1a10': '#ecfdf5',
    '#6ee7b7': '#059669',
    '#34d399': '#059669',

    # Warning/Yellow
    '#1a1200': '#fef3c7',
    '#0d0d00': '#fef3c7',
    '#1a1000': '#fef3c7',
    '#fbbf24': '#d97706',
    '#f59e0b': '#d97706',
    '#fde68a': '#b45309',

    # Info/Blue
    '#0f1535': '#e0e7ff',
    '#1a1535': '#eef2ff',
    '#0f1a2e': '#eff6ff',
    '#60a5fa': '#2563eb',
    '#4a7a9b': '#1e40af',
    '#9c9ab0': '#475569',
}

# Perform replacement
for old_color, new_color in color_map.items():
    content = re.sub(old_color, new_color, content, flags=re.IGNORECASE)

# Special cases
content = re.sub(r'color:\s*["\']white["\']', "color: '#ffffff'", content)
content = re.sub(r'color:\s*["\']#fff["\']', "color: '#ffffff'", content)
# We want logos and buttons to remain white text
# Let's write it back
with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Theme updated!")
