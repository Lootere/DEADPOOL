import ast
import unittest
from datetime import date, datetime, timezone
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "plugins" / "misc.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
FUNCTIONS = [
    node for node in TREE.body
    if isinstance(node, ast.FunctionDef)
    and node.name in {"_release_countdown_text", "_release_response"}
]
NAMESPACE = {
    "date": date,
    "datetime": datetime,
    "pytz": type("Pytz", (), {"timezone": staticmethod(lambda _name: timezone.utc)}),
    "TIMEZONE": "Asia/Kolkata",
    "html_escape": __import__("html").escape,
}
exec(compile(ast.Module(body=FUNCTIONS, type_ignores=[]), str(SOURCE), "exec"), NAMESPACE)
release_response = NAMESPACE["_release_response"]
countdown = NAMESPACE["_release_countdown_text"]


class ReleaseCountdownTests(unittest.TestCase):
    def test_upcoming_date_countdown(self):
        result = release_response(
            {"title": "Upcoming Film", "year": 2027, "release_date": "2026-11-12"},
            today=date(2026, 11, 3),
        )
        self.assertIn("UPCOMING RELEASE", result)
        self.assertIn("9 days to go", result)

    def test_released_date_has_no_negative_countdown(self):
        result = release_response(
            {"title": "Released Film", "release_date": "2026-11-02"},
            today=date(2026, 11, 3),
        )
        self.assertIn("RELEASED", result)
        self.assertNotIn("countdown", result.lower())

    def test_missing_and_year_only_dates_are_unconfirmed(self):
        for value in (None, "2027", "unknown"):
            with self.subTest(value=value):
                result = release_response(
                    {"title": "Unconfirmed", "release_date": value},
                    today=date(2026, 11, 3),
                )
                self.assertIn("Release date not officially confirmed yet.", result)

    def test_release_today_is_zero_day_boundary(self):
        result = release_response(
            {"title": "Today", "release_date": "2026-11-03"},
            today=date(2026, 11, 3),
        )
        self.assertIn("Releases today!", result)
        self.assertEqual(countdown("2026-11-03", today=date(2026, 11, 3)),
                         "⏳ <b>Releases today!</b>")


if __name__ == "__main__":
    unittest.main()
