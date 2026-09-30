"""Website scraper for extracting contact information.

For each business website found via OpenStreetMap, this module:
  - Fetches the homepage HTML
  - Extracts email addresses, phone numbers, and social media links
  - Tries common contact pages (/contact, /about, /team, /about-us)
  - Returns a structured dict suitable for the Contact model
"""
import logging
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Common paths to check for contact info
CONTACT_PATHS = [
    '/contact', '/contact-us', '/contacts',
    '/about', '/about-us', '/team', '/our-team', '/staff',
    '/imprint', '/legal',
]

# Regex patterns
EMAIL_RE = re.compile(
    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
)
# Phone: require + prefix OR at least 10 digits, to avoid matching
# years (2001-2026), dates, Fibonacci, etc.
PHONE_RE = re.compile(
    r'(?:\+\d{1,3}[\s.-]?\(?\d{1,4}\)?[\s.-]?\d{1,4}[\s.-]?\d{1,9})'  # + international
    r'|(?:\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})'  # US-style (555) 123-4567
    r'|(?:\d{2}[\s.-]?\d{4}[\s.-]?\d{4})'  # common intl 00 0000 0000
)
LINKEDIN_RE = re.compile(
    r'https?://(?:www\.)?linkedin\.com/(?:in|company)/[a-zA-Z0-9_-]+/?',
    re.IGNORECASE,
)
TWITTER_RE = re.compile(
    r'https?://(?:www\.)?(?:twitter|x)\.com/[a-zA-Z0-9_]+/?',
    re.IGNORECASE,
)
FACEBOOK_RE = re.compile(
    r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9._-]+/?',
    re.IGNORECASE,
)
INSTAGRAM_RE = re.compile(
    r'https?://(?:www\.)?instagram\.com/[a-zA-Z0-9._-]+/?',
    re.IGNORECASE,
)

# Emails to skip (generic / non-contact / template placeholders)
SKIP_EMAILS = {
    'example@example.com', 'noreply@example.com', 'no-reply@example.com',
    'donotreply@example.com', 'support@example.com',
    'info@yoursite.com', 'support@yoursite.com', 'hello@yoursite.com',
    'info@example.com', 'hello@example.com', 'contact@example.com',
    'admin@example.com', 'test@test.com', 'user@example.com',
    'youremail@example.com', 'email@example.com',
}
SKIP_EMAIL_RE = re.compile(
    r'^(noreply|no-reply|donotreply|sentry|wix|godaddy|wordpress|squarespace)@',
    re.IGNORECASE,
)
# Domains that indicate placeholder/template emails, not real contacts
SKIP_EMAIL_DOMAINS = {'yoursite.com', 'example.com', 'example.org', 'sentry.io'}


