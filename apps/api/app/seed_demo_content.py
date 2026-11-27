"""سید محتوای نمایشی — مقاله/کتابخانه/کمپین (پشت flag، قابل حذف).

تصمیم سرپرست (۱۴۰۵/۰۹/۰۴): محتواِ نمایشی برای تست صفحات وب (فید
مقالات، کتابخانه، صفحهٔ کمک‌مالی) فقط با flag صریح ساخته شود:

- flag: ``DEMO_SEED_ENABLED`` (پیش‌فرض ``false``). env توسعهٔ محلی
  (tools/dev/write_dev_env.py) آن را روشن می‌کند؛ production هرگز
  مقدار نمی‌دهد و حتی اگر مقدار بدهد، گارد production این ماژول
  نادیده‌اش می‌گیرد (``demo_seed_allowed``).
- قابل حذف: همهٔ ردیف‌ها برچسب ثابت دارند (slug مقاله‌ها،
  ``source_type=seed_demo`` آیتم‌های کتابخانه، عنوان مارکر کمپین) و
  ``delete_demo_content`` دقیقاً همین‌ها را می‌پایَد — حتی فایل‌های
  storage هم پاک می‌شوند. کمپینی که نیت/اهدای ارجاع‌شده داشته باشد
  حذف نمی‌شود (FK) و در خلاصه گزارش می‌شود.
- گروه‌ها/پست‌های نمایشی کامیونیتی جدا نیستند: ``seed_social_demo``
  (از app.seed) در اولین اجرا همین کار را می‌کند و این ماژول با آن
  تداخل ندارد.
- هیچ متن فقهی اختراعی: همهٔ متون صریحاً «نمایشی» هستند.
"""
from __future__ import annotations

import io
import logging
import sys
import wave
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage
from app.models.models import (
    Article,
    Donation,
    DonationCampaign,
    LibraryItem,
    PaymentIntent,
)

logger = logging.getLogger("maturidi.seed_demo_content")

# ---------------------------------------------------------------------------
# مارکرها (ثابت — مبنای idempotency و حذف)
# ---------------------------------------------------------------------------

def _L(fa: str, ar: str, en: str) -> dict:
    return {"fa": fa, "ar": ar, "en": en}


# مارک اختصاصی: seed_library.py (فاز ۹) همان «seed_demo» را می‌زند —
# جدا ماندن تا سیدها/حذف‌هایشان تداخل نگیرند.
DEMO_SOURCE_TYPE = "seed_demo_content"
_CAMPAIGN_FA = "کمپین نمایشی (دمو — قابل حذف)"
_CAMPAIGN_TITLE = _L(
    _CAMPAIGN_FA,
    "حملة تجريبية (للعرض فقط)",
    "Demo campaign (demo - safe to delete)",
)
_ARTICLE_SLUGS: tuple[str, ...] = ("demo-article-1", "demo-article-2")
_MEDIA_PREFIX = "demo-content/"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _tiptap(*paragraphs: str) -> dict:
    """اسناد Tiptap JSON حداقلی — همان فرمت ادیتور CRM."""
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]}
            for p in paragraphs
        ],
    }


def demo_seed_allowed(settings) -> bool:
    """flag روشن **و** محیط production نباشد.

    حتی ``DEMO_SEED_ENABLED=true`` در production نادیده گرفته می‌شود —
    محتوای نمایشی هرگز در production ساخته نمی‌شود.
    """
    if not bool(getattr(settings, "demo_seed_enabled", False)):
        return False
    return (getattr(settings, "app_env", "") or "").strip().lower() != "production"


# ---------------------------------------------------------------------------
# تولید فایل‌های واقعیِ سبک (بدون ffmpeg — فقط reportlab/wave/XML)
# ---------------------------------------------------------------------------


def _demo_pdf() -> bytes:
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    c.setFont("Helvetica", 14)
    c.drawString(60, 500, "Maturidi Academy - Demo Booklet")
    c.setFont("Helvetica", 10)
    c.drawString(60, 480, "This is a generated demo file for UI testing.")
    c.drawString(60, 464, "No invented fiqh content inside.")
    c.showPage()
    c.save()
    return buf.getvalue()


def _demo_wav(seconds: int = 3, rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * (rate * seconds))
    return buf.getvalue()


def _demo_mindmap() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<map version="1.0.1">\n'
        b'  <node TEXT="Maturidi Academy (demo)"/>\n'
        b'</map>\n'
    )


