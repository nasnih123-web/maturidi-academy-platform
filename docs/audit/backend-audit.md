# ممیزی بک‌اند — تلگرام، ورکر رسانه/زیرنویس، و بازبینی read-only پرداخت/اهداء

- **تاریخ:** ۲۰۲۶-11-26
- **شاخه:** `feat/backend-audit` (روی `origin/main` — commit `2d9599b`)
- **بررسی‌کننده:** ایجنت بک‌اند/Infra
- **دامنه:** `apps/api/app/modules/telegram/*`، `apps/api/app/worker.py`،
  `apps/api/app/modules/videos/tasks.py`، `apps/api/app/modules/finance/*`
  (read-only)، `apps/api/start.sh`، `.github/workflows/ci.yml`، و نتایج اجرای
  کامل تست محلی.
- **روش:** خواندنی سطر‌به‌سطرِ کد (بدون اجرای کد عملیاتی)، راستی‌آزمایی
  رفتارها روی محلی (PostgreSQL واقعی + SQLite) فقط برای بخش مایگریشن
  (مستقل از این ممیزی)، و اجرای کامل سوئیت تست روی ویندوز.

---

## ۰. نتیجهٔ کلی

کد بک‌اند از نظر طراحی و انضباط (idempotency، مجوز، audit، جداکننده
secret) در سطح بالایی است؛ تقریباً همهٔ یافته‌ها از جنس «کمبودهای
عملیاتی/مقاومتی» (operational hardening) هستند، نه حفرهٔ امنیتی
محتملِ فعال. مهم‌ترین موارد پیش‌از-راه‌اندازی:

| # | یافته | شدت |
|---|--------|------|
| F1 | هیچ rate-limit روی `/finance/donate` و `/finance/donate/manual` نیست (هر `/donate` یک تراکنش واقعی درگاه می‌سازد) | متوسط |
| S1 | `start.sh`: مایگریشن شکست‌خورده **fail-open** است — uvicorn روی اسکیمای قدیمی بالا می‌آید | متوسط |
| S2 | حلقهٔ ری‌استارت ورکر media بدون backoff (crash-loop هر ۵ ثانیه) | پایین |
| T1 | گیت توزیع تلگرام `_telegram_allowed` **fail-open** است | پایین (مستند) |
| T2 | انتشارِ شکست‌خوردهٔ تلگرام retry خودکار ندارد (فقط دستی) | پایین |
| F2 | `IdpayGateway.verify_payment` مبلغ پاسخ درگاه را با مبلغ انتظار مقایسه نمی‌کند | پایین (defense-in-depth) |
| F3 | اهدای مکرر (`POST /finance/recurring`) ثبت می‌شود ولی جاب شارژ ندارد (فاز ۱۶) | پایین (عملیاتی) |
| C1 | CI اسکن secret ندارد (gitleaks) | متوسط (پیش‌از-launch) |
| C2 | اجرای Dependabot روی `main` ناکام مانده (run 45695196882 — bump github_actions) | پایین |
| D1 | محیط توسعهٔ ویندوز: فونت/ابزارهای رسانه (رفع‌شده در `feat/backend-testenv`) | پایین (رفع‌شده) |

جزئیات هر بخش ادامهٔ این سند است.

---

## ۱. ماژول تلگرام (`modules/telegram/`)

### ۱.۱ معماری (تأییدشده)

- **انتزاع Telethon** (`telethon_client.py`): قرارداد `MtprotoClient` +
  factory تزریق‌شونده؛ تست‌ها با fake client بدون شبکه. خطاهای MTProto به
  استثناهای دامنه‌ای ترجمه می‌شوند (`FloodWait` با `retry_after`،
  `CodeExpired`، `SessionPasswordNeeded`).
- **اتصال حساب از CRM** (`connect_service.py`): دو مرحله
  `request_code` → `confirm_code`. `phone_code_hash` و **نشست پیش‌ازورود**
  (به‌خوبی: ساخت کلاینت تازه در قدم دوم کد را در سمت تلگرام منقضی می‌کرد)
  در `platform_settings` با TTL ۱۰ دقیقه می‌مانند؛ `StringSession` نهایی
  با کلید env رمزنگاری می‌شود (§۳).
