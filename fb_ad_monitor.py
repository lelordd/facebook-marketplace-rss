# fb_ad_monitor.py
# Copyright (c) 2024, regek
# All rights reserved.

# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
import waitress

import PyRSS2Gen
import tzlocal
from apscheduler.jobstores.base import ConflictingIdError
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from dateutil import parser
from flask import Flask, Response
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.firefox import GeckoDriverManager

# --- Constants ---
DEFAULT_DB_NAME = 'fb-rss-feed.db'
DEFAULT_LOG_LEVEL = 'INFO'
CONFIG_FILE_ENV_VAR = 'CONFIG_FILE'
DEFAULT_CONFIG_FILE = 'config.json'
LOG_LEVEL_ENV_VAR = 'LOG_LEVEL'
AD_DIV_SELECTOR = 'div.x78zum5.xdt5ytf.x1iyjqo2.xd4ddsz' # Selector for waiting
AD_LINK_TAG = 'a'
AD_TITLE_SELECTOR_STYLE = '-webkit-line-clamp' # Part of the style attribute for title span
AD_PRICE_SELECTOR_DIR = 'auto' # dir attribute for price span
SELENIUM_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0"
FACEBOOK_BASE_URL = "https://facebook.com"


class fbRssAdMonitor:
    """Monitors Facebook Marketplace search URLs for new ads and generates an RSS feed."""

    def __init__(self, json_file: str):
        """
        Initializes the fbRssAdMonitor instance.

        Args:
            json_file (str): Path to the configuration JSON file.
        """
        self.urls_to_monitor: List[str] = []
        self.url_filters: Dict[str, Dict[str, List[str]]] = {}
        self.database: str = DEFAULT_DB_NAME
        self.local_tz = tzlocal.get_localzone()
        self.log_filename: str = "fb_monitor.log" # Default, will be overwritten by config
        self.server_ip: str = "0.0.0.0" # Default
        self.server_port: int = 5000 # Default
        self.currency: str = "$" # Default
        self.refresh_interval_minutes: int = 15 # Default
        self.driver: Optional[webdriver.Firefox] = None
        self.logger: logging.Logger = logging.getLogger(__name__) # Placeholder, setup in set_logger
        self.scheduler: Optional[BackgroundScheduler] = None
        self.job_lock: Lock = Lock()

        self.load_from_json(json_file) # Load config which might overwrite defaults
        self.set_logger() # Setup logger after potentially getting log filename from config
        self.app: Flask = Flask(__name__)
        self.app.add_url_rule('/rss', 'rss', self.rss)
        self.rss_feed: PyRSS2Gen.RSS2 = PyRSS2Gen.RSS2(
            title="Facebook Marketplace Ad Feed",
            link=f"http://{self.server_ip}:{self.server_port}/rss", # Use configured IP/Port
            description="An RSS feed to monitor new ads on Facebook Marketplace",
            lastBuildDate=datetime.now(timezone.utc),
            items=[]
        )


    def set_logger(self) -> None:
        """
        Sets up logging configuration with both file and console streaming.
        Log level is fetched from the environment variable LOG_LEVEL.
        """
        self.logger = logging.getLogger(__name__) # Get the logger instance
        log_formatter = logging.Formatter(
            '%(levelname)s:%(asctime)s:%(funcName)s:%(lineno)d::%(message)s',
            datefmt='%m/%d/%Y %I:%M:%S %p'
        )

        # Get log level from environment variable, defaulting to INFO if not set
        log_level_str = os.getenv(LOG_LEVEL_ENV_VAR, DEFAULT_LOG_LEVEL).upper()
        try:
            log_level = logging.getLevelName(log_level_str)
            if not isinstance(log_level, int): # Check if getLevelName returned a valid level
                 # Use basicConfig for logging before logger is fully set up
                 logging.basicConfig(level=logging.WARNING)
                 logging.warning(f"Invalid LOG_LEVEL '{log_level_str}'. Defaulting to {DEFAULT_LOG_LEVEL}.")
                 log_level = logging.INFO
        except ValueError:
            logging.basicConfig(level=logging.WARNING)
            logging.warning(f"Invalid LOG_LEVEL '{log_level_str}'. Defaulting to {DEFAULT_LOG_LEVEL}.")
            log_level = logging.INFO


        # File handler (rotating log)
        try:
            file_handler = RotatingFileHandler(
                self.log_filename, mode='a', maxBytes=10*1024*1024, # Use 'a' for append
                backupCount=2, encoding='utf-8', delay=False # Use utf-8
            )
            file_handler.setFormatter(log_formatter)
            file_handler.setLevel(log_level)
            self.logger.addHandler(file_handler)
        except Exception as e:
             # Use basicConfig for fallback logging if file handler fails
            logging.basicConfig(level=logging.ERROR)
            logging.error(f"Failed to set up file logging handler for {self.log_filename}: {e}. Logging to console only.")


        # Stream handler (console output)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        console_handler.setLevel(log_level)

        # Set the logger level and add handlers
        self.logger.setLevel(log_level)
        # self.logger.addHandler(file_handler) # Added above with error handling
        self.logger.addHandler(console_handler)
        self.logger.info(f"Logger initialized with level {logging.getLevelName(log_level)}")


    def init_selenium(self) -> None:
        """
        Initializes Selenium WebDriver with Firefox options.
        Ensures any existing driver is quit first.
        """
        self.quit_selenium() # Ensure previous instance is closed

        try:
            self.logger.debug("Initializing Selenium WebDriver...")
            firefox_options = FirefoxOptions()
            firefox_options.add_argument("--no-sandbox")
            firefox_options.add_argument("--disable-dev-shm-usage")
            firefox_options.add_argument("--private")
            firefox_options.add_argument("--headless")
            firefox_options.set_preference("general.useragent.override", SELENIUM_USER_AGENT)
            firefox_options.set_preference("dom.webdriver.enabled", False)
            firefox_options.set_preference("useAutomationExtension", False)
            firefox_options.set_preference("privacy.resistFingerprinting", True)

            # Suppress GeckoDriverManager logs unless logger level is DEBUG
            log_level_gecko = logging.WARNING if self.logger.level > logging.DEBUG else logging.DEBUG
            os.environ['WDM_LOG_LEVEL'] = str(log_level_gecko) # Set env var for WDM logging level
            # Also configure WDM to use the logger's log file if possible
            os.environ['WDM_LOCAL'] = '1' # Try to use local cache
            # Note: WDM might still log to stderr/stdout depending on its internal setup

            gecko_driver_path = GeckoDriverManager().install()
            # Redirect selenium service logs to /dev/null (or NUL on windows) to prevent console spam
            service_log_path = 'nul' if os.name == 'nt' else '/dev/null'
            self.driver = webdriver.Firefox(
                service=FirefoxService(gecko_driver_path, log_path=service_log_path),
                options=firefox_options
            )
            self.logger.debug("Selenium WebDriver initialized successfully.")

        except WebDriverException as e:
            self.logger.error(f"WebDriverException during Selenium initialization: {e}")
            self.driver = None # Ensure driver is None if init fails
            raise # Re-raise the exception to be handled by the caller
        except Exception as e:
            self.logger.error(f"Unexpected error initializing Selenium: {e}")
            self.driver = None # Ensure driver is None if init fails
            raise # Re-raise the exception


    def quit_selenium(self) -> None:
        """Safely quits the Selenium WebDriver if it exists."""
        if self.driver:
            self.logger.debug("Quitting Selenium WebDriver...")
            try:
                self.driver.quit()
                self.logger.debug("Selenium WebDriver quit successfully.")
            except WebDriverException as e:
                self.logger.error(f"Error quitting Selenium WebDriver: {e}")
            except Exception as e:
                 self.logger.error(f"Unexpected error quitting Selenium WebDriver: {e}")
            finally:
                self.driver = None # Ensure driver is set to None


    def setup_scheduler(self) -> None:
        """
        Sets up the background job scheduler to check for new ads.
        """
        if self.scheduler and self.scheduler.running:
             self.logger.warning("Scheduler is already running.")
             return

        self.logger.info(f"Setting up scheduler to run every {self.refresh_interval_minutes} minutes.")
        self.scheduler = BackgroundScheduler(timezone=str(self.local_tz)) # Use local timezone
        job_id = 'check_ads_job' # Use a fixed ID
        try:
            self.scheduler.add_job(
                self.check_for_new_ads,
                'interval',
                id=job_id,
                minutes=self.refresh_interval_minutes,
                misfire_grace_time=60, # Increased grace time
                coalesce=True,
                next_run_time=datetime.now(self.local_tz) + timedelta(seconds=5) # Start soon
            )
            self.scheduler.start()
            self.logger.info(f"Scheduler started with job '{job_id}'.")
        except ConflictingIdError:
            self.logger.warning(f"Job '{job_id}' already exists. Attempting to resume scheduler.")
            # If scheduler wasn't running but job exists, try starting it
            if not self.scheduler.running:
                 try:
                      self.scheduler.start(paused=False)
                      self.logger.info("Scheduler resumed.")
                 except Exception as e:
                      self.logger.error(f"Failed to resume scheduler: {e}")

        except Exception as e:
             self.logger.error(f"Failed to setup or start scheduler: {e}")


    def local_time(self, dt: datetime) -> datetime:
        """Converts a UTC datetime object to local time."""
        if dt.tzinfo is None:
             # Assume UTC if no timezone info
             dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(self.local_tz)


    def load_from_json(self, json_file: str) -> None:
        """
        Loads configuration from a JSON file.

        Args:
            json_file (str): Path to the JSON file.

        Raises:
            FileNotFoundError: If the JSON file is not found.
            ValueError: If the JSON file is invalid or missing required keys.
            Exception: For other unexpected errors during loading.
        """
        self.logger.info(f"Loading configuration from {json_file}...")
        try:
            with open(json_file, 'r', encoding='utf-8') as file:
                data = json.load(file)

            # Validate and assign configuration values
            self.server_ip = data.get('server_ip', self.server_ip)
            self.server_port = data.get('server_port', self.server_port)
            self.currency = data.get('currency', self.currency)
            self.refresh_interval_minutes = data.get('refresh_interval_minutes', self.refresh_interval_minutes)
            self.log_filename = data.get('log_filename', self.log_filename)
            self.database = data.get('database_name', self.database) # Allow overriding DB name

            # Validate url_filters structure
            url_filters_raw = data.get('url_filters', {})
            if not isinstance(url_filters_raw, dict):
                 raise ValueError("'url_filters' must be a dictionary in the config file.")

            self.url_filters = url_filters_raw
            self.urls_to_monitor = list(self.url_filters.keys())

            if not self.urls_to_monitor:
                 self.logger.warning("No URLs found in 'url_filters'. Monitoring will be inactive.")

            self.logger.info("Configuration loaded successfully.")
            self.logger.debug(f"Monitoring URLs: {self.urls_to_monitor}")
            self.logger.debug(f"Refresh interval: {self.refresh_interval_minutes} minutes")
            self.logger.debug(f"Log file: {self.log_filename}")
            self.logger.debug(f"Database: {self.database}")


        except FileNotFoundError:
            self.logger.error(f"Configuration file not found: {json_file}")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding JSON from {json_file}: {e}")
            raise ValueError(f"Invalid JSON format in {json_file}") from e
        except KeyError as e:
             self.logger.error(f"Missing required key in configuration file {json_file}: {e}")
             raise ValueError(f"Missing key '{e}' in {json_file}") from e
        except ValueError as e: # Catch specific validation errors
             self.logger.error(f"Configuration error in {json_file}: {e}")
             raise
        except Exception as e:
            self.logger.exception(f"Unexpected error loading configuration from {json_file}: {e}") # Use exception for stack trace
            raise


    def apply_filters(self, url: str, title: str) -> bool:
        """
        Applies keyword filters specific to the URL to the ad title.
        Filters are defined in levels (e.g., "level1", "level2"). An ad must
        match at least one keyword from *each* defined level for the given URL.

        Args:
            url (str): The URL for which to apply filters.
            title (str): The title of the ad.

        Returns:
            bool: True if the title matches all filter levels for the URL, False otherwise.
        """
        filters = self.url_filters.get(url)
        if not filters:
            self.logger.debug(f"No filters defined for URL '{url}'. Ad '{title}' passes.")
            return True # No filters for this URL, so it passes

        if not isinstance(filters, dict):
             self.logger.warning(f"Filters for URL '{url}' are not a dictionary. Skipping filters.")
             return True # Invalid filter format, treat as passing

        try:
            # Sort levels numerically (level1, level2, ...)
            level_keys = sorted(
                [k for k in filters.keys() if k.startswith('level') and k[5:].isdigit()],
                key=lambda x: int(x[5:])
            )

            if not level_keys:
                 self.logger.debug(f"No valid 'levelX' keys found in filters for URL '{url}'. Ad '{title}' passes.")
                 return True # No valid levels defined

            # self.logger.debug(f"Applying filters for URL '{url}' to title '{title}'. Levels: {level_keys}")

            title_lower = title.lower()
            for level in level_keys:
                keywords = filters.get(level, [])
                if not isinstance(keywords, list):
                     self.logger.warning(f"Keywords for level '{level}' in URL '{url}' are not a list. Skipping level.")
                     continue # Skip invalid level format

                if not keywords:
                     self.logger.debug(f"No keywords defined for level '{level}' in URL '{url}'. Skipping level.")
                     continue # Skip empty level

                # Check if *any* keyword in this level matches
                if not any(keyword.lower() in title_lower for keyword in keywords):
                    self.logger.debug(f"Ad '{title}' failed filter level '{level}' for URL '{url}'. Keywords: {keywords}")
                    return False # Must match at least one keyword per level

            # If all levels passed
            self.logger.debug(f"Ad '{title}' passed all filter levels for URL '{url}'.")
            return True

        except Exception as e:
            self.logger.exception(f"Error applying filters for URL '{url}', title '{title}': {e}")
            return False # Fail safe on error


    def save_html(self, soup: BeautifulSoup, filename: str = 'output.html') -> None:
        """Saves the prettified HTML content of a BeautifulSoup object to a file."""
        try:
            html_content = soup.prettify()
            with open(filename, 'w', encoding='utf-8') as file:
                file.write(html_content)
            self.logger.debug(f"HTML content saved to {filename}")
        except Exception as e:
            self.logger.error(f"Error saving HTML to {filename}: {e}")


    def get_page_content(self, url: str) -> Optional[str]:
        """
        Fetches the page content using Selenium.

        Args:
            url (str): The URL of the page to fetch.

        Returns:
            Optional[str]: The HTML content of the page, or None if an error occurred.
        """
        if not self.driver:
             self.logger.error("Selenium driver not initialized. Cannot fetch page content.")
             return None
        try:
            self.logger.info(f"Requesting URL: {url}")
            self.driver.get(url)
            # Wait for a container element that typically holds the ads
            WebDriverWait(self.driver, 20).until( # Increased wait time
                EC.presence_of_element_located((By.CSS_SELECTOR, AD_DIV_SELECTOR))
            )
            self.logger.debug(f"Page content loaded successfully for {url}")
            return self.driver.page_source
        except WebDriverException as e:
            self.logger.error(f"Selenium error fetching page content for {url}: {e}")
            # Optionally save page source on error for debugging
            # try:
            #     page_source_on_error = self.driver.page_source
            #     error_filename = f"error_page_{int(time.time())}.html"
            #     with open(error_filename, "w", encoding="utf-8") as f:
            #         f.write(page_source_on_error)
            #     self.logger.info(f"Saved page source on error to {error_filename}")
            # except Exception as save_err:
            #      self.logger.error(f"Could not save page source on error: {save_err}")
            return None
        except Exception as e:
            self.logger.exception(f"Unexpected error fetching page content for {url}: {e}")
            return None


    def get_ads_hash(self, content: str) -> str:
        """
        Generates an MD5 hash for the given content (typically a URL).

        Args:
            content (str): The content to hash.

        Returns:
            str: The MD5 hash of the content.
        """
        return hashlib.md5(content.encode('utf-8')).hexdigest()


    def extract_ad_details(self, content: str, source_url: str) -> List[Tuple[str, str, str, str]]:
        """
        Extracts ad details from the page HTML content and applies URL-specific filters.

        Args:
            content (str): The HTML content of the page.
            source_url (str): The original URL the content was fetched from (used for filtering).

        Returns:
            List[Tuple[str, str, str, str]]: A list of tuples, where each tuple contains
                                             (ad_id_hash, title, price, ad_url).
                                             Only ads matching filters are included.
        """
        ads_found: List[Tuple[str, str, str, str]] = []
        try:
            soup = BeautifulSoup(content, 'html.parser')
            # --- Uncomment to save HTML for debugging ---
            # self.save_html(soup, f"page_content_{source_url.split('/')[-1].split('?')[0]}_{int(time.time())}.html")

            # Find all potential ad links (<a> tags with an href)
            ad_links = soup.find_all(AD_LINK_TAG, href=True)
            self.logger.debug(f"Found {len(ad_links)} potential ad links on {source_url}.")

            processed_urls = set() # Keep track of processed ad URLs to avoid duplicates from the same page

            for ad_link in ad_links:
                href = ad_link.get('href', '')
                # Basic validation of the link (e.g., starts with /marketplace/item/)
                if not href or not href.startswith('/marketplace/item/'):
                    continue

                # Construct full URL and normalize (remove query params)
                full_url = f"{FACEBOOK_BASE_URL}{href.split('?')[0]}"

                if full_url in processed_urls:
                     continue # Skip if already processed this ad URL on this page
                processed_urls.add(full_url)


                # Find title and price within the context of the current link
                # Look for a span with the specific style attribute for the title
                title_span = ad_link.find('span', style=lambda value: value and AD_TITLE_SELECTOR_STYLE in value)
                # Look for a span with dir='auto' for the price (more reliable than just text)
                price_span = ad_link.find('span', dir=AD_PRICE_SELECTOR_DIR)

                if title_span and price_span:
                    title = title_span.get_text(strip=True)
                    price = price_span.get_text(strip=True)

                    # Validate price format (starts with currency or is 'free')
                    if price.startswith(self.currency) or 'free' in price.lower():
                        # Generate a unique ID based on the ad's URL
                        ad_id_hash = self.get_ads_hash(full_url)

                        # Apply filters based on the source URL the ad was found on
                        if self.apply_filters(source_url, title):
                            ads_found.append((ad_id_hash, title, price, full_url))
                        # else:
                        #     self.logger.debug(f"Ad '{title}' ({full_url}) skipped due to filters for {source_url}.")
                    # else:
                    #      self.logger.debug(f"Price format invalid for ad '{title}' ({full_url}). Price found: '{price}'")

            self.logger.info(f"Extracted {len(ads_found)} ads matching filters from {source_url}.")
            return ads_found

        except Exception as e:
            self.logger.exception(f"Error extracting ad details from {source_url}: {e}")
            return []


    def get_db_connection(self) -> Optional[sqlite3.Connection]:
        """
        Establishes a connection to the SQLite database.

        Returns:
            Optional[sqlite3.Connection]: The database connection object, or None on error.
        """
        try:
            conn = sqlite3.connect(self.database, timeout=10) # Add timeout
            conn.row_factory = sqlite3.Row
            # Optional: Enable WAL mode for better concurrency
            # try:
            #      conn.execute("PRAGMA journal_mode=WAL;")
            # except sqlite3.Error as e:
            #      self.logger.warning(f"Could not enable WAL mode for database: {e}")
            self.logger.debug(f"Database connection established to {self.database}")
            return conn
        except sqlite3.Error as e:
            self.logger.error(f"Database connection error to {self.database}: {e}")
            return None


    def check_for_new_ads(self) -> None:
        """
        Checks for new ads on monitored URLs, updates the database, and adds new ads to the RSS feed object.
        This method is intended to be run as a scheduled job.
        """
        if not self.job_lock.acquire(blocking=False):
            self.logger.warning("Ad check job is already running. Skipping this execution.")
            return

        self.logger.info("Starting scheduled check for new ads...")
        conn = None
        new_ads_added_count = 0
        processed_urls_count = 0

        try:
            conn = self.get_db_connection()
            if not conn:
                self.logger.error("Failed to get database connection. Aborting ad check.")
                return # Cannot proceed without DB

            cursor = conn.cursor()
            # Keep track of ads added in this run to avoid duplicates if multiple URLs list the same ad
            added_ad_ids_this_run = set()

            for url in self.urls_to_monitor:
                processed_urls_count += 1
                self.logger.info(f"Processing URL ({processed_urls_count}/{len(self.urls_to_monitor)}): {url}")
                try:
                    self.init_selenium() # Initialize driver for this URL
                    if not self.driver:
                         self.logger.warning(f"Skipping URL {url} due to Selenium initialization failure.")
                         continue # Skip to next URL if driver init failed

                    content = self.get_page_content(url)
                    self.quit_selenium() # Quit driver after fetching content for this URL

                    if content is None:
                        self.logger.warning(f"No content received for URL: {url}. Skipping.")
                        continue

                    ads = self.extract_ad_details(content, url)
                    if not ads:
                         self.logger.info(f"No matching ads found or extracted for URL: {url}.")
                         continue


                    for ad_id, title, price, ad_url in ads:
                        if ad_id in added_ad_ids_this_run:
                             self.logger.debug(f"Ad '{title}' ({ad_id}) already processed in this run. Skipping.")
                             continue # Avoid processing the same ad multiple times if found via different source URLs

                        # Check if ad exists in DB (more robust check than just recent)
                        cursor.execute('SELECT ad_id FROM ad_changes WHERE ad_id = ?', (ad_id,))
                        existing_ad = cursor.fetchone()
                        now_utc = datetime.now(timezone.utc)
                        now_iso = now_utc.isoformat()

                        if existing_ad is None:
                            # Ad is completely new
                            self.logger.info(f"New ad detected: '{title}' ({price}) - {ad_url}")
                            new_item = PyRSS2Gen.RSSItem(
                                title=f"{title} - {price}",
                                link=ad_url,
                                description=f"Price: {price} | Title: {title}", # Simpler description
                                guid=PyRSS2Gen.Guid(ad_id, isPermaLink=False), # Use ad_id hash as GUID
                                pubDate=self.local_time(now_utc) # Use local time for pubDate
                            )
                            try:
                                cursor.execute(
                                    'INSERT INTO ad_changes (url, ad_id, title, price, first_seen, last_checked) VALUES (?, ?, ?, ?, ?, ?)',
                                    (ad_url, ad_id, title, price, now_iso, now_iso)
                                )
                                conn.commit()
                                # Prepend to the live RSS feed object
                                self.rss_feed.items.insert(0, new_item)
                                added_ad_ids_this_run.add(ad_id)
                                new_ads_added_count += 1
                                self.logger.debug(f"Successfully added new ad '{title}' to DB and RSS feed.")
                            except sqlite3.IntegrityError:
                                self.logger.warning(f"IntegrityError inserting ad '{title}' ({ad_id}). Might be a race condition. Updating last_checked.")
                                # If insert fails due to constraint (e.g., ad added between SELECT and INSERT), update last_checked
                                cursor.execute('UPDATE ad_changes SET last_checked = ? WHERE ad_id = ?',
                                               (now_iso, ad_id))
                                conn.commit()
                            except sqlite3.Error as db_err:
                                 self.logger.error(f"Database error processing ad '{title}' ({ad_id}): {db_err}")
                                 conn.rollback() # Rollback on error for this specific ad

                        else:
                             # Ad exists, update last_checked timestamp
                             self.logger.debug(f"Existing ad found: '{title}' ({ad_id}). Updating last_checked.")
                             cursor.execute('UPDATE ad_changes SET last_checked = ? WHERE ad_id = ?',
                                            (now_iso, ad_id))
                             conn.commit()


                except Exception as url_proc_err:
                     self.logger.exception(f"Error processing URL {url}: {url_proc_err}")
                     # Ensure driver is quit even if processing fails mid-way for a URL
                     self.quit_selenium()
                finally:
                     # Short delay between processing URLs
                     time.sleep(2)


            # --- Optional: Prune old ads from DB ---
            self.prune_old_ads(conn)

            self.logger.info(f"Finished ad check. Added {new_ads_added_count} new ads.")

        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error during ad check: {e}")
            if conn:
                 conn.rollback() # Rollback any potential partial changes
        except Exception as e:
            self.logger.exception(f"Unexpected error during ad check: {e}") # Use exception for stack trace
        finally:
            # Ensure driver is quit if the loop finished or broke unexpectedly
            self.quit_selenium()
            if conn:
                conn.close()
                self.logger.debug("Database connection closed.")
            self.job_lock.release()
            self.logger.debug("Ad check job lock released.")


    def prune_old_ads(self, conn: sqlite3.Connection, days_to_keep: int = 14) -> None:
        """Removes ads from the database that haven't been seen for a specified number of days."""
        if not conn:
             self.logger.warning("Cannot prune ads, database connection is not available.")
             return
        try:
             cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
             self.logger.info(f"Pruning ads last checked before {cutoff_date.isoformat()}...")
             cursor = conn.cursor()
             cursor.execute("DELETE FROM ad_changes WHERE last_checked < ?", (cutoff_date.isoformat(),))
             deleted_count = cursor.rowcount
             conn.commit()
             self.logger.info(f"Pruned {deleted_count} old ad entries from the database.")
        except sqlite3.Error as e:
             self.logger.error(f"Error pruning old ads from database: {e}")
             conn.rollback()


    def generate_rss_feed_from_db(self) -> None:
        """
        Generates the RSS feed items list from recent ad changes in the database.
        This replaces the current items in self.rss_feed.items.
        """
        self.logger.debug("Generating RSS feed items from database...")
        conn = None
        new_items: List[PyRSS2Gen.RSSItem] = []
        try:
            conn = self.get_db_connection()
            if not conn:
                 self.logger.error("Cannot generate RSS feed from DB: No database connection.")
                 # Keep existing items if DB fails
                 return

            cursor = conn.cursor()
            # Fetch ads from the last N days (e.g., 7 days) or based on refresh interval for relevance
            # Using a fixed period like 7 days might be more robust than relying on lastBuildDate
            relevant_period_start = datetime.now(timezone.utc) - timedelta(days=7)

            cursor.execute('''
                SELECT ad_id, title, price, url, last_checked
                FROM ad_changes
                WHERE last_checked >= ?
                ORDER BY last_checked DESC
                LIMIT 100
            ''', (relevant_period_start.isoformat(),)) # Limit number of items
            changes = cursor.fetchall()
            self.logger.debug(f"Fetched {len(changes)} ad changes from DB for RSS feed.")

            for change in changes:
                try:
                    # Ensure last_checked is parsed correctly
                    last_checked_dt_utc = parser.isoparse(change['last_checked'])
                    # Convert to local time for pubDate
                    pub_date_local = self.local_time(last_checked_dt_utc)

                    new_item = PyRSS2Gen.RSSItem(
                        title=f"{change['title']} - {change['price']}",
                        link=change['url'],
                        description=f"Price: {change['price']} | Title: {change['title']}", # Consistent description
                        guid=PyRSS2Gen.Guid(change['ad_id'], isPermaLink=False),
                        pubDate=pub_date_local
                    )
                    new_items.append(new_item)
                except (ValueError, TypeError) as e:
                    self.logger.error(f"Error processing ad change for RSS (ID: {change['ad_id']}): {e}. Skipping item.")
                except Exception as item_err:
                     self.logger.exception(f"Unexpected error creating RSS item for ad (ID: {change['ad_id']}): {item_err}. Skipping item.")


            # Update the RSS feed object
            self.rss_feed.items = new_items
            self.rss_feed.lastBuildDate = datetime.now(timezone.utc) # Update last build date
            self.logger.info(f"RSS feed updated with {len(new_items)} items from database.")

        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error generating RSS feed: {e}")
            # Optionally keep old items on error: `return` instead of `self.rss_feed.items = []`
            self.rss_feed.items = [] # Clear items on DB error to avoid stale data? Or keep old ones? Clearing for now.
        except Exception as e:
            self.logger.exception(f"Unexpected error generating RSS feed: {e}")
            self.rss_feed.items = [] # Clear items on unexpected error
        finally:
            if conn:
                conn.close()
                self.logger.debug("Database connection closed after RSS generation.")


    def rss(self) -> Response:
        """
        Flask endpoint handler. Generates and returns the RSS feed XML.
        """
        self.logger.info("RSS feed requested. Generating fresh feed from database.")
        # Regenerate the feed content from the DB every time it's requested
        # to ensure it's up-to-date, rather than relying solely on the scheduled update.
        self.generate_rss_feed_from_db()

        try:
            rss_xml = self.rss_feed.to_xml(encoding='utf-8')
            return Response(rss_xml, mimetype='application/rss+xml')
        except Exception as e:
             self.logger.exception(f"Error converting RSS feed to XML: {e}")
             return Response("Error generating RSS feed.", status=500, mimetype='text/plain')


    def run(self, debug_opt: bool = False) -> None:
        """
        Starts the Flask application and the background scheduler.

        Args:
            debug_opt (bool): Run Flask in debug mode. Defaults to False.
        """
        self.logger.info(f"Starting Flask server on {self.server_ip}:{self.server_port}...")
        # Start scheduler before Flask app
        self.setup_scheduler()

        try:
            # Use waitress or gunicorn in production instead of Flask's development server
            if debug_opt:
                 self.logger.warning("Running Flask in DEBUG mode.")
                 # When using scheduler, typically disable Flask's reloader
                 self.app.run(host=self.server_ip, port=self.server_port, debug=True, use_reloader=False)
            else:
                 # Consider using a production-ready server like waitress
                 try:
                     from waitress import serve
                     self.logger.info("Running Flask with Waitress production server.")
                     serve(self.app, host=self.server_ip, port=self.server_port, threads=4) # Example with waitress
                 except ImportError:
                     self.logger.warning("Waitress not found. Falling back to Flask development server.")
                     self.logger.warning("Install waitress for a production-ready server: pip install waitress")
                     self.app.run(host=self.server_ip, port=self.server_port, debug=False, use_reloader=False)


        except KeyboardInterrupt:
            self.logger.info("KeyboardInterrupt received. Shutting down...")
        except SystemExit:
            self.logger.info("SystemExit received. Shutting down...")
        except Exception as e:
             self.logger.exception(f"Error running the application: {e}")
        finally:
            self.shutdown()


    def shutdown(self) -> None:
        """Gracefully shuts down the scheduler and Selenium driver."""
        self.logger.info("Initiating shutdown sequence...")
        if self.scheduler and self.scheduler.running:
            self.logger.info("Shutting down scheduler...")
            try:
                 # wait=False allows faster shutdown, True waits for running jobs
                 self.scheduler.shutdown(wait=False)
                 self.logger.info("Scheduler shut down.")
            except Exception as e:
                 self.logger.error(f"Error shutting down scheduler: {e}")
        else:
             self.logger.info("Scheduler not running or not initialized.")

        self.quit_selenium() # Ensure Selenium driver is closed
        self.logger.info("Shutdown sequence complete.")


