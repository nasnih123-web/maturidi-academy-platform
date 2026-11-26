"""تست‌های زنجیرهٔ ابزار رسانه — B-04 (ADR-0027).

پوشش:
- media_tools_status با PATH خالی → همهٔ باینری‌ها missing و ready=False
- نام مدل STT با متغیر محیطی FASTER_WHISPER_MODEL override می‌شود
  (نبود/خالی/فاصله = پیش‌فرض small)
- با باینری‌های stub روی PATH (+ زبان‌های tesseract) → ready=True
- assert_media_tools_ready با ابزار غایب RuntimeError می‌دهد (fail loud)
- ورکر media گیت on_startup دارد و با ابزار غایب بالا نمی‌آید؛
  صف‌های دیگر این گیت را ندارند
- تسک‌ها خطای صریح می‌دهند: transcribe بدون faster-whisper و ocr بدون
  tesseract/pdftoppm → وضعیت failed با دلیل نام‌دار، نه سکوت
"""
from __future__ import annotations

import asyncio
import os
import stat
import uuid
from pathlib import Path

import pytest

from app.core import media_tools


@pytest.fixture
def empty_path(monkeypatch, tmp_path):
    """PATH بدون هیچ باینری‌ای — شبیه‌سازی ایمیجِ بدون زنجیرهٔ ابزار."""
    monkeypatch.setenv("PATH", str(tmp_path))
    media_tools._langs_cache = None
    return tmp_path


def _write_stub_tesseract(bin_dir: Path, langs: list[str]) -> None:
    """stub tesseract که به --list-langs فهرست زبان‌ها را جواب می‌دهد.

    لینوکس: اسکریپت sh؛ ویندوز: tesseract.bat (اسکریپت #!/bin/sh در
    ویندوز اجرا نمی‌شود و shutil.which آن را نمی‌یابد).
    """
    # بدون پرانتز: در اسکریپت bat، پرانتزِ داخل بلوک if (...) بلوک
    # را پیش‌از‌وقت می‌بندد و cmd با «was unexpected at this time»
    # می‌سوزد. parser media_tools فقط پیشوند این خط را فیلتر می‌کند.
    lines = ["List of available languages:"] + langs
    if os.name == "nt":
        (bin_dir / "tesseract.bat").write_text(
            "@echo off\r\n"
            'if "%~1"=="--list-langs" (\r\n'
            + "".join(f"  echo {l}\r\n" for l in lines)
            + ")\r\n"
            "exit /b 0\r\n",
            encoding="ascii",
        )
    else:
        # write_text در Python 3.13+ تعداد بایت نوشته‌شده را برمی‌گرداند
        # (int)؛ زنجیرهٔ .chmod روی بازنمی‌گردد خطا می‌دهد (CI لینوکس).
        t = bin_dir / "tesseract"
        t.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "--list-langs" ]; then\n'
            + "".join(f"  echo {l}\n" for l in lines)
            + "fi\n"
            "exit 0\n"
        )
        t.chmod(0o755)


