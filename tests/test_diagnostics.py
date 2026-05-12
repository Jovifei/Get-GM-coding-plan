import logging
import tempfile
import unittest
from pathlib import Path

from src.diagnostics import DiagnosticMarkdownHandler, diagnostic_step


class DiagnosticsTests(unittest.TestCase):
    def test_markdown_handler_writes_log_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "diagnostic.md"
            logger = logging.getLogger("tests.diagnostics.write")
            logger.handlers.clear()
            logger.setLevel(logging.INFO)
            logger.propagate = False
            handler = DiagnosticMarkdownHandler(log_path)
            logger.addHandler(handler)

            logger.info("hello markdown", extra={"step": "unit-test"})
            handler.close()

            content = log_path.read_text(encoding="utf-8")
            self.assertIn("# GLM_GET 运行诊断日志", content)
            self.assertIn("unit-test", content)
            self.assertIn("hello markdown", content)

    def test_diagnostic_step_records_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "diagnostic.md"
            logger = logging.getLogger("tests.diagnostics.failure")
            logger.handlers.clear()
            logger.setLevel(logging.INFO)
            logger.propagate = False
            handler = DiagnosticMarkdownHandler(log_path)
            logger.addHandler(handler)

            with self.assertRaises(RuntimeError):
                with diagnostic_step(logger, "关键步骤"):
                    raise RuntimeError("blocked here")
            handler.close()

            content = log_path.read_text(encoding="utf-8")
            self.assertIn("START 关键步骤", content)
            self.assertIn("FAIL 关键步骤", content)
            self.assertIn("blocked here", content)


if __name__ == "__main__":
    unittest.main()
