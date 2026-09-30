# دليل التشغيل والنشر — 3.1

**الحالة (30 سبتمبر 2026):** Supabase مهيأ، وحساب المدير الأول مربوط بمعرّف دخول. مستودع المصدر هو https://github.com/Mohammed-Nasser92/maritime-operations . لا يوجد رابط إنتاج أو خادم Render، وأسرار التشغيل لم تُضبط هنا. اختبر محليًا قبل الانتقال للنشر.

## 1. GitHub

المستودع الحالي: https://github.com/Mohammed-Nasser92/maritime-operations . لا تنشئ مستودعًا آخر. الخطوات التالية مرجع لإنشاء بيئة جديدة فقط؛ لا ترسل رمز وصول أو كلمة مرور.

إن تعذر الربط وتريد إنشاء المستودع يدويًا:

1. افتح https://github.com/new وسجل الدخول.
2. اختر Owner حسابك واسم `maritime-operations` أو الاسم الذي تفضله.
3. اختر Public وفق طلبك السابق. اترك خيارات تهيئة README وgitignore وLicense غير محددة، لأن المشروع يحتوي ملفاته.
4. اضغط Create repository وأرسل رابط المستودع فقط؛ لا نضع remote تخمينيًا.
5. بعد استلام الرابط والتفويض نربط المستودع ونرفع main. إذا نفذت محليًا، سجّل الدخول عبر GitHub CLI (`gh auth login`) ثم استخدم `git remote add origin <رابطك الفعلي>` و`git push -u origin main` من مجلد المشروع.

المجلد المحلي مهيأ بـGit. داخل الحزمة يوجد ملف تاريخ `repository.bundle` لاستعادة المستودع عبر `git clone repository.bundle maritime-operations` إذا احتجت التاريخ نفسه. عند فك ملفات المصدر مباشرة دون bundle، نفّذ git init -b main ثم git add . ثم git commit باستخدام هويتك المحلية. لا ترفع bundle إلى المستودع؛ هو وسيلة نقل فقط.

### دورة التعديل

أنشئ development من main، عدّل واختبر، ثم افتح Pull Request إلى main. Workflow `checks` يفحص بناء الواجهة والخادم وSQL والمتصفح وصورة Docker. فعّل حماية main واشتراط نجاح `validate` من إعدادات المستودع إذا كانت متاحة لحسابك. Render مهيأ للانتظار حتى نجاح checks، لكن تفعيل الحماية الحقيقي يُراجع بعد الربط. لا تعتبر كتابة YAML دليل تشغيل GitHub Actions.

## 2. Supabase

المشروع الحالي **Autonomous Maritime Surveillance UAV**، المرجع `rxqlccksknrjysluzgkt`، في `eu-central-1`، وقد طُبّقت المهاجرات الأربع بالفعل. **لا تعِد تنفيذ ملفات الإنشاء على هذا المشروع.**

لإنشاء بيئة أخرى فارغة فقط:
1. أنشئ المشروع في مؤسستك، وحدد المنطقة وكلمة مرور قاعدة البيانات داخل الخدمة.
2. نفذ `supabase/001_workspace.sql` ثم `002_complete_server.sql` ثم `003_live_workspace.sql` ثم `supabase/migrations/20260929173243_maritime_advisor_hardening.sql`.
3. تاريخ تطبيق MCP موجود في CLOUD_STATUS_AR.md. الملفات القديمة ليست داخل مجلد migrations القياسي؛ لا تستخدم `supabase db push` قبل توحيد تاريخ الهجرات، لأنه لن ينفذ 001–003 الموجودة خارجه.

ما بقي على المشروع الحالي:
1. آخر فحص في 30 سبتمبر أكد Email=true وdisable_signup=true: التسجيل العام مغلق الآن؛ اترك Allow new users to sign up معطلًا. راجع TOTP Enrollment/Verification من لوحة Authentication؛ هذه القيم لم يمكن التحقق منها في استجابة settings العامة. المستخدمون يضيفهم المدير.
2. من إعدادات API keys خذ Publishable وSecret، وأدخلهما مباشرة في البيئة المحلية أو Render. رابط API هو `https://rxqlccksknrjysluzgkt.supabase.co` وليس رابط الموقع.
3. حساب المدير الأول أُنشئ وربط بالفعل. استخدم معرّف الدخول المتفق عليه وكلمة المرور التي اخترتها، ثم اختبر Authenticator فعليًا. لا تعِد إنشاء الحساب نفسه.