def initialize_database(db_name: str, logger: logging.Logger) -> None:
    """Initializes the SQLite database and creates the necessary table if it doesn't exist."""
    conn = None
    try:
        logger.info(f"Initializing database: {db_name}")
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ad_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                ad_id TEXT UNIQUE NOT NULL, -- Hash of the ad URL, must be unique
                title TEXT NOT NULL,
                price TEXT NOT NULL,
                first_seen TEXT NOT NULL, -- ISO format datetime string (UTC)
                last_checked TEXT NOT NULL -- ISO format datetime string (UTC)
            )
        ''')
        # Optional: Add index for faster lookups
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ad_id ON ad_changes (ad_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_checked ON ad_changes (last_checked)')
        conn.commit()
        logger.info(f"Database '{db_name}' initialized successfully.")
    except sqlite3.Error as e:
        logger.error(f"Error initializing database {db_name}: {e}")
        raise # Re-raise to prevent application start if DB init fails
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    # Basic logger setup for initialization phase before config is loaded
    init_logger = logging.getLogger('init')
    init_handler = logging.StreamHandler()
    init_formatter = logging.Formatter('%(levelname)s:%(asctime)s::%(message)s', datefmt='%m/%d/%Y %I:%M:%S %p')
    init_handler.setFormatter(init_formatter)
    init_logger.addHandler(init_handler)
    init_logger.setLevel(logging.INFO)

    config_file = os.getenv(CONFIG_FILE_ENV_VAR, DEFAULT_CONFIG_FILE)
    init_logger.info(f"Using configuration file: {config_file}")

    if not os.path.exists(config_file):
        init_logger.error(f"Error: Config file '{config_file}' not found!")
        exit(1) # Use non-zero exit code for errors

    monitor_instance = None
    try:
        # Initialize monitor (loads config, sets up detailed logging)
        monitor_instance = fbRssAdMonitor(json_file=config_file)

        # Initialize database using the name from the loaded config
        initialize_database(monitor_instance.database, monitor_instance.logger)

        # Run the monitor (starts scheduler and Flask app)
        # Set debug_opt=True for development/debugging Flask
        monitor_instance.run(debug_opt=False)

    except (FileNotFoundError, ValueError, sqlite3.Error) as e:
         init_logger.error(f"Initialization failed: {e}")
         # Ensure shutdown is called if monitor was partially initialized
         if monitor_instance:
              monitor_instance.shutdown()
         exit(1)
    except Exception as e:
        init_logger.exception(f"An unexpected error occurred during startup or runtime: {e}")
        if monitor_instance:
             monitor_instance.shutdown()
        exit(1)


# Example JSON structure for URL-specific filters (remains the same)
# {
#     "server_ip": "0.0.0.0",
#     "server_port": 5000,
#     "currency": "$",
#     "refresh_interval_minutes": 15,
#     "log_filename": "fb_monitor.log",
#     "database_name": "fb-rss-feed.db", # Example: Allow overriding DB name
#     "url_filters": {
#         "https://www.facebook.com/marketplace/category/search?query=some%20item&exact=false": {
#             "level1": ["keyword1", "keyword2"],
#             "level2": ["must_have_this"]
#         },
#         "https://www.facebook.com/marketplace/brisbane/search?query=another%20search": {
#             "level1": ["brisbane_only_keyword"]
#         }
#     }
# }