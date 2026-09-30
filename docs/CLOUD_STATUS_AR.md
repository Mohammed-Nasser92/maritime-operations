# حالة الربط الحقيقية — تحديث 30 سبتمبر 2026 بتوقيت الرياض

## الهوية والمنطقة

| الحقل | الحالة |
|---|---|
| اسم المؤسسة المختار | Maritime UAV Student Team — فريق الطلاب للطائرات البحرية دون طيار |
| اسم المؤسسة الفعلي حاليًا | Maritime UAV Student Team؛ غيّره المستخدم وتم التحقق من الاسم عبر الخدمة |
| مرجع المؤسسة | jzzygktacczsicobnjnu |
| اسم مشروع Supabase المنشأ | Autonomous Maritime Surveillance UAV — المراقبة البحرية الذاتية بالطائرات دون طيار |
| مرجع المشروع | rxqlccksknrjysluzgkt |
| المنطقة الفعلية | Frankfurt / eu-central-1 |
| الخطة | Free؛ أداة التكلفة أفادت 0 شهريًا عند الإنشاء. لم يُفعّل اشتراك مدفوع |
| الحالة بعد الإنشاء | ACTIVE_HEALTHY |
| رابط API | https://rxqlccksknrjysluzgkt.supabase.co — ليس رابط واجهة الموقع |

