# Facebook Marketplace RSS Feed Generator

## Overview

This project generates a RSS feed for Facebook Marketplace, allowing you to track new ads based on customizable filters.  

Note: the code has been tested with `Python3` on `Linux` and `Windows 10`.

## Installation

1. **Clone the Repository:**

   ```bash
   git clone https://github.com/regek/facebook-marketplace-rss.git
   cd facebook-marketplace-rss
   ```

2. **Install Python Requirements:**

   ```bash
   pip install -r requirements.txt
   ```
3. **Install Firefox Browser:**

    [Linux install](https://support.mozilla.org/en-US/kb/install-firefox-linux)  
    [Windows install](https://support.mozilla.org/en-US/kb/how-install-firefox-windows)

## Configuration

1. **Modify or Create `config.json`:**

   - Copy `config.sample.json` to `config.json` and adjust the settings as needed.
   - At a minimum, you **must** modify the `currency` field to match your local marketplace.
   - Some currency symbols: USA: `$`, Canada: `CA$`, Europe: `€`, UK: `£`, Australia: `A$`
   - You can optionally change the `database_name`.

   Example `config.json`:

   ```json
   {
       "server_ip": "0.0.0.0",
       "server_port": 5000,
       "currency": "$",
       "refresh_interval_minutes": 15,
       "log_filename": "fb-rssfeed.log",
       "database_name": "fb-rss-feed.db",
       "url_filters": {
           "https://www.facebook.com/marketplace/category/search?query=smart%20tv&exact=false": {
               "level1": ["tv"],
               "level2": ["smart"],
               "level3": ["55\"", "55 inch"]
           },
           "https://www.facebook.com/marketplace/category/search?query=dishwasher&exact=false": {
               "level1": ["dishwasher"],
               "level2": ["kitchenaid", "samsung"]
           },
           "https://www.facebook.com/marketplace/category/search?query=free%20stuff&exact=false": {}
       }
   }
   ```

2. **Configuring URL Filters:**

   - **Browse Facebook Marketplace:** Perform a search with your desired keywords.
   - **Set Filters:** Apply search filters like sort order, price range, condition, etc.
   - **Copy URL:** Use the entire URL after setting the filters.

   The search function on Facebook Marketplace is incredibly frustrating. It often returns irrelevant results, even when you're searching for something specific. For instance, when you set the filter to "Date listed: Newest First," you might end up with spammy listings rather than relevant items. To improve the chances of finding what you're looking for, make sure to use the search filters.


   - **Define Search Terms:** For each URL, specify search terms in levels.  
     Keywords within a level are `OR` operations, and keywords between levels are `AND` operations.  
     Only ad `title` is searched  

     Example:
     - **URL 1:** `https://www.facebook.com/marketplace/page1`
       - **level1:** ["tv"]
       - **level2:** ["smart"]
       - **level3:** ["55\"", "55 inch"]

     This configuration will match titles containing "tv" and "smart" and either "55\"" or "55 inch". e.g., TCL 55" smart tv, smart tv 55 inch LG

     - **URL 2:** `https://www.facebook.com/marketplace/page2`
       - **level1:** ["dishwasher"]
       - **level2:** ["kitchenaid", "samsung"]

     This will match titles containing "dishwasher" and either "kitchenaid" or "samsung". e.g., samsung dishwasher xyz, slightly used kicthenaid dishwasher

     No custom filtering
     - **URL 3:** `https://www.facebook.com/marketplace/page2`

## Running the Application

1. **Run the Server:**

   The database (`fb-rss-feed.db` by default, or the name specified in `config.json`) will be created and initialized automatically the first time you run the server if it doesn't exist.

   ```bash
   python fb_ad_monitor.py
   ```

## Accessing the RSS Feed

- **Feed URL:** `http://server_ip:server_port/rss`

   Replace `server_ip` and `server_port` with your configured values (e.g., `http://localhost:5000/rss`).

- **Feed Updates:** The RSS feed displays ads that have been recently found or checked (typically within the last 7 days, based on database records). New ads matching your filters are added to the database and will appear in the feed shortly after being detected.

- **RSS Reader:** Use any RSS feed reader to monitor updates. For example, you can use [Feedbro](https://nodetics.com/feedbro/).

## Set log level (optional)
- set log level `export LOG_LEVEL=ERROR`

## How to run in a Docker container
- Provide `/path/to/config/directory`
- Leave the `server_ip` and `server_port` as default
```bash
docker run --name fb-mp-rss -d \
  -v /path/to/config/directory:/app/config \
  -e CONFIG_FILE=/app/config/config.json \
  -p 5000:5000 \
  regek/fb-mp-rss:latest
```

### How to run with Docker Compose
- Ensure you have `docker-compose.yml` in your project directory.
- Create your `config.json` file in the same directory.
- Run:
 ```bash
 docker-compose up -d
 ```
- The service will be available at `http://localhost:5000/rss`.
