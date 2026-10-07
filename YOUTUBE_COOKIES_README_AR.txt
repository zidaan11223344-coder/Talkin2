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

5) يمكن تمرير ملف Cookies مركّب داخل الاستضافة عبر:
YOUTUBE_COOKIES_FILE=/app/youtube_cookies.txt
أو وضع نص Netscape في المتغير السري YOUTUBE_COOKIES. لا تضع قيمة Cookies في GitHub أو في رسالة عامة.

6) دعم Spotify:
- أدخل رابط أغنية Spotify في أي أمر تشغيل أغنية؛ يحاول البوت جلب اسم الأغنية والفنان ثم البحث عن صوت قابل للتشغيل من مصادره المتاحة.
- للبحث في كتالوج Spotify بالنص، أضف SPOTIFY_CLIENT_ID وSPOTIFY_CLIENT_SECRET من تطبيق Spotify Developer.
- Spotify لا يتيح واجهة عامة لرابط صوت كامل؛ لن يحاول البوت تجاوز مشغل Spotify أو تنزيل صوت محمي. إذا تعذر إيجاد نسخة قابلة للتشغيل من المصادر الأخرى فسيظهر فشل التشغيل.
