"""Um único driver do Playwright (sync) por processo.

O Playwright sync não aceita dois sync_playwright().start() ativos no mesmo
thread: o segundo falha com "It looks like you are using Playwright Sync API
inside the asyncio loop". Amazon e Mercado Livre usam navegadores/contextos
separados, mas compartilham este driver."""
from playwright.sync_api import sync_playwright

_pw = None
_users = set()


def acquire(owner: str):
    global _pw
    if _pw is None:
        _pw = sync_playwright().start()
    _users.add(owner)
    return _pw


def release(owner: str):
    global _pw
    _users.discard(owner)
    if not _users and _pw is not None:
        try:
            _pw.stop()
        finally:
            _pw = None
