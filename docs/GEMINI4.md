# Google Business Phone Number Extractor

A Python script to automatically extract business phone numbers from Google Search results using Selenium. This tool is part of the **"best way to extract phone number automatically"** project.

## Overview

This script performs a Google search for a given business name and location, then extracts the phone number from the **knowledge panel** (the box that appears on the right side of search results for businesses). It uses a headless Chrome browser to simulate a real user, avoiding simple blocking mechanisms.

## Features

- Headless browser automation with Selenium/
- Automatic ChromeDriver management via `webdriver-manager`
- Three fallback extraction strategies:
  1. Direct CSS selector targeting Google's phone number attribute (`data-dtype='d3ph'`)
  2. Aria-label scanning for "Call phone number"
  3. Regex extraction from the right-hand panel text
- Handles both local and international formats
- Returns the phone number or a clear error message

## Requirements

- Python 3.6+
- Chrome browser installed
- The following Python packages (see installation)

## Installation

1.

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import urllib.parse
import time
import re

def get_business_phone(business_name: str, location: str) -> str:
"""
Searches Google for a business and extracts its phone number
from the knowledge panel.
""" # 1. Setup search query
query = f"{business_name} {location}"
encoded_query = urllib.parse.quote(query)
url = f"https://www.google.com/search?q={encoded_query}"

    # 2. Configure headless browser to look like a real user
    options = Options()
    options.add_argument("--headless")  # Run without opening a window
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        driver.get(url)
        time.sleep(3)  # Give Google's heavy JS time to render the panel

        # Strategy A: Target Google's specific data attribute for phones ('d3ph')
        try:
            phone_element = driver.find_element(By.CSS_SELECTOR, "a[data-dtype='d3ph']")

            # Check if it has the aria-label with the actual number
            aria_label = phone_element.get_attribute("aria-label")
            if aria_label and "Call phone number" in aria_label:
                # Extract just the number
                return aria_label.replace("Call phone number ", "").strip()

            # Fallback to the text inside the element
            if phone_element.text:
                return phone_element.text.strip()
        except:
            pass  # If Strategy A fails, fall through to Strategy B

        # Strategy B: Find any element with an aria-label containing 'Call phone number'
        try:
            aria_element = driver.find_element(By.CSS_SELECTOR, "[aria-label*='Call phone number']")
            label = aria_element.get_attribute("aria-label")
            return label.replace("Call phone number ", "").strip()
        except:
            pass

        # Strategy C: Regex scan the text of the right-hand panel as a last resort
        try:
            rhs_panel = driver.find_element(By.ID, "rhs")
            panel_text = rhs_panel.text
            # Simple regex for international or local phone numbers
            phone_match = re.search(r'(\+?[0-9\s]{8,20})', panel_text)
            if phone_match:
                return phone_match.group(0).strip()
        except:
            pass

        return "Phone number not found in knowledge panel."

    except Exception as e:
        return f"An error occurred: {str(e)}"
    finally:
        driver.quit()

# --- Example Usage ---

if **name** == "**main**":
biz = "L'école de ski Risoul"
loc = "Crots FRANCE"

    print(f"Searching for: {biz} in {loc}...")
    phone = get_business_phone(biz, loc)
    print(f"Result: {phone}")

2. **Install required packages** using pip:
   ```bash
   pip install selenium webdriver-manager
   ```
   How It Works
   Search Query Construction
   The business name and location are combined, URL-encoded, and used to build a Google search URL.

Headless Browser Setup
Chrome is launched in headless mode with a realistic user‑agent string to avoid detection.

Page Load
The page is loaded and a short sleep (time.sleep(3)) gives time for dynamic content (like the knowledge panel) to render.

Extraction Strategies (tried in order):

Strategy A: Find an <a> tag with data-dtype="d3ph" – a Google‑specific attribute for phone numbers. If it exists, the phone number is extracted from its aria-label or text.

Strategy B: Locate any element with aria-label containing "Call phone number" and extract the number from that label.

Strategy C: If the above fail, grab the entire right‑hand panel (<div id="rhs">) and use a regex to find a phone‑like pattern (e.g., +XX XXX XXX XXX or local numbers). This is a fallback and may yield false positives.

Return Value
The extracted phone number as a string, or a message indicating failure.

Important Notes
Rate Limiting & Legal Considerations
Automated scraping of Google Search may violate Google’s Terms of Service. Use responsibly and consider adding delays between requests or using official APIs (like Google Places API) for production use.

Dependency on Google's HTML Structure
The script relies on specific HTML attributes (data-dtype='d3ph', aria-label). Google may change these at any time, so the script may break and require updates.

Headless Detection
While we use a common user‑agent, Google can still detect headless browsers. For more robust scraping, consider using additional stealth techniques (e.g., undetected-chromedriver).

Locale
The phone number format may vary by region. The regex is basic and may not capture all possible formats. You may need to adjust it for your target region.

Possible Improvements
Implement exponential backoff and retries

Add support for paginated results or multiple business entries

Use a more sophisticated phone number parsing library (e.g., phonenumbers)

Integrate with a proxy rotation service to avoid IP bans

Add logging for debugging
