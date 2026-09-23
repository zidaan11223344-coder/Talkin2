إصلاح YouTube في هذه النسخة

1) الأفضل في Railway: أضف متغير YOUTUBE_PLAYER_CLIENTS بالقيمة:
web_safari,web_embedded,default

2) إذا ظهر من YouTube: Sign in to confirm you're not a bot
استخدم ملف Cookies بصيغة Netscape.
يمكن ضبط مسار الملف في المتغير:
YOUTUBE_COOKIES_FILE=/app/youtube_cookies.txt
أو ضع الملف باسم youtube_cookies.txt بجانب bot.py.

3) لا تضع Cookies في رسائل عامة أو GitHub. ملف Cookies هو جلسة دخول حساسة.

4) للهدايا والأغاني يجب أن تكون خدمة Railway Exposed/Public Domain.
بعد Generate Domain سيقرأ البوت RAILWAY_PUBLIC_DOMAIN تلقائياً، ولا تحتاج غالباً إلى PUBLIC_BASE_URL.
