import html
import requests

import config

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


def _track_link(deal: dict, link: str) -> str:
    """Wrap affiliate link with click tracking if DASHBOARD_URL is configured."""
    base = config.DASHBOARD_URL.rstrip("/") if config.DASHBOARD_URL else ""
    if base and deal.get("id"):
        return f"{base}/go/{deal['id']}"
    return link


def _format(deal: dict, link: str) -> str:
    title = html.escape(deal["title"])
    if "coupon" in deal:
        if deal["coupon"]:
            text = (f"🎟️ <b>CUPOM: <code>{deal['coupon']}</code></b> — "
                    f"{deal['store']}\n\n<b>{title}</b>\n\n")
        else:
            text = (f"🎟️ <b>CUPOM ATIVADO</b> — {deal['store']}\n\n"
                    f"<b>{title}</b>\n\n")
        if link:
            text += f"👉 <a href=\"{link}\">Usar cupom</a>"
        return text
    disc = int(deal.get("discount") or 0)
    header = f"🔥 <b>{disc}% OFF</b> — {deal['store']}\n\n" \
        if disc > 0 else f"🔥 <b>Oferta</b> — {deal['store']}\n\n"
    text = f"{header}<b>{title}</b>\n\n"
    if deal.get("price") and deal.get("original_price") \
            and deal["original_price"] > deal["price"]:
        text += (f"De: <s>R$ {deal['original_price']:.2f}</s>\n"
                 f"Por: <b>R$ {deal['price']:.2f}</b>\n\n")
    elif deal.get("price"):
        text += f"Por: <b>R$ {deal['price']:.2f}</b>\n\n"
    if deal.get("manual_coupon_code") and deal.get("manual_coupon_final_price"):
        code = html.escape(deal["manual_coupon_code"])
        text += (f"🎟️ Cupom: <code>{code}</code>\n"
                 f"Com cupom: <b>R$ {deal['manual_coupon_final_price']:.2f}</b>\n")
        if deal.get("manual_coupon_min_purchase"):
            text += f"Compra mínima: R$ {deal['manual_coupon_min_purchase']:.2f}\n"
        text += "\n"
    return text + f"👉 <a href=\"{link}\">Comprar</a>"


def send_for_approval(deal: dict, link: str) -> bool:
    """Manda a oferta pro admin com botões de aprovar/rejeitar."""
    if not config.TELEGRAM_ADMIN_CHAT_ID:
        return False
    text = "⏳ <b>APROVAR?</b>\n\n" + _format(deal, link)
    keyboard = {"inline_keyboard": [
        [
            {"text": "✅ Postar", "callback_data": f"ok:{deal['id']}"},
            {"text": "❌ Ignorar", "callback_data": f"no:{deal['id']}"},
        ],
        [
            {"text": "🚫 Produto", "callback_data": f"bp:{deal['id']}"},
            {"text": "🚫 Título", "callback_data": f"bt:{deal['id']}"},
        ],
    ]}
    try:
        if deal.get("image"):
            resp = requests.post(
                f"{API}/sendPhoto",
                json={
                    "chat_id": config.TELEGRAM_ADMIN_CHAT_ID,
                    "photo": deal["image"],
                    "caption": text,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return True
        resp = requests.post(
            f"{API}/sendMessage",
            json={
                "chat_id": config.TELEGRAM_ADMIN_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            },
            timeout=15,
        )
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f"[Telegram] erro ao pedir aprovação: {e}")
        return False


def format_whatsapp(deal: dict, link: str) -> str:
    if "coupon" in deal:
        code = f"*{deal['coupon']}*" if deal["coupon"] else "ATIVADO"
        text = (f"🎟️ CUPOM: {code} — {deal['store']}\n\n"
                f"{deal['title']}\n\n👉 {link}")
    else:
        disc = int(deal.get("discount") or 0)
        header = (f"🔥 *{disc}% OFF* — {deal['store']}\n\n"
                  if disc > 0 else f"🔥 *Oferta* — {deal['store']}\n\n")
        text = f"{header}{deal['title']}\n\n"
        if deal.get("price") and deal.get("original_price") \
                and deal["original_price"] > deal["price"]:
            text += (f"De: ~R$ {deal['original_price']:.2f}~\n"
                     f"Por: *R$ {deal['price']:.2f}*\n\n")
        elif deal.get("price"):
            text += f"Por: *R$ {deal['price']:.2f}*\n\n"
        if deal.get("manual_coupon_code") and deal.get("manual_coupon_final_price"):
            text += (f"🎟️ Cupom: *{deal['manual_coupon_code']}*\n"
                     f"Com cupom: *R$ {deal['manual_coupon_final_price']:.2f}*\n")
            if deal.get("manual_coupon_min_purchase"):
                text += f"Compra mínima: R$ {deal['manual_coupon_min_purchase']:.2f}\n"
            text += "\n"
        text += f"👉 {link}"
    return text


def send_whatsapp_ready(deal: dict, link: str) -> None:
    if not config.TELEGRAM_ADMIN_CHAT_ID:
        return
    text = format_whatsapp(deal, link)
    payload = {"chat_id": config.TELEGRAM_ADMIN_CHAT_ID}
    try:
        if deal.get("image"):
            resp = requests.post(f"{API}/sendPhoto", json={
                **payload, "photo": deal["image"], "caption": text,
            }, timeout=15)
            if resp.status_code == 200:
                return
        requests.post(f"{API}/sendMessage", json={
            **payload, "text": text,
        }, timeout=15)
    except requests.RequestException:
        pass


def send_price_alert(alert: dict, deal: dict) -> bool:
    """Notifica o admin que um alerta de preço foi atingido."""
    if not config.TELEGRAM_ADMIN_CHAT_ID:
        return False
    title = html.escape(alert["title"])
    text = (f"🔔 <b>ALERTA DE PREÇO ATINGIDO!</b>\n\n"
            f"<b>{title}</b>\n\n"
            f"Alvo: <b>R$ {alert['target_price']:.2f}</b>\n"
            f"Preço atual: <b>R$ {deal['price']:.2f}</b>\n"
            f"Loja: {deal['store']}\n\n"
            f"O produto voltou para a fila de aprovação.")
    try:
        if deal.get("image"):
            resp = requests.post(f"{API}/sendPhoto", json={
                "chat_id": config.TELEGRAM_ADMIN_CHAT_ID,
                "photo": deal["image"],
                "caption": text,
                "parse_mode": "HTML",
            }, timeout=15)
            if resp.status_code == 200:
                return True
        resp = requests.post(f"{API}/sendMessage", json={
            "chat_id": config.TELEGRAM_ADMIN_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=15)
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f"[Telegram] erro ao enviar alerta de preço: {e}")
        return False


def send_deal(deal: dict, link: str) -> bool:
    tracked = _track_link(deal, link)
    text = _format(deal, tracked)
    try:
        if deal.get("image"):
            resp = requests.post(
                f"{API}/sendPhoto",
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "photo": deal["image"],
                    "caption": text,
                    "parse_mode": "HTML",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return True
        resp = requests.post(
            f"{API}/sendMessage",
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f"[Telegram] erro ao enviar: {e}")
        return False
