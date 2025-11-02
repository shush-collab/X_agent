import io
import logging
import unittest

from src.utils import logger as logger_utils


class LoggerUtilsTests(unittest.TestCase):
    def setUp(self) -> None:
        logger_utils.clear_correlation_id()

    def test_correlation_id_in_output(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(logger_utils.LOG_FORMAT))
        handler.addFilter(logger_utils.CorrelationIdFilter())

        test_logger = logging.getLogger("test.correlation")
        test_logger.setLevel(logging.INFO)
        test_logger.handlers = [handler]
        test_logger.propagate = False

        logger_utils.set_correlation_id("abc123")
        test_logger.info("hello")
        output = stream.getvalue()

        self.assertIn("[abc123]", output)
        self.assertIn("hello", output)

    def test_service_specific_levels(self):
        crawler_logger = logger_utils.get_logger("services.crawler")
        safety_logger = logger_utils.get_logger("services.safety")

        self.assertEqual(crawler_logger.level, logging.DEBUG)
        self.assertEqual(safety_logger.level, logging.WARNING)

    def test_playwright_child_logger(self):
        playwright_logger = logger_utils.get_playwright_logger()
        self.assertEqual(playwright_logger.name, "playwright.browser")
        self.assertFalse(playwright_logger.propagate)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