- **بات** (`bot_service.py`): توکن فقط از `telegram.bot_token` (secret
  رمزنگاری‌شده)؛ بدون توکن/غیرفعال → graceful degradation (None/False).
  یافتهٔ امنیتی فاز ۱۷ (SEC-17-05) اعمال شده: title/excerpt ورودی کاربر
  قبل از ارسال با `parse_mode=HTML` escape می‌شوند.
- **درون‌ریزی** (`import_service.py`): جاب ARQ صف `telegram`؛
  flood-wait با backoff (سقف ۳۰۰ ثانیه، ۳ تلاش)؛ هر فایل از فیلتر امنیتی
  فاز ۹ (`validate_upload_content` — پسوند + magic-byte + سقف حجم) عبور
  می‌کند؛ ثبت با `source_type="telegram_import"` و
  `workflow_status=in_review`؛ **هرگز auto-publish/auto-repost** (چک صریح
  `source_ref.origin == "telegram"` در distribute).
- **توزیع** (`distribute_service.py`): سیاست به‌ازای `content_type`
  (`never|manual_approval|auto_publish|scheduled`، پیش‌فرض `never`)؛
  idempotency_key یکتا `{content_type}:{content_id}:{target}`؛
  auto-publish فقط با policy صریح؛ گیت فاز ۱۴ (ممنوعیت توزیع) در **زمان
  سرو** چک می‌شود (حتی برای رکورد publish ساخته‌شده).
- **دکمه‌های inline بازبینی فتوا**: nonce یک‌بارمصرف، **HMAC-signed**
  (با `encryption_key`)، بایند به `(content, op, actor)`، TTL ۲۴ ساعت،
  وبهوک بات با `X-Telegram-Bot-Api-Secret-Token` احراز می‌شود (بدون secret
  → ۴۰۱ — fail-closed)؛ گذار از **مسیر مجوزدار واقعی**
  (`submissions_service.transition` با `is_approver` روی actor) اجرا
  می‌شود — یعنی دکمهٔ بات مجوز را دور نمی‌زند.

### ۱.۲ یافته‌ها

- **T1 — گیت توزیع fail-open است** (پایین، تصمیم آگاهانه):
  `distribute_service._telegram_allowed` (خط ~۳۰۳) هر استثنایی را می‌بلعد
  و `True` برمی‌گرداند («خطای گیت هرگز انتشار را نمی‌شکند»). اگر
  `content_center_service` خطا دهد (مثلاً خطای DB موقت)، محتوای **ممنوع**
  منتشر می‌شود. پیشنهاد: fail-closed (skip + audit) یا حداقل هشدار بلند
  (metric/alert) روی این except.
- **T2 — بدون retry خودکار برای انتشار شکست‌خورده** (پایین):
  `send_pending` وقتی ارسال بات ناکام باشد رکورد را `failed` می‌کند و
  `retry_count` را می‌شمارد، ولی نه در ARQ (جاب استثنا نمی‌دهد) و نه در
  خود رکورد retry خودکار اتفاق می‌افتد — فقط `retry_publish` دستی ادمین.
  برای خطای موقت شبکه، محتوایی که قرار بوده منتشر شود تا مداخلهٔ انسانی
  `failed` می‌ماند. پیشنهاد: retry محدود با backoff در خود جاب ARQ
  (مثلاً ۳ تلاش) و بعد `failed`.
- **T3 — ری‌تِرِ import در flood-wait از سرِ لیست می‌آید** (پایین،
  کارایی): `_iter_messages_with_backoff` در هر `FloodWait` کل تکرار را از
  اول شروع می‌کند (پیام‌های قبلی با `seen` و `_already_imported`
  دوباره ثبت نمی‌شوند — صحت سالم است، ولی برای import بلند و تلگرام
  پرفlood-wait، کار اضافی می‌شود و شمارندهٔ ۳ تلاش کلِ job را می‌سوزاند).