class WebsiteScraper:
    """Scrapes a business website for contact information."""

    def __init__(self, timeout=15, max_pages=4):
        self.timeout = timeout
        self.max_pages = max_pages
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/125.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })

    # ------------------------------------------------------------------
    def scrape(self, url, business_name=''):
        """Scrape a single website for contact info.

        Returns a dict with keys: ``emails``, ``phones``, ``linkedin_url``,
        ``twitter_url``, ``facebook_url``, ``instagram_url``, ``names``,
        ``business_name``, ``source_url``, ``status``.
        """
        if not url:
            return self._empty_result(url, 'No website provided')

        result = {
            'emails': set(),
            'phones': set(),
            'linkedin_url': '',
            'twitter_url': '',
            'facebook_url': '',
            'instagram_url': '',
            'names': [],
            'business_name': '',
            'source_url': url,
            'status': 'Success',
            'pages_scraped': 0,
        }

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            url = f'https://{url}'
            parsed = urlparse(url)

        base_url = f'{parsed.scheme}://{parsed.netloc}'
        urls_to_try = [url] + [urljoin(base_url, p) for p in CONTACT_PATHS]
        urls_to_try = urls_to_try[:self.max_pages + 1]

        for page_url in urls_to_try:
            try:
                html = self._fetch(page_url)
                if not html:
                    continue
                result['pages_scraped'] += 1
                self._extract_from_html(html, page_url, result)
            except requests.RequestException as e:
                logger.debug('Failed to fetch %s: %s', page_url, e)
                continue
            time.sleep(0.3)  # be polite

        # Filter and deduplicate
        emails = set()
        for e in result['emails']:
            el = e.lower()
            domain = el.split('@')[-1] if '@' in el else ''
            if el in SKIP_EMAILS:
                continue
            if SKIP_EMAIL_RE.match(el):
                continue
            if domain in SKIP_EMAIL_DOMAINS:
                continue
            if el.endswith('.png') or el.endswith('.jpg') or el.endswith('.gif'):
                continue
            emails.add(el)
        result['emails'] = sorted(emails)
        result['phones'] = sorted(result['phones'])

        if not any([result['emails'], result['phones'], result['linkedin_url']]):
            result['status'] = 'No contact info found'

        return result

    # ------------------------------------------------------------------
    def _fetch(self, url):
        """Fetch HTML content from a URL."""
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code == 200:
                content_type = resp.headers.get('Content-Type', '')
                if 'text/html' in content_type or 'text/plain' in content_type:
                    return resp.text
            return None
        except requests.RequestException:
            return None

    # ------------------------------------------------------------------
    def _extract_from_html(self, html, source_url, result):
        """Extract contact info from HTML and update *result* in place."""
        soup = BeautifulSoup(html, 'lxml')

        # Remove script/style tags to avoid false positives
        for tag in soup(['script', 'style', 'noscript']):
            tag.decompose()

        # Extract business name from <title> or og:site_name (homepage only)
        if not result['business_name']:
            result['business_name'] = self._extract_business_name(soup, source_url)

        text = soup.get_text(separator=' ')

        # Extract emails
        for match in EMAIL_RE.findall(text):
            result['emails'].add(match)

        # Also check mailto: links
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('mailto:'):
                email = href[7:].split('?')[0].strip()
                if email and '@' in email:
                    result['emails'].add(email)

        # Extract phone numbers
        for match in PHONE_RE.findall(text):
            phone = match.strip()
            # Require at least 10 digits to qualify as a phone number
            digits = re.sub(r'\D', '', phone)
            if len(digits) >= 10:
                result['phones'].add(phone)

        # Also check tel: links
        for a in soup.find_all('a', href=True):
            if a['href'].startswith('tel:'):
                phone = a['href'][4:].strip()
                if phone:
                    result['phones'].add(phone)

        # Extract social media URLs from <a> tags
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if not result['linkedin_url']:
                m = LINKEDIN_RE.search(href)
                if m:
                    result['linkedin_url'] = m.group(0)
            if not result['twitter_url']:
                m = TWITTER_RE.search(href)
                if m:
                    result['twitter_url'] = m.group(0)
            if not result['facebook_url']:
                m = FACEBOOK_RE.search(href)
                if m:
                    result['facebook_url'] = m.group(0)
            if not result['instagram_url']:
                m = INSTAGRAM_RE.search(href)
                if m:
                    result['instagram_url'] = m.group(0)

        # Also check meta tags for social profile URLs
        for meta in soup.find_all('meta'):
            content = meta.get('content', '')
            if not result['linkedin_url']:
                m = LINKEDIN_RE.search(content)
                if m:
                    result['linkedin_url'] = m.group(0)

        # Try to extract person names from team/about pages
        self._extract_names(soup, result)

    # ------------------------------------------------------------------
    @staticmethod
    def _clean_duplicated_name(name):
        """Remove duplicated patterns in a business name.

        Handles cases where a website misconfigures its tags, e.g.
        "Kimo's Rockaway Beach | Kimo's Rockaway Beach" → "Kimo's Rockaway Beach"
        """
        parts = re.split(r'\s*[|·\-–—:]+\s*', name)
        if len(parts) >= 2:
            unique = []
            for p in parts:
                p = p.strip()
                if p and p.lower() not in (u.lower() for u in unique):
                    unique.append(p)
            if len(unique) == 1:
                return unique[0]
        return name

    # ------------------------------------------------------------------
    def _extract_business_name(self, soup, source_url):
        """Extract the business/website name from metadata.

        Priority: schema.org JSON-LD → og:site_name → logo alt → <title>.
        """
        # 1. Try schema.org JSON-LD (most reliable — explicit business name)
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                import json
                data = json.loads(script.string or '{}')
                if isinstance(data, list):
                    data = data[0] if data else {}
                name = (data.get('name') or data.get('@name') or
                        (data.get('publisher', {}) or {}).get('name', ''))
                if name and isinstance(name, str) and name.strip():
                    return name.strip()
            except (ValueError, TypeError):
                continue

        # 2. Try og:site_name meta tag
        og_site = soup.find('meta', property='og:site_name')
        if og_site and og_site.get('content', '').strip():
            name = og_site['content'].strip()
            return self._clean_duplicated_name(name)

        # 3. Try logo image alt text
        for img in soup.find_all('img', src=True):
            src = img.get('src', '').lower()
            alt = img.get('alt', '').strip()
            if alt and ('logo' in src or 'logo' in (img.get('class', [''])[0] if img.get('class') else '')):
                # Strip "Logo" suffix if present (e.g. "Web3Bridge Logo" → "Web3Bridge")
                alt = re.sub(r'\s+logo\s*$', '', alt, flags=re.IGNORECASE).strip()
                if alt and len(alt) < 50:
                    return alt

        # 4. Try <title> tag (least reliable — often SEO keywords)
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
            parts = re.split(r'\s*[|·\-–—:]+\s*', title)
            if len(parts) >= 2:
                # When title is "SEO Keywords | Business Name", the business
                # name is usually the LAST part (after the separator).
                # When it's "Business Name | SEO Keywords", it's the FIRST.
                # Heuristic: pick the shorter part (business names are short)
                shortest = min(parts, key=len).strip()
                if shortest:
                    return shortest
            return parts[0].strip() if parts else title

        # 5. Fall back to domain name
        parsed = urlparse(source_url)
        domain = parsed.netloc.replace('www.', '')
        parts = domain.split('.')
        if parts and parts[0]:
            return parts[0].capitalize()
        return ''

    # ------------------------------------------------------------------
    def _extract_names(self, soup, result):
        """Best-effort extraction of actual person names from team/about pages.

        Only extracts from elements that clearly contain person names —
        elements with class/id containing team, staff, author, member,
        founder, ceo, director.  Does NOT grab random capitalized text from
        headings (which are often course names, feature titles, etc.).
        """
        # Stricter pattern: require at least one common first-name-like word
        # structure (2+ capitalized words, 2-4 chars each, no all-caps)
        name_patterns = re.compile(r'\b[A-Z][a-z]{2,15}(?:\s+[A-Z][a-z]{2,15}){1,2}\b')

        # Only look in elements explicitly marked as team/staff/author
        for el in soup.find_all(attrs={'class': re.compile(
            r'team|staff|author|member|founder|ceo|director|person|profile', re.I
        )}):
            text = el.get_text(strip=True)
            if text and len(text) < 100:
                for name in name_patterns.findall(text):
                    # Skip common false positives
                    lower = name.lower()
                    if any(skip in lower for skip in (
                        'privacy', 'policy', 'terms', 'contact', 'about',
                        'home', 'read', 'more', 'learn', 'click', 'submit',
                        'token', 'knowledge', 'blockchain', 'security',
                    )):
                        continue
                    if name not in result['names'] and len(result['names']) < 5:
                        result['names'].append(name)

    # ------------------------------------------------------------------
    @staticmethod
    def _empty_result(url, reason):
        return {
            'emails': [],
            'phones': [],
            'linkedin_url': '',
            'twitter_url': '',
            'facebook_url': '',
            'instagram_url': '',
            'names': [],
            'business_name': '',
            'source_url': url or '',
            'status': reason,
            'pages_scraped': 0,
        }
