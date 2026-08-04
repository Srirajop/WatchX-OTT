import os
import openai
from dotenv import load_dotenv

load_dotenv('backend/.env')
client = openai.OpenAI(
    api_key=os.getenv('GEMINI_API_KEY'),
    base_url='https://generativelanguage.googleapis.com/v1beta/openai/'
)

print("Checking key:", os.getenv('GEMINI_API_KEY')[:10] + "...")

long_prompt = "Hello, here is some text: " + ("word " * 10000) + " Can you summarize this in 10 words?"

try:
    print('Testing gemini-2.5-flash-lite with HUGE prompt...')
    response = client.chat.completions.create(
        model='gemini-2.5-flash-lite',
        messages=[{'role': 'user', 'content': long_prompt}],
        max_tokens=8000
    )
    print('SUCCESS:', response.choices[0].message.content)
except Exception as e:
    print('FAILED:', str(e))
