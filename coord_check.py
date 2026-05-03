import pyautogui
import time

print("Move your mouse to the point")
time.sleep(3)
x, y = pyautogui.position()
print(f"THE PERFECT SPOT IS: x={x}, y={y}")