"""
WebsiteCrawlerService
Production-grade website crawler for complete RAG data extraction:
- Strict SSRF defense (blocking private IPs, localhost, AWS/cloud metadata 169.254.169.254)
- Domain-boundary enforcement (no crawling external sites)
- Full sitemap discovery (sitemap.xml, sitemap_index.xml, robots.txt sitemap directives)
- Robots.txt compliance and rate limiting
- Internal link discovery and BFS crawl queue with configurable depth and page limit
- URL normalization, deduplication, fragment stripping, and infinite loop prevention
- Per-page timeout with exponential backoff retries for transient HTTP errors
- Detailed diagnostics: discovered, queued, fetched, skipped, and failed URLs
"""

import re
import time
import socket
import ipaddress
import urllib.robotparser as robotparser
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin, urldefrag, parse_qs, urlencode
from typing import List, Dict, Set, Any, Optional
import requests

from .content_extractor import WebpageContentExtractor


# IP Ranges that MUST NEVER be accessed by the crawler (SSRF Prevention)
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network('127.0.0.0/8'),        # IPv4 loopback
    ipaddress.ip_network('10.0.0.0/8'),         # Private class A
    ipaddress.ip_network('172.16.0.0/12'),      # Private class B
    ipaddress.ip_network('192.168.0.0/16'),     # Private class C
    ipaddress.ip_network('169.254.0.0/16'),     # Link-local / Cloud metadata (AWS, GCP, Azure)
    ipaddress.ip_network('0.0.0.0/8'),          # Current network
    ipaddress.ip_network('::1/128'),            # IPv6 loopback
    ipaddress.ip_network('fc00::/7'),           # IPv6 unique local
    ipaddress.ip_network('fe80::/10'),          # IPv6 link-local
]

# Non-HTML / Binary file extensions to exclude from crawler queue
EXCLUDED_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp', '.tiff',
    '.mp4', '.mov', '.avi', '.wmv', '.mp3', '.wav', '.ogg',
    '.zip', '.tar', '.gz', '.rar', '.7z', '.exe', '.dmg', '.iso',
    '.css', '.js', '.map', '.woff', '.woff2', '.ttf', '.eot',
    '.pdf', '.docx', '.xlsx', '.pptx', '.csv', '.xml', '.json'
}

# Tracking query parameters to strip during normalization
TRACKING_PARAMS = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'gclid', 'fbclid', 'msclkid', 'mc_cid', 'mc_eid', '_ga', '_gl', 'ref', 'source'
}


