"""Small lexical helpers for source evidence; not a compiler or anti-copy proof.

Process each source file separately. Comment characters become spaces; existing
whitespace, newlines and quoted contents remain unchanged.
Java/Go blocks do not nest; Rust blocks do. Supported forms follow the Rust token
and comment reference and JLS3 string/text-block rules, without Java Unicode-escape
preprocessing or full grammar/edition validation. Invalid unfinished strings are
preserved to EOF, and unfinished comments are blanked to EOF. Preserved strings
can still contain fake API names: the output remains weak lexical evidence.

https://doc.rust-lang.org/reference/tokens.html
https://doc.rust-lang.org/reference/comments.html
https://docs.oracle.com/javase/specs/jls/se25/html/jls-3.html
"""

import re

_TEXT_BLOCK = re.compile(r'"""[ \t\f]*(?:\r\n|\r|\n)')


def _quoted_end(text, start, delimiter):
    cursor = start + len(delimiter)
    while cursor < len(text):
        if text[cursor] == "\\":
            cursor += 2
        elif text.startswith(delimiter, cursor):
            return cursor + len(delimiter)
        else:
            cursor += 1
    return len(text)


def _rust_raw_end(text, start):
    if start and ("_" + text[start - 1]).isidentifier():
        return None
    for prefix in ("br", "cr", "r"):
        if not text.startswith(prefix, start):
            continue
        cursor = start + len(prefix)
        while (
            cursor < len(text)
            and text[cursor] == "#"
            and cursor - start - len(prefix) <= 255
        ):
            cursor += 1
        count = cursor - start - len(prefix)
        if count > 255 or cursor >= len(text) or text[cursor] != '"':
            continue
        closing = '"' + "#" * count
        end = text.find(closing, cursor + 1)
        return len(text) if end < 0 else end + len(closing)
    return None


def _rust_character_end(text, start):
    cursor = start + 1
    if cursor >= len(text):
        return None
    if text[cursor] == "\\":
        # An escaped character cannot be a Rust lifetime. Keeping an invalid
        # unfinished form to EOF avoids interpreting its contents as real code.
        return _quoted_end(text, start, "'")
    if (
        text[cursor] not in "'\r\n"
        and cursor + 1 < len(text)
        and text[cursor + 1] == "'"
    ):
        return cursor + 2
    # 'a, 'static, '_ and 'r#ident are lifetime/label tokens, not long strings.
    return None


def strip_c_style_comments(text: str, *, language: str = "java") -> str:
    """Blank comments, preserve other characters and character offsets; call per file.

    Languages are java (default), go and rust. This is deliberately not a full
    lexer/parser, Unicode-escape translator or runtime/anti-copy verification.
    """
    if not isinstance(text, str):
        raise TypeError("source-text-must-be-string")
    if language not in {"java", "go", "rust"}:
        raise ValueError("unsupported-source-language")
    output = list(text)
    cursor, length = 0, len(text)
    while cursor < length:
        start = cursor
        if text.startswith("//", cursor):
            cursor += 2
            while (
                cursor < length
                and text[cursor] != "\n"
                and (language != "java" or text[cursor] != "\r")
            ):
                cursor += 1
        elif text.startswith("/*", cursor):
            cursor += 2
            depth = 1
            while cursor < length and depth:
                if language == "rust" and text.startswith("/*", cursor):
                    depth += 1
                    cursor += 2
                elif text.startswith("*/", cursor):
                    depth -= 1
                    cursor += 2
                else:
                    cursor += 1
        else:
            end = _rust_raw_end(text, cursor) if language == "rust" else None
            if end is not None:
                cursor = end
            elif text[cursor] == '"':
                delimiter = '"'
                if language == "java" and _TEXT_BLOCK.match(text, cursor):
                    delimiter = '"""'
                cursor = _quoted_end(text, cursor, delimiter)
            elif language == "go" and text[cursor] == "`":
                end = text.find("`", cursor + 1)
                cursor = length if end < 0 else end + 1
            elif text[cursor] == "'":
                end = (
                    _rust_character_end(text, cursor)
                    if language == "rust"
                    else _quoted_end(text, cursor, "'")
                )
                cursor = end if end is not None else cursor + 1
            else:
                cursor += 1
            continue
        for index in range(start, cursor):
            if not text[index].isspace():
                output[index] = " "
    return "".join(output)
