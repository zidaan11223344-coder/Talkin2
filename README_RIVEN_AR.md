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
RIVEN_DB_PORT=3306
RIVEN_DB_USER=<اسم مستخدم MySQL من Riven>
RIVEN_DB_PASSWORD=<كلمة سر MySQL من Riven>
RIVEN_DATABASE_KIND=mysql
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

بما أن البورت `3306` فهو MySQL/MariaDB، لذلك استخدم `RIVEN_DATABASE_KIND=mysql`. يبني البوت اتصال MySQL تلقائياً ويشفّر الرموز الخاصة في اسم المستخدم وكلمة السر. إذا كان Riven يضيف المتغير `DATABASE_URL` تلقائياً، يمكن ترك الحقول المنفصلة و`RIVEN_DATABASE_URL` فارغة؛ البوت يستخدم `DATABASE_URL` كبديل.

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

## لعبة الكركيت

تم دمج لعبة الكركيت داخل `Talkin2` مع نفس طبقة حفظ الحالة. أضف هذه المتغيرات إلى خدمة RavenHost:

```text
BOT_DATA_DIR=/data/talkin2
ASSET_HTTP_ENABLED=1
RAVEN_PUBLIC_DOMAIN=https://اسم-خدمة-البوت.example
```

إذا لم يكن لديك Volume، تبقى حالة المباراة والنقاط محفوظة في Riven عند ضبط متغيرات قاعدة البيانات أعلاه. يفضّل استخدام Volume على `/data` أيضًا لحفظ صور النتائج المولدة.

أوامر الماستر داخل الغرفة أو في الخاص:

```text
تشغيل الكركت
إيقاف الكركت
```

بعد التشغيل يختار الماستر عدد اللاعبين بإرسال `1` إلى `4`. ثم يرسل اللاعبون `Join`، وبعد اكتمال الفريق تبدأ المباراة. أثناء اللعب يرسل اللاعب الرقم من `0` إلى `6`. صور الأرقام والدَك والهتريك تُرسل تلقائيًا من `/assets/`، وصورة النتيجة من `/cricket-media/`.

يمكن استخدام الاختصارات القديمة أيضًا: `.cr 1` للتشغيل و`.cr 0` للإيقاف.
