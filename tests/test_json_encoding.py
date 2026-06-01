# SPDX-FileCopyrightText: 2026 AmariNoa
#
# SPDX-License-Identifier: MIT

"""Regression tests for the MCP JSON serialization (_json).

Guards against the bug where json.dumps' default ensure_ascii=True emitted
non-ASCII text (e.g. Japanese) as \\uXXXX escape sequences, which some local
LLMs could not interpret when the string was handed back to them.
"""

import json

from leantime_mcp.server import _json


def test_no_unicode_escape_sequences_in_output():
    """Non-ASCII characters are emitted literally, not as \\uXXXX escapes."""
    out = _json({"clientName": "TestParam天", "lastname": "天鈴"})
    # The literal two-character sequence backslash-u must not appear.
    assert "\\u" not in out
    assert "天鈴" in out
    assert "TestParam天" in out


def test_output_is_valid_json_and_round_trips():
    """Output parses back to the original object (decoded characters intact)."""
    obj = {
        "headline": "MCP接続検証テスト",
        "clientName": "天鈴のあ",
        "nested": [{"name": "のあ"}, {"name": "天鈴"}],
        "ascii": "plain",
        "number": 3,
    }
    out = _json(obj)
    assert json.loads(out) == obj


def test_survives_mcp_wire_reencoding():
    """Even if an outer layer re-encodes with ensure_ascii=True, the receiver
    parses the content back to the same decoded characters."""
    content = _json({"lastname": "天鈴"})
    wire = json.dumps({"content": content})  # default ensure_ascii=True
    recovered = json.loads(wire)["content"]
    assert recovered == content
    assert json.loads(recovered) == {"lastname": "天鈴"}


def test_ascii_only_output_unchanged():
    """Pure-ASCII payloads serialize exactly as before (indent=2)."""
    obj = {"a": 1, "b": "x"}
    assert _json(obj) == json.dumps(obj, indent=2)


def test_indentation_preserved():
    """Pretty-printing (indent=2) is retained."""
    out = _json({"a": "天"})
    assert out == '{\n  "a": "天"\n}'