لم تظهر منطقة شرق أوسط في [قائمة Supabase الرسمية](https://supabase.com/docs/guides/platform/regions) عند التنفيذ. اختيرت فرانكفورت لأنها متاحة أيضًا ضمن [مناطق Render](https://render.com/docs/regions). ملف render.yaml يحدد frankfurt، لكن خدمة Render نفسها لم تُنشأ.

## ما طُبّق

| المصدر المحلي | اسم المهاجرة المستضافة | إصدار سجل Supabase |
|---|---|---|
| supabase/001_workspace.sql | maritime_workspace | 20260929172534 |
| supabase/002_complete_server.sql | maritime_complete_server | 20260929172553 |
| supabase/003_live_workspace.sql | maritime_live_workspace | 20260929172613 |
| supabase/migrations/20260929173243_maritime_advisor_hardening.sql | maritime_advisor_hardening | 20260929173354 |

الاختلاف بين توقيت الملف الأخير وسجل الخادم ناتج عن إنشاء الملف بالـCLI ثم تطبيقه عبر MCP. لا تعِد تطبيقه أو تشغّل db push دون مواءمة سجل الهجرات أولًا.

أُنشئت جداول profiles وmissions وtracks وevents وdrone_state وaudit_log وcommand_capabilities وcommand_requests وws_tickets وlogin_identities وlogin_attempts وtelemetry_history. RLS مفعّل على الجداول الـ12.

أُنشئ مخزن الصور الخاص event-images. أُضيفت معاملات استقبال الأحداث ومراجعتها، وإعادة الإرسال الآمنة، وحفظ بيانات الدرون وتاريخها، وتذاكر اتصال المتصفح. كانت القاعدة بلا أحداث أو أعضاء عند فحص الإنشاء. أُضيف حساب المدير الأول لاحقًا، كما هو موضح في تحديث الحساب أدناه.

## ملاحظات الفحص المتبقية

بعد نقل مساعدي الصلاحيات إلى maritime_private وتحسين سياستين وإضافة ثمانية فهارس، لم يظهر WARN أو ERROR في مستشاري الأمان والأداء.

- [RLS Enabled No Policy](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy): ثلاث ملاحظات INFO على login_attempts وlogin_identities وws_tickets. هذه جداول خاصة بالخادم عمدًا، وصلاحيات العميل مسحوبة؛ عدم وجود سياسة عميل يمنع الوصول ولا يحتاج سياسة سماح.
- [Unused Index](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index): 12 ملاحظة INFO وقت الفحص. المشروع جديد بلا حمل تشغيل؛ لا تُحذف الفهارس قبل قياس الاستخدام الفعلي.

التفاصيل والحدود في TEST_REPORT.md. فحوص المستشار ليست اختبار اختراق أو ضمانًا لجاهزية كل مسارات التشغيل.

## ما لم يتم بعد

1. اسم المؤسسة تحقق بالفعل، ولا يلزم تغييره.
2. مراجعة إعدادات Auth/TOTP وتعطيل التسجيل العام، وإدخال أسرار الخادم في بيئة التشغيل، وتجربة حساب المدير الذي جرى تجهيزه.
3. المستودع أنشأه المستخدم: https://github.com/Mohammed-Nasser92/maritime-operations . تُنشر فيه ملفات هذه النسخة؛ اكتمال GitHub Actions يتحقق من صفحة Actions ولا يُفترض من وجود YAML.
4. Render مؤجل بطلب المستخدم حتى تجهيز حسابه واختباره؛ الاختبار الأول سيكون على جهازه متصلًا بقاعدة Supabase. لم تُنشأ أي خدمة.
5. ربط Jetson وأجهزة GPS والفيديو وWSS وطابور الانقطاع مؤجل إلى آخر مرحلة بطلب المستخدم.

لا ترسل كلمة مرور أو Secret/API token في المحادثة. تدخل القيم السرية في إعدادات البيئة الخاصة بالخادم مباشرة. الاسم المختار هنا هو اسم مشروع Supabase؛ لم يُغيَّر تصميم الواجهة أو محتواها بهذا التحديث.

## مراجعة HTTP وإعدادات البيئة — 30 سبتمبر

- المشروع ACTIVE_HEALTHY، والمنطقة eu-central-1، واسم المؤسسة مطابق للاسم الذي اختاره المستخدم.
- GET / أعاد 404 مع requested path is invalid: هذا جذر API بلا صفحة موقع.
- GET /auth/v1/settings بالمفتاح العام أعاد 200: خدمة Auth متاحة، Email مفعّل وAnonymous Users معطل.
- disable_signup=false: التسجيل العام لا يزال مفتوحًا. يجب إيقاف Allow new users to sign up في إعدادات Authentication قبل اعتماد التشغيل. لا يمنح التسجيل وحده صلاحية قراءة بيانات المشروع لأن العضوية وAAL2 مطلوبان.
- طلب قراءة events وlogin_identities من دور anon أعاد 401 وpermission denied. لا تُنفذ اقتراح GRANT الموجود في رسالة PostgreSQL؛ المنع مقصود.
- مساعد الصلاحيات القديم عبر REST أعاد 404، بما يطابق نقله إلى مخطط خاص.
- فحوص SQL: 12 جدولًا بـRLS، وصفر Auth users وprofiles وlogin identities وTOTP factors موثقة وصور.
- أُعيد فحص المستشارين: لا WARN/ERROR؛ ملاحظات INFO الموثقة أعلاه باقية.
- حالة TOTP Enrollment/Verification لا يعرضها رد settings المستخدم؛ لم نعتبرها مفعلة دون دليل. راجعها في لوحة Supabase.
- لا تتوفر هنا مفاتيح الخادم السرية؛ لذلك اختبار الدخول الفعلي ورفع صورة/توقيع رابطها عبر HTTP ما زالا متوقفين على تهيئة البيئة وحساب المدير.
- أُصلح استيراد bootstrap_admin وassign_login_id عند تشغيلهما كوحدات Python، وأمر الدليل أصبح run_module. وصل كلاهما إلى أول حقل إدخال بنجاح دون إنشاء حساب، ونجحت 76 حالة pytest بعد التعديل.

الخطوة التالية للمستخدم موضحة في PREVIEW_AND_GITHUB_AR.md. لا يُطلب إرسال أي كلمة مرور أو مفتاح سري.

## تحديث الحساب والمستودع — 30 سبتمبر 2026

أنشأ المستخدم مستودع GitHub العام وأرسل رابطه، وأنشأ مستخدم Auth وأرسل UID. تم التحقق من أن البريد مؤكد والحساب غير مجهول وغير محظور؛ ثم أُضيف profile بدور admin وactive=true وربط login_id بمعرّف المستخدم وبريده الفعلي داخل جدول الخادم الخاص. لم تتغير كلمة المرور، ولم توضع هوية المستخدم أو بريده أو كلمة مروره في المستودع.

اختبار SQL باستخدام دور authenticated وسياق AAL1 لهذا الحساب: has_workspace_access=false وis_workspace_admin=false وصفر ملفات شخصية مرئية. هذا يثبت أن صلاحية المدير لا تتجاوز شرط المصادقة الثنائية؛ ليس اختبار دخول أو TOTP حقيقيًا. اختبار أول دخول وإعداد عامل المصادقة ما زال مطلوبًا من المستخدم على جهازه بعد ضبط البيئة.

GitHub يحفظ المصدر؛ إنشاء المستودع ورفع الكود لا يعني تفعيل GitHub Pages أو Render أو وجود رابط دخول عام. النشر وربط الدرون ما زالا مؤجلين.
