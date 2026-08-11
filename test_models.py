import os, sys, requests
from dotenv import load_dotenv
load_dotenv('backend/.env')

headers={'Authorization': 'Bearer ' + os.environ['GROQ_API_KEY'], 'Content-Type': 'application/json'}
payload = {
    'messages': [{'role': 'user', 'content': 'Hello, just reply with a JSON object { "status": "ok" }'}],
    'model': 'llama-3.1-8b-instant'
}

for m in ['llama-3.1-8b-instant', 'llama-3.3-70b-versatile', 'openai/gpt-oss-120b', 'allam-2-7b']:
    payload['model'] = m
    try:
        r = requests.post('https://api.groq.com/openai/v1/chat/completions', headers=headers, json=payload)
        print(f'{m}: {r.status_code}')
        if r.status_code != 200:
            print(r.json())
    except Exception as e:
        print(f'{m}: Error {e}')
