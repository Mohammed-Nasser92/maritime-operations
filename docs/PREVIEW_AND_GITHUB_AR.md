# حسابك للاختبار وربط GitHub — 30 سبتمبر 2026

الترتيب المعتمد: مراجعة Supabase → تجهيز حساب المدير وتشغيل الموقع محليًا للاختبار → رفع المصدر إلى GitHub → النشر بعد موافقتك → ربط Level 2 والدرون أخيرًا. إنشاء المستودع يمكن إنجازه الآن بالتوازي مع تجهيز الحساب.

## معنى الرابط الحالي

https://rxqlccksknrjysluzgkt.supabase.co هو عنوان خدمات Supabase. فتح الجذر يعيد requested path is invalid لأنه لا يحتوي واجهة الموقع. فحص Auth settings عبر HTTP أعاد 200 فعلًا.

اسم المؤسسة واسم المشروع قابلان للتسمية، أما project ref فهو معرّف تقني منفصل. لا نحتاج تغييره لاختيار عنوان جميل لموقعك؛ عنوان الموقع يحدد عند نشر الواجهة. توفر Supabase نطاقًا مخصصًا أو Vanity Subdomain تجريبيًا وفق شروطها المدفوعة: https://supabase.com/docs/guides/platform/custom-domains . لم نفعّل أي إضافة مدفوعة.

## 1. اضبط Auth في Supabase

افتح https://supabase.com/dashboard واختر مشروع Autonomous Maritime Surveillance UAV:

1. داخل Authentication ابحث عن إعداد **Allow new users to sign up** ضمن إعدادات Sign In / Providers أو General Configuration، وأوقفه ثم احفظ. الاسم مهم لأن ترتيب القوائم قد يتغير. آخر فحص أكد أن التسجيل العام أصبح مغلقًا؛ اتركه كذلك.
2. اترك تسجيل الدخول بالبريد/كلمة المرور مفعّلًا. الواجهة ستستخدم ID، والخادم يحوّله داخليًا إلى البريد.
3. في إعدادات Multi-Factor Authentication راجع **TOTP Enrollment** و**TOTP Verification** واجعلهما مفعّلين. لا تُلغ شرط AAL2 في الكود أو RLS.

مراجع Supabase:
- https://supabase.com/docs/guides/auth/general-configuration
- https://supabase.com/docs/guides/auth/auth-mfa

## 2. حسابك جاهز — والخطوات التالية مرجع لحساب جديد

حساب المستخدم الأول أُنشئ وربط كمدير بالفعل؛ لا تنشئه مرة أخرى. استخدم ID المتفق عليه وكلمة المرور التي أدخلتها داخل Supabase. إعداد Authenticator يتم عند أول دخول إلى الموقع.

لإنشاء حساب جديد من لوحة Supabase: Authentication → Users → Add user → Create new user. أدخل بريدك وكلمة مرور قوية لا تقل عن 12 حرفًا داخل Supabase فقط. إن ظهر Auto Confirm User فعّله لحسابك الذي تنشئه إداريًا، أو أكمل تأكيد البريد قبل محاولة الدخول.

بعد الإنشاء أرسل في المحادثة **User UID** ومعرّف الدخول الذي تريده (مثل mar-001) واسم العرض. هذه ليست أسرار دخول. سنطابق UID مع مستخدم Auth ونضيف profile بدور admin وربط login_id، بعد التأكد من عدم التكرار. هذا الربط أُنجز للحساب الأول؛ إنشاء مستخدم Auth جديد وحده لا يفتح لوحة المشروع.

بديل عند توفر جهازك: أداة bootstrap_admin تنشئ حساب Auth وملف المدير وربط ID معًا بعد ضبط البيئة في الخطوة التالية. استخدم هذا البديل فقط إذا لم تنشئ الحساب من لوحة Supabase، كي لا تنشئ حسابًا مكررًا. أمرها المصحح موجود في DEPLOYMENT_AR.md، وكلمة المرور تُدخل محليًا دون إظهارها.

## 3. اختبار الموقع قبل Render على Windows

