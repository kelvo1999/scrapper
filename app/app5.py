# used selenium

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
from datetime import datetime
from urllib.parse import urljoin

# Config
HEADLESS = True
DELAY = 5
BASE_URL = "https://www.costcoinsider.com/category/coupons/"

# Setup headless browser
def start_browser():
    options = Options()
    if HEADLESS:
        options.add_argument('--headless')
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--log-level=3")  # Reduce noise
    # options.add_argument('--disable-gpu')
    # options.add_argument('--no-sandbox')
    # options.add_argument("--disable-software-rasterizer")
    
    return webdriver.Chrome(options=options)

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def extract_discount(text):
    match = re.search(r'\$(\d+(?:\.\d{1,2})?)\s*off', text, re.IGNORECASE)
    return match.group(1) if match else ""

def extract_limit(text):
    match = re.search(r'(Limit\s*\d+|Limited\s*time)', text, re.IGNORECASE)
    return match.group(0) if match else ""

def extract_original_price(text):
    match = re.search(r'\$(\d+\.\d{2})(?:\s*[\-–]\s*\$?\d+\.\d{2})?', text)
    return match.group(1) if match else ""

def extract_common(driver, url, article_type):
    print(f"🌐 Visiting {url}")
    driver.get(url)
    time.sleep(DELAY)
    soup = BeautifulSoup(driver.page_source, 'html.parser')

    title = soup.title.text if soup.title else url
    publish_match = re.search(r'\b[A-Za-z]+\s\d{4}\b', title)
    discount_period = re.search(r'[A-Za-z]+\s\d{1,2}(st|nd|rd|th)?\s*through\s*[A-Za-z]+\s\d{1,2}(st|nd|rd|th)?', title, re.IGNORECASE)

    items = soup.select('.entry-content ul li, .coupon-item, .hot-buy-item, .deal-item, p')
    data = []

    for item in items:
        text = clean_text(item.get_text())
        if len(text.split()) < 3:
            continue

        # Brand parsing (first word with capital)
        brand_match = re.match(r'^([A-Z][a-zA-Z]+)', text)
        brand = brand_match.group(1) if brand_match else ""
        description = text[len(brand):].strip() if brand else text

        channel = ""
        if "warehouse" in text.lower() and "online" in text.lower():
            channel = "In-Warehouse + Online"
        elif "warehouse" in text.lower():
            channel = "In-Warehouse"
        elif "online" in text.lower():
            channel = "Online"

        discount_text = extract_discount(text)

        data.append({
            'scrape_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'article_name': title,
            'publish_date': publish_match.group(0) if publish_match else "",
            'item_brand': brand,
            'item_description': description,
            'discount': f"${discount_text}" if discount_text else "",
            'discount_cleaned': discount_text,
            'count_limit': extract_limit(text),
            'channel': channel,
            'discount_period': discount_period.group(0) if discount_period else "",
            'item_original_price': extract_original_price(text),
            'source_url': url,
            'type': article_type
        })

    print(f"✅ Extracted {len(data)} items from {article_type}")
    return data

def main():
    # Start browser
    driver = start_browser()

    # Current pages
    coupon_url = "https://www.costcoinsider.com/costco-april-2025-coupon-book/"
    hotbuys_url = "https://www.costcoinsider.com/costco-april-2025-hot-buys-coupons/"

    coupon_data = extract_common(driver, coupon_url, "Coupon Book")
    hotbuys_data = extract_common(driver, hotbuys_url, "Hot Buys")

    # Output
    today = datetime.now().strftime("%Y-%m-%d")
    pd.DataFrame(coupon_data).to_csv(f"Coupon_Books_{today}.csv", index=False)
    pd.DataFrame(hotbuys_data).to_csv(f"Hot_Buys_{today}.csv", index=False)

    print("\n🎉 Done scraping!")
    print(f"📁 Coupon CSV: Coupon_Books_{today}.csv")
    print(f"📁 Hot Buys CSV: Hot_Buys_{today}.csv")
    driver.quit()

if __name__ == "__main__":
    main()