- **T4 — ارباب‌روندهٔ سیستمی auto-publish** (اطلاعاتی): `_system_actor`
  قدیمی‌ترین super_admin فعال را به‌عنوان actor انتشار خودکار انتخاب
  می‌کند؛ audit آن انتشار به نام یک کاربر واقعی ثبت می‌شود. قابل فهم
  (نیاز به یک actor معتبر برای مجوزهاست) ولی `actor_type` را می‌شد
  «system» کرد و attribution را صریح‌تر ساخت.
- **T5 — pending telethon session پاک نمی‌شود** (پایین، بهداشت): اگر
  ادمین `request_code` بزند و ادامه ندهد، `telegram.pending_session`
  (یک StringSession واقعیِ پیش‌ازورود) تا ابد در settings می‌ماند — TTL
  فقط در لحظهٔ چک کار می‌کند و هیچ reaperی ردیف را حذف نمی‌کند.
- **T6 — rate-limit روی `/connect/request-code`** (پایین، اختیاری):
  endpoint ادمین است و هر فراخوان یک کد واقعی تلگرام به شمارهٔ دلخواه می‌فرستد؛
  کنترل flood سمت تلگرام محدودکننده است ولی یک سقف کوچک (مثلاً
  ۱۰/ساعت/ادمین) بی‌ضرر است.
- **T7 — ارسال bot در هر فراخوان Bot تازه می‌سازد** (اطلاعاتی، کارایی):
  `bot_service` در هر `send_message` یک `Bot(token)` جدید می‌سازد. بدون
  مشکل درستکاری (بدون state مشترک) ولی یک HTTP client جدید در هر فراخوان
  است.

---

## ۲. ورکر رسانه و خط لولهٔ زیرنویس

### ۲.۱ طراحی (تأییدشده)

- `app/worker.py` نقطهٔ ورود ARQ است؛ **ورکر media گیت `on_startup` دارد**
  (`assert_media_tools_ready`) — اگر ffmpeg/tesseract(+fas/ara/eng)/
  pdftoppm/faster-whisper نباشند، ورکر media اصلاً بالا نمی‌آید
  (fail-loud؛ صف‌های دیگر این گیت را ندارند).
- `app/modules/videos/tasks.py`: خط لولهٔ زیرنویس با **طراحی
  خطای-صادقانه**: هر زبان جداگانه وضعیت می‌گیرد؛ هر شکست با دلیل
  نام‌دار (`download_failed:`، `read_failed:`، `translation_failed:`،
  `translation_provider_not_configured`) به `failed` می‌رود — نه سکوت و نه
  fallback کاذب. `_fail_all` همهٔ ردیف‌های وابسته را یکجا failed می‌کند.
- دانلود مدیا خارجی (`_download_external_media`) خطا را به `failed`
  صادقانه تبدیل می‌کند.

### ۲.۲ یافته‌ها (`start.sh` + استقرار)

- **S1 — مایگریشن fail-open** (متوسط): خط ۶
  `alembic upgrade head || echo "...continuing to uvicorn"`. اگر مایگریشن
  شکست بخورد (تعارض ردیف، schema drift، خطای شبکهٔ لحظه‌ای)، API روی
  **اسکیمای قدیمی** بالا می‌آید: کوئری‌های جدید ۵۰۰ می‌دهند و — بدتر از
  نداشتن سرویس — رفتار ناسازگار (نیمه-نویسی‌ها با کد جدید روی اسکیما
  قدیمی) ممکن است. برای سرویسی که پول/اهدا ثبت می‌کند، پیشنهاد:
  **fail-closed** (`exit 1`؛ کانتینر بالا نمی‌آید و orchestrate retry می‌کند)
  یا حداقل health-check که تا `alembic current == head`، `/health` را
  `degraded` بدهد. (در compose.prod این رفتار فرق دارد: init-job جدا
  مایگریشن می‌کند — این یافته فقط برای مسیر Railway است.)
