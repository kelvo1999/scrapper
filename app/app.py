import pytesseract
from PIL import Image
import csv
from datetime import datetime
import os

# 1. Set path to tesseract.exe (Windows users)
pytesseract.pytesseract.tesseract_cmd = r'C:/Users/kelvin.shisanya/Desktop/scrapper/tesseract.exe'



# 2. Load the image
image_path = 'Costco-April-2025-Hot-Buys-Coupons-Page-1.jpg'  # <- Replace with your actual image filename

if not os.path.exists(image_path):
    print(f"❌ Image not found: {image_path}")
    exit()

img = Image.open(image_path)

# 3. OCR: Extract text
extracted_text = pytesseract.image_to_string(img)

if not extracted_text.strip():
    print("⚠️ Warning: No text was extracted from the image.")
    exit()

# 4. Build the CSV row
row = {
    'scrape_datetime': datetime.now().strftime("%Y/%m/%dT%H:%M:%S"),
    'article_name': 'Costco April 2025 Hot Buys Coupons',
    'publish_date': '',  # Future enhancement
    'item_brand': '',  # Future enhancement
    'item_description': extracted_text.strip(),
    'discount': '',
    'discount_cleaned': '',
    'count_limit': '',
    'channel': '',
    'discount_period': '',
    'item_original_price': ''
}

# 5. Define CSV file and headers
csv_file = 'scraped_output.csv'
headers = list(row.keys())

# 6. Save or append to CSV
try:
    with open(csv_file, 'x', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerow(row)
        print(f"✅ New CSV created and data written to: {csv_file}")
except FileExistsError:
    with open(csv_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writerow(row)
        print(f"✅ Data appended to existing CSV: {csv_file}")
