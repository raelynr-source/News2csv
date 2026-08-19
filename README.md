# CloakBrowser DuckDuckGo News Scraper

This is a Python tool that searches DuckDuckGo News with CloakBrowser and
produces one CSV of search results for each topic.

## Download the project

Before installing anything, download this repository and open a terminal in its
folder. Choose one of these methods.

### Option 1: Clone with Git

If [Git](https://git-scm.com/downloads) is installed, open Terminal (macOS or
Linux) or PowerShell (Windows), then run:

```sh
git clone https://github.com/raelynr-source/News2csv/.git
cd News2csv-main
```

`git clone` downloads the project. `cd News2csv-main` moves your terminal
into the downloaded project folder, where you should run the rest of the
commands in this guide.

### Option 2: Download a ZIP

1. Open the
   [repository on GitHub](https://github.com/raelynr-source/News2csv).
2. Select the green **Code** button, then select **Download ZIP**.
3. Extract the downloaded ZIP file.
4. Open Terminal or PowerShell and move into the extracted folder. For example,
   if it was extracted in your Downloads folder:

macOS or Linux:

```sh
cd ~/Downloads/News2csv-main
```

Windows PowerShell:

```powershell
cd ~\Downloads\News2csv-main
```

If you extracted it somewhere else, use that folder's path instead.

## Install

You need Python 3.10 or newer.

### Ubuntu Linux prerequisite

On Linux, install Microsoft TrueType core fonts before running the scraper.
Having these common browser fonts available helps CloakBrowser present a more
typical browser environment and reduces the chance of DuckDuckGo blocking it.

On Ubuntu, run:

```sh
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository multiverse
sudo apt update
sudo apt install ttf-mscorefonts-installer
sudo fc-cache -f -v
```

The installer may show a Microsoft font license screen. Use **Tab** to select
**OK** or **Yes**, then press **Enter** to accept it and continue.

### macOS and Linux

From the project folder, run:

```sh
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m cloakbrowser install
```

### Windows PowerShell

From the project folder, run:

```powershell
# Confirm Python is installed
py --version

# Create the virtual environment
py -m venv .venv

# Activate it
.\.venv\Scripts\Activate.ps1

# Upgrade pip and install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Download CloakBrowser's Chromium
python -m cloakbrowser install

# Run the scraper
python .\scraper.py "Apple" "Bottom" "Jeans"
```

## Run

Run one or more searches:

```sh
python scraper.py "Apple" "Bottom" "Jeans"
```

That command writes 3 CSVs of the top DuckDuckGo News results containing
the words "Apple", "Bottom", and "Jeans". Each CSV contains fields such as the
headline, URL, description, date, and source.

You must provide at least one search query:

```sh
python scraper.py "age verification law"
```

You can also change the number of results:

```sh
python scraper.py "age verification law" --max-results 50
```

## Rate limits

DuckDuckGo may temporarily rate limit repeated searches. The script defaults to
25 results per query, waits 60-90 seconds between successful searches, and
caches successful responses for 24 hours in `.search_cache`. Re-running the same
query with the same options during that window uses the cache instead of making
another DuckDuckGo request.

For a gentler run, use fewer results and a longer pause:

```sh
python scraper.py "age verification law" "data breach federal" --max-results 5 --sleep-seconds 180 --sleep-jitter-seconds 120
```

For a monthly batch, shuffle the query order and keep going if one query is
temporarily blocked:

```sh
python scraper.py \
  "'age verification' AND 'law' OR 'policy' OR 'rule'" \
  "'Data breach' AND 'Federal'" \
  "'Protest' AND 'Student' OR 'federal' OR 'worker'" \
  --max-results 10 \
  --sleep-seconds 180 \
  --sleep-jitter-seconds 120 \
  --shuffle-queries \
  --continue-on-error
```

If a search fails or DuckDuckGo returns a block/challenge page, the script
retries 3 times with longer waits between retries. To keep going when one query
keeps failing, add:

```sh
python scraper.py "age verification law" "data breach federal" --continue-on-error
```

Use `--refresh` when you want fresh results even if there is a valid cache entry,
or `--no-cache` to disable caching completely.

For a visible browser window while debugging, add:

```sh
python scraper.py "age verification law" --max-results 3 --headed
```

## Tests

The default tests use local HTML fixtures and do not make live DuckDuckGo
requests:

```sh
python -m pytest
```

For a manual live smoke test, run:

```sh
python scraper.py "age verification law" --max-results 3 --continue-on-error
```

I write a monthly newsletter tracking major changes in privacy governing activism and technology https://raelyn.info/newsletter/
Here are the search terms I use to source content monthly:

"'age verification' AND 'law' OR 'policy' OR 'rule'"
"'Data' OR 'Detention' AND 'Center'"""
"'Data breach' AND 'Federal'"
"'Protest' AND 'Student' OR 'federal' OR 'worker'"
"'federal' AND 'website'"