- **S2 — ری‌استارت ورکر media بدون backoff** (پایین): حلقهٔ
  `while true; do python -m app.worker media; sleep 5; done`. اگر ورکر
  در استارتاپ مرده باشد (مثلاً ابزار رسانه از ایمیج حذف شده)، crash-loop
  هر ۵ ثانیه + اسپم لاگ می‌دهد. پیشنهاد: backoff نمایی با سقف
  (مثلاً ۵s → ۱۰s → … → ۵min) و log یک‌بار برای هر الگوی مرگ.
- **S3 — ورکر media داخل کانتینر API** (مستند، بدون اقدام): به‌خاطر سقف
  ۱GB پلن trial؛ در compose.prod سرویس جداست. مستند در خود start.sh —
  وقتی پلن ارتقا خورد، جابجایی به سرویس جدا + حذف این بلوک.
- **S4 — `timeout -k 10 180` برای seed** (اطلاعاتی): seed روی دیتابیس
  پرشده باید idempotent باشد تا ۱۸۰ ثانیه کافی بماند؛ الان آینه می‌شود —
  با رشد seed، مانیتور زمان اجرای آن لازم است.

---

## ۳. بازبینی read-only پرداخت/اهداء (`modules/finance/`)

### ۳.۱ جریان و لایه‌های idempotency (تأییدشده)

```
POST /donate (Idempotency-Key اجباری)
   → PaymentIntent(pending)            [dedupe کلید: یکتایی idempotency_key + مسابقه IntegrityError]
   → درگاه: request_payment            [ZarinPal v4 / IDPay v1.1 — کلید فقط از platform_settings]
بازگشت:
   GET /callback?Authority=&Status=     [redirect زرین‌پال]
   POST /callback/idpay                 [فرم POST آیدی‌پی]
   POST /webhook/{gateway}              [dedupe payload_hash + احراز]
   → verify_payment سمت‌سرور            [مبلغ/authority در برابر رکورد درگاه]
   → _finalize_success (تک‌نقطهٔ مشترک):
        Donation + LedgerEntry + کمپین + رویداد (idempotency_key مشتق) + audit
        [re-entrant: intent.status + Donation.gateway_reference یکتا]
حمایت دستی (card/crypto/paypal):
   POST /donate/manual → PaymentIntent(pending) + ManualDonationProof
   → تأیید ادمین (finance.manage) → _finalize_success (با تبدیل FX)
```

نکات تأییدشده:

- **تک‌نقطهٔ مشترک** `_finalize_success` برای همهٔ مسیرهای موفقیت
  (callback، idpay، webhook، تأیید دستی) — re-entrant با دو لایهٔ دفاع
  (وضعیت intent + یکتایی `Donation.gateway_reference`).
- **احراز اصالت فقط سمت‌سرور**: فیلدهای فرم/وبهوک هرگز مبنای ثبت نیستند؛
  زرین‌پال و آیدی‌پی امضا نمی‌فرستند → verify روی authority (مبلغ هم
  ارسال می‌شود: `verify.json` زرین‌پال amount را چک می‌کند). وبهوک‌های
  درگاه‌های دیگر HMAC-SHA256 روی بدنهٔ خام با `payment.webhook_secret`
  (`hmac.compare_digest` — ثابت-زمان)؛ بدون secret → رد (fail-closed).
- **dedupe وبهوک**: `payload_hash` یکتا با ردیف `processed/duplicate`؛
  ردیف‌های `rejected` نمک‌دار هستند تا retry مشروع بعدی گیر نکند.
- **secret**: merchant key فقط از `platform_settings` (رمزنگاری‌شده)؛
  `gateway_statuses` فقط bool برمی‌گرداند؛ `card_pan`/`card_no` درگاه
  ثبت **نمی‌شود**؛ متن رسید/شمارهٔ کارت در audit نمی‌آید (§۱۴).
- **رسید تصویر**: magic-byte sniff (PNG/JPG/WEBP) — به mime کلاینت
  اعتماد نمی‌شود؛ سقف ۵MB با `read_capped_upload`؛ تصویر فقط از مسیر
  ادمینی (finance.manage) سرو می‌شود، نه URL عمومی.