_ARTICLE_SPECS: list[dict] = [
    {
        "slug": "demo-article-1",
        "title": _L(
            "مقالهٔ نمایشی ۱ (دمو — قابل حذف)",
            "مقالة تجريبية ١ (للعرض فقط)",
            "Demo article 1 (demo - safe to delete)",
        ),
        "body": _tiptap(
            "این یک مقالهٔ نمایشی است و فقط برای تست صفحات وب ساخته شده؛ محتوای فقهی ندارد.",
            "This is a demo article created only to test the web pages; it contains no fiqh content.",
        ),
    },
    {
        "slug": "demo-article-2",
        "title": _L(
            "مقالهٔ نمایشی ۲ (دمو — قابل حذف)",
            "مقالة تجريبية ٢ (للعرض فقط)",
            "Demo article 2 (demo - safe to delete)",
        ),
        "body": _tiptap(
            "مقالهٔ دوم نمایشی — برای تست فهرست و صفحهٔ مقاله با دادهٔ واقعی.",
            "Second demo article - to test the article list and page with real data.",
        ),
    },
]

_LIBRARY_SPECS: list[dict] = [
    {
        "kind": "pdf",
        "ext": ".pdf",
        "mime": "application/pdf",
        "make": _demo_pdf,
        "title": _L(
            "جزوهٔ نمایشی (دمو — قابل حذف)",
            "كراسة تجريبية (للعرض فقط)",
            "Demo booklet (demo - safe to delete)",
        ),
        "transcript": None,
        "duration": None,
    },
    {
        "kind": "audio",
        "ext": ".wav",
        "mime": "audio/wav",
        "make": _demo_wav,
        "title": _L(
            "صوت نمایشی (دمو — قابل حذف)",
            "صوت تجريبي (للعرض فقط)",
            "Demo audio (demo - safe to delete)",
        ),
        "transcript": "متن نمایشی برای آزمون جست‌وجوی کتابخانه.",
        "duration": 3,
    },
    {
        "kind": "mindmap",
        "ext": ".mm",
        "mime": "application/xml",
        "make": _demo_mindmap,
        "title": _L(
            "نقشهٔ فکری نمایشی (دمو — قابل حذف)",
            "خريطة ذهنية تجريبية (للعرض فقط)",
            "Demo mindmap (demo - safe to delete)",
        ),
        "transcript": None,
        "duration": None,
    },
]


# ---------------------------------------------------------------------------
# ساخت
# ---------------------------------------------------------------------------


async def _seed_articles(db: AsyncSession) -> int:
    created = 0
    for spec in _ARTICLE_SPECS:
        exists = (
            await db.execute(
                select(Article.id).where(Article.slug == spec["slug"]).limit(1)
            )
        ).first()
        if exists:
            continue
        db.add(
            Article(
                title=spec["title"],
                body=spec["body"],
                slug=spec["slug"],
                workflow_status="published",
                published_at=_utcnow(),
                author_name="آکادمی ماتریدی",
            )
        )
        created += 1
    return created


async def _seed_library(db: AsyncSession) -> int:
    storage = get_storage()
    existing = (
        await db.execute(
            select(LibraryItem.kind).where(LibraryItem.source_type == DEMO_SOURCE_TYPE)
        )
    ).scalars().all()
    existing_kinds = set(existing)
    created = 0
    for spec in _LIBRARY_SPECS:
        if spec["kind"] in existing_kinds:
            continue
        data = spec["make"]()
        media_key = f"{_MEDIA_PREFIX}demo-{spec['kind']}{spec['ext']}"
        await storage.put_object(media_key, data, spec["mime"])
        db.add(
            LibraryItem(
                kind=spec["kind"],
                title=spec["title"],
                description=_L("فایل نمایشی برای تست کتابخانه.", "ملف تجريبي.", "Demo file for library UI testing."),
                media_key=media_key,
                topic_tags=["demo", "نمایشی"],
                visibility="public",
                workflow_status="published",
                version=1,
                ai_scopes=[],
                include_in_fatwa_rag=False,
                ai_indexed=False,
                transcript=spec["transcript"],
                transcript_status="done" if spec["transcript"] else "pending",
                ocr_status="pending",
                duration_seconds=spec["duration"],
                file_size_bytes=len(data),
                mime_type=spec["mime"],
                source_type=DEMO_SOURCE_TYPE,
                source_ref={"seed": "demo-content-v1", "kind": spec["kind"]},
                published_at=_utcnow(),
            )
        )
        created += 1
    return created


def _find_demo_campaign(db_rows: list) -> DonationCampaign | None:
    """تطبیع JSONB title با fa-field در پایتون (الگوی seed_pms_demo)."""
    for row in db_rows:
        if (row.title or {}).get("fa") == _CAMPAIGN_FA:
            return row
    return None


