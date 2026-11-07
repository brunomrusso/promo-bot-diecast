import os
import re
import socket
import time
from datetime import datetime, timedelta
from pathlib import Path

import config
from core import db
from . import pw_shared

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
    previous = ml_session_state()
    new_episode = (previous.get("status") != "verification_required"
                   or not previous.get("alerted"))
    db.set_system_state("ml_session", {
        "status": "verification_required",
        "message": "Mercado Livre requer verificação manual",
        "url": url,
        "alerted": True,
        "retry_at": (datetime.utcnow() + timedelta(hours=2)).isoformat(timespec="seconds"),
    })
    db.update_store_health("Mercado Livre", "blocked", error="Verificação manual necessária")
    if new_episode:
        try:
            from core import notifier
            notifier.notify_admin(
                "⚠️ Mercado Livre bloqueado por verificação/anti-bot. "
                "Buscas no ML pausadas; demais lojas seguem. Verifique Saúde no painel."
            )
        except Exception as e:
            print(f"[ML] falha ao notificar bloqueio: {e}")


def mark_ml_ready():
    db.set_system_state("ml_session", {"status": "ready", "message": "Sessão disponível"})


def is_ml_verification(page):
    try:
        url = page.url.lower()
        title = page.title().lower()
        body = page.inner_text("body")[:4000].lower()
        if is_ml_error(page):
            return False  # página de erro ("Ops! Ocorreu um erro") não é anti-bot: não pausa o ML
        return ("captcha" in url or "wall/logged" in url
                or "account-verification" in url or "segurança" in title
                or "verificação" in body or "captcha" in body
                or "error accediendo" in body)
    except Exception:
        return False


def is_ml_error(page):
    """Página de erro do ML (anúncio/filtro que não existe mais, erro temporário). Não é bloqueio."""
    try:
        title = page.title().lower()
        body = page.inner_text("body")[:2000].lower()
        return ("ocorreu um erro" in title or "ocurrió un error" in title
                or "houve um erro" in body or "hubo un error" in body or "ocorreu um erro" in body)
    except Exception:
        return False


def _clear_stale_profile_lock():
    """O perfil veio copiado de outra máquina (migração) ou o Chrome caiu: o SingletonLock antigo
    faz o Chrome travar esperando ("perfil em uso em outro computador"). Remove só se o dono não existe."""
    lock = PROFILE_DIR / "SingletonLock"
    try:
        target = os.readlink(lock)
    except OSError:
        return
    host, _, pid = target.rpartition("-")
    if host == socket.gethostname() and pid.isdigit() and os.path.exists(f"/proc/{pid}"):
        return
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (PROFILE_DIR / name).unlink()
        except FileNotFoundError:
            pass
    print(f"[ML] trava antiga do perfil removida ({target})")


# Economia de proxy: o bot só precisa do texto/dados da página. Imagens, vídeos, fontes e rastreadores
# não passam pelo proxy (que é cobrado por GB). O login manual (ml-login.sh) desliga isso: ML_ECONOMIA=0.
_BLOQ_TIPOS = {"image", "media", "font"}
_BLOQ_DOMINIOS = ("google-analytics.com", "googletagmanager.com", "doubleclick.net", "facebook.net",
                  "facebook.com/tr", "hotjar", "clarity.ms", "googlesyndication.com")


def _economia(route):
    req = route.request
    if req.resource_type in _BLOQ_TIPOS or any(d in req.url for d in _BLOQ_DOMINIOS):
        return route.abort()
    return route.continue_()


def _get_context():
    """Contexto persistente: cookies/sessão do ML ficam salvos em disco."""
    global _ctx, _pw
    if _ctx is None:
        _pw = pw_shared.acquire("ml")
        PROFILE_DIR.mkdir(exist_ok=True)
        _clear_stale_profile_lock()
        proxy = config.ml_playwright_proxy()
        if proxy:
            print(f"[ML] usando proxy {proxy['server']}")
        try:
            _ctx = _pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), channel="chrome",
                headless=False, args=_args, locale="pt-BR", proxy=proxy,
            )
        except Exception:
            _ctx = _pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=False, args=_args,
                locale="pt-BR", proxy=proxy,
            )
        if proxy and os.getenv("ML_ECONOMIA", "1") != "0":
            _ctx.route("**/*", _economia)
            print("[ML] economia de proxy ligada (sem imagens, vídeos, fontes e rastreadores)")
    return _ctx


def close_context():
    global _ctx, _pw, _api_page
    _api_page = None
    if _ctx:
        try:
            _ctx.close()
        finally:
            _ctx = _pw = None
            pw_shared.release("ml")


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


_api_page = None  # uma página do Gerador de Links fica aberta e é reaproveitada (economiza proxy)


def _link_page():
    global _api_page
    if _api_page is not None and not _api_page.is_closed() and "mercadolivre.com.br" in _api_page.url:
        return _api_page
    _api_page = _get_context().new_page()
    _api_page.goto(LINKBUILDER_URL, timeout=45000)
    _api_page.wait_for_timeout(2000)
    return _api_page


def _ml_link_api(product_url: str, tag: str) -> str:
    """meli.la com uma etiqueta específica (mesma API do Gerador de Links). '' se falhar."""
    global _api_page
    try:
        page = _link_page()
        if is_ml_verification(page) or "login" in page.url or "identification" in page.url:
            mark_ml_verification(page.url)
            page.close()
            _api_page = None
            return ""
        res = page.evaluate("""async ([u, t]) => {
            const r = await fetch('/affiliate-program/api/v2/stripe/user/links', {method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url: u, tag: t})});
            return {s: r.status, j: r.ok ? await r.json() : null};
        }""", [product_url, tag])
        j = (res or {}).get("j") or {}
        link = j.get("short_url") or ""
        if j.get("tag") == tag and re.match(r"https://meli\.la/\w+$", link):
            return link
        print(f"[ML-link] etiqueta {tag}: resposta inesperada (HTTP {(res or {}).get('s')})")
    except Exception as e:
        print(f"[ML-link] etiqueta {tag}: erro {e}")
        try:
            if _api_page is not None:
                _api_page.close()
        except Exception:
            pass
        _api_page = None
    return ""


def ml_affiliate_link(product_url: str, tag: str = None, fallback: bool = True) -> str:
    """Gera link de afiliado meli.la. Com tag: usa essa etiqueta (canal); sem tag: etiqueta em uso na conta."""
    key = (product_url, tag)
    if key in _link_cache:
        return _link_cache[key]
    if not ml_available():
        return product_url
    if tag:
        link = _ml_link_api(product_url, tag)
        if not link and "?" in product_url:  # recusou o link com filtros (?pdp_filters=...): tenta o link limpo, na mesma página
            link = _ml_link_api(product_url.split("?", 1)[0], tag)
        if link:
            _link_cache[key] = link
            db.cache_affiliate_link(f"Mercado Livre#{tag}", product_url, link)
            return link
        if not fallback:
            return product_url  # site: tenta de novo na próxima rodada em vez de usar outra etiqueta
        # falhou com a etiqueta: segue pelo gerador normal (etiqueta padrão) para não perder a venda
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
            link = links[0]
            _link_cache[(product_url, None)] = link
            db.cache_affiliate_link("Mercado Livre", product_url, link)
            return link
        print(f"[ML-link] falha ao gerar link p/ {product_url[:60]}")
    except Exception as e:
        print(f"[ML-link] erro: {e}")
    return product_url
