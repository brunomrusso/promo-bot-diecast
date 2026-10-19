import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from core import db
from playwright.sync_api import sync_playwright

PROFILE_DIR = Path(__file__).parent.parent / "chrome_profile_ml"
CUPONS_URL = "https://www.mercadolivre.com.br/cupons"
LINKBUILDER_URL = "https://www.mercadolivre.com.br/afiliados/linkbuilder#hub"

# sem --start-minimized: a janela precisa ficar visível pro login manual
_args = [
    "--disable-blink-features=AutomationControlled",
]

_ctx = None
_pw = None


def ml_session_state():
    state = db.get_system_state().get("ml_session")
    return state["value"] if state else {"status": "unknown"}


def ml_available():
    state = ml_session_state()
    if state.get("status") != "verification_required":
        return True
    retry_at = state.get("retry_at")
    return bool(retry_at and datetime.utcnow() >= datetime.fromisoformat(retry_at))


def mark_ml_verification(url=""):
    db.set_system_state("ml_session", {
        "status": "verification_required",
        "message": "Mercado Livre requer verificação manual",
        "url": url,
        "retry_at": (datetime.utcnow() + timedelta(hours=2)).isoformat(timespec="seconds"),
    })
    db.update_store_health("Mercado Livre", "blocked", error="Verificação manual necessária")


def mark_ml_ready():
    db.set_system_state("ml_session", {"status": "ready", "message": "Sessão disponível"})


def is_ml_verification(page):
    try:
        url = page.url.lower()
        title = page.title().lower()
        body = page.inner_text("body")[:4000].lower()
        return ("captcha" in url or "wall/logged" in url
                or "account-verification" in url or "segurança" in title
                or "verificação" in body or "captcha" in body)
    except Exception:
        return False


def _get_context():
    """Contexto persistente: cookies/sessão do ML ficam salvos em disco."""
    global _ctx, _pw
    if _ctx is None:
        _pw = sync_playwright().start()
        PROFILE_DIR.mkdir(exist_ok=True)
        try:
            _ctx = _pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), channel="chrome",
                headless=False, args=_args, locale="pt-BR",
            )
        except Exception:
            _ctx = _pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=False, args=_args,
                locale="pt-BR",
            )
    return _ctx


def close_context():
    global _ctx, _pw
    if _ctx:
        _ctx.close()
        _pw.stop()
        _ctx = _pw = None


def _is_login_page(page) -> bool:
    try:
        url = page.url
        if "identification" in url or url.rstrip("/").endswith("/login"):
            return True
        body = page.inner_text("body")[:4000].lower()
        return "iniciar sess" in body or "digite seu e-mail" in body
    except Exception:
        return False


def _wait_login(page, timeout=300):
    """Se cair na tela de login, espera o usuário logar manualmente."""
    if not _is_login_page(page):
        return True
    print("[ML-cupons] LOGIN NECESSÁRIO: faça login na janela do Chrome "
          "que abriu (só na primeira vez)")
    start = time.time()
    while time.time() - start < timeout:
        if not _is_login_page(page):
            return True
        time.sleep(3)
    return False


def collect_ml_coupons():
    """Raspa cupons globais da página /cupons do ML (requer login 1x)."""
    if not ml_available():
        return []
    try:
        ctx = _get_context()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(CUPONS_URL, timeout=45000)
        page.wait_for_load_state("load")
        page.wait_for_timeout(3000)
        if is_ml_verification(page):
            mark_ml_verification(page.url)
            return []
        if not _wait_login(page):
            print("[ML-cupons] login não concluído a tempo")
            return []
        page.wait_for_load_state("load")
        page.wait_for_timeout(3000)
        body = page.inner_text("body")
    except Exception as e:
        print(f"[ML-cupons] erro: {e}")
        return []

    deals = []
    # formato do card: "20% OFF MAQUININHAS" / "Cupom 20% OFF MAQUININHAS"
    # ou "Cupom ativado de 10% OFF em produtos de Loja X"
    for m in re.finditer(
            r"Cupom\s+(\d+%|R\$\s*\d+(?:[.,]\d+)?)\s*OFF(?:\s+([A-ZÁÉÍÓÚÑ0-9]{3,}))?",
            body):
        discount_text = re.sub(r"\s+", " ", m.group(1)).strip()
        code = m.group(2)
        minimo = ""
        ctx = body[m.end():m.end() + 300]
        mm = re.search(r"Compra m[íi]nima\s*R\$\s*([\d.,]+)", ctx)
        if mm:
            minimo = f" | mín. R$ {mm.group(1)}"
        key = code or discount_text
        deals.append({
            "id": f"ml-cupom-{key}-{discount_text}",
            "store": "Mercado Livre",
            "title": f"{discount_text} OFF no Mercado Livre{minimo}",
            "coupon": code or "",
            "url": "https://www.mercadolivre.com.br/cupons",
            "image": "",
            "discount": 0,
            "price": None,
            "original_price": None,
            "affiliate_ready": True,
        })
    return deals


_link_cache = {}


def ml_affiliate_link(product_url: str) -> str:
    """Gera link de afiliado meli.la via Gerador de Links do hub (sessão logada)."""
    if product_url in _link_cache:
        return _link_cache[product_url]
    if not ml_available():
        return product_url
    try:
        ctx = _get_context()
        page = ctx.new_page()
        page.goto(LINKBUILDER_URL, timeout=45000)
        page.wait_for_timeout(3500)
        if is_ml_verification(page):
            mark_ml_verification(page.url)
            page.close()
            return product_url
        if "login" in page.url or "identification" in page.url:
            mark_ml_verification(page.url)
            print("[ML-link] sessão expirada, relogue")
            page.close()
            return product_url
        ta = page.query_selector("textarea")
        ta.fill(product_url)
        page.get_by_text("Gerar", exact=True).first.click()
        page.wait_for_timeout(5000)
        links = re.findall(
            r"https://meli\.la/\w+|https://mercadolivre\.com/sec/\w+",
            page.content(),
        )
        page.close()
        if links:
            _link_cache[product_url] = links[0]
            return links[0]
        print(f"[ML-link] falha ao gerar link p/ {product_url[:60]}")
    except Exception as e:
        print(f"[ML-link] erro: {e}")
    _link_cache[product_url] = product_url
    return product_url
