from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

try:
    response = client.post(
        "/transcribe-and-align", 
        files={
            "audio": ("test.webm", b"empty_audio"),
        }
    )
    print("STATUS CODE:", response.status_code)
    print("RESPONSE BODY:", response.text)
except Exception as e:
    import traceback
    traceback.print_exc()