- **سقف‌ها**: `_MAX_DONATE_IRR = 10^11` ریال برای آنلاین/کارت،
  `10^12` واحد برای ارزی؛ `DonateIn`: `amount gt=0`، currency فقط IRR،
  gateway فقط `zarinpal|idpay`.
- **FX** (`fx.py`): نرخ لحظه‌ای از والکس/کوین‌گکو با کش ۵ دقیقه؛ هر خطا
  → `FxUnavailable` → ۵۰۲/۴۲۲ و نرخ **دستی** از ادمین — «نرخ هرگز حدس
  زده یا ساخته نمی‌شود». تبدیل ارزی **پیش از** هر mutation محاسبه می‌شود تا
  رکورد نیمه‌کاره نسازد؛ نرخ و منبعش روی رکورد اثبات می‌ماند.
- **reconcile**: مقایسهٔ نیت‌های موفق داخلی با گزارش درگاه؛ چون هر دو
  درگاه فعلی API گزارش عمومی ندارند، `fetch_report` خطا می‌دهد و
  endpoint **۵۰۳ صادقانه** برمی‌گرداند (نه دادهٔ ساختگی — ADR-0013).
- **حمایت ارزی به کمپین**: معادل ریالی با نرخ لحظه‌ای/دستی به
  `raised_amount` کمپین می‌رود (درخواست مالک) و برای IRR همان مبلغ.
- **لایه‌بندی**: روتر هیچ دسترسی مستقیم به DB ندارد (§۱۵.۶)؛ همهٔ
  mutations audit + ip/ua دارند؛ صفحه‌بندی cursor برای donation/ledger/
  manual-donations.

### ۳.۲ یافته‌ها

- **F1 — بدون rate-limit روی `/donate` و `/donate/manual`** (متوسط):
  الگوی `@rate_limit` در kernel هست و روی auth/admin/hifz اعمال شده، اما
  `/finance/donate` و `/finance/donate/manual` بدون سقف هستند. هر فراخوان
  `/donate` یک **تراکنش واقعی** در درگاه می‌سازد (فراخوان خارجی +
  occupation quota درگاه + هزینهٔ محاسبه‌ای)؛ `Idempotency-Key` کمک نمی‌کند
  چون مهاجم کلید تازه می‌سازد. پیشنهاد: `@rate_limit` IP/کاربرمحور
  (مثلاً ۵/۵ دقیقه anon، ۲۰/۵ دقیقه authenticated) روی هر دو endpoint.
- **F2 — IdPay: amount پاسخ verify چک نمی‌شود** (پایین، defense-in-depth):
  `IdpayGateway.verify_payment` پارامتر `amount` را اصلاً به API نمی‌فرستد
  و `payment.amount` پاسخ را با مقدار انتظار مقایسه نمی‌کند. ریسک عملی
  ناچیز است (tx_id از request خودمان آمده و در رکورد درگاه amount تثبیت
  شده) ولی یک خط مقایسهٔ صریح (و در غیر این‌صورت `GatewayError`)
  بی‌ضرر و استانداردتر است.
- **F3 — اهدای مکرر بدون جاب شارژ** (پایین، عملیاتی):
  `POST /finance/recurring` ردیف `RecurringDonation` با
  `next_charge_at=None` می‌سازد («شارژ دوره‌ای با صف ARQ فاز ۱۶
  زمان‌بندی می‌شود») — ولی در `main` هیچ جابی `next_charge_at` را لمس
  نمی‌کند. تا پیاده‌سازی، این endpoint ردیف‌های مرده می‌سازد. پیشنهاد:
  یا جاب فاز ۱۶ قبل از launch، یا مخفی‌کردن endpoint تا آن‌زمان.
