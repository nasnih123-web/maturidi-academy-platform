"""اصالح انحراف مدل↔مایگریشن — هم‌راستا کردن دیتابیس با مدل.

Revision ID: d8e5f6a7b9c3
Revises: 0f64b32a1eae
Create Date: 2026-11-26

چک‌لیستِ `alembic check` روی PostgreSQL واقعی (هد `0f64b32a1eae`)
شش دستهٔ انحراف نشان می‌داد؛ هر کدام در جهت درست اصلاح شده
(دستگاه به‌سوی مدل، نه برعکس):

۱) NOT NULL (۶ ستون): مدل `Mapped[...]` غیر-nullable است ولی
   مایگریشن‌ها ستون را nullable ساخته‌اند (projects/tasks/
   staff_members با `_ts()`؛ children_* در فاز ۴). با گارد داده:
   ابتدا NULLها با مقدار پیش‌فرض پر می‌شوند، سپس SET NOT NULL.

۲) نوع JSONB→JSON (۹ ستون): مایگریشن‌های پراکنده (فاز ۴/۷/۸ و
   video_playlists) `postgresql.JSONB` نوشته‌اند ولی قرارداد مدل
   (models.py خط ۴۹: «JSONB روی PostgreSQL، JSON روی SQLite —
   همان ستون، بدون تغییر کد») نوع `JSON` است و ۱۰۴ ستون دیگرِ
   دیتابیس هم `json` ساده هستند. تبدیل jsonb→json بدون از دست
   رفتن داده است و دیتابیس را کاملاً سازگار با مدل می‌کند.
   (هیچ ایندکس GIN و هیچ اپراتور JSONB روی این ۹ ستون نیست.)

۳) یکتایی (۹ قید): مدل‌ها `unique=True, index=True` دارند که در
   SQLAlchemy 2.0 یک ایندکس یکتای `ix_...` می‌سازد (بدون قید
   جداگانه)، ولی مایگریشن‌ها هم قید یکتا و هم ایندکس ساده ساخته
   بودند. ایندکس ساده حذف و ایندکس یکتا می‌شود و قید تکراری
   حذف می‌گردد. pages ایندکسش از قبل یکتا بود؛ certificates
   فقط قید داشت و ایندکسش ساخته می‌شود.

۴) نام‌های ایندکس (۱۱ ایندکس): ستون‌ها در فازهای بعد تغییر نام
   کرده‌اند (status→workflow_status، hijri→hijri_day/month،
   library_item_ref→source_library_item_ref، parent→parent_id،
   requires→requires_course_id، user→user_id) و ایندکس ترکیبی
   user_ayah_notes به سه ایندکس ساده شده (همان چیزی که مدل
   اعلام می‌کند). ایندکس‌های قدیمی حذف و جدید ساخته می‌شوند.

۵) ایندکس‌های گمشدهٔ مدل (۱۲ ایندکس): `index=True` در مدل هست
   ولی مایگریشن نساخته (created_atها، notif_type، madhab،
   related_entity_*) — ساخته می‌شوند.

۶) ایندکس‌های اضافهٔ home_sections: `ix_home_sections_key`
   (تکرار قید یکتای `home_sections_key_key` که مدل اعلام می‌کند)
   و `ix_home_sections_sort_order` (مدل ایندکسی روی sort_order
   ندارد؛ جدول تنظیمات کوچکی است) حذف می‌شوند.

بیرون از دامنهٔ این مایگریشن (مستند در env.py):
   - ایندکس‌های HNSW و trgm روی fiqh_knowledge_chunks صرفاً
     خاصیت عملکردی PostgreSQL هستند (مایگریشن e2b3c4d5f6a7،
     gated با is_pg) و عمداً در مدل نیستند تا به اسکیما SQLite
     نریزند؛ در مقایسهٔ alembic با include_indexes مستثنی‌اند.

downgrade همهٔ موارد را برمی‌گرداند؛ تنها بخش غیرقابل‌برگشت
UPDATEهای گارد بخش ۱ است (NULLهای قدیمی را پر کرده است).
"""
from collections.abc import Sequence

import sqlalchemy as sa  # noqa: F401  (سازگاری سبک با بقیهٔ مایگریشن‌ها)

# با alias import — نام‌های table/column در حلقه‌های پایین‌تر این فایل
# به‌عنوان متغیر لوپ استفاده می‌شوند و نام import را می‌پوشانند
# (UnboundLocalError).
from sqlalchemy import column as sa_column
from sqlalchemy import func
from sqlalchemy import table as sa_table

from alembic import op

revision: str = "d8e5f6a7b9c3"
down_revision: str | None = "0f64b32a1eae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# جداول/ستون‌ها در هر بخش — یک‌جا تعریف تا upgrade/downgrade همنوا بمانند
# ---------------------------------------------------------------------------

