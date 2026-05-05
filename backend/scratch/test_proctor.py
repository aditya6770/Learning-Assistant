import os, requests, json
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
url = "https://openrouter.ai/api/v1/chat/completions"

payload = {
    "model": "google/gemini-2.5-flash",
    "messages": [
        {
            "role": "user",
            "content": "Hello, can you see this text? Respond with JSON: {\"status\": \"ok\"}"
        }
    ],
    "max_tokens": 300
}

headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
response = requests.post(url, headers=headers, json=payload)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
