إعداد الحفظ الدائم على GitHub

ضع هذه المتغيرات في Environment Variables / Secrets في مكان تشغيل البوت:

GITHUB_SYNC=1
GITHUB_REPO=zidaan11223344-coder/Talkin1
GITHUB_BRANCH=main
GITHUB_DATA_DIR=bot_data
GITHUB_TOKEN=التوكن الخاص بك

مهم:
- لا تضع GITHUB_TOKEN داخل bot.py.
- يجب أن يكون التوكن Fine-grained وله صلاحية Contents: Read and write للمستودع.
- الملفات ستظهر داخل مجلد bot_data في المستودع.
- تشمل النسخة الاحتياطية إحصاءات الألعاب ومستويات اللاعبين وترتيب النجوم في `game_stats.json` و`game_levels.json`.
- تشمل المزامنة أيضًا النقاط، التوثيقات، VIP، الماسترات، الردود، الترحيبات، الغرف، الحماية، إعدادات الألعاب، الرهانات، والهدايا/النشر. ويُنشئ أمر `نسخ احتياطي` ملف `backup_manifest.json` للتحقق من اكتمال الملفات وتطابقها.
- لا تشارك التوكن في المحادثة.
