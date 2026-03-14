# Phase 1b — RAG pipeline tests
import json
import pytest


def load_golden_queries():
    with open("tests/golden_queries.json") as f:
        return json.load(f)


@pytest.mark.parametrize("case", load_golden_queries())
def test_rag_golden(case):
    # TODO: call services/rag.py and assert expected output
    pass
