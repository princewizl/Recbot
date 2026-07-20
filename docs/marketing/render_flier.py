from pathlib import Path
from playwright.sync_api import sync_playwright

html = Path(r"c:\Users\Olufemi\Documents\PROJECTS\Recbot\docs\marketing\collxct-flier.html")
png = Path(r"c:\Users\Olufemi\Documents\PROJECTS\Recbot\docs\marketing\collxct-flier.png")

import os
chrome = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1228\chrome-win64\chrome.exe")

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=chrome)
    page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
    page.goto(html.as_uri())
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)  # let webfonts settle
    page.screenshot(path=str(png))
    browser.close()

print("flier written:", png, png.stat().st_size, "bytes")
