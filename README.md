# PC Planner

![GitHub language count](https://img.shields.io/github/languages/count/zqily/pcplanner)
![GitHub top language](https://img.shields.io/github/languages/top/zqily/pcplanner?style=flat&logo=python&logoColor=white&color=306998)

An automated PC build planner that scrapes live prices from Tokopedia to keep your dream build up-to-date, saving hours of manual calculations.

<img width="1195" height="824" alt="pcplanner" src="https://github.com/user-attachments/assets/00e82727-b8ac-468a-99a0-c68f9f9afbb1" />

---

## About The Project

I was planning a new PC build and grew tired of the tedious, repetitive chore of checking component prices every few days. Manually visiting half a dozen product pages, copying the new prices into a spreadsheet, and recalculating the total cost was a massive headache.

This project was built to solve that exact problem.

The PC Planner is a simple but effective Python application with a clean GUI. You input the Tokopedia links for your desired components, and with a single click, it scrapes the live name and price for every item, instantly updating your total build cost. What used to be a 15-minute chore is now a 5-second task.

### Key Features

-   **💰 Live Price Scraping:** Automatically fetches the latest item names and prices from any valid Tokopedia URL.
-   **⚡ Multi-threaded Performance:** Scrapes all component pages concurrently, making the update process fast and efficient.
-   **📋 Organized Layout:** A clean UI with separate tabs for core PC components and peripherals.
-   **📊 Automatic Totals:** The total cost of the build is calculated and displayed in real-time.
-   **💾 Persistent Data:** Your list of links is automatically saved and loaded between sessions.

### Built With

-   [Python](https://www.python.org/)
-   [PyQt6](https://riverbankcomputing.com/software/pyqt/) for the GUI
-   [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) for web scraping

---

## Getting Started

To get a local copy up and running, follow these simple steps.

### Prerequisites

Make sure you have Python 3.x and pip installed on your system.

-   **Python**
    ```sh
    python --version
    ```

### Installation

1.  **Clone the repository**
    ```sh
    git clone https://github.com/zqily/pcplanner.git
    cd pcplanner
    ```

2.  **Install the required packages**
    A `requirements.txt` file is included for easy installation.
    ```sh
    pip install -r requirements.txt
    ```

3.  **Run the application**
    ```sh
    python main.py
    ```

---

## Usage

1.  Launch the application.
2.  Navigate to either the `PC Components` or `Peripherals` tab.
3.  Click "Add Item" on the top right corner of the window.
4.  Paste the full Tokopedia product URL into the input field next to it, and add optional name and specs of the item, and click "OK"
5.  Repeat for all the parts you want to track. Your data will be saved automatically.
7.  The application will fetch the latest data and update the "Item Name," "Price," and "Total" fields.

---

## Limitations & Technical Notes

-   **Tokopedia Only:** This scraper is specifically designed for **Tokopedia** product pages and will not work with other e-commerce sites like Amazon or Shopee.
-   **Scraping Approach:** I initially attempted to add Shopee support, but their anti-bot measures proved too robust for a simple implementation. I also experimented with more advanced libraries like Playwright, but found they were surprisingly detected and blocked by Tokopedia. The simpler, classic combination of `requests` and `BeautifulSoup4` worked flawlessly and was more than fast enough for this use case.

---

## License

Distributed under the MIT License. See `LICENSE` file for more information.

---

## Contact

zqil - [My Website](https://zqily.net) *(<- You can replace this with the correct link to your site)*
