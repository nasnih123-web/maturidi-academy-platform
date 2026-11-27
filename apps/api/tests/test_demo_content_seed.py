"""سید محتوای نمایشی (flag-controlled, deletable).

تصمیم سرپرست: محتوا نمایشی (مقاله/کتابخانه/کمپین) فقط با flag
DEMO_SEED_ENABLED ساخته شود — در dev روشن، در production خاموش —
و قابل حذف باشد (برچسب‌محور).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

# ---------------------------------------------------------------------------
# گارد flag: production هرگز
# ---------------------------------------------------------------------------


def test_demo_seed_allowed_matrix():
    from app.core.config import Settings
    from app.seed_demo_content import demo_seed_allowed

    assert demo_seed_allowed(Settings(app_env="dev", demo_seed_enabled=True))
    assert not demo_seed_allowed(Settings(app_env="dev", demo_seed_enabled=False))
    # حتی flag روشن در production → ممنوع (لایهٔ دوم دفاع)
    assert not demo_seed_allowed(Settings(app_env="production", demo_seed_enabled=True))
    assert not demo_seed_allowed(Settings(app_env="staging", demo_seed_enabled=False))


# ---------------------------------------------------------------------------
# ساخت idempotent + حذف کامل
# ---------------------------------------------------------------------------


@pytest.fixture()
def demo_storage(monkeypatch, tmp_path):
    """storage ماژول سید → دایرکتوری تست (فایل‌ها واقعی ولی ایزوله)."""
    import app.seed_demo_content as mod
    from app.core.storage import LocalStorageProvider
    from app.seed_demo_content import DEMO_SOURCE_TYPE

    provider = LocalStorageProvider(str(tmp_path / "storage"))
    monkeypatch.setattr(mod, "get_storage", lambda: provider)
    return {"provider": provider, "dir": tmp_path / "storage", "module": mod,
            "source_type": DEMO_SOURCE_TYPE}


async def _counts(db):
    """فقط ردیف‌های مارک‌دار این سید — نه کل جدول‌ها (بسته‌به‌تست‌های
    هم‌سشن که مقاله/کمپین خودش را می‌سازند)."""
    import app.seed_demo_content as mod
    from app.models.models import Article, DonationCampaign, LibraryItem

    articles = (
        await db.execute(
            select(func.count())
            .select_from(Article)
            .where(Article.slug.in_(mod._ARTICLE_SLUGS))
        )
    ).scalar()
    library = (
        await db.execute(
            select(func.count())
            .select_from(LibraryItem)
            .where(LibraryItem.source_type == mod.DEMO_SOURCE_TYPE)
        )
    ).scalar()
    # title JSONB است — فیلتر مارک در پایتون (الگوی seed_pms_demo).
    camps = (await db.execute(select(DonationCampaign))).scalars().all()
    campaign = sum(1 for c in camps if (c.title or {}).get("fa") == mod._CAMPAIGN_FA)
    return {"articles": articles, "library": library, "campaign": campaign}


@pytest.mark.asyncio
async def test_seed_demo_content_idempotent_and_deletable(tc, demo_storage):
    mod = demo_storage["module"]
    async with tc["maker"]() as db:
        # ۱) ساخت
        first = await mod.seed_demo_content(db)
        await db.commit()
        assert first == {"articles": 2, "library": 3, "campaign": 1}

        counts = await _counts(db)
        assert counts == {"articles": 2, "library": 3, "campaign": 1}

        # فایل‌های storage واقعی ساخته شده‌اند
        assert (demo_storage["dir"] / "demo-content" / "demo-pdf.pdf").exists()
        assert (demo_storage["dir"] / "demo-content" / "demo-audio.wav").exists()

        # ۲) idempotency — اجرا دوم هیچ ردیف تازه‌ای نمی‌سازد
        second = await mod.seed_demo_content(db)
        await db.commit()
        assert second == {"articles": 0, "library": 0, "campaign": 0}
        assert await _counts(db) == counts

        # ۳) حذف — همهٔ ردیف‌ها + فایل‌ها
        deleted = await mod.delete_demo_content(db)
        await db.commit()
        assert deleted["articles"] == 2
        assert deleted["library"] == 3
        assert deleted["campaign_deleted"] is True
        assert deleted["campaign_kept_has_donations"] is False

        assert await _counts(db) == {"articles": 0, "library": 0, "campaign": 0}
        assert not (demo_storage["dir"] / "demo-content" / "demo-pdf.pdf").exists()
        assert not (demo_storage["dir"] / "demo-content" / "demo-audio.wav").exists()

        # ۴) حذف دوباره idempotent است
        again = await mod.delete_demo_content(db)
        assert again == {
            "articles": 0,
            "library": 0,
            "campaign_deleted": False,
            "campaign_kept_has_donations": False,
        }


@pytest.mark.asyncio
async def test_demo_articles_are_published_with_valid_tiptap(tc, demo_storage):
    mod = demo_storage["module"]
    async with tc["maker"]() as db:
        await mod.seed_demo_content(db)
        await db.commit()

        from app.models.models import Article

        articles = (
            await db.execute(select(Article).where(Article.slug.startswith("demo-article-")))
        ).scalars().all()
        assert len(articles) == 2
        for art in articles:
            assert art.workflow_status == "published"
            assert art.published_at is not None
            # اسناد Tiptap معتبر: doc/paragraph/text
            assert art.body["type"] == "doc"
            assert any(
                block.get("type") == "paragraph" for block in art.body["content"]
            )
        await mod.delete_demo_content(db)
        await db.commit()


@pytest.mark.asyncio
async def test_campaign_delete_blocked_by_donation_refs(tc, demo_storage):
    """کمپین نمایشی با نیت پرداخت ارجاع‌شده حذف نمی‌شود (FK)."""
    from app.models.models import PaymentIntent

    mod = demo_storage["module"]
    async with tc["maker"]() as db:
        await mod.seed_demo_content(db)
        await db.commit()

        from app.models.models import DonationCampaign

        campaign = (
            await db.execute(select(DonationCampaign))
        ).scalars().first()
        assert campaign is not None

        db.add(
            PaymentIntent(
                idempotency_key=f"demo-guard-{uuid.uuid4().hex[:8]}",
                amount=10_000,
                campaign_id=campaign.id,
                gateway="zarinpal",
                status="pending",
            )
        )
        await db.commit()

        result = await mod.delete_demo_content(db)
        await db.commit()
        assert result["campaign_deleted"] is False
        assert result["campaign_kept_has_donations"] is True

        # پاک‌سازی: نیت را حذف کن، بعد کمپین قابل حذف می‌شود
        from sqlalchemy import delete as sa_delete

        await db.execute(sa_delete(PaymentIntent).where(PaymentIntent.campaign_id == campaign.id))
        await db.commit()
        again = await mod.delete_demo_content(db)
        await db.commit()
        assert again["campaign_deleted"] is True
