import ast
import re
import unittest
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "plugins" / "pm_filter.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
FUNCTION = next(
    node for node in TREE.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "_normalize_conversational_search"
)
NAMESPACE = {"re": re}
exec(compile(ast.Module(body=[FUNCTION], type_ignores=[]), str(SOURCE), "exec"), NAMESPACE)
normalize = NAMESPACE["_normalize_conversational_search"]


class ConversationalSearchTests(unittest.TestCase):
    def test_removes_conversational_filler_and_genre_request_words(self):
        self.assertEqual(normalize("2023 ki mast action movie"), "2023 action")
        self.assertEqual(normalize("Please find a great action film"), "a great action")

    def test_preserves_articles_and_title_words(self):
        for title in ("The Batman", "A Beautiful Mind", "An Education"):
            with self.subTest(title=title):
                self.assertEqual(normalize(title), title.casefold())

    def test_normalizes_punctuation_as_word_boundaries(self):
        self.assertEqual(normalize("Dune: Part Two (2024)!"), "dune part two 2024")
        self.assertEqual(normalize("Spider-Man: No Way Home"), "spider man no way home")

    def test_preserves_numbers_and_multiword_titles(self):
        self.assertEqual(normalize("3 Idiots 2009"), "3 idiots 2009")
        self.assertEqual(normalize("The Lord of the Rings: 2001"), "the lord of the rings 2001")

    def test_preserves_search_filter_terms(self):
        query = "The Boys S02E03 Hindi 1080p 2023"
        self.assertEqual(normalize(query), query.casefold())

    def test_ordinary_queries_remain_searchable(self):
        for query in ("Jawan", "Dune Part Two", "The Batman 2022"):
            with self.subTest(query=query):
                self.assertEqual(normalize(query), query.casefold())


if __name__ == "__main__":
    unittest.main()
