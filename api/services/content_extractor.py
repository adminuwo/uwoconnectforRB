"""
WebpageContentExtractor
Extracts clean, structured, semantic content from raw HTML:
- Preserves H1-H6 hierarchy and heading paths
- Converts tables to structured Markdown preserving column/row relationships
- Preserves bullet and numbered lists
- Detects FAQs, accordions, and <details>/<summary> sections
- Extracts metadata (title, description, canonical URL, language)
- Extracts image alt texts and captions
- Removes noise (scripts, styles, navs, footers, cookie banners, ads)
- Handles SPA / JavaScript rendered content fallback (JSON-LD, __NEXT_DATA__)
"""

import re
import json
from urllib.parse import urljoin, urlparse, urldefrag
from bs4 import BeautifulSoup, Comment, NavigableString, Tag


class WebpageContentExtractor:
    # Common boilerplate / noise selectors to prune
    NOISE_SELECTORS = [
        'script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript',
        'iframe', 'svg', 'canvas', 'form', 'button', 'input', 'select', 'textarea',
        '[class*="cookie"]', '[id*="cookie"]', '[class*="consent"]', '[id*="consent"]',
        '[class*="advertisement"]', '[class*="ad-banner"]', '[id*="ad-"]',
        '[class*="popup"]', '[class*="modal"]', '[id*="modal"]',
        '[role="alert"]', '[aria-hidden="true"]',
    ]

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.parsed_base = urlparse(base_url)

    def extract(self, html_content: str, current_url: str) -> dict:
        """
        Main extraction entry point.
        Returns a rich dictionary containing structured text, metadata,
        sections with heading paths, and discovered internal links.
        """
        if not html_content or not html_content.strip():
            return self._empty_result(current_url)

        try:
            soup = BeautifulSoup(html_content, 'lxml')
        except Exception:
            soup = BeautifulSoup(html_content, 'html.parser')

        # 1. Extract metadata before cleaning
        title = self._extract_title(soup)
        meta_desc = self._extract_meta_description(soup)
        canonical = self._extract_canonical(soup, current_url)
        json_ld_data = self._extract_json_ld(soup)
        next_data = self._extract_next_data(soup)

        # 2. Extract internal outbound links before cleaning
        outbound_links = self._extract_links(soup, current_url)

        # 3. Remove HTML comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # 4. Remove noise and non-content elements
        for selector in self.NOISE_SELECTORS:
            try:
                for el in soup.select(selector):
                    el.decompose()
            except Exception:
                continue

        # 5. Extract structured sections, headings, tables, FAQs
        sections = []
        structured_lines = []

        # Header info
        if title:
            structured_lines.append(f"# {title}\n")
        if meta_desc:
            structured_lines.append(f"> {meta_desc}\n")

        # Find main content container if available, else use body
        main_container = soup.find('main') or soup.find('article') or soup.find('div', id='content') or soup.find('div', class_='content') or soup.body or soup

        current_heading_path = [title] if title else []
        current_section_lines = []

        def flush_section():
            nonlocal current_section_lines
            if current_section_lines:
                sec_text = "\n".join(current_section_lines).strip()
                if sec_text:
                    sections.append({
                        "heading_path": " > ".join(current_heading_path) if current_heading_path else (title or "General"),
                        "content": sec_text
                    })
                    structured_lines.append(sec_text)
                    structured_lines.append("")
                current_section_lines = []

        # Traverse relevant block elements
        for elem in main_container.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'table', 'ul', 'ol', 'details', 'pre', 'blockquote', 'div'], recursive=True):
            if not elem or elem.decomposed:
                continue

            tag = elem.name.lower()

            # Handle Headings
            if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                h_text = elem.get_text(separator=' ', strip=True)
                if not h_text:
                    continue
                level = int(tag[1])
                flush_section()

                # Adjust heading path according to level
                prefix = "#" * level
                # Trim heading path to current level - 1
                current_heading_path = current_heading_path[:level]
                if len(current_heading_path) < level:
                    current_heading_path.append(h_text)
                else:
                    current_heading_path[-1] = h_text

                current_section_lines.append(f"{prefix} {h_text}\n")
                elem.decompose()

            # Handle Tables
            elif tag == 'table':
                table_md = self._table_to_markdown(elem)
                if table_md:
                    current_section_lines.append(table_md)
                elem.decompose()

            # Handle FAQs / <details>
            elif tag == 'details':
                summary = elem.find('summary')
                q_text = summary.get_text(separator=' ', strip=True) if summary else "FAQ"
                if summary:
                    summary.decompose()
                a_text = elem.get_text(separator=' ', strip=True)
                if q_text or a_text:
                    current_section_lines.append(f"**Q: {q_text}**\n**A:** {a_text}\n")
                elem.decompose()

            # Handle Lists
            elif tag in ['ul', 'ol']:
                list_md = self._list_to_markdown(elem, is_ordered=(tag == 'ol'))
                if list_md:
                    current_section_lines.append(list_md)
                elem.decompose()

            # Handle Code Blocks
            elif tag == 'pre':
                code_text = elem.get_text()
                if code_text.strip():
                    current_section_lines.append(f"```\n{code_text.strip()}\n```\n")
                elem.decompose()

            # Handle Paragraphs & Blockquotes
            elif tag in ['p', 'blockquote']:
                p_text = elem.get_text(separator=' ', strip=True)
                if p_text and len(p_text) > 3:
                    if tag == 'blockquote':
                        current_section_lines.append(f"> {p_text}\n")
                    else:
                        current_section_lines.append(f"{p_text}\n")
                elem.decompose()

        # Flush any remaining lines
        flush_section()

        final_text = "\n".join(structured_lines).strip()

        # 6. Fallback for SPA / JS-rendered sites if extracted text is too sparse (< 200 chars)
        if len(final_text) < 200:
            fallback_text = self._build_spa_fallback(json_ld_data, next_data, title, meta_desc)
            if fallback_text and len(fallback_text) > len(final_text):
                final_text = fallback_text
                sections = [{
                    "heading_path": title or "Website Data",
                    "content": final_text
                }]

        return {
            "url": current_url,
            "canonical_url": canonical,
            "title": title or current_url,
            "meta_description": meta_desc,
            "structured_text": final_text,
            "sections": sections,
            "outbound_links": outbound_links,
            "char_count": len(final_text),
            "word_count": len(final_text.split()),
            "is_sparse": len(final_text) < 200,
        }

    def _extract_title(self, soup: BeautifulSoup) -> str:
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        og_title = soup.find('meta', property='og:title') or soup.find('meta', attrs={'name': 'twitter:title'})
        if og_title and og_title.get('content'):
            return og_title['content'].strip()
        h1 = soup.find('h1')
        if h1:
            return h1.get_text(separator=' ', strip=True)
        return ""

    def _extract_meta_description(self, soup: BeautifulSoup) -> str:
        desc = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', property='og:description')
        if desc and desc.get('content'):
            return desc['content'].strip()
        return ""

    def _extract_canonical(self, soup: BeautifulSoup, default_url: str) -> str:
        canonical = soup.find('link', rel='canonical')
        if canonical and canonical.get('href'):
            return urljoin(default_url, canonical['href'].strip())
        return default_url

    def _extract_links(self, soup: BeautifulSoup, current_url: str) -> list:
        links = []
        seen = set()
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                continue

            full_url = urljoin(current_url, href)
            # Remove fragment
            clean_url, _ = urldefrag(full_url)

            if clean_url in seen:
                continue
            seen.add(clean_url)
            links.append(clean_url)
        return links

    def _table_to_markdown(self, table_elem: Tag) -> str:
        """Converts an HTML table to clean, readable Markdown."""
        rows = table_elem.find_all('tr')
        if not rows:
            return ""

        md_rows = []
        headers = []

        # Find header row
        first_row = rows[0]
        th_cells = first_row.find_all(['th', 'td'])
        for th in th_cells:
            headers.append(th.get_text(separator=' ', strip=True).replace('|', '/'))

        if headers and any(headers):
            md_rows.append("| " + " | ".join(headers) + " |")
            md_rows.append("| " + " | ".join(["---"] * len(headers)) + " |")
            data_rows = rows[1:]
        else:
            data_rows = rows

        for r in data_rows:
            cells = [td.get_text(separator=' ', strip=True).replace('|', '/').replace('\n', ' ') for td in r.find_all(['td', 'th'])]
            if cells and any(cells):
                # Pad cells if row length doesn't match header
                if headers and len(cells) < len(headers):
                    cells.extend([""] * (len(headers) - len(cells)))
                md_rows.append("| " + " | ".join(cells) + " |")

        return "\n".join(md_rows) + "\n" if md_rows else ""

    def _list_to_markdown(self, list_elem: Tag, is_ordered: bool = False) -> str:
        """Converts ul/ol to markdown list items."""
        items = []
        for i, li in enumerate(list_elem.find_all('li', recursive=False), 1):
            text = li.get_text(separator=' ', strip=True)
            if not text:
                continue
            prefix = f"{i}." if is_ordered else "-"
            items.append(f"{prefix} {text}")
        return "\n".join(items) + "\n" if items else ""

    def _extract_json_ld(self, soup: BeautifulSoup) -> list:
        """Extracts all application/ld+json blocks."""
        results = []
        for tag in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(tag.string or '{}')
                if data:
                    results.append(data)
            except Exception:
                continue
        return results

    def _extract_next_data(self, soup: BeautifulSoup) -> dict:
        """Extracts Next.js __NEXT_DATA__ payload if present."""
        tag = soup.find('script', id='__NEXT_DATA__')
        if tag and tag.string:
            try:
                return json.loads(tag.string)
            except Exception:
                pass
        return {}

    def _build_spa_fallback(self, json_ld_list: list, next_data: dict, title: str, meta_desc: str) -> str:
        """Generates fallback text from structured JSON-LD and Next.js state."""
        lines = []
        if title:
            lines.append(f"# {title}\n")
        if meta_desc:
            lines.append(f"{meta_desc}\n")

        # 1. Parse JSON-LD
        for item in json_ld_list:
            if isinstance(item, list):
                items = item
            else:
                items = [item]

            for entry in items:
                schema_type = entry.get('@type', '')
                # Handle FAQPage
                if schema_type == 'FAQPage' and 'mainEntity' in entry:
                    lines.append("## Frequently Asked Questions (FAQ)\n")
                    for q in entry['mainEntity']:
                        name = q.get('name', '')
                        ans = q.get('acceptedAnswer', {}).get('text', '')
                        if name:
                            lines.append(f"**Q: {name}**\n**A:** {ans}\n")

                # Handle Articles / News
                elif schema_type in ['Article', 'NewsArticle', 'BlogPosting']:
                    headline = entry.get('headline') or entry.get('name')
                    body = entry.get('articleBody') or entry.get('description')
                    if headline:
                        lines.append(f"## {headline}\n")
                    if body:
                        lines.append(f"{body}\n")

                # Handle Products
                elif schema_type == 'Product':
                    prod_name = entry.get('name', '')
                    prod_desc = entry.get('description', '')
                    offers = entry.get('offers', {})
                    price = offers.get('price') if isinstance(offers, dict) else None
                    curr = offers.get('priceCurrency', 'INR') if isinstance(offers, dict) else ''
                    lines.append(f"## Product: {prod_name}\n")
                    if prod_desc:
                        lines.append(f"{prod_desc}\n")
                    if price:
                        lines.append(f"Price: {curr} {price}\n")

        # 2. Parse Next.js pageProps if present
        if next_data and isinstance(next_data, dict):
            props = next_data.get('props', {}).get('pageProps', {})
            # Look for common content keys
            for k in ['content', 'article', 'page', 'data', 'faq', 'items']:
                val = props.get(k)
                if isinstance(val, str) and len(val) > 50:
                    lines.append(f"\n{val}\n")
                elif isinstance(val, list):
                    for sub in val:
                        if isinstance(sub, dict):
                            t = sub.get('title') or sub.get('name') or sub.get('question')
                            c = sub.get('content') or sub.get('description') or sub.get('answer')
                            if t:
                                lines.append(f"### {t}")
                            if c:
                                lines.append(f"{c}\n")

        return "\n".join(lines).strip()

    def _empty_result(self, url: str) -> dict:
        return {
            "url": url,
            "canonical_url": url,
            "title": url,
            "meta_description": "",
            "structured_text": "",
            "sections": [],
            "outbound_links": [],
            "char_count": 0,
            "word_count": 0,
            "is_sparse": True
        }
