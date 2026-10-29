import csv,json,html,zipfile
from pathlib import Path
from collections import Counter
out=Path('outputs/Calibration30_Review')
summary=json.loads((out/'Review_Summary.json').read_text(encoding='utf-8'))
changes=json.loads((out/'Change_Log.json').read_text(encoding='utf-8'))
notes={
'13401':'تغيير تشغيل الـpipeline إلى غير مذكور وفق تعريف execute؛ الشبكة غير مؤكدة؛ إضافة قراءة الحالة بواسطة أداة أخرى.',
'18830':'الاعتماد على datasets مع قبول مدخلات مجلوبة مسبقًا لا يحسم جلب الأداة؛ قراءة غير مؤكدة. فصل بحث screen عن الأداة الحالية.',
'25575':'الإبقاء على قراءة دليل المنتجات؛ لا تعديل مقترح.',
'74402':'الإبقاء على تعديل التقويم وإضافة المصادر وإزالتها؛ إسناد عرض المعرّفات إلى list_calendars.',
'39392':'الإبقاء على قراءة تاريخ الأوامر؛ أسماء الحالات BUY وCANCELED لا تعني شراءً أو حذفًا تنفذه الأداة.',
'21540':'البث اتصال وإرسال معاملة، وليس تشغيل كود؛ لا ندّعي تأكيد المعاملة على السلسلة. الفاعل المسؤول عن الاسترداد غير محدد؛ فصل أفعال المسار اليدوي.',
'10422':'الإبقاء على إضافة المحتوى وحفظ المسودة. أوامر عدم استدعاء publish/unpublish تعليمات تنسيق، وليست نفيًا عالميًا لأفعال الأداة.',
'12866':'إكمال نوع نفي الكتابة وإضافة نفي حذف سجلات الشركة ضمن النطاق نفسه.',
'8566':'تغيير القراءة إلى غير مذكور؛ الحساب والتحديث الأسبوعي وحدهما لا يثبتان جلب البيانات.',
'12702':'إضافة فحص الكود كقراءة؛ الاحتفاظ بالتشغيل المثبت؛ لا نفترض أن التحصيل المالي إجراء مستقل لمقدم الخدمة.',
'60988':'فحص الكود والإعدادات المقدمة قراءة واضحة؛ قبول المدخلات من المستدعي لا يجعل هذا الفحص غامضًا.',
'39151':'إكمال نوع نفي الكتابة الشرطي؛ حذف حقل هو فعل الأداة، ومسح الصف بالكامل يخص forget_credentials.',
'55458':'الإبقاء على قراءة قائمة kata؛ اسم Codewars وحده لا يثبت الشبكة.',
'26770':'الإبقاء على استرجاع الأنماط؛ فصل متابعة get_requirement. مثال agent يشغل shell لا يثبت تشغيل الأداة الحالية.',
'36678':'الإبقاء على قراءة الحالة. عدم إتاحة النسخ القديمة في هذا endpoint لا يثبت حذفها.',
'54045':'الإبقاء على جلب الصفحة والشبكة المفتوحة؛ أي URL صريح، فلا نفترض قيودًا مخفية. إرجاع النص لا يثبت حفظ ملف.',
'25993':'إضافة تعديل صلاحية المفتاح؛ اعتبار الحذف غير مؤكد عند revocation بدل تأكيد إزالة السجل.',
'56462':'الكتابة مثبتة لكن إضافة المفتاح مقابل استبداله غير محسومة؛ فصل recall وforget. مدة الاحتفاظ وحدها لا تثبت حذفًا ينفذه save.',
'52440':'مقارنة البنود وفحصها قراءة حتى لو قدمها المستدعي؛ لا يلزم افتراض تنزيل خارجي.',
'36107':'الإبقاء على عدم ذكر الأنواع الخمسة؛ تقدير تكلفة pentest لا يثبت تنفيذ pentest أو تشغيل كود.',
'69446':'الإبقاء على القراءة ونفي الكتابة والحذف؛ API GET ومسار نسبي يجعلان الشبكة غير مؤكدة، والوجهة غير محددة.',
'69614':'تعديل البيانات مثبت؛ صيغة API/PATCH تحدد عملية ووجهة مسماة لكن النقل الشبكي غير صريح وفق العتبة المحافظة المقترحة.',
'35417':'تكوين تطبيق من API surfaces لا يحسم مَن يجلب البيانات؛ قراءة وشبكة غير مؤكدتين. الاحتفاظ بنفي جلب الروابط العشوائية؛ approved surfaces تحدد مجموعة مغلقة.',
'60950':'الإبقاء على عرض الحساب ونفي الكتابة والحذف؛ إكمال حقل mode للنفي.',
'71489':'التسجيل كتابة واضحة؛ المراقبة اللاحقة وفاعلها غير محسومين. لا نفترض provider أو وجهة يحددها المستدعي من كلمة custom فقط.',
'2573':'التحقق من حقول manifest فحص واضح. إصلاح اقتباس نفي قراءة الأسرار ليشمل أداة النفي نفسها.',
'31007':'الإبقاء على قراءة inventory ونفي فحص geodatabase؛ رابط التنزيل المعاد ليس تنزيلًا بواسطة الأداة.',
'59913':'الإبقاء على البحث داخل نص مقدم؛ تحسين اقتباس الدليل. جلب النص عبر gateway يخص أداة أخرى.',
'9322':'التشغيل مثبت؛ البيئة الدائمة لا تحسم إنشاءها مقابل إرجاع بيئة موجودة. scraping إشارة غير محسومة للشبكة، والوجهة غير محددة.',
'42102':'الإبقاء على تعديل التصنيف وإنشاء قاعدة مستقبلية كجزء من العملية؛ المسار النسبي PATCH وحده لا يثبت نقلًا شبكيًا.'}
original=list(csv.DictReader((out/'Menna_Original_Unchanged.csv').open(encoding='utf-8-sig',newline='')))
ids=list(dict.fromkeys(r['tool_id'] for r in original))
tr=''.join('<tr><td dir="ltr">'+html.escape(t)+'</td><td>'+notes[t.split(':')[1]]+'</td></tr>' for t in ids)
page='''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>مراجعة تصنيف الثلاثين أداة</title><style>body{font:17px/1.9 Segoe UI,Arial;max-width:1100px;margin:35px auto;padding:0 20px;color:#142638}h1,h2{color:#125e73}table{border-collapse:collapse;width:100%}td,th{border:1px solid #cedae1;padding:12px;vertical-align:top}th{background:#e7f1f5}code{direction:ltr;unicode-bidi:isolate;background:#eef2f5;padding:2px 5px}li{margin:8px 0}.note{padding:18px;background:#fff5d9}a{color:#125e73}</style>
<h1>مراجعة تصنيف الثلاثين أداة</h1><p>هذه مراجعة بمساعدة نموذج، تضم تعديلات مقترحة وليست تحكيمًا بشريًا نهائيًا أو قياسًا للدقة. احتُفظ بالملف الأصلي دون تغيير حتى يمكن الرجوع إليه ومقارنته بملف تسنيم المستقل.</p>
<p class="note">راجعت النسخة المحلية الموجودة في مجلد العمل. اسمها وحجمها يطابقان الملف المرفوع، لكن تعذّر تنزيل المرفوع للتحقق من التطابق الحرفي. الحجم: 106130 بايت. إذا كانت النسخة المحلية مختلفة عن آخر تعديلاتك، يلزم تطبيق المراجعة على النسخة الصحيحة.</p>
<h2>النتيجة</h2><p>الأصل: 30 أداة و158 صفًا. اقترحت تعديل 30 صفًا موجودًا وإضافة 15 ادعاءً؛ ستة منها تحل محل صفوف not_stated، لذلك النسخة المقترحة تضم 167 صفًا. التغييرات تخص 23 أداة، وتشمل إصلاح حقول واقتباسات وإضافة أفعال تخص أدوات أخرى؛ هذا ليس عدد الأدوات المصنفة خطأ.</p>
<p>كل اقتباسات الملف الأصلي موجودة حرفيًا في الوصف. هذا فحص نصي، ولا يضمن أن معنى الاقتباس يدعم التصنيف. نجحت فحوص الحقول المطلوبة والأدلة في النسخة المقترحة.</p>
<h2>الملفات</h2><ul>
<li><code>Menna_Original_Unchanged.csv</code>: نسخة الأصل كما هي.</li>
<li><code>Menna_Reviewed_Proposals.csv</code>: التصنيفات المقترحة، مع الحالات غير المحسومة معلّمة للمراجعة.</li>
<li><code>Change_Log.csv</code>: السبب والقيم قبل وبعد. رقم السجل يحسب الرأس رقم 1؛ ليس رقم السطر الفيزيائي لأن الأوصاف تتضمن أسطرًا داخلية.</li>
<li><code>Guide_Addendum_Proposed.txt</code>: توضيحات القواعد المقترحة قبل التثبيت.</li></ul>
<h2>أهم القرارات المطلوب تثبيتها</h2><ol>
<li>قراءة وفحص نص مقدم من المستدعي يمكن أن يكون read. الحساب من مدخلات فقط لا يُصنّف تلقائيًا كقراءة؛ ننظر إلى العملية الموصوفة.</li>
<li>حداثة البيانات وحدها لا تثبت الجلب. غموض القراءة يحتاج علاقة نصية بجلب أو فحص أو مصدر بيانات، وليس مجرد اسم score أو فترة تحديث.</li>
<li>API quota مرتبط بعملية محددة، أو method/path بلا تواصل صريح: الشبكة uncertain وفق العتبة المحافظة المقترحة. اسم الخدمة يحدد الوجهة، ولا يحسم القدرة.</li>
<li>تعطيل أو سحب صلاحية مفتاح هو تعديل لحالته. لا نؤكد حذف السجل؛ uncertain للحذف اقتراح يحتاج حسم معنى الإزالة المنطقية في الدليل.</li>
<li>الفعل الذي توفره العملية يظل tool effect ولو نفّذته خدمة خارجية. التنظيف المستقل لدورة الحياة فقط يُنسب إلى provider عند وجود دليل واضح. الفاعل غير المذكور يبقى unknown.</li>
<li>وجود multiple claims للفعل نفسه أو أفعال other_tool لا يزيد أفعال الأداة الحالية تلقائيًا. قارني التصنيفات حسب الفاعل والنطاق والشرط.</li></ol>
<h2>ملاحظات الأدوات الثلاثين</h2><table><thead><tr><th>الأداة</th><th>نتيجة المراجعة</th></tr></thead><tbody>'''+tr+'''</tbody></table>
<h2>قبل مقارنة ملف تسنيم</h2><p>احتفظي بهذه المقترحات للمناقشة بعد أن تنتهي تسنيم من تصنيفها المستقل. نقارن نسختيكما الأصليتين أولًا، ثم نناقش أسباب الاختلاف ونحفظ القرارات النهائية. لا نحسب اتفاق البشر باستخدام نسخة عدّلها الموديل بدل نسختك الأصلية.</p>
<p>لا تُعد الحالات غير المحسومة أخطاء مثبتة. التعديلات هنا مقترحات وفق الدليل الحالي وتوضيحاته، ولا نستخدمها مرجعًا مستقلًا لتقييم الموديل نفسه.</p></html>'''
(out/'Review_AR.html').write_text(page,encoding='utf-8')
(out/'Guide_Addendum_Proposed.txt').write_text('''PROPOSED CALIBRATION ADDENDUM - NOT FROZEN
1. Keep tool operation effects distinct from autonomous provider lifecycle and other-tool advice. Backend service involvement alone does not establish provider lifecycle. Unknown attribution => actor unknown and review.
2. Network capability and destination are separate. Operation-linked quota supports uncertain network. Method/relative-route syntax without explicit communication supports uncertain network. A named service identifies a possible target, not transport proof. No hypothetical hidden allowlists.
3. Freshness, retrieval/inspection, and computation are distinct. Periodic score updates alone => no read claim. A concrete unresolved acquisition relationship may support uncertain read. Inspecting/searching supplied existing material can affirm read. Generic calculation does not automatically affirm read.
4. Generic pipeline triggering and transaction broadcasting do not affirm execute unless code, scripts, programs or commands are actually described. Submission does not assert ledger confirmation.
5. Revocation explicitly changes credential validity; represent modifying write. Deletion remains uncertain until logical-removal versus status-change convention is adjudicated.
6. Every write claim, including denials, has a mode; use unknown where the text does not resolve it. Network domain unspecified => review. Conditions alone do not create uncertainty.
7. A negation evidence span must include the negation operator, not just a coordinated positive fragment.
8. Returns a new text/chart blob does not automatically mean persistent write. Provisioning versus returning an existing workspace may remain unresolved.
9. Record explicit other-tool actions separately with their actor. Do not extract illustrative examples or instructions to invoke tools as capabilities of the current tool. This review records named actions; it does not exhaustively label every workflow prohibition or contextual example.
10. Preserve original human labels. AI-reviewed proposals are calibration material, not independent human ground truth. Await Tasneem independent file before human agreement/adjudication.
''',encoding='utf-8')
with (out/'Tool_Audit30.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.writer(f);w.writerow(['tool_id','review_note_ar'])
 for tid in ids:w.writerow([tid,notes[tid.split(':')[1]]])
with zipfile.ZipFile(out/'Calibration30_Review_Package.zip','w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(out.iterdir()):
  if p.suffix!='.zip':z.write(p,p.name)
print('Review package created; 30 tool audit entries; original preserved.')
