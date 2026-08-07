import argparse
import hashlib
import json
import random
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from bs4 import BeautifulSoup


DUCKDUCKGO_NEWS_URL = "https://duckduckgo.com/"
RESULT_COLUMNS = ["title", "url", "description", "date", "source"]
SAFESEARCH_PARAMS = {
    "on": "1",
    "moderate": "-1",
    "off": "-2",
}
BLOCK_PATTERNS = (
    "captcha",
    "challenge",
    "verify you are human",
    "unusual traffic",
    "too many requests",
    "temporarily blocked",
    "access denied",
)


class SearchBlockedError(RuntimeError):
    """Raised when the search page appears to be blocked or challenged."""


class SearchNavigationError(RuntimeError):
    """Raised when the browser cannot load enough page content to parse."""


def safe_filename(query):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", query).strip("_")
    return name or "duckduckgo_news"


def build_news_url(query, timelimit, region, safesearch):
    params = {
        "q": query,
        "iar": "news",
        "ia": "news",
        "kl": region,
        "kp": SAFESEARCH_PARAMS[safesearch],
    }
    if timelimit:
        params["df"] = timelimit
    return f"{DUCKDUCKGO_NEWS_URL}?{urlencode(params)}"


def cache_key(query, max_results, timelimit, region, safesearch):
    payload = {
        # Include a parser version so bad results produced by an older parser
        # are not silently reused after an extraction fix.
        "engine": "cloakbrowser-duckduckgo-news-v2",
        "query": query,
        "max_results": max_results,
        "timelimit": timelimit,
        "region": region,
        "safesearch": safesearch,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_cache(cache_dir, key, cache_ttl_hours):
    cache_path = cache_dir / f"{key}.json"
    if not cache_path.exists():
        return None

    with cache_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    fetched_at = datetime.fromisoformat(payload["fetched_at"])
    expires_at = fetched_at + timedelta(hours=cache_ttl_hours)
    if datetime.now(timezone.utc) > expires_at:
        return None

    return payload["results"]


def write_cache(cache_dir, key, results):
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{key}.json"
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    with cache_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, default=str)


def visible_text(element):
    return " ".join(element.get_text(" ", strip=True).split())


def first_attr(element, attrs):
    for attr in attrs:
        value = element.get(attr)
        if value:
            return value
    return ""


def is_likely_blocked_html(html):
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()
    return any(pattern in text for pattern in BLOCK_PATTERNS)


def is_result_container(element):
    attrs = " ".join(
        str(value)
        for key, value in element.attrs.items()
        if key in {"class", "id", "data-testid", "data-layout"}
    ).lower()
    if not attrs:
        return element.name == "article" and element.find("a", href=True)
    return (
        element.name == "article"
        or "result" in attrs
        or "news" in attrs
        or "tile" in attrs
    ) and element.find("a", href=True)


def external_urls(element):
    return {
        link["href"]
        for link in element.find_all("a", href=True)
        if link["href"].startswith(("http://", "https://"))
    }


def find_result_containers(soup):
    candidates = []
    for element in soup.find_all(["article", "div", "li"]):
        if not is_result_container(element):
            continue
        # A page-level wrapper such as ``#news-results`` also matches the broad
        # result heuristics, but it contains links for every card. Treat only
        # elements that resolve to one destination as individual results.
        urls = external_urls(element)
        if len(urls) != 1:
            continue
        candidates.append(element)

    containers = []
    candidate_ids = {id(element) for element in candidates}
    for element in candidates:
        # DuckDuckGo commonly nests result-ish elements (for example a card,
        # body, and title). Keep the outermost single-result element so the
        # description, source, and date are not discarded.
        if any(id(parent) in candidate_ids for parent in element.parents):
            continue
        containers.append(element)
    return containers


