from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

try:
    with open(r"d:\Downloads\OTTWatchX\T13.22212 - Only Time Will Tell.docx_cleaned.pdf", "rb") as script_file:
        response = client.post(
            "/transcribe-and-align", 
            files={
                "audio": ("test.webm", b"empty_audio"),
                "script": ("script.pdf", script_file, "application/pdf")
            }
        )
    print("STATUS CODE:", response.status_code)
    print("RESPONSE BODY:", response.text)
except Exception as e:
    import traceback
    traceback.print_exc()