مخزن `event-images` خاص بالفعل، بحد 10MiB وصيغ JPEG/PNG/WebP. لا تحوله Public.

لا يوجد ملف SQLite أصلي هنا. إذا كان لديك بيانات قديمة، نراجع نسخة منها ونجهز نقلًا بمطابقة الأعداد والمعرفات والصور قبل اعتماد PostgreSQL. هذه الحزمة لا تمسح SQLite ولا تزعم أنها نقلته.

## 3. متغيرات البيئة

| الاسم | القيمة ومصدرها | التعامل |
|---|---|---|
| APP_ENV | development محليًا، production في Render | إعداد |
| SUPABASE_URL | Project URL من Supabase، HTTPS بلا مسار | إعداد الخادم |
| SUPABASE_SECRET_KEY | Secret API key من مشروعك | سري؛ الخادم فقط |
| SUPABASE_PUBLISHABLE_KEY | sb_publishable_ من API keys | يوضع في الخادم أيضًا؛ لا مفتاح في الواجهة |
| INGEST_API_KEY | قيمة عشوائية طويلة مشتركة مع Jetson | سر، 32 حرفًا على الأقل؛ ولّد مثلًا `python -c "import secrets; print(secrets.token_urlsafe(48))"` محليًا |
| ALLOWED_ORIGINS | أصل موقع Render الفعلي، ومعه أصل GitHub Pages إن استخدمته، مفصولة بفاصلة | HTTPS في الإنتاج، دون مسار المستودع |
| PORT | تحدده Render؛ محليًا 8000 | لا حاجة لتغييره في Render |
| FORWARDED_ALLOW_IPS | عناوين/CIDR الوكلاء الموثوقين وفق إعداد الخدمة الفعلي | يراجع عند النشر؛ لا تضبط * على خادم مكشوف مباشرة |

لا نضيف DATABASE_URL أو SUPABASE_SERVICE_ROLE_KEY كمتغيرات وهمية؛ هذا الخادم يستخدم REST/RPC، واسم السر الذي يقرؤه فعلًا هو SUPABASE_SECRET_KEY. لا ترسل أسرارًا في المحادثة ولا تسجل أجسام طلبات الدخول.

## 4. تشغيل محلي متصل بمشروع Supabase

من جذر المشروع (Python 3.12 أو 3.13):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server/requirements.txt
Copy-Item .env.example .env
```

عدّل `.env` محليًا بالقيم الفعلية وAPP_ENV=development. ثم:

```powershell
.\.venv\Scripts\python.exe -m uvicorn server.app:app --env-file .env --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

افتح http://127.0.0.1:8000. الخادم يقدم الواجهة نفسها؛ لا يلزم خادم ملفات منفصل. في Linux/macOS استخدم `.venv/bin/python` و`cp .env.example .env`. `.env` لا يُقرأ تلقائيًا خارج أمر --env-file؛ Docker Compose يستخدم ملفه أو البيئة، وRender يحقن متغيراته.

### أول حساب وMFA

بعد تحميل متغيرات البيئة في طرفية خاصة، شغل `server/bootstrap_admin.py` لإضافة ID وبريد فعلي واسم وكلمة مرور. يمكن تحميل الملف المحلي صراحة:

```powershell
.\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; import runpy; load_dotenv(); runpy.run_module('server.bootstrap_admin', run_name='__main__')"
```

لربط ID بحساب موجود استخدم `server/assign_login_id.py` بالطريقة نفسها؛ لا يغير الدور أو كلمة المرور. أول دخول يعرض QR: امسحه بتطبيق Authenticator وأدخل الرمز. الدخول التالي يطلب الرمز الحالي. لا يوجد حساب تجريبي أو تجاوز MFA. استعادة الهاتف المفقود تتم بعد تحقق مالك Supabase من الهوية وإلغاء العامل والجلسات عبر الإدارة الموثوقة.

## 5. Render — مؤجل حتى اختبار المستخدم وموافقته على الانتقال للنشر

