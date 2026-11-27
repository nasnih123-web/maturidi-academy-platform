"""FIX2-06 — env توسعهٔ محلی bootstrap + چک‌لیست سلامت واقعی.

قرارداد:
- write_dev_env.py یک env صریحِ فقط-dev می‌سازد (نه کپی قالب
  production): APP_ENV=dev، دیتابیس SQLite، CAPTCHA_ENABLED=false
  (با دلیل مستند)، بای‌پس فقط-dev ClamAV روشن و پرسر و صدا، و
  secretهای تصادفی تازه (نه CHANGE_ME). فایل موجود بازنویسی نمی‌شود.
- bootstrap_check.py روی سرویس زنده سه چک واقعی می‌زند و با هر
  شکست غیرصفر خارج می‌شود (این‌جا روی stub HTTP قطعی تست می‌شود).
- نحو اسکریپت‌های پوسته معتبر است (bash -n).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.shellutil import usable_bash

REPO_ROOT = Path(__file__).resolve().parents[3]
WRITE_ENV = REPO_ROOT / "tools" / "dev" / "write_dev_env.py"
CHECK = REPO_ROOT / "tools" / "dev" / "bootstrap_check.py"


def _load_write_env():
    spec = importlib.util.spec_from_file_location("write_dev_env", WRITE_ENV)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rendered_dev_env_parses_with_expected_values(tmp_path, monkeypatch):
    module = _load_write_env()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert module.main() == 0

    from app.core.config import Settings

    settings = Settings(_env_file=str(tmp_path / ".env"))
    assert settings.app_env == "dev"
    assert settings.captcha_enabled is False
    assert settings.clamav_allow_insecure_dev_bypass is True
    assert settings.database_url.startswith("sqlite")
    assert settings.jwt_secret not in ("", "CHANGE_ME")
    assert len(settings.jwt_secret) >= 32
    assert "localhost:5173" in settings.cors_allow_origins

    api_env = (tmp_path / "apps" / "api" / ".env").read_text(encoding="utf-8")
    assert "CAPTCHA_ENABLED=false" in api_env
    assert "CLAMAV_ALLOW_INSECURE_DEV_BYPASS=true" in api_env


def test_write_dev_env_never_overwrites(tmp_path, monkeypatch):
    module = _load_write_env()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert module.main() == 0
    target = tmp_path / ".env"
    target.write_text("EDITED=by-user\n", encoding="utf-8")
    assert module.main() == 0
    assert target.read_text(encoding="utf-8") == "EDITED=by-user\n"


# ---------------------------------------------------------------------------
# bootstrap_check روی stub HTTP قطعی
# ---------------------------------------------------------------------------


def _stub_server(transcribe_status: int, transcribe_code: str | None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # سکوت لاگ تست
            pass

        def _json(self, status: int, payload: dict):
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/health":
                self._json(200, {"status": "ok", "env": "dev"})
            else:
                self._json(404, {})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            if self.path == "/api/v1/auth/register":
                self._json(201, {"id": "u1"})
            elif self.path == "/api/v1/auth/login":
                self._json(200, {"access_token": "tok"})
            elif self.path == "/api/v1/voice/transcribe":
                if transcribe_status == 200:
                    self._json(200, {"text": ""})
                else:
                    self._json(
                        transcribe_status,
                        {"error": {"code": transcribe_code, "message": "stub"}},
                    )
            else:
                self._json(404, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _run_check(server, io_encoding: str = "utf-8") -> subprocess.CompletedProcess:
    port = server.server_address[1]
    # PYTHONIOENCODING: خروجی ابزار شامل متن فارسی و ✓/✗ است؛ روی
    # ویندوز با locale غیر-UTF-8 (مثلاً cp1252) فرزند روی همان print
    # UnicodeEncodeError می‌داد — env صریح، تست را از locale میز
    # مستقل می‌کند.
    env = dict(os.environ, PYTHONIOENCODING=io_encoding)
    return subprocess.run(
        [sys.executable, str(CHECK), "--base-url", f"http://127.0.0.1:{port}"],
        # encoding صریح: decode خروجی فرزند را از locale میز (که روی
        # ویندوز اغلب cp1252 است) مستقل می‌کند و با encoding فرزند
        # هم‌راستا می‌شود؛ وگرنه ✓/✗ و متن فارسی به mojibake تبدیل
        # می‌شدند. (W-08: ابزارها حالا خودشان روی کنسول غیر-UTF-8
        # خروجی را UTF-8 می‌کنند، پس decode همیشه utf-8 است.)
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False, env=env,
    )


def test_bootstrap_check_passes_when_scan_ok_and_stt_unconfigured():
    server = _stub_server(503, "stt_unavailable")
    try:
        proc = _run_check(server)
    finally:
        server.shutdown()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.count("✓") >= 4  # health/register/login/upload + جمع‌بندی


def test_bootstrap_check_fails_when_antivirus_unavailable():
    server = _stub_server(503, "antivirus_unavailable")
    try:
        proc = _run_check(server)
    finally:
        server.shutdown()
    assert proc.returncode == 1
    assert "✗" in proc.stdout


# ---------------------------------------------------------------------------
# W-08 — خروجی مستقل از ترمینال (کنسول cp1252 ویندوز فارسی)
# ---------------------------------------------------------------------------
# بازتولید قطعی: PYTHONIOENCODING=cp1252 encoding خروجی فرزند را
# cp1252 می‌کند — دقیقاً همان کرشِ میدانی (UnicodeEncodeError «charmap»)
# بدون نیاز به ویندوز. بدون گارد داخل اسکریپت‌ها این تست‌ها می‌شکنند.


def test_write_dev_env_survives_cp1252_console(tmp_path):
    """write_dev_env.py مستقیم (بدون چتر bootstrap.ps1) روی کنسول
    cp1252 نمی‌افتد و هر دو فایل env ساخته می‌شوند."""
    # اسکریپت ROOT را از مسیر خودش می‌گیرد (parents[2]) — کپی در درخت
    # ساختگی تا نوشتن در tmp باشد، نه ریشهٔ ریپو.
    fake = tmp_path / "tools" / "dev"
    fake.mkdir(parents=True)
    target = fake / "write_dev_env.py"
    target.write_text(
        WRITE_ENV.read_text(encoding="utf-8"), encoding="utf-8"
    )
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    proc = subprocess.run(
        [sys.executable, str(target)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False, env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "UnicodeEncodeError" not in (proc.stdout + proc.stderr)
    assert (tmp_path / ".env").exists()
    assert (tmp_path / "apps" / "api" / ".env").exists()


def test_bootstrap_check_survives_cp1252_console():
    """bootstrap_check.py خودشان مستقل از ترمینال است (نه فقط زیر
    bootstrap.ps1)."""
    server = _stub_server(503, "stt_unavailable")
    try:
        proc = _run_check(server, io_encoding="cp1252")
    finally:
        server.shutdown()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "UnicodeEncodeError" not in (proc.stdout + proc.stderr)
    assert "✓" in proc.stdout


_SEED_PROBE = """
import asyncio
import os

