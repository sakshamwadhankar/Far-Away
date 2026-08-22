"""
backend/komvos/desktop/destructive.py

Explicit, defensible classification rules for destructive desktop actions.

Destructive operations are actions that can cause data loss, state corruption,
security boundary violation, unauthorized publication, irreversible system
modifications, or financial transactions.

Evaluates language-independent signals (roles, control types, automation IDs,
key combinations, target processes) alongside a comprehensive multilingual
keyword dictionary (English, Spanish, German, French, Chinese, Japanese,
Russian, Portuguese).

When classification is uncertain or ambiguous, the classifier FAILS SAFE by
classifying the action as destructive.
"""

from __future__ import annotations

import re

from komvos.desktop.models import (
    ActionType,
    DesktopAction,
    DestructiveClassification,
)

# ── Multilingual regex pattern sets for destructive keywords ─────────────────

# Deletion across EN, ES, DE, FR, ZH, JA, RU, PT
_DELETION_PATTERNS = (
    r"(?i)\b(delete|del|rm|remove|trash|erase|wipe|shred|truncate|drop|uninstall|"
    r"purge|destroy|eliminar|borrar|suprimir|desinstalar|destruir|vaciar|löschen|"
    r"loeschen|entfernen|vernichten|deinstallieren|bereinigen|supprimer|effacer|"
    r"retirer|désinstaller|desinstaller|détruire|detruire|удалить|стереть|"
    r"уничтожить|деинсталлировать|очистить|excluir|apagar|remover)\b"
    r"|(删除|移除|清空|卸载|销毁|抹掉|削除|消去|破棄|アンインストール|クリア)"
)

# Overwrite & Reset across EN, ES, DE, FR, ZH, JA, RU, PT
_OVERWRITE_PATTERNS = (
    r"(?i)\b(overwrite|replace|discard|revert|reset|format|clear all|sobrescribir|"
    r"reemplazar|descartar|revertir|restablecer|formatear|überschreiben|ueberschreiben|"
    r"ersetzen|verwerfen|zurücksetzen|zuruecksetzen|formatieren|écraser|ecraser|"
    r"remplacer|rejeter|rétablir|retablir|réinitialiser|reinitialiser|formater|"
    r"перезаписать|заменить|сбросить|форматировать|sobrescrever|substituir|redefinir)\b"
    r"|(覆盖|替换|重置|格式化|还原|放弃|上書き|置換|リセット|初期化|フォーマット)"
)

# System, Shell & Security Tools
_SYSTEM_SECURITY_PATTERNS = (
    r"(?i)\b(regedit|powershell|cmd|cmd\.exe|netsh|taskkill|sc stop|chmod|chown|sudo|"
    r"runas|firewall|antivirus|password|keyring|credential|settings|control panel|"
    r"uac|diskpart|mkfs|bash|sh|zsh|system32|services\.msc|regedt32)\b"
)

# Communication & Publishing
_COMMUNICATION_PUBLISH_PATTERNS = (
    r"(?i)\b(send|publish|post|submit|deploy|tweet|broadcast|push|share|commit|"
    r"enviar|publicar|emitir|compartir|senden|veröffentlichen|veroeffentlichen|"
    r"teilen|übertragen|envoyer|publier|partager|soumettre|отправить|опубликовать|"
    r"поделиться)\b"
    r"|(发送|发布|提交|分享|推送|送信|公開|投稿|共有|プッシュ)"
)

# Financial & Payments
_FINANCIAL_PATTERNS = (
    r"(?i)\b(buy|purchase|pay|payment|subscribe|checkout|order|transfer|credit card|"
    r"cvv|billing|wire|comprar|pagar|pago|suscribir|pedido|transferencia|tarjeta|"
    r"kaufen|bezahlen|zahlung|abonnieren|bestellen|überweisung|ueberweisung|"
    r"kreditkarte|acheter|payer|paiement|s'abonner|commander|virement|carte|"
    r"купить|оплатить|платеж|подписаться|заказать|перевод|pagamento|assinar)\b"
    r"|(购买|支付|付款|订阅|下单|转账|信用卡|購入|支払|決済|定期購入|注文|振込)"
)

_DANGEROUS_HOTKEYS = (
    {"alt", "f4"},
    {"ctrl", "d"},
    {"ctrl", "w"},
    {"ctrl", "q"},
    {"ctrl", "shift", "w"},
    {"shift", "delete"},
    {"cmd", "q"},
    {"cmd", "w"},
)

# Language-independent role indicators
_DESTRUCTIVE_ROLES = frozenset({
    "destructive_button",
    "danger_button",
    "delete_button",
    "close_button",
    "confirm_danger",
    "dialog_destructive",
})

_BENIGN_ROLES = frozenset({
    "tab",
    "tab_item",
    "tree_item",
    "scroll_bar",
    "status_bar",
    "tooltip",
    "separator",
})

_DANGEROUS_AUTOMATION_IDS = (
    r"(?i)(delete|remove|uninstall|format|reset|discard|purge|destroy|kill|"
    r"uac|security|firewall|buy|checkout|payment|order|submit|send)"
)