async def _seed_campaign(db: AsyncSession) -> int:
    rows = (await db.execute(select(DonationCampaign))).scalars().all()
    if _find_demo_campaign(list(rows)) is not None:
        return 0
    db.add(
        DonationCampaign(
            title=_CAMPAIGN_TITLE,
            description=_L(
                "کمپین نمایشی برای تست صفحهٔ کمک‌مالی و جریان اهدا؛ قابل حذف.",
                "حملة تجريبية لاختبار صفحة التبرع - يمكن حذفها.",
                "Demo campaign for testing the donation page and flow; safe to delete.",
            ),
            goal_amount=100_000_000,
            raised_amount=0,
            status="active",
        )
    )
    return 1


async def seed_demo_content(db: AsyncSession) -> dict:
    """ساخت محتوای نمایشی (idempotent) — فقط با flag روشن (dev)."""
    summary = {
        "articles": await _seed_articles(db),
        "library": await _seed_library(db),
        "campaign": await _seed_campaign(db),
    }
    await db.flush()
    return summary


# ---------------------------------------------------------------------------
# حذف
# ---------------------------------------------------------------------------


async def delete_demo_content(db: AsyncSession) -> dict:
    """حذف دقیق محتوای نمایشی (برچسب‌محور) + فایل‌های storage.

    کمپینی که نیت پرداخت یا اهدای ارجاع‌شده داشته باشد حذف **نمی‌شود**
    (FK)؛ در خلاصه گزارش می‌شود تا کاربر تصمیم بگیرد.
    """
    storage = get_storage()

    # ۱) مقالات (slug ثابت)
    articles = (
        await db.execute(select(Article).where(Article.slug.in_(_ARTICLE_SLUGS)))
    ).scalars().all()
    for art in articles:
        await db.delete(art)

    # ۲) آیتم‌های کتابخانه (source_type ثابت) + فایل‌ها
    items = (
        await db.execute(
            select(LibraryItem).where(LibraryItem.source_type == DEMO_SOURCE_TYPE)
        )
    ).scalars().all()
    for item in items:
        for key in (item.media_key, item.cover_media_key):
            if key:
                try:
                    await storage.delete_object(key)
                except Exception as exc:  # noqa: BLE001 - فایل نبودن خطا نیست
                    logger.warning("demo seed: حذف فایل storage نشد: %s: %s", key, exc)
        await db.delete(item)

    # ۳) کمپین (عنوان مارکر) — با گارد FK
    campaign_rows = (
        await db.execute(select(DonationCampaign))
    ).scalars().all()
    campaign = _find_demo_campaign(list(campaign_rows))
    campaign_deleted = False
    campaign_blocked = False
    if campaign is not None:
        intent_refs = (
            await db.execute(
                select(func.count())
                .select_from(PaymentIntent)
                .where(PaymentIntent.campaign_id == campaign.id)
            )
        ).scalar()
        donation_refs = (
            await db.execute(
                select(func.count())
                .select_from(Donation)
                .where(Donation.campaign_id == campaign.id)
            )
        ).scalar()
        if intent_refs or donation_refs:
            campaign_blocked = True
        else:
            await db.delete(campaign)
            campaign_deleted = True

    await db.flush()
    return {
        "articles": len(articles),
        "library": len(items),
        "campaign_deleted": campaign_deleted,
        "campaign_kept_has_donations": campaign_blocked,
    }


def _force_utf8_stdio() -> None:
    """W-08: خروجی مستقل از ترمینال (کنسول cp1252 ویندوز فارسی)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            enc = (getattr(stream, "encoding", None) or "").lower()
            if "utf" in enc:
                continue
            # getattr: typing.py TextIO (بدون reconfigure) را هم می‌پوشد
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    _force_utf8_stdio()
    import asyncio

    from app.core.config import get_settings

    settings = get_settings()
    from app.core.database import engine

    if "--delete" in sys.argv:
        async def _do_delete() -> None:
            from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

            maker = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            async with maker() as db:
                result = await delete_demo_content(db)
                await db.commit()
            print(f"حذف محتوای نمایشی: {result}")

        asyncio.run(_do_delete())
    else:
        if not demo_seed_allowed(settings):
            print(
                "DEMO_SEED_ENABLED روشن نیست (یا production است) — کاری انجام نمی‌شود."
            )
            sys.exit(1)

        async def _do_seed() -> None:
            from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

            maker = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            async with maker() as db:
                result = await seed_demo_content(db)
                await db.commit()
            print(f"ساخت محتوای نمایشی: {result}")

        asyncio.run(_do_seed())
