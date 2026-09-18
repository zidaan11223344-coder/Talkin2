# -*- coding: utf-8 -*-
"""Ordered command menus (help1 .. help6) sent as clean lists."""

MENUS = {
    "help1": (
        "🎮 help1: الألعاب الجديدة / New Games:",
        [
            "سائق/ driver", "قناص/ sniper", "جري/ running", "عامل/ worker",
            "قبطان/ captain", "قتل/ kill", "مفتاح/ key", "باب/ door",
            "عبور/ crossing", "مصعد/ elevator", "مصارع/ wrestler",
            "تفكيك/ defuse", "سير/ walk", "حارس/ guard", "سرق/ rob",
            "دفاع/ defense", "سحق / crush",
        ],
    ),
    "help2": (
        "🎁 help2: الهدايا / Gifts:",
        [
            "gv — قائمة الهدايا / gifts list",
            "gv@رقم@اسم_المستخدم — إرسال هدية",
            "مثال: gv@1@ahmed",
            "تُرسل بطاقة بالصورة + اسم المرسل والمستقبل",
        ],
    ),
    "help3": (
        "🎵 help3: الأغاني / Music:",
        [
            "تشغيل اسم_الأغنية",
            "اغنية اسم_الأغنية",
            "music song name",
            "ايقاف / stop — إيقاف الطلب الحالي",
        ],
    ),
    "help4": (
        "💰 help4: النقاط / Points:",
        [
            "نقاطي / points — رصيدك",
            "sa@اسم_المستخدم@كمية — تحويل نقاط",
            "توب / top — أعلى الأرصدة",
        ],
    ),
    "help5": (
        "🛡️ help5: أوامر الإدارة / Admin:",
        [
            "k@ اسم — طرد / kick",
            "b@ اسم — حظر / ban",
            "u@ اسم — فك الحظر / unban",
            "a@ اسم — مشرف / admin",
            "o@ اسم — مالك / owner",
            "دخول اسم_الغرفة — دخول غرفة",
            "inv — دعوة أعضاء الغرفة",
            "say النص — تحدث بالبوت",
            "vi@اسم_المستخدم — توثيق الحساب وإرسال إشعار خاص",
            "unvi@اسم_المستخدم — إزالة التوثيق",
            "vip@اسم_المستخدم — توثيق VIP وإرسال إشعار خاص",
            "unvip@اسم_المستخدم — إلغاء VIP",
        ],
    ),
    "help6": (
        "⭐ help6: المستوى / Level:",
        [
            "لفلي / lvl / top",
            "مستواي / level",
        ],
    ),
}

ALIASES = {
    "الالعاب": "help1", "الألعاب": "help1", "games": "help1",
    "الهدايا": "help2", "gifts": "help2",
    "الاغاني": "help3", "الأغاني": "help3", "music": "help3",
    "النقاط": "help4", "points": "help4",
    "الاداره": "help5", "الإدارة": "help5", "admin": "help5",
    "المستوى": "help6", "level": "help6",
}


def menu_text(key):
    title, items = MENUS[key]
    lines = [title, ""]
    for item in items:
        lines.append("🔹" + item)
        lines.append("")
    return "\n".join(lines).rstrip()


def help_index():
    lines = ["📚 قوائم الأوامر / Command menus", "━━━━━━━━━━━━"]
    for key in MENUS:
        lines.append(f"🔹{key} — {MENUS[key][0].split(':',1)[-1].strip()}")
    lines.append("━━━━━━━━━━━━")
    lines.append("اكتب اسم القائمة مثل: help1")
    return "\n".join(lines)


def resolve(text):
    key = str(text or "").strip().casefold().replace(" ", "")
    if key in MENUS:
        return key
    return ALIASES.get(key)