def classify_action(
    action: DesktopAction,
    target_element_name: str | None = None,
    target_element_role: str | None = None,
    target_automation_id: str | None = None,
) -> DestructiveClassification:
    """
    Classify whether a planned desktop action is destructive.

    Evaluates:
      1. Action type semantics (done / wait / screenshot vs mutations).
      2. Key combinations and dangerous hotkeys (Alt+F4, Shift+Delete, etc.).
      3. Language-independent UI element metadata (roles, automation IDs).
      4. Target application identity (system shells, registry tools).
      5. Typed text & target labels across EN, ES, DE, FR, ZH, JA, RU, PT.
      6. Fail-safe rule: when context is uncertain, classifies as DESTRUCTIVE.
    """
    # Safe read-only actions
    if action.action_type in (
        ActionType.SCREENSHOT,
        ActionType.WAIT,
        ActionType.DONE,
    ):
        return DestructiveClassification(
            is_destructive=False,
            reason=f"Action '{action.action_type.value}' is read-only.",
            category="read_only",
        )

    # 1. Check dangerous hotkeys
    if action.action_type == ActionType.HOTKEY and action.keys:
        lowered_keys = {k.lower().strip() for k in action.keys}
        for danger in _DANGEROUS_HOTKEYS:
            if danger.issubset(lowered_keys):
                combo = "+".join(action.keys)
                return DestructiveClassification(
                    is_destructive=True,
                    reason=(
                        f"Dangerous hotkey combo '{combo}' "
                        "can close applications or delete data."
                    ),
                    category="system_hotkey",
                )

    # 2. Check single key presses
    if action.action_type == ActionType.PRESS_KEY and action.key:
        key_lower = action.key.lower().strip()
        if key_lower in ("delete", "del"):
            return DestructiveClassification(
                is_destructive=True,
                reason="Direct 'Delete' key press can destroy data or files.",
                category="deletion",
            )

    # 3. Check language-independent automation roles & IDs
    if target_element_role and target_element_role.lower() in _DESTRUCTIVE_ROLES:
        return DestructiveClassification(
            is_destructive=True,
            reason=(
                f"UI element role '{target_element_role}' is an explicit "
                "destructive control."
            ),
            category="destructive_role",
        )

    if target_automation_id and re.search(
        _DANGEROUS_AUTOMATION_IDS, target_automation_id
    ):
        return DestructiveClassification(
            is_destructive=True,
            reason=(
                "UI automation ID indicates destructive operation: "
                f"{target_automation_id!r}"
            ),
            category="dangerous_automation_id",
        )

    # 4. Check target application
    if action.target_application and re.search(
        _SYSTEM_SECURITY_PATTERNS, action.target_application
    ):
        return DestructiveClassification(
            is_destructive=True,
            reason=(
                "Target application is a system/security tool: "
                f"{action.target_application!r}"
            ),
            category="system_security",
        )

    # 5. Check typed text
    if action.action_type == ActionType.TYPE_TEXT and action.text:
        text = action.text
        if re.search(_DELETION_PATTERNS, text):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Typed text contains deletion keywords: {text!r}",
                category="deletion",
            )
        if re.search(_OVERWRITE_PATTERNS, text):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Typed text contains overwrite keywords: {text!r}",
                category="overwrite",
            )
        if re.search(_SYSTEM_SECURITY_PATTERNS, text):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Typed text references system/security tools: {text!r}",
                category="system_security",
            )
        if re.search(_COMMUNICATION_PUBLISH_PATTERNS, text):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Typed text contains publication/sending keywords: {text!r}",
                category="communication_publish",
            )
        if re.search(_FINANCIAL_PATTERNS, text):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Typed text contains financial/payment keywords: {text!r}",
                category="financial",
            )

    # 6. Check target UI element text and semantics
    combined_target = " ".join(
        filter(
            None,
            [
                target_element_name,
                target_element_role,
                action.target_application,
                action.expected_outcome,
            ],
        )
    )

    if combined_target:
        if re.search(_DELETION_PATTERNS, combined_target):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Target UI element implies deletion: {combined_target!r}",
                category="deletion",
            )
        if re.search(_OVERWRITE_PATTERNS, combined_target):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Target UI implies overwrite/reset: {combined_target!r}",
                category="overwrite",
            )
        if re.search(_SYSTEM_SECURITY_PATTERNS, combined_target):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Target is system/security setting: {combined_target!r}",
                category="system_security",
            )
        if re.search(_COMMUNICATION_PUBLISH_PATTERNS, combined_target):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Target triggers publishing/sending: {combined_target!r}",
                category="communication_publish",
            )
        if re.search(_FINANCIAL_PATTERNS, combined_target):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Target is financial transaction: {combined_target!r}",
                category="financial",
            )

    # 7. Non-destructive standard navigation clicks or text inputs
    if action.action_type in (
        ActionType.CLICK,
        ActionType.DOUBLE_CLICK,
        ActionType.RIGHT_CLICK,
        ActionType.SCROLL,
    ):
        # Ordinary scroll is non-destructive
        if action.action_type == ActionType.SCROLL:
            return DestructiveClassification(
                is_destructive=False,
                reason="Scroll action is non-destructive.",
                category="navigation",
            )

        # Explicitly benign UI roles
        if target_element_role and target_element_role.lower() in _BENIGN_ROLES:
            return DestructiveClassification(
                is_destructive=False,
                reason=f"Safe UI interaction on benign role {target_element_role!r}.",
                category="navigation",
            )

        # Standard click with known non-empty name that passed all checks
        if target_element_name:
            return DestructiveClassification(
                is_destructive=False,
                reason=f"Safe UI interaction on element {target_element_name!r}.",
                category="interaction",
            )

    # Standard safe text entry without trigger keywords
    if action.action_type == ActionType.TYPE_TEXT and action.text:
        return DestructiveClassification(
            is_destructive=False,
            reason="Standard benign text input.",
            category="typing",
        )

    # 8. FAIL SAFE: when an action's context or target is unknown,
    # classify as destructive
    return DestructiveClassification(
        is_destructive=True,
        reason=(
            f"Uncertain or unverified action target for '{action.action_type.value}'; "
            "failing safe as destructive."
        ),
        category="fail_safe_uncertainty",
    )
