import re
from bs4 import BeautifulSoup

ALLOWED_TAGS = {
    'p', 'b', 'i', 'u', 'strong', 'em', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'br', 'hr', 'blockquote', 'code', 'pre', 'span', 'div',
    'table', 'thead', 'tbody', 'tr', 'th', 'td', 'sub', 'sup', 'mark'
}

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target', 'rel'],
    'span': ['class'],
    'div': ['class'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
}

ALLOWED_SCHEMES = {'http', 'https', 'mailto', 'tel'}

def sanitize_html(html_content: str) -> str:
    """
    Sanitizes HTML / Rich-text to prevent XSS attacks and dangerous script execution.
    Strips scripts, iframes, objects, forms, and event handlers (onclick, onerror, etc.).
    Only permits safe formatting tags and safe URL protocols.
    """
    if not html_content or not isinstance(html_content, str):
        return ""

    # If pure plain text without tags, return as is
    if '<' not in html_content and '>' not in html_content:
        return html_content.strip()

    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # 1. Remove dangerous executable or embedding elements
        for dangerous_tag in soup.find_all(['script', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'style', 'meta', 'link', 'base']):
            dangerous_tag.decompose()

        # 2. Inspect all remaining tags
        for tag in soup.find_all(True):
            if tag.name not in ALLOWED_TAGS:
                # Unwrap tag: keep inner text, remove tag itself
                tag.unwrap()
            else:
                # Filter attributes
                allowed_for_tag = ALLOWED_ATTRIBUTES.get(tag.name, [])
                attrs = dict(tag.attrs)
                for attr_name, attr_val in attrs.items():
                    # Strip all event handlers (onclick, onload, etc.)
                    if attr_name.lower().startswith('on'):
                        del tag.attrs[attr_name]
                        continue

                    if attr_name not in allowed_for_tag:
                        del tag.attrs[attr_name]
                        continue

                    # Validate URL schemes for links
                    if tag.name == 'a' and attr_name == 'href':
                        val = str(attr_val).strip()
                        # Check scheme
                        match = re.match(r'^([a-zA-Z0-9+.-]+):', val)
                        if match:
                            scheme = match.group(1).lower()
                            if scheme not in ALLOWED_SCHEMES:
                                del tag.attrs['href']
                        elif val.startswith('//') or val.startswith('javascript:'):
                            del tag.attrs['href']
                        else:
                            # Relative URL or anchor is okay, but enforce rel="noopener noreferrer" if target="_blank"
                            pass

                if tag.name == 'a' and tag.get('target') == '_blank':
                    tag.attrs['rel'] = 'noopener noreferrer'

        return str(soup).strip()
    except Exception:
        # Fallback regex strip if parser fails
        clean = re.sub(r'<script[^>]*?>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<iframe[^>]*?>.*?</iframe>', '', clean, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'on\w+="[^"]*"', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r"on\w+='[^']*'", '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'javascript:', '', clean, flags=re.IGNORECASE)
        return clean.strip()
