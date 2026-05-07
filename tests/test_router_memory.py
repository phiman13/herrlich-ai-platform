import asyncio
import json
import pytest
from unittest.mock import patch

from agents.router import route_with_llm


def test_list_memories_intent():
    with patch("agents.router._call_claude_sync",
               return_value=json.dumps({
                   "intent": "memory",
                   "confidence": 9,
                   "params": {"mode": "list", "query": None},
                   "reasoning": "test",
               })):
        result = asyncio.run(route_with_llm("Was weißt du über mich?"))
    assert result["intent"] == "memory"
    assert result["params"]["mode"] == "list"


def test_delete_memory_intent():
    with patch("agents.router._call_claude_sync",
               return_value=json.dumps({
                   "intent": "memory",
                   "confidence": 9,
                   "params": {"mode": "delete", "query": "Siemens"},
                   "reasoning": "test",
               })):
        result = asyncio.run(route_with_llm("Vergiss was ich über Siemens gesagt habe"))
    assert result["intent"] == "memory"
    assert result["params"]["mode"] == "delete"
    assert result["params"]["query"] == "Siemens"


def test_memory_is_valid_intent():
    with patch("agents.router._call_claude_sync",
               return_value=json.dumps({
                   "intent": "memory",
                   "confidence": 9,
                   "params": {"mode": "list", "query": None},
                   "reasoning": "test",
               })):
        result = asyncio.run(route_with_llm("Erinnerungen zeigen"))
    # Should not fall back to personal (memory is now a valid intent)
    assert result["intent"] == "memory"
    assert result["confidence"] != 0
