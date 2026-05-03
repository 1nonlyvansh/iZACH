import cv2
import numpy as np
import pyautogui # noqa: F401  # reserved for screenshot fallback
from PIL import ImageGrab
import os

# Create directory if missing
if not os.path.exists("assets/icons"):
    os.makedirs("assets/icons")

print("INSTRUCTIONS: Drag a box around the icon you want to save. Press 's' to save, 'q' to quit.")

# Capture full screen
screen = np.array(ImageGrab.grab())
screen = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)

# Selection logic
roi = cv2.selectROI("Icon Grabber - iZACH", screen, fromCenter=False, showCrosshair=True)
x, y, w, h = roi

if w > 0 and h > 0:
    crop = screen[y:y+h, x:x+w]
    name = input("Enter name for this icon (e.g., chrome): ")
    cv2.imwrite(f"assets/icons/{name}.png", crop)
    print(f"Saved to assets/icons/{name}.png")

cv2.destroyAllWindows()