import google.generativeai as genai
import os # noqa: F401

# PASTE YOUR KEY HERE
GENAI_API_KEY = "AIzaSyBq3wHiWTNRqse3sqcvp3xL0BZ3mZCEEjw" 

try:
    client = genai.Client(api_key=GENAI_API_KEY)
    print("--- SEARCHING FOR AVAILABLE MODELS ---")
    
    # We ask the server: "What can I use?"
    # The new library uses a slightly different way to list models, 
    # so we will try a direct generation test on the most common ones.
    
    candidates = [
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
        "gemini-1.5-pro",
        "gemini-1.0-pro",
        "gemini-pro"
    ]
    
    for model_name in candidates:
        print(f"Testing {model_name}...", end=" ")
        try:
            response = client.models.generate_content(
                model=model_name,
                contents="Hello"
            )
            print("✅ SUCCESS!")
        except Exception as e:
            if "429" in str(e):
                print("⚠️ Quota Limit (But it exists!)")
            elif "404" in str(e):
                print("❌ Not Found")
            else:
                print(f"❌ Error: {e}")

except Exception as e:
    print(f"CRITICAL ERROR: {e}")

input("\nPress Enter to close...")
