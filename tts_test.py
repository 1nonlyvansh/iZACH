import asyncio
import edge_tts
import pygame
import os

async def speak():
    filename = "temp_tts.mp3"

    communicate = edge_tts.Communicate(
        "Test number one. Test number two. Test number three.",
        "en-US-AriaNeural"
    )
    await communicate.save(filename)

    pygame.mixer.init()
    pygame.mixer.music.load(filename)
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)

    pygame.mixer.quit()
    os.remove(filename)

asyncio.run(speak())