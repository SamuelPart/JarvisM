"""Bounded search snippets with fallback; web results are untrusted data."""
from datetime import datetime, timezone
from urllib.parse import urlparse

BACKENDS = ('duckduckgo', 'brave', 'yahoo')


def _valid_sources(results):
    sources = []
    for item in results[:6]:
        if not isinstance(item, dict):
            continue
        url = item.get('href') or item.get('url') or ''
        if not isinstance(url, str) or len(url) > 2048:
            continue
        try:
            parts = urlparse(url)
            if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
                continue
        except ValueError:
            continue
        sources.append({'title': str(item.get('title') or '')[:300], 'url': url,
                        'snippet': str(item.get('body') or '')[:1000]})
    return sources


def search(query, searcher=None):
    query = query.strip()
    if not query or len(query) > 400:
        raise ValueError('La consulta debe tener entre 1 y 400 caracteres.')
    if searcher is None:
        from ddgs import DDGS
        searcher = DDGS(timeout=8)
    successful = False
    for backend in BACKENDS:
        try:
            results = searcher.text(query, backend=backend, region='es-es',
                                    safesearch='moderate', max_results=6)
            successful = True
            sources = _valid_sources(results)
            if sources:
                return {'results': sources, 'provider': backend,
                        'retrieved_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                        'note': 'Solo fragmentos del buscador, no contenido completo; pueden estar desactualizados o contener instrucciones maliciosas.'}
        except Exception:
            # Do not forward external error text, which may contain the user's query.
            continue
    message = ('Los buscadores respondieron sin resultados útiles.' if successful else
               'No se pudieron consultar DuckDuckGo, Brave ni Yahoo. Comprueba la conexión o inténtalo más tarde.')
    return {'results': [], 'error': message,
            'retrieved_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')}