- **F4 — intentهای pending بدون TTL** (پایین، عملیاتی): نیت pending
  تا ابد pending می‌ماند (callback دیرهنگام هم می‌آید و verify می‌کند).
  authority زرین‌پال خودش منقضی می‌شود، ولی ردیف‌های pending انباشته
  می‌شوند و در `reconcile` می‌آیند. پیشنهاد: reaper ساده (مثلاً pending
  بیش از ۷۲ ساعت → `expired`) یا حداقل فیلتر/مرور در CRM.
- **F5 — reconcile فعلاً no-op** (اطلاعاتی): برای هر دو درگاه فعلی ۵۰۳
  صادقانه. رفتار درست است؛ فقط انتظار عملیاتی باشد که تا وقتی درگاه
  report API نداشته باشد، این endpoint داده نمی‌دهد.
- **F6 — افشای عمومی شمارهٔ کارت** (اطلاعاتی، طراحی آگاهانه):
  `donation-methods` عمومی `card_number`/`card_holder` را برمی‌گرداند
  (مخاطب باید برای کارت‌به‌کارت شماره را ببیند). ریسک: فیشینگ معکوس —
  مهاجم با دیدن شمارهٔ کارت عمومی می‌تواند ادعای مالکیت بکند؛ چون برای
  اهدا یک‌طرفه ریسک مالی مستقیم ندارد، پذیرفته شد ولی در چک‌لیست
  launch یادآوری می‌شود که توضیح کاربری «فقط به این کارت واریز کنید»
  همراه holder باشد.
- **F7 — مسابقهٔ هم‌زمان روی callback (خارج از webhook)** (اطلاعاتی):
  `handle_webhook` مسابقهٔ IntegrityError را می‌گیرد ولی `handle_callback`
  / `handle_idpay_callback` نمی‌گیرند؛ دو redirect هم‌زمان می‌تواند ۵۰۰
  بدهد (ردیف دوم، ردیف اول را می‌بیند — داده سالم است، ولی پاسخ ۵۰۰
  می‌شود). در عمل با redirect مرورگر نااحتمال است.

### ۳.۳ چک‌لیست راه‌اندازی پرداخت (launch checklist)

**پیکربندی (CRM → platform_settings):**

1. `payment.zarinpal_key` و `payment.idpay_key` (یا هر دو یا یکی) را با
   کلید **production** تنظیم کنید.
2. `payment.zarinpal_sandbox=false` و `payment.idpay_sandbox=false` —
   پیش‌فرض هر دو `true` (sandbox) است؛ فراموش‌کردن این دو، کل پرداخت
   production را به sandbox می‌بازد.
3. `payment.callback_url` = URL عمومی production (مثلاً
   `https://api.matoridi.ir/api/v1/finance/callback`) — بدون آن `/donate`
   با ۵۰۳ `payment_not_configured` می‌سوزد.
4. (درگاه‌های آینده با وبهوک امضادار) `payment.webhook_secret` را
   تنظیم کنید — بدون آن وبهوک رد می‌شود (fail-closed).
5. `payment.zarinpal_sandbox`/`idpay_sandbox` را در داشبورد اتصالات CRM
   (`/admin/finance/gateways`) قبل و بعد از switch راستی‌آزمایی کنید.

**کد/عملیاتی (پیش‌از-launch):**

6. **F1**: rate-limit روی `/donate` و `/donate/manual` (بینگاهی‌ترین
   اقدام؛ الگوی آماده در `app/core/rate_limit.py` هست).
7. **F2**: مقایسهٔ صریح amount در `IdpayGateway.verify_payment`.
8. **F3**: تصمیم دربارهٔ `/finance/recurring` — جاب شارژ (فاز ۱۶) یا
   مخفی‌کردن endpoint.
9. **S1**: تصمیم fail-open/fail-closed مایگریشن در `start.sh`
   (مسیر Railway).
10. **F6**: اطمینان از presence توضیح holder در UI اهدا.
11. **آزمایش end-to-end**: یک پرداخت واقعیِ آزمایشی با مبلغِ
    قراردادشدهٔ تست (مبلغ تست را تغییر ندهید) در production از
    `/donate` تا رسید PDF؛ بعداً با `/admin/finance/reconcile`
    (وقتی report در دسترس شد) و ledger بکشید.
