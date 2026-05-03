import speech_recognition as sr
print("--- MICROPHONE LIST ---")
for index, name in enumerate(sr.Microphone.list_microphone_names()):
    print(f"ID {index}: {name}")