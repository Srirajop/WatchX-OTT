import json

raw = '''```json
{
    "script_rules": [
        {
            "rule": "Maximum 37 characters per line",
            "verbatim_quote": "Max Characters per line: 37"
        },
        {
            "rule": "Maximum 2 lines per subtitle",
            "verbatim_quote": "Max Number of lines: 2"
        },
        {
            "rule": "For two-speaker titles, begin each line with a hyphen without space.",
            "verbatim_quote": "For two-speaker titles: begin each line with a hyphen without space."   
'''

import re
cleaned = re.sub(r'```(?:json)?\s*', '', raw).strip().rstrip('`')

def _repair(text):
    in_string = False
    escape_next = False
    stack = []
    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if not in_string:
            if ch == '{': stack.append('{')
            elif ch == '}': 
                if stack and stack[-1] == '{': stack.pop()
            elif ch == '[': stack.append('[')
            elif ch == ']': 
                if stack and stack[-1] == '[': stack.pop()
            
    if not in_string: text = text.rstrip(' ,\n\t\r')
    suffix = ''
    if in_string: suffix += '"'
    
    # Close based on stack (reverse order)
    for char in reversed(stack):
        if char == '{': suffix += '}'
        elif char == '[': suffix += ']'
        
    return text + suffix

repaired = _repair(cleaned)
print('Repaired:')
print(repr(repaired))
try:
    json.loads(repaired)
    print('SUCCESS')
except Exception as e:
    print('ERROR:', e)
