# scraper.py
import re
import json
import requests
import time
from bs4 import BeautifulSoup

# Headers to mimic a real browser visit
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def clean_price(price_text):
    """Removes 'Rp', dots, and converts to an integer."""
    if not price_text:
        return 0 # Returning 0 is fine here as it's a utility for found text
    nums = re.findall(r'\d+', str(price_text))
    return int("".join(nums)) if nums else 0

def scrape_tokopedia(url, session=None):
    """
    Scrapes a Tokopedia product page for its price and main image URL.
    This version prioritizes the stable JSON-LD script tag over brittle HTML elements.
    Includes retry logic for network requests.

    Args:
        url (str): The URL of the Tokopedia product page.
        session (requests.Session, optional): A session object to use for the request. Defaults to None.

    Returns:
        tuple: A tuple containing (price_as_int, image_url_str).
               Returns (None, None) for each respective value on failure.
    """
    if "tokopedia.com" not in url:
        print(f"Error: URL is not a Tokopedia link: {url}")
        return None, None

    requester = session if session else requests
    max_retries = 3
    retry_delay = 2  # seconds
    response = None

    for attempt in range(max_retries):
        try:
            response = requester.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()
            break  # Success
        except requests.exceptions.RequestException as e:
            print(f"Network error on attempt {attempt + 1}/{max_retries} for {url}: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                print(f"All retries failed for {url}.")
                return None, None

    if not response:
        # Should not be reached, but as a safeguard.
        return None, None

    try:
        soup = BeautifulSoup(response.text, 'html.parser')

        price = None
        image_url = None

        # --- Method 1: The Robust JSON-LD Method (Preferred) ---
        script_tag = soup.find('script', type='application/ld+json')
        if script_tag:
            try:
                # The script tag might contain multiple JSON objects, concatenated. We need to find the right one.
                json_content = script_tag.string
                # Look for a JSON object that has '@type': 'Product'
                # This is more robust than assuming the first/only object is the one we want.
                # A simple way to handle multiple objects is to wrap in an array and parse
                json_data_list = json.loads(f'[{json_content.replace("}{", "},{")}]')
                
                product_data = None
                for item in json_data_list:
                    if item.get('@type') == 'Product':
                        product_data = item
                        break
                
                if product_data:
                    # Safely navigate the JSON structure
                    offers = product_data.get('offers', [])
                    if isinstance(offers, list) and len(offers) > 0:
                        price = clean_price(offers[0].get('price'))
                    elif isinstance(offers, dict): # Sometimes it's a dict, not a list
                         price = clean_price(offers.get('price'))

                    images = product_data.get('image', [])
                    if isinstance(images, list) and len(images) > 0:
                        image_url = images[0]

            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                print(f"Could not parse JSON-LD from {url}. Error: {e}")
                # If JSON parsing fails, we'll proceed to the fallback method.
        
        # --- Method 2: Fallback to HTML scraping if JSON-LD fails or is missing ---
        if price is None:
            price_element = soup.find('div', {'data-testid': 'lblPDPDetailProductPrice'})
            if price_element:
                price = clean_price(price_element.text)
            else:
                print(f"Warning: Price element not found for {url}")
                # price remains None
        
        if image_url is None:
            # Tokopedia image galleries often use a specific test ID
            image_element = soup.find('img', {'data-testid': 'PDPMainImage'})
            if image_element and image_element.get('src'):
                image_url = image_element['src']
            else:
                # A broader fallback if the specific test ID is not found
                image_container = soup.find('div', class_='css-1nchjne')
                if image_container:
                    image_element_fallback = image_container.find('img')
                    if image_element_fallback and image_element_fallback.get('src'):
                        image_url = image_element_fallback['src']

            if not image_url:
                print(f"Warning: Image element not found for {url}")

        if price is None and image_url is None:
            # Signal total failure to the caller
            print(f"Error: Failed to scrape both price and image for {url}")
            return None, None
            
        return price, image_url

    except Exception as e:
        print(f"An error occurred while parsing {url}: {e}")
        return None, None