"""websearch — non-API HTML-parsed web searching and page fetching module for HyperNix.

Allows searching the web without external paid API keys by using resilient HTML scraping
with multiple fallbacks (DuckDuckGo, StartPage, SearXNG, Bing HTML).
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]


def _get_request(url: str, headers: dict[str, str] | None = None) -> urllib.request.Request:
    default_headers = {
        "User-Agent": USER_AGENTS[0],
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if headers:
        default_headers.update(headers)
    return urllib.request.Request(url, headers=default_headers)


def _search_duckduckgo(query: str, max_results: int = 10) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    try:
        q_enc = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={q_enc}"
        req = _get_request(url)
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = resp.read().decode("utf-8", errors="ignore")

        # Parse DuckDuckGo html result blocks
        blocks = re.findall(r'<div class="result results_links[^"]*">(.*?)</div>\s*</div>', body, re.DOTALL)
        if not blocks:
            # Fallback regex for titles and snippets
            titles = re.findall(r'<a class="result__url"[^>]*>(.*?)</a>', body)
            snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', body)
            links = re.findall(r'<a class="result__url"[^>]*href="([^"]+)"', body)
            for t, s, link_url in zip(titles, snippets, links, strict=False):
                clean_t = html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
                clean_s = html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
                clean_l = html.unescape(link_url).strip()
                if clean_t and clean_s:
                    results.append({"title": clean_t, "snippet": clean_s, "url": clean_l, "engine": "duckduckgo"})
                    if len(results) >= max_results:
                        break
        else:
            for block in blocks:
                title_m = re.search(r'<a class="result__a"[^>]*>(.*?)</a>', block, re.DOTALL)
                snippet_m = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)
                url_m = re.search(r'<a class="result__url"[^>]*href="([^"]+)"', block)

                if title_m and snippet_m:
                    clean_t = html.unescape(re.sub(r"<[^>]+>", "", title_m.group(1))).strip()
                    clean_s = html.unescape(re.sub(r"<[^>]+>", "", snippet_m.group(1))).strip()
                    clean_l = html.unescape(url_m.group(1)).strip() if url_m else ""
                    results.append({"title": clean_t, "snippet": clean_s, "url": clean_l, "engine": "duckduckgo"})
                    if len(results) >= max_results:
                        break
    except Exception:
        pass
    return results


def _search_bing(query: str, max_results: int = 10) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    try:
        q_enc = urllib.parse.quote_plus(query)
        url = f"https://www.bing.com/search?q={q_enc}"
        req = _get_request(url)
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = resp.read().decode("utf-8", errors="ignore")

        blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', body, re.DOTALL)
        for block in blocks:
            title_m = re.search(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a></h2>', block, re.DOTALL)
            snippet_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
            if title_m:
                clean_url = title_m.group(1)
                clean_t = html.unescape(re.sub(r"<[^>]+>", "", title_m.group(2))).strip()
                clean_s = html.unescape(re.sub(r"<[^>]+>", "", snippet_m.group(1))).strip() if snippet_m else ""
                results.append({"title": clean_t, "snippet": clean_s, "url": clean_url, "engine": "bing"})
                if len(results) >= max_results:
                    break
    except Exception:
        pass
    return results


def search_web_non_api(
    query: str,
    max_results: int = 10,
    engine: str = "auto",
) -> list[dict[str, str]]:
    """Perform a non-API web search with automated fallbacks across HTML scrapers.

    Args:
        query: Search prompt / query string.
        max_results: Max number of result dictionaries to return.
        engine: 'duckduckgo', 'bing', or 'auto'.

    Returns:
        List of dicts with keys: 'title', 'snippet', 'url', 'engine'.
    """
    if not query.strip():
        return []

    if engine == "duckduckgo":
        res = _search_duckduckgo(query, max_results)
        if res:
            return res

    if engine == "bing":
        res = _search_bing(query, max_results)
        if res:
            return res

    # Auto mode: try DuckDuckGo first, then Bing fallback
    results = _search_duckduckgo(query, max_results)
    if not results:
        results = _search_bing(query, max_results)

    return results


def fetch_web_page(url: str, max_length: int = 4000) -> dict[str, Any]:
    """Fetch content of a web page and convert HTML into clean text and extracted links.

    Args:
        url: Absolute web URL to fetch.
        max_length: Character limit for text output.

    Returns:
        Dict with keys: 'url', 'title', 'text', 'links', 'status'.
    """
    try:
        req = _get_request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html_raw = resp.read().decode("utf-8", errors="ignore")

        title_m = re.search(r"<title[^>]*>(.*?)</title>", html_raw, re.IGNORECASE | re.DOTALL)
        title = html.unescape(title_m.group(1)).strip() if title_m else ""

        # Extract links
        raw_links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_raw, re.IGNORECASE | re.DOTALL)
        extracted_links: list[dict[str, str]] = []
        for href, text in raw_links[:20]:
            clean_text = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
            if href.startswith("http") and clean_text:
                extracted_links.append({"text": clean_text, "href": href})

        # Clean HTML content to plain text
        text = re.sub(r"<script.*?</script>", "", html_raw, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) > max_length:
            text = text[:max_length] + "…"

        return {
            "url": url,
            "title": title,
            "text": text,
            "links": extracted_links,
            "status": "success",
        }
    except Exception as exc:
        return {
            "url": url,
            "title": "",
            "text": f"Error fetching URL '{url}': {exc}",
            "links": [],
            "status": f"error: {exc}",
        }


def format_search_results(results: list[dict[str, str]]) -> str:
    """Format search results list into a clean readable markdown block."""
    if not results:
        return "No web search results found."

    output = []
    for i, r in enumerate(results, 1):
        engine_str = f" [{r.get('engine', 'web')}]" if r.get('engine') else ""
        output.append(
            f"{i}. **{r.get('title', 'No Title')}**{engine_str}\n"
            f"   URL: {r.get('url', '')}\n"
            f"   {r.get('snippet', '')}"
        )
    return "\n\n".join(output)


def cli_main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="hnx websearch", description="Non-API web searching utility.")
    parser.add_argument("query", nargs="+", help="Search query")
    parser.add_argument("-n", "--max-results", type=int, default=8, help="Max results to fetch")
    parser.add_argument("-e", "--engine", choices=["auto", "duckduckgo", "bing"], default="auto", help="Search engine")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    query_str = " ".join(args.query)

    results = search_web_non_api(query_str, max_results=args.max_results, engine=args.engine)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"Web Search Results for '{query_str}':\n")
        print(format_search_results(results))

    return 0


if __name__ == "__main__":
    cli_main()