1. افتح https://dashboard.render.com وسجل الدخول، ثم اربط GitHub وامنح الوصول للمستودع.
2. استخدم New → Blueprint وحدد المستودع/main. راجع `render.yaml`.
3. راجع اسم الخدمة والمنطقة والخطة قبل الإنشاء. ملف render.yaml يحدد frankfurt لتوافق منطقة قاعدة البيانات. `starter` اقتراح لخادم مستمر، وليس شراءً تم؛ توقف عند أي شاشة دفع حتى تقرر.
4. أدخل كل متغير `sync: false` من الجدول أعلاه في Render، ولا ترسل المفاتيح بالمحادثة. ALLOWED_ORIGINS يكون أصل رابط الخدمة الذي تعينه Render؛ أضف Pages عند الحاجة.
5. البناء Dockerfile=`deploy/Dockerfile`، Context=جذر المستودع، وRoot Directory فارغ. لا تختَر server كجذر؛ الواجهة موجودة في index.html بالجذر.
6. التشغيل مضمّن في Docker: `python server/run.py`، المنفذ PORT، عامل واحد، بلا reload أو access log. Health Check=`/health`.
7. بعد اكتمال النشر افتح رابط HTTPS الحقيقي واختبر `/health` ثم الدخول وMFA. لا نسجل رابطًا افتراضيًا على أنه منتج منشور.

Render يدير HTTPS. الواجهة تستخدم أصل الصفحة تلقائيًا وتحوله إلى WSS للمتصفح. `/health` يعيد 503 إذا فشل عامل انتهاء المهلة؛ نجاح فحص الصحة وحده لا يكفي لاعتماد النظام. راجع إعدادات proxy والأحجام ومراقبة الأخطاء والنسخ الاحتياطية وسياسة الاحتفاظ قبل التشغيل الطويل. صورة Docker لم تُبنَ محليًا إذا لم يتوفر Docker؛ CI يتولى ذلك عند الربط.

## 6. GitHub Pages اختياري للواجهة نفسها

إذا أردت استضافة الواجهة عبر Pages أيضًا، عدّل `phase2ApiUrl` فقط في web/app.js إلى رابط Render الفعلي دون /api/v1، ثم `python build_frontend.py` والتزم بالاختبارات والرفع. لا تضف مفاتيح Supabase. في GitHub: Settings → Pages → Deploy from a branch → main → /(root) → Save. أضف أصل https://YOUR-USERNAME.github.io إلى ALLOWED_ORIGINS، لا مسار المستودع. Pages لا يشغل Python. ترك API URL فارغًا مناسب لعرض Render الموحد، وليس لصفحة Pages مستقلة.

## 7. Level 2 والتحقق النهائي

REST موجود للأحداث والصور والتليمترية والأوامر حسب API_CONTRACT. الرفع الناجح يعيد received=true وevent_id، مع بيانات الحدث وحالة duplicate. يجب إعادة الطلب نفسه بمعرف ثابت بعد فقد ACK.

WSS المتاح حاليًا للمتصفح فقط `/api/v1/ws` بتذكرة من `/api/v1/ws-ticket`. **لا يوجد حتى الآن WSS producer لJetson**. بعد تثبيت عقد Level 2 نضيف اتصال Jetson الصادر عبر 4G، وإرسال الأوامر عليه، والتأكيدات والطابور المحلي الدائم وإعادة المحاولة. لا يعتمد التصميم على فتح اتصال وارد إلى Jetson، ولا يرسل FastAPI MAVLink مباشرة إلى Pixhawk. لا نفعل follow/resume أو ربطهما بالقبول والمهلة قبل تثبيت قواعد الفريق والتحقق على Jetson.

نفذ ACCEPTANCE_AR بعد الربط: هاتف + حاسب + شبكة 4G، Auth/MFA، حفظ/قراءة الأحداث والصور، الأرشيف، GPS، WebSocket، القبول والرفض، انقطاع الشبكة وإعادة المحاولة، وصول الأمر وACK من Jetson. لم تنجح هذه الاختبارات المستضافة بعد لأنها لم تُجرَ.

مراجع رسمية: https://render.com/docs/blueprint-spec ، https://render.com/docs/health-checks ، https://render.com/docs/websocket ، https://supabase.com/docs/guides/auth/auth-mfa/totp