os.environ.setdefault("APP_ENV", "dev")
from cryptography.fernet import Fernet

os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from app import seed
from app.core.database import Base, engine
import app.models  # noqa: F401  (ثبت مدل‌ها)

# همان کاری که entrypoint `python -m app.seed` قبل از main() می‌کند
seed._force_utf8_stdio()


async def setup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


asyncio.run(setup())

# اجرای ۱: seed کامل با env مدیر (مسیر bootstrap.ps1)
os.environ["ADMIN_EMAIL"] = "w08-admin@example.com"
os.environ["ADMIN_PASSWORD"] = "W08TestPass123"
asyncio.run(seed.main())

# اجرای ۲: idempotent — بدون env مدیر (re-run bootstrap)
os.environ.pop("ADMIN_EMAIL", None)
os.environ.pop("ADMIN_PASSWORD", None)
asyncio.run(seed.main())

from sqlalchemy import select
from app.models.models import Role, User, UserRole


async def verify():
    async with engine.connect() as conn:
        ids = (
            await conn.execute(
                select(User.id)
                .join(UserRole, UserRole.user_id == User.id)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.name == "super_admin")
            )
        ).scalars().all()
        emails = (
            await conn.execute(
                select(User.email).where(User.id.in_(ids))
            )
        ).scalars().all()
    print(f"super_admin_count={len(ids)}")
    for e in emails:
        print(f"admin_email={e}")


asyncio.run(verify())
print("PROBE-OK")
"""


def test_seed_survives_cp1252_and_is_idempotent(tmp_path):
    """W-08: seed کامل زیر کنسول cp1252 — کرش نمی‌کند، مدیر ارشد
    commit می‌شود، و اجرای دوم بدون env مدیر idempotent است."""
    db = tmp_path / "w08.db"
    probe = tmp_path / "seed_probe.py"
    probe.write_text(_SEED_PROBE, encoding="utf-8")
    env = dict(
        os.environ,
        PYTHONIOENCODING="cp1252",
        PYTHONPATH=str(REPO_ROOT / "apps" / "api"),
        DATABASE_URL=f"sqlite+aiosqlite:///{db}",
    )
    proc = subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600, check=False, env=env,
        cwd=str(REPO_ROOT / "apps" / "api"),
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-3000:]
    assert "UnicodeEncodeError" not in out
    # مدیر commit شده و دقیقاً یکی (idempotency)
    assert "super_admin_count=1" in out
    assert "admin_email=w08-admin@example.com" in out
    # هر دو اجرا تا انتها رفته‌اند
    assert out.count("seed انجام شد") >= 2


_BASH = usable_bash()


@pytest.mark.skipif(not _BASH, reason="bash سالم در این محیط نیست")
def test_shell_scripts_syntax_ok():
    for script in (REPO_ROOT / "bootstrap.sh", REPO_ROOT / "apps" / "api" / "setup.sh"):
        proc = subprocess.run(
            [_BASH, "-n", str(script)], capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, f"{script}: {proc.stderr}"


_POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@pytest.mark.skipif(not _POWERSHELL, reason="PowerShell در این محیط نیست")
def test_bootstrap_ps1_parses():
    """W-08: تغییرات bootstrap.ps1 (بلوک UTF-8) نباید خطای نحوی بزند."""
    script = (
        "$t=$null; $e=$null;"
        f"[void][System.Management.Automation.Language.Parser]::ParseFile"
        f"('{REPO_ROOT}/bootstrap.ps1',[ref]$t,[ref]$e);"
        "if ($e) { $e | ForEach-Object { Write-Output $_.Message }; exit 1 }"
    )
    proc = subprocess.run(
        [_POWERSHELL, "-NoProfile", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
