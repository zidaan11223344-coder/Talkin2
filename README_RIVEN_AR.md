# إعداد قاعدة بيانات Riven للبوت

## اسم قاعدة البيانات

استخدم الاسم التالي عند إنشاء قاعدة البيانات في Riven:

```text
talkin_bot_db
```

## متغيرات الخدمة داخل `.env`

أنشئ ملفاً باسم `.env` بجانب `bot.py` داخل خدمة Riven، وضع فيه المتغيرات التالية:

```text
RIVEN_DATABASE_NAME=talkin_bot_db
RIVEN_DB_HOST=<عنوان PostgreSQL من Riven>
RIVEN_DB_PORT=<البورت من Riven>
RIVEN_DB_USER=<اسم مستخدم PostgreSQL من Riven>
RIVEN_DB_PASSWORD=<كلمة سر PostgreSQL من Riven>
# اختياري فقط إذا أعطاك Riven رابط اتصال جاهزاً:
RIVEN_DATABASE_URL=
GITHUB_SYNC=1
GITHUB_REPO=zidaan11223344-coder/Talkin4
GITHUB_BRANCH=main
GITHUB_DATA_DIR=bot_data
GITHUB_TOKEN=<توكن GitHub بصلاحية الكتابة إلى Talkin4>
DATABASE_BACKUP_INTERVAL_SECONDS=21600
GITHUB_JSON_MIRROR=0
```

إذا كان Riven يضيف المتغير `DATABASE_URL` تلقائياً، يمكن ترك الحقول المنفصلة و`RIVEN_DATABASE_URL` فارغة؛ البوت يستخدم `DATABASE_URL` كبديل. عند توفر الحقول المنفصلة، يبني البوت رابط PostgreSQL تلقائياً ويشفّر الرموز الخاصة في اسم المستخدم وكلمة السر.

البوت يستدعي `load_dotenv()` عند التشغيل، لذلك يقرأ ملف `.env` تلقائياً. بعد حفظ الملف أعد تشغيل الخدمة أو نفّذ Redeploy.

## ماذا يفعل البوت؟

- ينشئ جدول `bot_state` تلقائياً عند أول اتصال.
- يحفظ كل ملف حالة JSON كسجل مستقل داخل PostgreSQL.
- يحتفظ بملفات JSON محلياً كـCache وخطة احتياط.
- عند إعادة التشغيل، يستعيد البيانات من PostgreSQL قبل تشغيل البوت.
- لا يرفع كل تغيير إلى GitHub عند تفعيل PostgreSQL.
- ينشئ نسخة JSON مجمعة إلى مجلد `bot_data` في Talkin4 كل 6 ساعات افتراضياً.
- يمكن تنفيذ النسخ فوراً من أمر الماستر:

```text
نسخ احتياطي
```

## أول تشغيل

1. أنشئ قاعدة PostgreSQL باسم `talkin_bot_db` في Riven.
2. انسخ `Host` إلى `RIVEN_DB_HOST`، و`Port` إلى `RIVEN_DB_PORT`، و`Database` إلى `RIVEN_DATABASE_NAME`، و`Username` إلى `RIVEN_DB_USER`، و`Password` إلى `RIVEN_DB_PASSWORD` داخل `.env`.
3. أضف `GITHUB_TOKEN` بصلاحية الكتابة إلى مستودع Talkin4 الخاص داخل `.env`.
4. أعد تشغيل الخدمة.
5. ابحث في سجل التشغيل عن:

```text
[STATE-DB] PostgreSQL enabled: talkin_bot_db
```

6. نفّذ `نسخ احتياطي` بعد التأكد من اتصال القاعدة.

## ملاحظات أمان

- اجعل مستودع Talkin4 خاصاً؛ النسخ قد تحتوي على نقاط وأسماء مستخدمين وإعدادات حظر.
- لا ترفع ملف `.env` إلى GitHub؛ أضفه إلى `.gitignore` إن لم يكن موجوداً.
- لا تضع رابط قاعدة البيانات أو توكن GitHub داخل أي ملف يتم رفعه إلى المستودع.
- لا تغيّر `GITHUB_JSON_MIRROR` إلى `1` إلا إذا أردت مرآة GitHub مع كل حفظ؛ القيمة `0` هي الأفضل لتقليل الحمل.
- لا توقف النسخة القديمة من JSON أو GitHub قبل التأكد من نجاح اتصال PostgreSQL ونسخة احتياطية قابلة للاستعادة.
