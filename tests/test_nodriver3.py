import os
import sys
sys.path.append('src')
from dotenv import load_dotenv
load_dotenv()
from core.config import find_chrome_executable, CHROMIUM_BINARY_PATH
print(f"ENV VAR CHROMIUM_BINARY_PATH: {os.getenv('CHROMIUM_BINARY_PATH')}")
print(f"CONFIG CHROMIUM_BINARY_PATH: {CHROMIUM_BINARY_PATH}")
print(f"FIND FUNCTION: {find_chrome_executable()}")
