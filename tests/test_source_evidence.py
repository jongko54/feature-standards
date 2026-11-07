"""Lexical evidence regressions, with no compiler, host build or model calls."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from source_evidence import strip_c_style_comments


def blank(text):
    return "".join(character if character.isspace() else " " for character in text)


class SourceEvidenceTests(unittest.TestCase):
    def test_java_wildcard_and_separate_controller_javadoc_regression(self):
        application = 'class App { String route = "/api/**"; }\n'
        controller = (
            "import dev.featurestandards.core.authorization.*;\n"
            "import dev.featurestandards.core.listing.Listing;\n"
            "policy.decide(); Listing.parseQuery(); Listing.page();\n"
        )
        tail = "/** Controller errors. */\nclass Errors {}\n"
        combined = application + controller + tail
        old = re.sub(r"/\*.*?\*/|//[^\n]*", "", combined, flags=re.DOTALL)
        self.assertNotIn("policy.decide()", old)
        actual = "".join(
            strip_c_style_comments(source) for source in (application, controller, tail)
        )
        self.assertEqual(
            actual,
            application
            + controller
            + blank(tail.splitlines(True)[0])
            + "class Errors {}\n",
        )

    def test_real_line_block_and_doc_comments_lose_fake_api_evidence(self):
        comments = [
            "// Policy decide() parseQuery() page()",
            "/* 'fake' Policy \"page()\" */",
            "/** parseQuery() */",
        ]
        for comment in comments:
            with self.subTest(comment=comment):
                source = comment + "\nreal();"
                self.assertEqual(
                    strip_c_style_comments(source), blank(comment) + "\nreal();"
                )

    def test_java_escaped_strings_and_chars_keep_literal_markers(self):
        literals = [
            r'"http://host/api/**"',
            r'"quote: \" // /* */ \\"',
            r"'/'",
            r"'\''",
            r"'\\'",
            r"'\u0041'",
        ]
        for literal in literals:
            with self.subTest(literal=literal):
                source = literal + "; /* real */\n"
                self.assertEqual(
                    strip_c_style_comments(source),
                    literal + "; " + blank("/* real */") + "\n",
                )

    def test_java_text_block_handles_quotes_escapes_and_comment_markers(self):
        literal = '"""  \r\nhttp://host/api/**\n"quoted" // stays\n\\""" still inside /* body */\n"""'
        source = literal + "; // real\r\nnext();"
        self.assertEqual(
            strip_c_style_comments(source),
            literal + "; " + blank("// real") + "\r\nnext();",
        )

    def test_go_raw_and_interpreted_urls_do_not_start_comments(self):
        for literal in (
            '`http://host/\n/* raw */ " quote \\`',
            '"http://host/path/*literal*/"',
        ):
            source = literal + " // remove\n"
            self.assertEqual(
                strip_c_style_comments(source, language="go"),
                literal + " " + blank("// remove") + "\n",
            )

    def test_rust_raw_string_byte_and_c_prefixes_with_matching_hashes(self):
        for prefix in ("r", "br", "cr"):
            for count in (0, 1, 2, 255):
                hashes = "#" * count
                body = (
                    "// body /* body */ \\"
                    if not count
                    else '// body /* body */ \\"' + "#" * (count - 1) + " partial"
                )
                literal = prefix + hashes + '"' + body + '"' + hashes
                with self.subTest(prefix=prefix, hashes=count):
                    self.assertEqual(
                        strip_c_style_comments(
                            literal + " /* real */", language="rust"
                        ),
                        literal + " " + blank("/* real */"),
                    )

    def test_rust_lifetimes_labels_and_raw_lifetimes_are_not_character_strings(self):
        source = "fn f<'a, 'static, '_>(x: &'a str) { 'label: loop { /* fake Policy */ real(); } }\nlet x: &'r#async str; // fake page()\n"
        expected = source.replace(
            "/* fake Policy */", blank("/* fake Policy */")
        ).replace("// fake page()", blank("// fake page()"))
        self.assertEqual(strip_c_style_comments(source, language="rust"), expected)

    def test_rust_and_go_character_escape_forms_do_not_swallow_later_comments(self):
        for literal in (
            "'😀'",
            r"'\u{1F600}'",
            r"'\x2f'",
            r"b'/'",
            r"'\U0001F600'",
            r"'\141'",
            "'_'",
            "'a'",
        ):
            with self.subTest(literal=literal):
                language = "go" if literal in {r"'\U0001F600'", r"'\141'"} else "rust"
                self.assertEqual(
                    strip_c_style_comments(literal + " // fake\n", language=language),
                    literal + " " + blank("// fake") + "\n",
                )

    def test_rust_nested_comments_remove_all_depths_and_keep_line_positions(self):
        comment = "/* outer Policy\r\n /* inner parseQuery() */\n page() */"
        self.assertEqual(
            strip_c_style_comments(comment + " real();", language="rust"),
            blank(comment) + " real();",
        )

    def test_java_and_go_blocks_do_not_nest_and_keep_real_calls(self):
        source = "/* outer /* marker */ actualCall(); /* tail */"
        expected = (
            blank("/* outer /* marker */") + " actualCall(); " + blank("/* tail */")
        )
        for language in ("java", "go"):
            self.assertEqual(
                strip_c_style_comments(source, language=language), expected
            )

    def test_unterminated_comment_cannot_consume_a_separate_file(self):
        first, second = "/* unfinished fake()", "actual.decide(); // fake page()\n"
        result = strip_c_style_comments(first) + "\n" + strip_c_style_comments(second)
        self.assertEqual(
            result,
            blank(first) + "\nactual.decide(); " + blank("// fake page()") + "\n",
        )

    def test_unterminated_strings_and_trailing_escapes_finish_without_damage(self):
        for source in (
            '"unterminated /* literal',
            '"tail\\',
            "`raw /* literal",
            'r##"raw // literal',
            '"""\ntext block /* literal',
            "'\\",
        ):
            with self.subTest(source=source):
                language = (
                    "go"
                    if source.startswith("`")
                    else "rust"
                    if source.startswith("r#")
                    else "java"
                )
                self.assertEqual(
                    strip_c_style_comments(source, language=language), source
                )
        self.assertEqual(strip_c_style_comments("// end"), blank("// end"))
        self.assertEqual(strip_c_style_comments("/* end\\"), blank("/* end\\"))

    def test_comments_keep_unicode_newlines_and_cannot_join_identifiers(self):
        source = "한글😀\tparse/* 합쳐지면 안 됨 */Query\r\n// 주석\rnext();"
        expected = source.replace(
            "/* 합쳐지면 안 됨 */", blank("/* 합쳐지면 안 됨 */")
        ).replace("// 주석", blank("// 주석"))
        result = strip_c_style_comments(source)
        self.assertEqual(result, expected)
        self.assertEqual(len(result), len(source))
        self.assertNotIn("parseQuery", result)
        self.assertEqual(result.count("\r"), source.count("\r"))
        self.assertEqual(result.count("\n"), source.count("\n"))
