import os
import shutil
import comtypes

# 1. Find where comtypes is hiding
comtypes_path = os.path.dirname(comtypes.__file__)
gen_path = os.path.join(comtypes_path, 'gen')

print(f"Found comtypes at: {comtypes_path}")

# 2. Delete the corrupted 'gen' folder
if os.path.exists(gen_path):
    try:
        shutil.rmtree(gen_path)
        print("✅ SUCCESS: Corrupted Audio Cache (gen folder) deleted.")
    except Exception as e:
        print(f"❌ ERROR: Could not delete folder. Try running VS Code as Administrator.\nError: {e}")
else:
    print("ℹ️ Note: Cache was already clean.")

print("\n🚀 You can now run main.py!")