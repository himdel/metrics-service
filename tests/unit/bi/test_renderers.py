import pytest

from apps.bi.v1.renderers import csv_safe, json_to_csv


class TestCsvSafe:
    def test_normal_string(self):
        assert csv_safe("hello") == "hello"

    def test_equals_prefix(self):
        assert csv_safe("=cmd") == "'=cmd"

    def test_plus_prefix(self):
        assert csv_safe("+cmd") == "'+cmd"

    def test_minus_prefix(self):
        assert csv_safe("-cmd") == "'-cmd"

    def test_at_prefix(self):
        assert csv_safe("@cmd") == "'@cmd"

    def test_tab_prefix(self):
        assert csv_safe("\tcmd") == "'\tcmd"

    def test_none(self):
        assert csv_safe(None) == ""

    def test_number(self):
        assert csv_safe(42) == "42"


class TestJsonToCsv:
    def test_flat_dict(self):
        result = json_to_csv({"a": 1, "b": 2})
        lines = result.strip().split("\n")
        assert len(lines) == 2
        assert "a" in lines[0]
        assert "b" in lines[0]
        assert "1" in lines[1]

    def test_list_of_dicts(self):
        data = [{"name": "foo", "count": 1}, {"name": "bar", "count": 2}]
        result = json_to_csv(data)
        lines = result.strip().split("\n")
        assert len(lines) == 3
        assert "name" in lines[0]
        assert "foo" in lines[1]
        assert "bar" in lines[2]

    def test_nested_dict(self):
        data = {"top": {"nested": "value"}}
        result = json_to_csv(data)
        lines = result.strip().split("\n")
        assert "top.nested" in lines[0]
        assert "value" in lines[1]

    def test_empty_dict(self):
        result = json_to_csv({})
        assert result.strip() == ""

    def test_empty_list(self):
        result = json_to_csv([])
        lines = result.strip().split("\n")
        assert "value" in lines[0]

    def test_csv_injection_prevention(self):
        data = {"key": "=SUM(A1)"}
        result = json_to_csv(data)
        assert "'=SUM(A1)" in result