def extract_title_and_url(container):
    links = [
        link
        for link in container.find_all("a", href=True)
        if link["href"].startswith(("http://", "https://"))
    ]
    if not links:
        return "", ""

    heading = container.find(re.compile(r"^h[1-6]$"))
    if heading:
        heading_link = heading.find_parent("a", href=True)
        if heading_link in links:
            return visible_text(heading), heading_link["href"]

    links.sort(key=lambda link: len(visible_text(link)), reverse=True)
    title_link = links[0]
    return visible_text(title_link), title_link["href"]


def extract_source(container, url):
    source_attrs = ("data-source", "data-provider")
    for element in container.find_all(True):
        value = first_attr(element, source_attrs)
        if value and len(value) < 80:
            return value

    for class_name in ("source", "publisher", "provider", "domain"):
        element = container.find(class_=re.compile(class_name, re.I))
        if element:
            text = visible_text(element)
            if text:
                return text

    heading = container.find(re.compile(r"^h[1-6]$"))
    if heading:
        for element in container.find_all(["span", "small"]):
            if element is heading or heading in element.parents:
                continue
            if element.find_previous(re.compile(r"^h[1-6]$")) is heading:
                break
            text = visible_text(element)
            if text and len(text) < 80 and not extract_date_from_text(text):
                return text

    match = re.match(r"https?://([^/]+)", url)
    return match.group(1).removeprefix("www.") if match else ""


