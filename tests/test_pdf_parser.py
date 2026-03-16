"""
Tests for services/pdf_parser.py

All pure unit tests — no external dependencies.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from services.pdf_parser import _parse_table, _parse_lines


# ── _parse_table ───────────────────────────────────────────────────────────────

class TestParseTable:
    def test_normal_table(self):
        table = [
            ["Info", "601", "603"],
            ["Lawrence", "7:15a", "7:45a"],
        ]
        result = _parse_table(table)
        assert len(result) == 1
        assert "Info: Lawrence" in result[0]
        assert "601: 7:15a" in result[0]
        assert "603: 7:45a" in result[0]

    def test_multiple_data_rows(self):
        table = [
            ["Info", "601"],
            ["Lawrence", "7:15a"],
            ["Sunnyvale", "7:22a"],
        ]
        result = _parse_table(table)
        assert len(result) == 2

    def test_skips_empty_rows(self):
        table = [
            ["Info", "601"],
            [None, None],
            ["Lawrence", "7:15a"],
        ]
        result = _parse_table(table)
        assert len(result) == 1
        assert "Lawrence" in result[0]

    def test_skips_sentinel_dash_values(self):
        table = [
            ["Info", "601", "603"],
            ["Lawrence", "--", "7:45a"],
        ]
        result = _parse_table(table)
        assert "601" not in result[0]
        assert "603: 7:45a" in result[0]

    def test_skips_single_dash(self):
        table = [
            ["Info", "601"],
            ["Lawrence", "-"],
        ]
        result = _parse_table(table)
        assert "601" not in result[0]

    def test_empty_table_returns_empty(self):
        assert _parse_table([]) == []

    def test_header_only_returns_empty(self):
        assert _parse_table([["Info", "601"]]) == []

    def test_none_header_uses_info_label(self):
        table = [
            [None, "601"],
            ["Lawrence", "7:15a"],
        ]
        result = _parse_table(table)
        assert "Info: Lawrence" in result[0]

    def test_all_empty_cells_row_skipped(self):
        table = [
            ["Info", "601"],
            ["", ""],
        ]
        result = _parse_table(table)
        assert result == []

    def test_pipe_separator_between_parts(self):
        table = [
            ["Info", "601", "603"],
            ["Lawrence", "7:15a", "7:45a"],
        ]
        result = _parse_table(table)
        assert " | " in result[0]


# ── _parse_lines ───────────────────────────────────────────────────────────────

class TestParseLines:
    def test_exactly_five_lines(self):
        text = "\n".join([f"line{i}" for i in range(5)])
        result = _parse_lines(text)
        assert len(result) == 1
        assert "line0" in result[0]
        assert "line4" in result[0]

    def test_ten_lines_gives_two_blocks(self):
        text = "\n".join([f"line{i}" for i in range(10)])
        result = _parse_lines(text)
        assert len(result) == 2

    def test_seven_lines_gives_two_blocks(self):
        text = "\n".join([f"line{i}" for i in range(7)])
        result = _parse_lines(text)
        assert len(result) == 2

    def test_empty_string_returns_empty(self):
        assert _parse_lines("") == []

    def test_single_line(self):
        result = _parse_lines("only one line")
        assert len(result) == 1
        assert result[0] == "only one line"

    def test_whitespace_only_lines_stripped(self):
        text = "line1\n   \nline2\n\nline3"
        result = _parse_lines(text)
        # Whitespace-only lines should be excluded
        combined = " | ".join(result)
        assert "line1" in combined
        assert "line2" in combined
        assert "line3" in combined

    def test_blocks_joined_with_pipe(self):
        text = "a\nb\nc\nd\ne"
        result = _parse_lines(text)
        assert " | " in result[0]