@pytest.fixture
def stub_bin_path(monkeypatch, tmp_path):
    """باینری‌های stub روی PATH؛ tesseract به --list-langs جواب می‌دهد."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if os.name == "nt":
        # ffmpeg/ffprobe/pdftoppm در تست‌ها اجرا نمی‌شوند (فقط
        # shutil.which)؛ stub با پسوند ویندوزی کافی است.
        for name in ("ffmpeg", "ffprobe", "pdftoppm"):
            (bin_dir / f"{name}.exe").write_bytes(b"stub")
        _write_stub_tesseract(bin_dir, ["eng", "fas", "ara", "osd"])
    else:
        for name in ("ffmpeg", "ffprobe", "pdftoppm"):
            f = bin_dir / name
            f.write_text("#!/bin/sh\nexit 0\n")
            f.chmod(f.stat().st_mode | stat.S_IEXEC)
        _write_stub_tesseract(bin_dir, ["eng", "fas", "ara", "osd"])
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    media_tools._langs_cache = None
    return bin_dir


def test_status_all_missing(empty_path, monkeypatch):
    monkeypatch.setattr(media_tools, "faster_whisper_installed", lambda: False)
    status = media_tools.media_tools_status()
    assert status["ready"] is False
    assert status["binaries"] == {
        "ffmpeg": None, "ffprobe": None, "tesseract": None, "pdftoppm": None,
    }
    for tool in ("ffmpeg", "ffprobe", "tesseract", "pdftoppm", "faster-whisper"):
        assert tool in status["missing"]
    assert status["stt_model"] == "small"


def test_stt_model_env_override(monkeypatch):
    """FASTER_WHISPER_MODEL از محیط خوانده می‌شود؛ خالی/فاصله = small.

    ثابت هنگام import خوانده می‌شود، پس اعمال override نیازمند reload
    ماژول است؛ در پایان env پاک و ماژول به حالت پیش‌فرض برگردانده
    می‌شود تا تست‌های دیگر آلوده نشوند.
    """
    import importlib

    monkeypatch.setenv("FASTER_WHISPER_MODEL", "base")
    importlib.reload(media_tools)
    try:
        assert media_tools.FASTER_WHISPER_MODEL == "base"
        assert media_tools.media_tools_status()["stt_model"] == "base"
        monkeypatch.setenv("FASTER_WHISPER_MODEL", "   ")
        importlib.reload(media_tools)
        assert media_tools.FASTER_WHISPER_MODEL == "small"
    finally:
        monkeypatch.delenv("FASTER_WHISPER_MODEL", raising=False)
        importlib.reload(media_tools)
    assert media_tools.FASTER_WHISPER_MODEL == "small"


def test_status_ready_with_stubs(stub_bin_path, monkeypatch):
    monkeypatch.setattr(media_tools, "faster_whisper_installed", lambda: True)
    status = media_tools.media_tools_status()
    assert status["ready"] is True, status
    assert status["missing"] == []
    assert {"fas", "ara", "eng"} <= set(status["tesseract_langs"])


def test_status_missing_tesseract_langs(stub_bin_path, monkeypatch, tmp_path):
    """tesseract هست ولی پک زبان فارسی/عربی نیست → ready=False با نام دقیق."""
    _write_stub_tesseract(stub_bin_path, ["eng"])
    media_tools._langs_cache = None
    monkeypatch.setattr(media_tools, "faster_whisper_installed", lambda: True)
    status = media_tools.media_tools_status()
    assert status["ready"] is False
    assert "tesseract-langs:fas+ara" in status["missing"]


def test_assert_ready_raises_loudly(empty_path, monkeypatch):
    monkeypatch.setattr(media_tools, "faster_whisper_installed", lambda: False)
    with pytest.raises(RuntimeError, match="media tools missing"):
        media_tools.assert_media_tools_ready()


def test_assert_ready_passes_with_stubs(stub_bin_path, monkeypatch):
    monkeypatch.setattr(media_tools, "faster_whisper_installed", lambda: True)
    status = media_tools.assert_media_tools_ready()
    assert status["ready"] is True


def test_media_worker_startup_gate(empty_path, monkeypatch):
    """ورکر media با ابزار غایب بالا نمی‌آید؛ صف critical این گیت را ندارد."""
    monkeypatch.setattr(media_tools, "faster_whisper_installed", lambda: False)
    from app.worker import _make_settings_class, _media_startup

    media_settings = _make_settings_class("media")
    assert hasattr(media_settings, "on_startup")
    with pytest.raises(RuntimeError, match="media tools missing"):
        asyncio.run(_media_startup({}))

    critical_settings = _make_settings_class("critical")
    assert not hasattr(critical_settings, "on_startup")


async def _make_library_item(tc) -> str:
    from app.models.models import LibraryItem

    async with tc["maker"]() as db:
        item = LibraryItem(
            kind="audio",
            title={"fa": "تست رسانه"},
            media_key="library/test-media.mp3",
            visibility="public",
            workflow_status="approved",
        )
        db.add(item)
        await db.commit()
        return str(item.id)


@pytest.fixture
def patch_session_local(tc, monkeypatch):
    monkeypatch.setattr("app.core.database.SessionLocal", tc["maker"])
    return tc


async def test_transcribe_task_explicit_error_without_faster_whisper(
    tc, patch_session_local, monkeypatch
):
    """faster-whisper غایب → تسک failed با دلیل صریح stt_unavailable."""
    monkeypatch.setattr(
        "app.core.media_tools.faster_whisper_installed", lambda: False
    )
    from app.modules.library.tasks import transcribe_media

    item_id = await _make_library_item(tc)
    out = await transcribe_media({}, item_id)
    assert out["ok"] is False
    assert out["reason"].startswith("stt_unavailable")

    from app.models.models import LibraryItem

    async with tc["maker"]() as db:
        item = await db.get(LibraryItem, uuid.UUID(item_id))
        assert item.transcript_status == "failed"
        assert "stt_unavailable" in (item.processing_error or "")


async def test_ocr_task_explicit_error_without_tools(tc, patch_session_local, empty_path):
    """tesseract/pdftoppm غایب → تسک failed با دلیل صریح ocr_tools_missing."""
    from app.modules.library.tasks import ocr_pdf

    item_id = await _make_library_item(tc)
    out = await ocr_pdf({}, item_id)
    assert out["ok"] is False
    assert out["reason"].startswith("ocr_tools_missing")

    from app.models.models import LibraryItem

    async with tc["maker"]() as db:
        item = await db.get(LibraryItem, uuid.UUID(item_id))
        assert item.ocr_status == "failed"
        assert "ocr_tools_missing" in (item.processing_error or "")


async def test_health_reports_media_tools(tc):
    r = await tc["client"].get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert "media_tools" in body
    assert body["media_tools"]["stt_engine"] == "faster-whisper"
    assert body["media_tools"]["stt_model"] == "small"
