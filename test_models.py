import os
import openai
from dotenv import load_dotenv

load_dotenv('backend/.env')
client = openai.OpenAI(
    api_key=os.getenv('GEMINI_API_KEY'),
    base_url='https://generativelanguage.googleapis.com/v1beta/openai/'
)

print("Checking key:", os.getenv('GEMINI_API_KEY')[:10] + "...")

try:
    print('Testing gemini-2.0-flash...')
    response = client.chat.completions.create(
        model='gemini-2.0-flash',
        messages=[{'role': 'user', 'content': 'Hello!'}],
        max_tokens=10
    )
    print('SUCCESS 2.0-flash:', response.choices[0].message.content)
except Exception as e:
    print('FAILED 2.0-flash:', str(e))

try:
    print('Testing gemini-1.5-flash...')
    response = client.chat.completions.create(
        model='gemini-1.5-flash',
        messages=[{'role': 'user', 'content': 'Hello!'}],
        max_tokens=10
    )
    print('SUCCESS 1.5-flash:', response.choices[0].message.content)
except Exception as e:
    print('FAILED 1.5-flash:', str(e))

try:
    print('Testing gemini-2.5-flash-lite...')
    response = client.chat.completions.create(
        model='gemini-2.5-flash-lite',
        messages=[{'role': 'user', 'content': 'Hello!'}],
        max_tokens=10
    )
    print('SUCCESS 2.5-flash-lite:', response.choices[0].message.content)
except Exception as e:
    print('FAILED 2.5-flash-lite:', str(e))