def extract_date_from_text(text):
    patterns = (
        r"\b\d+\s+(?:minutes?|hours?|days?|weeks?|months?)\s+ago\b",
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b",
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(0)
    return ""


def extract_date(container):
    time_element = container.find("time")
    if time_element:
        return first_attr(time_element, ("datetime", "title")) or visible_text(time_element)

    return extract_date_from_text(visible_text(container))


def extract_description(container, title, source, published_date):
    title_text = title.lower()
    rejected = {title_text, source.lower(), published_date.lower()}
    candidates = []
    for element in container.find_all(["p", "span", "div"]):
        text = visible_text(element)
        normalized = text.lower()
        if len(text) < 35 or normalized in rejected or title_text in normalized:
            continue
        if text.startswith(("http://", "https://")):
            continue
        candidates.append((element, text))

    if not candidates:
        return ""

    leaf_candidates = [
        (element, text)
        for element, text in candidates
        if not any(
            element in other.parents
            for other, _ in candidates
            if other is not element
        )
    ]
    descriptions = leaf_candidates or candidates
    descriptions.sort(key=lambda candidate: len(candidate[1]), reverse=True)
    return descriptions[0][1]


def normalize_result(container):
    title, url = extract_title_and_url(container)
    if not title or not url:
        return None

    source = extract_source(container, url)
    published_date = extract_date(container)
    description = extract_description(container, title, source, published_date)
    return {
        "title": title,
        "url": url,
        "description": description,
        "date": published_date,
        "source": source,
    }


def parse_duckduckgo_news_html(html, max_results):
    if is_likely_blocked_html(html):
        raise SearchBlockedError("DuckDuckGo returned a block or challenge page.")

    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_urls = set()
    for container in find_result_containers(soup):
        result = normalize_result(container)
        if not result or result["url"] in seen_urls:
            continue
        seen_urls.add(result["url"])
        results.append(result)
        if len(results) >= max_results:
            break
    return results


def scrape_news(page, query, max_results, timelimit, region, safesearch):
    url = build_news_url(
        query=query,
        timelimit=timelimit,
        region=region,
        safesearch=safesearch,
    )
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass

    results = parse_duckduckgo_news_html(page.content(), max_results)
    scroll_attempts = 0
    while len(results) < max_results and scroll_attempts < 4:
        scroll_attempts += 1
        page.mouse.wheel(0, 1400)
        page.wait_for_timeout(1500)
        more_button = page.get_by_role("button", name=re.compile("more results", re.I))
        try:
            if more_button.count():
                more_button.first.click(timeout=3000)
                page.wait_for_timeout(2000)
        except Exception:
            pass
        next_results = parse_duckduckgo_news_html(page.content(), max_results)
        if len(next_results) <= len(results):
            break
        results = next_results

    if not results:
        raise SearchNavigationError("No DuckDuckGo News results were found.")
    return results[:max_results]


def scrape_news_with_retries(
    page,
    query,
    max_results,
    timelimit,
    region,
    safesearch,
    retries,
    retry_wait_seconds,
):
    for attempt in range(1, retries + 2):
        try:
            return scrape_news(
                page=page,
                query=query,
                max_results=max_results,
                timelimit=timelimit,
                region=region,
                safesearch=safesearch,
            )
        except Exception as error:
            if attempt > retries:
                raise

            wait_seconds = retry_wait_seconds * (2 ** (attempt - 1))
            wait_seconds += random.uniform(0, min(10, retry_wait_seconds))
            print(
                f"Search failed for {query!r}: {error}. "
                f"Retrying in {wait_seconds:.0f} seconds...",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Search DuckDuckGo News with CloakBrowser and write one CSV per query."
    )
    parser.add_argument(
        "queries",
        nargs="+",
        help="Search queries. Wrap multi-word queries in quotes.",
    )
    parser.add_argument("--max-results", type=int, default=25)
    parser.add_argument("--timelimit", default="m", help="DuckDuckGo time limit: d, w, m.")
    parser.add_argument("--region", default="us-en")
    parser.add_argument("--safesearch", default="off", choices=["on", "moderate", "off"])
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=60,
        help="Base seconds to wait between successful searches.",
    )
    parser.add_argument(
        "--sleep-jitter-seconds",
        type=float,
        default=30,
        help="Random extra seconds to wait after each successful search.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of times to retry a failed search.",
    )
    parser.add_argument(
        "--retry-wait-seconds",
        type=float,
        default=120,
        help="Initial seconds to wait before retrying. Later retries wait longer.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Skip failed searches after retries instead of stopping the whole run.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".search_cache"),
        help="Directory for cached search responses.",
    )
    parser.add_argument(
        "--cache-ttl-hours",
        type=float,
        default=24,
        help="Hours to reuse cached responses before searching again.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable reading and writing cached responses.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached responses but write new successful responses.",
    )
    parser.add_argument(
        "--shuffle-queries",
        action="store_true",
        help="Search queries in random order.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window instead of running headless.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    import pandas as pd
    from cloakbrowser import launch

    queries = list(args.queries)
    if args.shuffle_queries:
        random.shuffle(queries)

    browser = launch(headless=not args.headed)
    try:
        page = browser.new_page()
        for index, query in enumerate(queries):
            print(f"Searching: {query}")
            key = cache_key(
                query=query,
                max_results=args.max_results,
                timelimit=args.timelimit,
                region=args.region,
                safesearch=args.safesearch,
            )

            results = None
            made_request = False
            if not args.no_cache and not args.refresh:
                results = read_cache(args.cache_dir, key, args.cache_ttl_hours)
                if results is not None:
                    print(f"Using cached results for: {query}")

            try:
                if results is None:
                    results = scrape_news_with_retries(
                        page=page,
                        query=query,
                        max_results=args.max_results,
                        timelimit=args.timelimit,
                        region=args.region,
                        safesearch=args.safesearch,
                        retries=args.retries,
                        retry_wait_seconds=args.retry_wait_seconds,
                    )
                    made_request = True
                    if not args.no_cache:
                        write_cache(args.cache_dir, key, results)
            except Exception as error:
                if not args.continue_on_error:
                    raise
                print(f"Skipping {query!r} after retries: {error}", file=sys.stderr)
                continue

            filename = f"{date.today().strftime('%Y-%m')}_{safe_filename(query)}.csv"
            pd.DataFrame(results, columns=RESULT_COLUMNS).to_csv(filename, index=False)
            print(f"Wrote: {filename}")

            if made_request and index < len(queries) - 1:
                wait_seconds = args.sleep_seconds + random.uniform(
                    0, args.sleep_jitter_seconds
                )
                time.sleep(wait_seconds)
    finally:
        browser.close()


if __name__ == "__main__":
    main()