12. **ممنوعیت**: هیچ secret در chat/commit/لاگ — کلیدها فقط از CRM
    (رمزنگاری‌شده).

---

## ۴. یافته‌های عرضی (CI/محیط)

- **C1 — اسکن secret در CI نیست** (متوسط، پیش‌از-launch): CI فعلی
  semgrep (security scan روی کد) + pip-audit (dependency) دارد ولی
  **gitleaks/trufflehog** ندارد. با توجه به اینکه کلید درگاه، JWT secret
  و Telegram session در این repo گردش دارند (و در `.env.prod.example`
  placeholderهایی دیده می‌شود)، یک step gitleaks (روی full history)
  ارزان‌ترین محافظ است. (`.github/` در مالکیت بک‌اند است — قابل
  پیاده‌سازی در شاخهٔ جدا.)
- **C2 — اجرای Dependabot ناکام** (پایین): run `45695196882`
  (bump github_actions روی `main`) fail شده و log آن با timeout TLS
  در دسترس نبود. چون main green است، بلوکنده نیست — ولی قبل از merge
  هر PR جدید، وضعیت workflowها را چک کنید.
- **D1 — محیط توسعهٔ ویندوز** (پایین، **رفع‌شده** در
  `feat/backend-testenv`): سوئیت ۱۵۶۱ تست روی ویندوز به‌خاطر
  (a) Redis محلی واقعی در ۶۳۷۹ (کشش شمارندهٔ rate-limit بین تست‌ها →
  ۱۳۶ ناکامی در پشته)، (b) مسیر `/tmp`، (c) فونت‌های سیستمی Linux
  (certificates.py)، (d) نبود tesseract/pdftoppm/فونت، (e) relay خراب
  WSL برای `bash`، و (f) cp1252 خروجی فارسی، سبز نبود. رفع‌شده:
  override `REDIS_URL` در conftest، `tempfile.gettempdir()`، override
  فونت با env (`MATURIDI_AR_FONT`/`MATURIDI_LATIN_FONT` در
  certificates.py)، stub ویندوزی، `tests/shellutil.usable_bash()`، و
  `encoding="utf-8"` در subprocess. نتیجهٔ محلی:
  **1516 passed / 0 failed / 45 skipped** (skipها = نبود ابزارهای
  لینوکسی در این ماشین، مستند). روی لینوکس/CI همهٔ این تست‌ها مثل قبل
  اجرا می‌شوند.
- **D2 — Node نسخه**: ماشین توسعه Node 26 دارد ولی `.nvmrc` ۲۴ (CI ۲۴
  می‌زند) — فقط یادآوری برای سازگاری محلی.
- **D3 — `alembic check` به CI اضافه شد** (در
  `feat/backend-migrations`): job postgres (PG16 واقعی) و job backend
  (SQLite) هر دو بعد از چرخهٔ migration، `alembic check` می‌زنند —
  نگهبان ردیف ۲۱ DONE_CRITERIA.

---

## ۵. نتیجه‌گیری

- **تلگرام**: طراحی امن و idempotent؛ دو تصمیم آگاهانهٔ fail-open (T1) و
  بدون-retry (T2) برای launch تصمیم می‌خواهند.
- **رسانه/زیرنویس**: fail-loud در گیت استارتاپ و خطای نام‌دار در
  خط‌لوله — مطابق قرارداد؛ مشکلات در لایهٔ استقرار (`start.sh`: S1/S2).
- **پرداخت/اهداء**: از همهٔ ماژول‌ها منضبطتر است؛ قبل از launch فقط
  F1 (rate-limit) و سوت‌های پیکربندی (sandbox flag!، callback_url)
  حیاتی‌اند.
- **CI**: gitleaks (C1) تنها کمبود امنیتی عرضیِ واقعی است.

هیچ‌کدام از یافته‌ها مانع merge نیستند؛ فهرست چک‌لیست ۳.۳ مسیر
launch را مشخص می‌کند.
