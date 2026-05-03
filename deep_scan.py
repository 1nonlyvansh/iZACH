import requests
import json

# Your API Key
API_KEY = "AIzaSyBq3wHiWTNRqse3sqcvp3xL0BZ3mZCEEjw"

print("--- DEEP SCAN DIAGNOSTIC ---")
print(f"Key being used: {API_KEY[:10]}... (Hidden)")

# TEST 1: Check if the Key works AT ALL (List Models)
print("\n1. Pinging Google Server to list models...")
url_list = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"

try:
    response = requests.get(url_list)
    data = response.json()
    
    if "error" in data:
        print("❌ CRITICAL ERROR:")
        print(json.dumps(data, indent=2))
    elif "models" in data:
        print("✅ CONNECTION SUCCESSFUL. Your key works.")
        print("   Here are the models you are allowed to use:")
        found_any = False
        for m in data["models"]:
            # We only care about models that can CHAT (generateContent)
            if "generateContent" in m.get("supportedGenerationMethods", []):
                print(f"   - {m['name']}")
                found_any = True
        
        if not found_any:
            print("   ⚠️ WARNING: No Chat models found in your list.")
    else:
        print("⚠️ Unknown response format.")
        print(data)

except Exception as e:
    print(f"❌ NETWORK ERROR: {e}")

print("\n-----------------------------")
input("Press Enter to close...")