Since the project needs the use of Optical Character Recognition (OCR) python will be perfect for data extraction. 
First trial will be with an image and see if the data is aligned as per the provided format

Tools required
1. Python
2. Libraries 
    a. pytesseract - for google ocr engine
    b. pillow - for handling images
    c. openCV - for preporecessing images
    d. Scrapy - ibrary to scrape the data from the specified website and save it to a CSV file.

Decided to go with webscrapping on day two to try and ease the process

APP8
Key Features:
1. Complete End-to-End Solution:

    Handles both coupon books and hot buys

    Outputs two separate Excel files matching your templates

2. Advanced Image Processing:

    Multiple preprocessing steps for optimal OCR accuracy

    OpenCV-based denoising and thresholding

    PIL-based contrast and sharpness enhancement

3. Intelligent Data Extraction:

    Robust regex patterns for all fields

    Special handling for hot buy-specific fields (channels, dates)

    Automatic pagination for hot buys

4. Error Handling:

    Multiple fallback selectors

    Comprehensive error checking

    Tesseract initialization verification

5. Excel-Perfect Output:

    Column ordering matches the samples

    Proper datetime formatting

    Consistent field extraction