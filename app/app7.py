import requests
from bs4 import BeautifulSoup
import pandas as pd 
import re
from datetime import datetime

# Configuration
BASE_URL = "https://www.costcoinsider.com"
URLS = {
    "coupon_books": "https://www.costcoinsider.com/costco-april-2025-coupon-book/",
    "hot_buys": "https://www.costcoinsider.com/costco-april-2025-hot-buys-coupons/"
}
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def get_page(url):
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching {url}: {str(e)}")
        return None

def extract_coupons(html, source_url):
    soup = BeautifulSoup(html, 'html.parser')
    
    # Debug output
    with open("debug_page.html", "w", encoding="utf-8") as f:
        f.write(str(soup))
    
    coupons = []
    for element in soup.find_all(string=True):
        text = element.strip()
        if not text or len(text) < 20:
            continue
        
        if re.search(r'\$\d+\.\d{2}\s*off|\$\d+\s*off', text, re.IGNORECASE):
            brand = re.search(r'^([A-Z][a-zA-Z0-9&]+)', text)
            discount = re.search(r'(\$\d+(?:\.\d{2})?)\s*off', text)
            price = re.search(r'\$(\d+\.\d{2})(?=\D|$)', text)
            limit = re.search(r'(Limit\\s+\\d+|While\\s+supplies\\s+last)', text, re.IGNORECASE)
            
            coupons.append({
                'Item': text,
                'Brand': brand.group(1) if brand else '',
                'Discount': discount.group(1) if discount else '',
                'Price': f"${price.group(1)}" if price else '',
                'Limit': limit.group(0) if limit else '',
                'Valid From': '',
                'Valid To': '',
                'Source': source_url
            })
    
    return coupons

def main():
    for label, url in URLS.items():
        print(f"Processing {label}: {url}")
        html = get_page(url)
        if not html:
            print(f"Failed to fetch {label}")
            continue

        coupons = extract_coupons(html, url)

        if not coupons:
            print(f"No coupons found for {label}. Check 'debug_page.html'.")
            continue

        df = pd.DataFrame(coupons)
        filename = "coupon_books.csv" if label == "coupon_books" else "hot_buys_coupons.csv"
        df.to_csv(filename, index=False)
        print(f"✅ Saved {len(df)} {label} items to {filename}")

if __name__ == "__main__":
    main()
