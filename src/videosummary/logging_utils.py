from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def _try_enable_utf8_console() -> None:
    # Best-effort: avoid Chinese mojibake on Windows terminals.
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")


def configure_logging(verbose: bool = False, debug: bool = False, log_file: str | None = None) -> None:
    _try_enable_utf8_console()

    level = logging.INFO
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, mode="a", encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


def log_phase(phase: str, message: str, level: int = logging.INFO) -> None:
    logging.log(level, f"[{phase}] {message}")


@contextmanager
def timed_step(phase: str, step: str) -> Iterator[None]:
    start = time.perf_counter()
    log_phase(phase, f"开始: {step}")
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        log_phase(phase, f"完成: {step} (耗时 {elapsed:.2f}s)")
