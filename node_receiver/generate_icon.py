"""
Run this once to create a demo icon.png for the iZACH Node Receiver tray.
Replace icon.png with iZACH's actual logo PNG anytime — receiver auto-picks it up.
"""

from PIL import Image, ImageDraw, ImageFont

SIZE = 64

img  = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Outer glow ring
draw.ellipse([0, 0, SIZE, SIZE], fill=(15, 80, 200, 60))
# Main circle — iZACH blue
draw.ellipse([4, 4, SIZE - 4, SIZE - 4], fill=(30, 120, 255, 255))
# Inner highlight
draw.ellipse([8, 8, 30, 28], fill=(80, 170, 255, 80))

# "iZ" text
try:
    font = ImageFont.truetype("arialbd.ttf", 22)
except Exception:
    font = ImageFont.load_default()

draw.text((13, 18), "iZ", fill=(255, 255, 255, 255), font=font)

img.save("icon.png")
print("icon.png saved — replace with iZACH logo PNG anytime.")