فك Maritime_Phase3.zip في مجلد جديد، ولا تستبدل مجلد level3_server القديم أو قاعدة SQLite الموجودة عندك. افتح مجلد Maritime_Phase3 في VS Code. من Terminal PowerShell في جذر المجلد:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server/requirements.txt
Copy-Item .env.example .env
```

نفذ Copy-Item أول مرة فقط حتى لا تستبدل إعداداتك. افتح .env داخل VS Code وعدّل:

- SUPABASE_URL إلى https://rxqlccksknrjysluzgkt.supabase.co
- SUPABASE_SECRET_KEY إلى Secret API key من إعدادات API keys في مشروعك. ليس كلمة مرور قاعدة البيانات. احتفظ به في جهازك فقط.
- SUPABASE_PUBLISHABLE_KEY إلى المفتاح الذي يبدأ sb_publishable_ من المشروع نفسه.
- INGEST_API_KEY إلى قيمة عشوائية طويلة تولدها محليًا: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- APP_ENV=development، وALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000، وFORWARDED_ALLOW_IPS=127.0.0.1.

بعد تهيئة الحساب شغّل:

```powershell
.\.venv\Scripts\python.exe -m uvicorn server.app:app --env-file .env --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

افتح http://127.0.0.1:8000 على الجهاز نفسه. أدخل ID وكلمة المرور، ثم سجّل Authenticator في أول دخول وأدخل الرمز. بعد التحقق تستطيع فتح لوحة المراقبة والأرشيف ومرجع الأحداث والتتبع بحساب المدير. القاعدة خالية من الأحداث حاليًا، فلا يعني فراغ اللوحات فشل الاتصال.

هذا عنوان محلي: كتابته على الهاتف لا يفتح الموقع الموجود على الكمبيوتر. اختبار الوصول من أي جهاز عبر الإنترنت يأتي بعد النشر الذي أجلته. ولا يوجد الآن رابط عام جاهز لتسجيل الدخول.

لا ترفع .env أو مفاتيح أو كلمات مرور إلى GitHub. ملف .gitignore يستبعد .env مسبقًا.

## 4. المستودع الحالي وخطوات الإنشاء المرجعية

المستودع موجود: https://github.com/Mohammed-Nasser92/maritime-operations . لا تكرّر إنشاؤه. الخطوات التالية مرجع فقط لمستودع جديد.

1. افتح https://github.com/new وسجل الدخول.
2. Owner: حسابك Mohammed-Nasser92.
3. Repository name: maritime-operations.
4. Description اختياري: Autonomous Maritime Surveillance UAV — Level 3 Server and Dashboard.
5. اختر Public وفق طلبك السابق.
6. اترك Add README و.gitignore وLicense دون تهيئة، لأن المصدر موجود لدينا. إن أنشأته مع README لا تحذفه؛ أرسل الرابط لنراجع المحتوى قبل الدمج.
7. اضغط Create repository، ثم أرسل رابط صفحة المستودع فقط. تأكد أن إضافة GitHub في ChatGPT مخولة للوصول لهذا المستودع إذا كان الوصول محددًا لمستودعات مختارة.

لا ترفع ZIP أو repository.bundle أو index.html وحده لتشغيل النظام الكامل؛ المستودع يحتاج مجلد server وملفات الإعداد والواجهة والاختبارات أيضًا. ملف bundle داخل الحزمة وسيلة لنقل تاريخ Git فقط.

لا تحتاج إرسال كلمة مرور GitHub أو Personal Access Token. لا تفعّل Pages الآن كتجربة دخول كاملة؛ Python/FastAPI يحتاج خادمًا، وPages يستضيف ملفات الواجهة فقط.

## الفحوص التي ما زالت مرتبطة بهذه الخطوات

بعد ضبط حسابك والأسرار: دخول حقيقي وTOTP صحيح/خاطئ، حفظ صورة وقراءة رابطها الموقّع، إنشاء حدث ومراجعته، انتهاء المهلة، الأرشيف وWebSocket، والخروج وإلغاء الوصول. بعد النشر: HTTPS/CORS/proxy والجوال ومدة الاتصال. بعد تسليم Level 2: الأجهزة الحقيقية والطابور والأوامر. لم تُسجل هذه الحالات كنجاح قبل تنفيذها.
