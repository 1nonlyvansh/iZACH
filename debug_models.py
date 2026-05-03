
import google.generativeai as genai
import os # noqa: F401

# Your Key
GOOGLE_API_KEY = "AIzaSyAnwa1AMP2C0aX0RFKz3b6cWPVb4vkI61E"

client = genai.Client(api_key=GOOGLE_API_KEY)

print("🔍 Checking available models for your key...\n")

try:
    # List all models
    for model in client.models.list():
        name = model.name
        # We only care about models that can generate content (chat/vision)
        if "generateContent" in model.supported_actions:
            print(f"✅ FOUND: {name}")
            
except Exception as e:
    print(f"❌ Error listing models: {e}")