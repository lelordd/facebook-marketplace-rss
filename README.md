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

You can configure the application by directly editing the `config.json` file or by using the web-based configuration editor. The web editor is generally recommended for ease of use and to ensure the configuration is correctly formatted.

### 1. Editing Configuration via Web UI (Recommended)

After starting the application (see "Running the Application" section), you can access a web interface to edit its configuration.

-   **Access URL:** `http://<server_ip>:<server_port>/edit-config`
    (Replace `<server_ip>` and `<server_port>` with the values from your `config.json`, e.g., `http://localhost:5000/edit-config` if using default server settings).
-   **Functionality:** This interface allows you to modify all settings that are typically found in `config.json`, including:
    -   Server IP and Port
    -   Currency Symbol
    -   Refresh Interval (choose from presets or set a custom value)
    -   URL Filters:
        -   Add new Facebook Marketplace search URLs to monitor.
        -   Define multi-level keyword filters for each URL (keywords within a level are OR'd, keywords between levels are AND'd).
        -   Remove existing URL filters or keyword levels.
-   **Saving Changes:** When you save the configuration through the UI:
    -   The `config.json` file on the server is automatically updated with your changes.
    -   A backup of the previous `config.json` is created (e.g., `config.json.bak`) in the same directory.
    -   The application reloads the new configuration and restarts its monitoring tasks with the new settings. This means any changes to refresh intervals or filters take effect immediately without needing to manually restart the server.

### 2. Manually Modifying `config.json`

If you prefer to edit the configuration file directly, or if you need to set up the initial `config.json` before running the server for the first time:

1.  **Locate or Create `config.json`:**
    -   Copy [`config.sample.json`](config.sample.json:1) to `config.json` in the project's root directory.
    -   Adjust the settings as needed.
    -   At a minimum, you **must** modify the `currency` field to match your local marketplace.
    -   Some currency symbols: USA: `$`, Canada: `CA$`, Europe: `€`, UK: `£`, Australia: `A$`
    -   You can optionally change other settings like `database_name`, `log_filename`, `server_ip`, and `server_port`.

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

2.  **Configuring URL Filters (Manual Method):**
    This section details how to structure the `url_filters` in `config.json` if editing manually. The web UI provides a more interactive way to manage these.

    -   **Browse Facebook Marketplace:** Perform a search with your desired keywords.
    -   **Set Filters:** Apply search filters like sort order, price range, condition, etc.
    -   **Copy URL:** Use the entire URL after setting the filters. This URL will be a key in the `url_filters` object.

    The search function on Facebook Marketplace can be frustrating. It often returns irrelevant results. Using specific search filters on Facebook Marketplace before copying the URL is highly recommended.

    -   **Define Search Terms:** For each URL, specify search terms in levels (e.g., `level1`, `level2`).
        Keywords within a single level (e.g., multiple items in `level1`) are treated as `OR` operations.
        Keywords between different levels (e.g., `level1` AND `level2`) are treated as `AND` operations.
        Only the ad `title` is searched by these keyword filters.
        If a URL has an empty object `{}` as its filter, all items from that URL will be included without keyword filtering.

        Example:
        -   **URL 1:** `https://www.facebook.com/marketplace/some_query_for_tvs`
            ```json
            "level1": ["tv"],
            "level2": ["smart"],
            "level3": ["55\"", "55 inch"]
            ```
          This configuration will match titles containing "tv" AND "smart" AND (either "55\"" OR "55 inch").
          e.g., "TCL 55\" smart tv", "smart tv 55 inch LG"

        -   **URL 2:** `https://www.facebook.com/marketplace/some_query_for_dishwashers`
            ```json
            "level1": ["dishwasher"],
            "level2": ["kitchenaid", "samsung"]
            ```
          This will match titles containing "dishwasher" AND (either "kitchenaid" OR "samsung").
          e.g., "samsung dishwasher xyz", "slightly used kitchenaid dishwasher"

## Running the Application

1. **Run the Server:**

   The database (`fb-rss-feed.db` by default, or the name specified in `config.json`) will be created and initialized automatically the first time you run the server if it doesn't exist.

   ```bash
   python fb_ad_monitor.py
   ```

## Accessing the Application via Web Browser

Once the server is running (see "Running the Application"), you can access the following endpoints using your web browser:

-   **RSS Feed URL:** `http://<server_ip>:<server_port>/rss`
    -   This is the main RSS feed generated from your Facebook Marketplace searches and filters.
    -   Replace `<server_ip>` and `<server_port>` with the values configured in your `config.json` (e.g., `http://localhost:5000/rss` if using default server settings).
    -   The feed displays ads recently found or checked (typically within the last 7 days, based on database records). New ads matching your filters are added to the database and will appear in the feed shortly after detection.
    -   Use any RSS feed reader to monitor updates. For example, [Feedbro](https://nodetics.com/feedbro/).

-   **Configuration Editor URL:** `http://<server_ip>:<server_port>/edit-config`
    -   This web page allows you to view and modify the application's configuration (`config.json`) directly in your browser.
    -   Changes made here are saved to `config.json`, and the application automatically reloads the new settings.
    -   Refer to the "Configuration" section (specifically "Editing Configuration via Web UI") for detailed information on using this editor.

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
