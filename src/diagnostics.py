"""Markdown diagnostics for long-running purchase flows."""
import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class DiagnosticMarkdownHandler(logging.Handler):
    """Append log records to a Markdown document."""

    def __init__(self, path: Path):
        super().__init__(level=logging.INFO)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._write_header()

    def _write_header(self):
        with self.path.open("w", encoding="utf-8") as file:
            file.write("# GLM_GET 运行诊断日志\n\n")
            file.write(f"- 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            file.write("| 时间 | 级别 | 步骤 | 信息 |\n")
            file.write("| --- | --- | --- | --- |\n")

    def emit(self, record: logging.LogRecord):
        try:
            timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
            step = getattr(record, "step", "-")
            message = self.format(record)
            line = f"| {timestamp} | {record.levelname} | {self._escape(step)} | {self._escape(message)} |\n"
            with self._lock:
                with self.path.open("a", encoding="utf-8") as file:
                    file.write(line)
        except Exception:
            self.handleError(record)

    @staticmethod
    def _escape(value) -> str:
        return str(value).replace("|", "\\|").replace("\n", "<br>")


def init_diagnostics(log_dir: Path) -> Path:
    diagnostics_dir = Path(log_dir) / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    report_path = diagnostics_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    handler = DiagnosticMarkdownHandler(report_path)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger(__name__).info("诊断日志已启用: %s", report_path, extra={"step": "diagnostics"})
    return report_path


@contextmanager
def diagnostic_step(logger: logging.Logger, step: str):
    start = time.perf_counter()
    logger.info("START %s", step, extra={"step": step})
    try:
        yield
    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.exception("FAIL %s，用时 %.2fs: %s", step, elapsed, exc, extra={"step": step})
        raise
    else:
        elapsed = time.perf_counter() - start
        logger.info("OK %s，用时 %.2fs", step, elapsed, extra={"step": step})