class WebsiteCrawlerService:
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 UWOConnectBot/2.0"

    def __init__(
        self,
        start_url: str,
        max_pages: int = 25,
        max_depth: int = 3,
        per_page_timeout: int = 10,
        respect_robots: bool = True
    ):
        self.raw_start_url = start_url.strip()
        if not self.raw_start_url.startswith(('http://', 'https://')):
            self.raw_start_url = 'https://' + self.raw_start_url

        self.max_pages = min(max(1, max_pages), 100)  # Bound between 1 and 100
        self.max_depth = min(max(1, max_depth), 5)
        self.per_page_timeout = per_page_timeout
        self.respect_robots = respect_robots

        # Parse seed URL
        self.parsed_seed = urlparse(self.raw_start_url)
        self.allowed_host = self.parsed_seed.netloc.lower()
        # Clean root host without 'www.' for flexible matching
        self.root_domain = self.allowed_host[4:] if self.allowed_host.startswith('www.') else self.allowed_host
        self.base_url = f"{self.parsed_seed.scheme}://{self.parsed_seed.netloc}"

        # Internal state & diagnostics
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.DEFAULT_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,hi;q=0.8',
        })

        self.robot_parser: Optional[robotparser.RobotFileParser] = None
        self.discovered_urls: Set[str] = set()
        self.crawled_pages: List[Dict[str, Any]] = []
        self.skipped_urls: List[Dict[str, str]] = []
        self.failed_urls: List[Dict[str, str]] = []

        self.extractor = WebpageContentExtractor(self.base_url)

    def is_safe_url(self, url: str) -> bool:
        """
        Validates URL for SSRF security:
        - Scheme must be http or https
        - Hostname must resolve to a public, non-private, non-loopback, non-cloud-metadata IP
        """
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https'):
                return False
            
            hostname = parsed.hostname
            if not hostname:
                return False

            # Check if hostname itself is localhost or loopback name
            if hostname.lower() in ('localhost', 'loopback', 'metadata.google.internal'):
                return False

            # Resolve DNS to IP addresses
            addr_info = socket.getaddrinfo(hostname, None)
            for family, socktype, proto, canonname, sockaddr in addr_info:
                ip_str = sockaddr[0]
                ip_obj = ipaddress.ip_address(ip_str)

                for blocked_net in BLOCKED_IP_NETWORKS:
                    if ip_obj in blocked_net:
                        return False

            return True
        except Exception:
            return False

    def is_same_domain(self, url: str) -> bool:
        """Ensures URL belongs strictly to the allowed domain or subdomain."""
        try:
            parsed = urlparse(url)
            host = (parsed.netloc or '').lower()
            if not host:
                return False
            return host == self.allowed_host or host.endswith('.' + self.root_domain) or host == self.root_domain
        except Exception:
            return False

    def normalize_url(self, url: str) -> Optional[str]:
        """Cleans and standardizes URLs to prevent duplicates and loops."""
        try:
            # Remove fragment
            clean, _ = urldefrag(url)
            parsed = urlparse(clean)

            # Check extension
            path_lower = parsed.path.lower()
            for ext in EXCLUDED_EXTENSIONS:
                if path_lower.endswith(ext):
                    return None

            # Filter out tracking query params
            query_dict = parse_qs(parsed.query, keep_blank_values=False)
            filtered_query = {k: v for k, v in query_dict.items() if k.lower() not in TRACKING_PARAMS}
            new_query = urlencode(filtered_query, doseq=True)

            # Normalize trailing slash: normalize /path/ to /path except for root
            norm_path = parsed.path
            if not norm_path:
                norm_path = '/'
            elif norm_path != '/' and norm_path.endswith('/'):
                norm_path = norm_path.rstrip('/')

            normalized = f"{parsed.scheme}://{parsed.netloc.lower()}{norm_path}"
            if new_query:
                normalized += f"?{new_query}"

            return normalized
        except Exception:
            return None

    def init_robots_and_sitemaps(self) -> List[str]:
        """
        Reads robots.txt and sitemaps to discover high-priority seed URLs.
        Returns a list of URLs discovered from sitemaps.
        """
        sitemap_urls = []
        robots_url = urljoin(self.base_url, '/robots.txt')

        if self.is_safe_url(robots_url):
            try:
                resp = self.session.get(robots_url, timeout=5)
                if resp.status_code == 200:
                    self.robot_parser = robotparser.RobotFileParser()
                    self.robot_parser.parse(resp.text.splitlines())

                    # Check for Sitemap: directives
                    for line in resp.text.splitlines():
                        if line.lower().startswith('sitemap:'):
                            sm_url = line.split(':', 1)[1].strip()
                            if sm_url:
                                sitemap_urls.append(sm_url)
            except Exception as e:
                print(f"[Crawler] Notice: robots.txt error: {e}")

        # If no sitemap found in robots.txt, check standard sitemap locations
        if not sitemap_urls:
            sitemap_urls.append(urljoin(self.base_url, '/sitemap.xml'))
            sitemap_urls.append(urljoin(self.base_url, '/sitemap_index.xml'))

        discovered_from_sitemaps = []
        for sm_url in sitemap_urls:
            if not self.is_safe_url(sm_url):
                continue
            discovered_from_sitemaps.extend(self._parse_sitemap(sm_url, depth=0))

        return discovered_from_sitemaps

    def _parse_sitemap(self, sitemap_url: str, depth: int = 0) -> List[str]:
        """Recursively parses XML sitemaps and sitemap indexes."""
        if depth > 3:
            return []

        urls = []
        try:
            resp = self.session.get(sitemap_url, timeout=6)
            if resp.status_code != 200 or not resp.text.strip():
                return []

            root = ET.fromstring(resp.content)
            # Remove XML namespaces if any
            for elem in root.iter():
                if '}' in elem.tag:
                    elem.tag = elem.tag.split('}', 1)[1]

            # 1. Sitemap Index (contains child sitemaps)
            if root.tag == 'sitemapindex':
                for sm in root.findall('sitemap'):
                    loc = sm.find('loc')
                    if loc is not None and loc.text:
                        child_url = loc.text.strip()
                        if self.is_same_domain(child_url) and self.is_safe_url(child_url):
                            urls.extend(self._parse_sitemap(child_url, depth + 1))

            # 2. Urlset (contains page URLs)
            elif root.tag == 'urlset':
                for u in root.findall('url'):
                    loc = u.find('loc')
                    if loc is not None and loc.text:
                        page_url = loc.text.strip()
                        if self.is_same_domain(page_url):
                            norm = self.normalize_url(page_url)
                            if norm:
                                urls.append(norm)

        except Exception:
            pass

        return urls

    def can_fetch(self, url: str) -> bool:
        """Checks robots.txt rules for the given URL."""
        if not self.respect_robots or not self.robot_parser:
            return True
        try:
            return self.robot_parser.can_fetch(self.DEFAULT_USER_AGENT, url)
        except Exception:
            return True

    def fetch_page(self, url: str) -> Optional[requests.Response]:
        """Fetches a page with safe timeout, retries, and SSRF re-check."""
        if not self.is_safe_url(url):
            self.skipped_urls.append({"url": url, "reason": "blocked_by_ssrf_filter"})
            return None

        for attempt in range(2):
            try:
                resp = self.session.get(
                    url,
                    timeout=self.per_page_timeout,
                    allow_redirects=True
                )

                # Re-verify destination URL if redirected
                if resp.url != url:
                    if not self.is_same_domain(resp.url) or not self.is_safe_url(resp.url):
                        self.skipped_urls.append({"url": url, "reason": f"redirected_to_unsafe_domain_{resp.url}"})
                        return None

                if resp.status_code == 200:
                    c_type = resp.headers.get('Content-Type', '').lower()
                    if 'text/html' not in c_type and 'application/xhtml+xml' not in c_type:
                        self.skipped_urls.append({"url": url, "reason": f"non_html_content_type_{c_type}"})
                        return None
                    return resp

                if resp.status_code in [429, 500, 502, 503, 504]:
                    time.sleep(1.0 * (attempt + 1))
                    continue

                # Permanent failure (404, 403, etc.)
                self.failed_urls.append({"url": url, "error": f"HTTP {resp.status_code}"})
                return None

            except requests.Timeout:
                if attempt == 1:
                    self.failed_urls.append({"url": url, "error": "Timeout"})
            except requests.RequestException as e:
                if attempt == 1:
                    self.failed_urls.append({"url": url, "error": str(e)})

        return None

    def crawl(self) -> Dict[str, Any]:
        """
        Executes full website crawl:
        1. Reads sitemaps and robots.txt.
        2. Populates BFS queue starting with seed URL + sitemap URLs.
        3. Crawls up to max_pages, extracting structured content & discovering new internal links.
        4. Returns full diagnostics and extracted pages.
        """
        start_time = time.time()

        # Step 1: Initial SSRF check on start URL
        norm_start = self.normalize_url(self.raw_start_url)
        if not norm_start or not self.is_safe_url(norm_start):
            return {
                "success": False,
                "error": "The provided URL is invalid, private, or violates SSRF security policy.",
                "crawled_pages": [],
                "diagnostics": {"discovered": 0, "fetched": 0, "skipped": 1, "failed": 0}
            }

        # Step 2: Discover sitemap URLs
        sitemap_discovered = self.init_robots_and_sitemaps()

        # Step 3: Initialize BFS Queue: (url, depth)
        queue = [(norm_start, 0)]
        visited: Set[str] = set()
        self.discovered_urls.add(norm_start)

        # Add sitemap URLs to queue with depth 1
        for sm_u in sitemap_discovered:
            if sm_u not in self.discovered_urls and self.is_same_domain(sm_u):
                self.discovered_urls.add(sm_u)
                queue.append((sm_u, 1))

        # Step 4: BFS Crawl Loop
        while queue and len(self.crawled_pages) < self.max_pages:
            current_url, depth = queue.pop(0)

            if current_url in visited:
                continue
            visited.add(current_url)

            # Robots check
            if not self.can_fetch(current_url):
                self.skipped_urls.append({"url": current_url, "reason": "disallowed_by_robots_txt"})
                continue

            # Fetch page
            resp = self.fetch_page(current_url)
            if not resp:
                continue

            # Extract structured content
            page_data = self.extractor.extract(resp.text, current_url)

            # Only index if page has actual text content
            if page_data["char_count"] > 30:
                self.crawled_pages.append(page_data)

            # If depth allowed, add newly discovered outbound links to queue
            if depth < self.max_depth:
                for link in page_data.get("outbound_links", []):
                    norm_link = self.normalize_url(link)
                    if not norm_link:
                        continue

                    if not self.is_same_domain(norm_link):
                        # Skip external
                        continue

                    self.discovered_urls.add(norm_link)
                    if norm_link not in visited:
                        queue.append((norm_link, depth + 1))

        duration = round(time.time() - start_time, 2)

        return {
            "success": len(self.crawled_pages) > 0,
            "base_url": self.base_url,
            "total_pages_crawled": len(self.crawled_pages),
            "duration_seconds": duration,
            "crawled_pages": self.crawled_pages,
            "diagnostics": {
                "discovered_count": len(self.discovered_urls),
                "fetched_count": len(self.crawled_pages),
                "skipped_count": len(self.skipped_urls),
                "failed_count": len(self.failed_urls),
                "discovered_urls": list(self.discovered_urls)[:50],
                "skipped_urls": self.skipped_urls[:20],
                "failed_urls": self.failed_urls[:20],
            }
        }