# (جدول، ستون، مقدار پرکنندهٔ NULL) — func.now() دایالکت‌آگاه است
# (PG: now()، SQLite: CURRENT_TIMESTAMP)؛ SQL خام نمی‌نویسیم.
_NOT_NULLS: list[tuple[str, str, object]] = [
    ("children_quiz_questions", "is_active", True),
    ("children_quiz_questions", "updated_at", func.now()),
    ("children_progress", "updated_at", func.now()),
    ("projects", "created_at", func.now()),
    ("staff_members", "created_at", func.now()),
    ("tasks", "created_at", func.now()),
]

# (جدول، ستون) — در دیتابیس jsonb، در مدل json
_JSONB_TO_JSON: list[tuple[str, str]] = [
    ("children_quiz_attempts", "question_ids"),
    ("children_quiz_attempts", "answers"),
    ("children_quiz_questions", "payload"),
    ("hifz_tasmi_sessions", "state"),
    ("hifz_test_questions", "counts"),
    ("hifz_test_questions", "raw_events"),
    ("user_activity_events", "meta"),
    ("video_playlists", "title"),
    ("video_playlists", "description"),
]

# (جدول، ستون، نام ایندکس سادهٔ فعلی، نام قید یکتای فعلی)
_UNIQUE_PAIRS: list[tuple[str, str, str, str]] = [
    ("api_keys", "key_hash", "ix_api_keys_key_hash", "api_keys_key_hash_key"),
    ("article_categories", "slug", "ix_article_categories_slug", "article_categories_slug_key"),
    ("articles", "slug", "ix_articles_slug", "articles_slug_key"),
    ("fatwa_categories", "slug", "ix_fatwa_categories_slug", "fatwa_categories_slug_key"),
    ("nisab_price_cache", "source", "ix_nisab_price_cache_source", "uq_nisab_price_cache_source"),
    ("staff_members", "user_id", "ix_staff_members_user_id", "uq_staff_members_user_id"),
    (
        "telegram_distribution_policies",
        "content_type",
        "ix_telegram_distribution_policies_content_type",
        "telegram_distribution_policies_content_type_key",
    ),
]

# (نام ایندکس قدیمی، جدول، [ستون‌های قدیمی])
_OLD_INDEXES: list[tuple[str, str, list[str]]] = [
    ("ix_course_prerequisites_requires", "course_prerequisites", ["requires_course_id"]),
    ("ix_dhikr_sessions_user", "dhikr_sessions", ["user_id"]),
    ("ix_fatwa_submissions_status", "fatwa_submissions", ["workflow_status"]),
    (
        "ix_fiqh_knowledge_chunks_library_item_ref",
        "fiqh_knowledge_chunks",
        ["source_library_item_ref"],
    ),
    ("ix_islamic_events_hijri", "islamic_events", ["hijri_month", "hijri_day"]),
    ("ix_nav_items_parent", "nav_items", ["parent_id"]),
    ("ix_user_ayah_notes_user_surah_ayah", "user_ayah_notes", ["user_id", "surah", "ayah"]),
]

