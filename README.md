# سامانه استخراج، اعتبارسنجی و تجمیع نرخ ارز (Currency Scraping Pipeline)

این پروژه یک پایپ‌لاین خودکار برای استخراج نرخ ارز از منابع مختلف ایرانی و بین‌المللی (Alanchand، TGJU، Bonbast، Navasan)، اعتبارسنجی آماری داده‌ها، محاسبه میزان اطمینان (Confidence Engine)، محاسبه تغییرات روزانه و ثبت اتمیک در دیتابیس PostgreSQL است.

این سرویس کاملاً مطابق با استاندارد **`DOCKER_DEPLOYMENT_STANDARDS-V1.0.0`** داکرایز شده و آماده استقرار روی پلتفرم‌های ابری (از جمله Render) می‌باشد.

---

## ۱. پیش‌نیازها

- [Docker](https://docs.docker.com/get-docker/) نسخه 20 به بالا
- دیتابیس PostgreSQL (یا سرویس Supabase) دارای جداول مربوطه
- فایل تنظیمات متغیرهای محیطی (`.env`)

---

## ۲. متغیرهای محیطی (Environment Variables)

برای راه‌اندازی پروژه، ابتدا فایل نمونه `.env.example` را به `.env` کپی کرده و اطلاعات اتصال را تکمیل کنید:

```bash
cp .env.example .env
```

| نام متغیر | الزامی؟ | پیش‌فرض | توضیحات |
| :--- | :---: | :---: | :--- |
| `DATABASE_URL` | **بله** | - | رشته اتصال کامل به دیتابیس PostgreSQL (شامل یوزر، پسورد، هاست و پورت) |
| `PORT` | خیر | `10000` | پورتی که وب‌سرور روی آن گوش می‌دهد (مطابق استاندارد Render: 10000) |
| `PIPELINE_INTERVAL_SECONDS` | خیر | `60` | فاصله زمانی بین هر دور اجرای پایپ‌لاین به ثانیه |
| `CHROMEDRIVER_PATH` | خیر | `/usr/bin/chromedriver` | مسیر باینری ChromeDriver در کانتینر (به صورت خودکار در داکر ست شده است) |
| `CHROME_BIN` | خیر | `/usr/bin/chromium` | مسیر باینری مرورگر Chromium (به صورت خودکار در داکر ست شده است) |

> ⚠️ **نکته امنیتی مهم:** هیچ‌گاه فایل `.env` یا اطلاعات محرمانه دیتابیس را در ریپازیتوری کامیت نکنید.

---

## ۳. اجرای پروژه با Docker (تست الزامی قبل از PR)

مطابق استاندارد استقرار، هر سه مرحله زیر باید قبل از ساخت Pull Request با موفقیت انجام شوند:

### مرحله ۱: ساخت ایمیج Docker
از ریشه پروژه دستور زیر را اجرا کنید:

```bash
docker build -t app .
```

### مرحله ۲: اجرای کانتینر
پس از تکمیل مقادیر در فایل `.env`، کانتینر را اجرا نمایید:

```bash
docker run --rm -p 10000:10000 --env-file .env -e PORT=10000 app
```

### مرحله ۳: بررسی سلامت سرویس (Health Check)
در یک ترمینال دیگر، اندپوینت سلامت برنامه را بررسی کنید:

```bash
curl http://localhost:10000/health
```

نمونه خروجی استاندارد HTTP 200:

```json
{
  "status": "healthy",
  "service": "currency-pipeline",
  "uptime_seconds": 15.2,
  "timestamp": "2026-10-20T12:00:00Z",
  "database": {
    "configured": true
  },
  "scheduler": {
    "status": "running",
    "interval_seconds": 60,
    "iteration": 1,
    "is_running_pipeline": false,
    "last_run": {
      "started_at": "2026-10-20T12:00:01Z",
      "completed_at": "2026-10-20T12:00:18Z",
      "duration_seconds": 17.3,
      "snapshot_id": 1284,
      "status": "complete",
      "published_rates": 28,
      "error": null
    }
  }
}
```

---

## ۴. اجرای تست‌های نرم‌افزاری

برای اجرای تست‌های واحد و یکپارچگی پروژه:

```bash
python -m pytest
```

یا اجرای تست اختصاصی وب‌سرور و Health Check:

```bash
python -m unittest tests/test_server.py
```

---

## ۵. راهنمای استقرار در Render (Render Deployment)

مسئول استقرار برای راه‌اندازی این سرویس در Render، یک **Web Service** با مشخصات ثابت زیر ایجاد می‌کند:

- **Language / Environment:** `Docker`
- **Region:** `Frankfurt`
- **Branch:** `develop`
- **Root Directory:** *(خالی)*
- **Dockerfile Path:** `./Dockerfile`
- **Docker Build Context:** `.`
- **Instance Type:** `Free`
- **Health Check Path:** `/health`
- **Auto Deploy:** فعال

### ثبت متغیرهای محیطی در Render Dashboard:
در بخش **Environment Variables** سرویس در Render:
- `DATABASE_URL`: رشته اتصال دیتابیس پروداکشن
- `PORT`: `10000`
- `PIPELINE_INTERVAL_SECONDS`: `60` (یا بازه دلخواه شما)
