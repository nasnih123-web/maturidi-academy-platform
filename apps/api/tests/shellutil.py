"""ابزار مشترک تست‌ها: یافتن bash سالم برای اسکریپت‌های پوسته.

روی ویندوز دو دامنه وجود دارد:
1. `shutil.which("bash")` ممکن است یک bash سالم روی PATH بیابد،
   اما `subprocess.run(["bash", ...])` از ترتیب جستجوی
   CreateProcess استفاده می‌کند که در آن System32 **قبل** از PATH
   بررسی می‌شود؛ اگر relay خراب WSL (System32\\bash.exe) نصب
   باشد، نام ساده به او می‌رسد و هر اجرا با خطای
   `WSL ... execvpe(/bin/bash) failed` می‌سوزد.
2. حتی اگر which به مسیر سالم برسد، اجرای واقعی لازم است تا از
   کارکردن‌داشتن آن مطمئن شویم.

به‌همین‌دلیل `usable_bash()` نام ساده را مستقیم برمی‌گرداند؛
کاندیداهای PATH را (به‌ترتیب) با اجرای واقعی پراوب می‌کند و
مسیرِ bashی را که واقعاً اجرا می‌شود برمی‌گرداند، وگرنه None.
تست‌های وابسته به bash یا skip می‌شوند یا از همان مسیر
برمی‌گردانده استفاده می‌کنند — هر دو روی لینوکس/CI بدون تغییر
رفتار می‌مانند (اولین bash سالم PATH همان /usr/bin/bash است).
"""
from __future__ import annotations

import os
import shutil
import subprocess


def usable_bash() -> str | None:
    """مسیر یک bash قابل‌اجرا (با اجرای واقعی تأییدشده)، وگرنه None."""
    candidates: list[str] = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        for name in ("bash.exe", "bash"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                candidates.append(p)
    found = shutil.which("bash")
    if found:
        candidates.append(found)

    seen: set[str] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        probe = subprocess.run([c, "-c", "true"], capture_output=True, check=False)
        if probe.returncode == 0:
            return c
    return None