# (نام ایندکس جدید، جدول، [ستون]) — بازسازی‌ها + ایندکس‌های گمشدهٔ مدل
_NEW_INDEXES: list[tuple[str, str, list[str]]] = [
    ("ix_course_prerequisites_requires_course_id", "course_prerequisites", ["requires_course_id"]),
    ("ix_dhikr_sessions_user_id", "dhikr_sessions", ["user_id"]),
    ("ix_fatwa_submissions_workflow_status", "fatwa_submissions", ["workflow_status"]),
    ("ix_fatwa_submissions_created_at", "fatwa_submissions", ["created_at"]),
    (
        "ix_fiqh_knowledge_chunks_source_library_item_ref",
        "fiqh_knowledge_chunks",
        ["source_library_item_ref"],
    ),
    ("ix_islamic_events_hijri_day", "islamic_events", ["hijri_day"]),
    ("ix_islamic_events_hijri_month", "islamic_events", ["hijri_month"]),
    ("ix_nav_items_parent_id", "nav_items", ["parent_id"]),
    ("ix_user_ayah_notes_user_id", "user_ayah_notes", ["user_id"]),
    ("ix_user_ayah_notes_surah", "user_ayah_notes", ["surah"]),
    ("ix_user_ayah_notes_ayah", "user_ayah_notes", ["ayah"]),
    ("ix_dhikr_daily_counts_date", "dhikr_daily_counts", ["date"]),
    ("ix_dhikr_daily_counts_user_id", "dhikr_daily_counts", ["user_id"]),
    ("ix_notifications_notif_type", "notifications", ["notif_type"]),
    ("ix_question_clusters_created_at", "question_clusters", ["created_at"]),
    ("ix_social_comments_created_at", "social_comments", ["created_at"]),
    ("ix_social_posts_status", "social_posts", ["status"]),
    ("ix_tasks_created_at", "tasks", ["created_at"]),
    ("ix_tasks_related_entity_id", "tasks", ["related_entity_id"]),
    ("ix_tasks_related_entity_type", "tasks", ["related_entity_type"]),
    ("ix_zakat_rule_configs_madhab", "zakat_rule_configs", ["madhab"]),
]


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # ۱) NOT NULL — ابتدا گارد داده (NULLها را با مقدار پیش‌فرض پر می‌کند)
    for table_name, column_name, fill_value in _NOT_NULLS:
        t = sa_table(table_name, sa_column(column_name))
        op.execute(
            t.update()
            .where(t.c[column_name].is_(None))
            .values(**{column_name: fill_value})
        )
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                column_name, existing_nullable=True, nullable=False
            )

    # ۲) jsonb → json (فقط PG؛ روی SQLite ستون‌ها از ابتدا json هستند)
    if is_pg:
        for table, column in _JSONB_TO_JSON:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} "
                f"TYPE json USING {column}::json"
            )

    # ۳) یکتایی — ایندکس ساده حذف، ایندکس یکتا جایگزین، قید تکراری حذف.
    #    حین کار همیشه دست‌کم یکی از قید/ایندکس یکتا فعال است.
    #    حذف قید فقط روی PG: در SQLite، UNIQUE بدون نام ثبت می‌شود
    #    (sqlite_autoindex) و نه قابل حذف است نه نیاز به حذف دارد —
    #    یکتایی با ایندکس یکتای جایگزین تضمین می‌شود.
    for table, column, index_name, uq_name in _UNIQUE_PAIRS:
        op.drop_index(index_name, table_name=table)
        op.create_index(index_name, table, [column], unique=True)
        if is_pg:
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_constraint(uq_name, type_="unique")
    # certificates: فقط قید بود؛ ایندکس یکتا را اول می‌سازیم (نامش با
    # ایندکس ضمنی قید تکرار نمی‌شود) و بعد قید را حذف می‌کنیم
    op.create_index("ix_certificates_code", "certificates", ["code"], unique=True)
    if is_pg:
        with op.batch_alter_table("certificates") as batch_op:
            batch_op.drop_constraint("uq_certificates_code", type_="unique")
    # pages: ایندکس ix_pages_slug از قبل یکتا بود؛ فقط قید تکراری حذف
    if is_pg:
        with op.batch_alter_table("pages") as batch_op:
            batch_op.drop_constraint("pages_slug_key", type_="unique")

    # ۴) نام‌های ایندکس قدیمی
    for index_name, table, _cols in _OLD_INDEXES:
        op.drop_index(index_name, table_name=table)
    for index_name, table, cols in _NEW_INDEXES:
        op.create_index(index_name, table, cols)

    # ۶) ایندکس‌های اضافهٔ home_sections
    op.drop_index("ix_home_sections_key", table_name="home_sections")
    op.drop_index("ix_home_sections_sort_order", table_name="home_sections")


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # ۶ معکوس
    op.create_index("ix_home_sections_key", "home_sections", ["key"], unique=True)
    op.create_index("ix_home_sections_sort_order", "home_sections", ["sort_order"])

    # ۴ معکوس
    for index_name, table, _cols in _NEW_INDEXES:
        op.drop_index(index_name, table_name=table)
    for index_name, table, cols in _OLD_INDEXES:
        op.create_index(index_name, table, cols)

    # ۳ معکوس — اول قید می‌سازد (یکتایی حفظ می‌شود)، بعد ایندکس یکتا
    # حذف و ایندکس ساده باز می‌گردد
    op.drop_index("ix_certificates_code", table_name="certificates")
    with op.batch_alter_table("certificates") as batch_op:
        batch_op.create_unique_constraint("uq_certificates_code", ["code"])
    with op.batch_alter_table("pages") as batch_op:
        batch_op.create_unique_constraint("pages_slug_key", ["slug"])
    for table, column, index_name, uq_name in _UNIQUE_PAIRS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_unique_constraint(uq_name, [column])
        op.drop_index(index_name, table_name=table)
        op.create_index(index_name, table, [column])

    # ۲ معکوس — json → jsonb (فقط PG)
    if is_pg:
        for table, column in _JSONB_TO_JSON:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} "
                f"TYPE jsonb USING {column}::jsonb"
            )

    # ۱ معکوس — DROP NOT NULL (UPDATEهای گارد برگشت ندارند)
    for table_name, column_name, _fill_value in _NOT_NULLS:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                column_name, existing_nullable=False, nullable=True
            )
