import os
import requests
from dotenv import load_dotenv

def check_quota():
    load_dotenv()
    api_key = os.getenv("YOUTUBE_API_KEY")
    
    if not api_key:
        print("ERROR: YOUTUBE_API_KEY not found in .env")
        return

    print(f"Checking quota for API Key: {api_key[:5]}...{api_key[-5:]}")
    
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": "test",
        "maxResults": 1,
        "key": api_key
    }
    
    try:
        r = requests.get(url, params=params, timeout=10)
        print(f"HTTP Status: {r.status_code}")
        
        if r.status_code == 200:
            print("SUCCESS: Your YouTube API quota is NOT exceeded.")
            data = r.json()
            items = data.get('items', [])
            if items:
                print(f"Sample Video Title: {items[0]['snippet']['title']}")
            else:
                print("No items returned, but request was successful.")
        elif r.status_code == 403:
            error_data = r.json().get("error", {})
            errors = error_data.get("errors", [{}])
            reason = errors[0].get("reason", "unknown")
            message = error_data.get("message", "No message provided")
            
            if reason == "quotaExceeded":
                print("FAILURE: Quota Exceeded! Your daily limit has been reached.")
            else:
                print(f"FAILURE: Error 403 - {reason}: {message}")
        elif r.status_code == 400:
            print("FAILURE: Error 400 - Bad Request. Your API Key might be invalid or restricted.")
        elif r.status_code == 401:
            print("FAILURE: Error 401 - Unauthorized. Your API Key is likely incorrect.")
        else:
            print(f"WARNING: Unexpected Status Code: {r.status_code}")
            print(r.text)
            
    except Exception as e:
        print(f"CRITICAL: Network Error - {str(e)}")

if __name__ == "__main__":
    check_quota()
