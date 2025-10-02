# scraper.py
import re
import json
import requests
import time
import logging
from bs4 import BeautifulSoup

# --- Logging Configuration ---
# Configure logging to provide structured, informative output.
# This replaces all print() statements for better diagnostics.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- Constants ---
# Headers to mimic a real browser visit
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

# --- Helper Functions ---
def clean_price(price_text):
    """Removes 'Rp', dots, and converts to an integer."""
    if not price_text:
        return 0
    nums = re.findall(r'\d+', str(price_text))
    return int("".join(nums)) if nums else 0

# --- Main Scraper Function ---
def scrape_tokopedia(url, session=None):
    """
    Scrapes a Tokopedia product page for its price and main image URL.
    This version prioritizes the stable JSON-LD script tag over brittle HTML elements,
    includes retry logic, and uses logging for better error reporting.

    Args:
        url (str): The URL of the Tokopedia product page.
        session (requests.Session, optional): A session object to use for the request. Defaults to None.

    Returns:
        tuple: A tuple containing (price_as_int, image_url_str).
               Returns (None, None) for each respective value on failure.
    """
    if "tokopedia.com" not in url:
        logging.error(f"URL is not a valid Tokopedia link: {url}")
        return None, None

    requester = session if session else requests
    max_retries = 3
    retry_delay = 2  # seconds
    response = None

    # --- Network Request with Retry Logic ---
    for attempt in range(max_retries):
        try:
            response = requester.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()
            break  # Success
        except requests.exceptions.RequestException as e:
            logging.warning(f"Network error on attempt {attempt + 1}/{max_retries} for {url}: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logging.error(f"All network retries failed for {url}.")
                return None, None

    if not response:
        return None, None

    # --- Parsing Logic ---
    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        price = None
        image_url = None

        # --- Method 1: The Robust JSON-LD Method (Preferred) ---
        script_tag = soup.find('script', type='application/ld+json')
        if script_tag:
            try:
                json_content = script_tag.string
                # Handle multiple JSON objects concatenated together by wrapping them in an array
                json_data_list = json.loads(f'[{json_content.replace("}{", "},{")}]')
                
                product_data = next((item for item in json_data_list if item.get('@type') == 'Product'), None)
                
                if product_data:
                    offers = product_data.get('offers', [])
                    if isinstance(offers, list) and offers:
                        price = clean_price(offers[0].get('price'))
                    elif isinstance(offers, dict):  # Sometimes it's a dict, not a list
                        price = clean_price(offers.get('price'))

                    images = product_data.get('image', [])
                    if isinstance(images, list) and images:
                        image_url = images[0]

            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                logging.warning(f"Could not parse JSON-LD from {url}. Error: {e}. Proceeding to HTML fallback.")
        else:
            logging.info(f"No JSON-LD script tag found for {url}. Using HTML fallback method.")

        # --- Method 2: Fallback to HTML scraping if JSON-LD fails or is missing ---
        # Refined fallback with specific logging for easier debugging
        if price is None:
            price_testid = 'lblPDPDetailProductPrice'
            price_element = soup.find('div', {'data-testid': price_testid})
            if price_element:
                price = clean_price(price_element.text)
                logging.info(f"Successfully found price for {url} using fallback data-testid '{price_testid}'.")
            else:
                logging.warning(f"Price fallback failed: data-testid '{price_testid}' not found for {url}")
        
        if image_url is None:
            image_testid = 'PDPMainImage'
            image_element = soup.find('img', {'data-testid': image_testid})
            if image_element and image_element.get('src'):
                image_url = image_element['src']
                logging.info(f"Successfully found image for {url} using fallback data-testid '{image_testid}'.")
            else:
                # If the primary testid fails, log it and try a broader search
                logging.warning(f"Image fallback failed: data-testid '{image_testid}' not found for {url}. Trying next fallback.")
                image_container_class = 'css-1nchjne' # This class may change, but serves as an example
                image_container = soup.find('div', class_=image_container_class)
                if image_container:
                    image_element_fallback = image_container.find('img')
                    if image_element_fallback and image_element_fallback.get('src'):
                        image_url = image_element_fallback['src']
                        logging.info(f"Successfully found image for {url} using fallback class '{image_container_class}'.")
                else:
                    logging.warning(f"Image fallback failed: container class '{image_container_class}' not found for {url}.")

        # --- Final Check and Return ---
        if price is None and image_url is None:
            logging.error(f"Total scraping failure: Could not find price or image for {url} after all methods.")
            return None, None
            
        return price, image_url

    except Exception as e:
        # Catch any unexpected parsing errors and log with a traceback
        logging.error(f"An unexpected error occurred while parsing {url}: {e}", exc_info=True)
        return None, None
