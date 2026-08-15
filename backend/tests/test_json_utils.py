import json
import pytest
from app.services.json_utils import strip_markdown_json

def test_plain_json_string():
    raw = """{"name": "test", "value": 123}"""
    result = strip_markdown_json(raw)
    assert result == raw
    assert json.loads(result) == {"name": "test", "value": 123}

def test_plain_json_string_with_surrounding_whitespace():
    raw = """   
	 {"key": "val"} 
  """
    result = strip_markdown_json(raw)
    assert result == '{"key": "val"}'
    assert json.loads(result) == {"key": "val"}

def test_json_inside_code_block_with_language_tag():
    raw = """```json
{"candidates": [{"category": "numeric_value"}]}
```"""
    result = strip_markdown_json(raw)
    assert result == '{"candidates": [{"category": "numeric_value"}]}'
    assert json.loads(result) == {"candidates": [{"category": "numeric_value"}]}

def test_json_inside_code_block_with_uppercase_language_tag():
    raw = """```JSON
{"status": "ok"}
```"""
    result = strip_markdown_json(raw)
    assert result == '{"status": "ok"}'
    assert json.loads(result) == {"status": "ok"}

def test_json_inside_code_block_without_language_tag():
    raw = """```
{"candidates": []}
```"""
    result = strip_markdown_json(raw)
    assert result == '{"candidates": []}'
    assert json.loads(result) == {"candidates": []}

def test_json_inside_code_block_with_surrounding_commentary():
    raw = """Here is the analysis:
```json
{"site": "산노리 2지점"}
```
Please review."""
    result = strip_markdown_json(raw)
    assert result == '{"site": "산노리 2지점"}'
    assert json.loads(result) == {"site": "산노리 2지점"}

def test_nested_code_blocks():
    # Markdown with inline code formatting or backtick symbols inside JSON fields
    raw = """```json
{"category": "annotation_resolution", "rationale": "Use `foo` instead of `bar`"}
```"""
    result = strip_markdown_json(raw)
    assert json.loads(result) == {"category": "annotation_resolution", "rationale": "Use `foo` instead of `bar`"}

def test_multiple_code_blocks_extracts_first():
    raw = """```json
{"first": 1}
```
Some text
```json
{"second": 2}
```"""
    result = strip_markdown_json(raw)
    assert json.loads(result) == {"first": 1}

def test_empty_and_whitespace_input():
    assert strip_markdown_json("") == ""
    assert strip_markdown_json("""   
	  """) == ""
    assert strip_markdown_json(None) == ""

