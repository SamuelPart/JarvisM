"""Safe URL rendering and spoken output without reading links aloud."""
import html
import re
from urllib.parse import urlsplit

URL = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)
TRAILING = '.,;:!?)]}'


def without_links(text):
    return URL.sub('', text).strip()


def markup(text):
    pieces, position = [], 0
    for match in URL.finditer(text):
        raw = match.group(0)
        url = raw.rstrip(TRAILING)
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme.lower() in ('http', 'https') and bool(parsed.hostname) and not parsed.username and not parsed.password
        except ValueError:
            valid = False
        if not valid:
            continue
        pieces.append(html.escape(text[position:match.start()]))
        escaped = html.escape(url, quote=True)
        pieces.append(f'<a href="{escaped}" style="color:#80ddea;">{escaped}</a>')
        pieces.append(html.escape(raw[len(url):]))
        position = match.end()
    pieces.append(html.escape(text[position:]))
    return ''.join(pieces).replace('\n', '<br>')
