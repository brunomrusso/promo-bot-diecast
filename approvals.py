import requests

import config
import db

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
_offset = 0


def _post(method: str, payload: dict):
    try:
        requests.post(f"{API}/{method}", json=payload, timeout=15)
    except requests.RequestException:
        pass


def _handle_callback(cb: dict):
    global _offset
    data = cb.get("data", "")
    action, _, pid = data.partition(":")
    row = db.get_pending(pid)
    qid = cb["id"]
    msg = cb.get("message", {})
    if not row:
        _post("answerCallbackQuery",
              {"callback_query_id": qid, "text": "já decidido"})
        return
    store, title, price, url, image, original, discount = row
    deal = {"id": pid, "store": store, "title": title, "price": price,
            "url": url, "image": image, "original_price": original,
            "discount": discount}
    if action == "ok":
        db.create_job("approve_pending", {"product_id": pid, "coupon": {}})
        answer = "aprovação recebida; validando oferta"
    elif action == "bp":
        db.add_blacklist("product", pid, title)
        db.set_status(pid, "blacklisted")
        answer = "produto bloqueado 🚫"
    elif action == "bt":
        db.add_blacklist("term", title, title)
        db.set_status(pid, "blacklisted")
        answer = "título bloqueado 🚫"
    else:
        db.set_status(pid, "rejected")
        answer = "ignorado ❌"
    _post("answerCallbackQuery", {"callback_query_id": qid, "text": answer})
    if msg.get("message_id"):
        _post("editMessageReplyMarkup", {
            "chat_id": msg["chat"]["id"],
            "message_id": msg["message_id"],
            "reply_markup": {"inline_keyboard": []},
        })


def poll_updates():
    """Loop de long-polling: processa cliques nos botões de aprovação."""
    global _offset
    while True:
        try:
            r = requests.get(
                f"{API}/getUpdates",
                params={"offset": _offset, "timeout": 30,
                        "allowed_updates": ["callback_query"]},
                timeout=40,
            )
            for upd in r.json().get("result", []):
                _offset = upd["update_id"] + 1
                if "callback_query" in upd:
                    _handle_callback(upd["callback_query"])
        except requests.RequestException:
            continue
