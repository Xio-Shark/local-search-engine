from __future__ import annotations

from lse.tokenizer import split_identifier, tokenize_cjk_run, tokenize_stream


def test_code_identifier_tokenization():
    tokens = split_identifier("localSearchEngine")
    assert "local" in tokens
    assert "search" in tokens
    assert "engine" in tokens
    assert "localsearchengine" in tokens

    snake_tokens = split_identifier("delta_codec_v2")
    assert "delta" in snake_tokens
    assert "codec" in snake_tokens
    assert "v2" in snake_tokens

    path_tokens = split_identifier("com.localengine.IndexManager")
    assert "index" in path_tokens
    assert "manager" in path_tokens


def test_cjk_and_mixed_tokenization():
    tokens = tokenize_cjk_run("搜索引擎")
    assert "搜索引擎" in tokens
    assert "搜索" in tokens
    assert "索引" in tokens
    assert "引擎" in tokens
    assert "搜" in tokens
    assert "引" in tokens

    mixed_tokens = tokenize_stream("测试 C++多线程 与 GPT-4o架构 设计")
    assert "测试" in mixed_tokens
    assert "c++" in mixed_tokens
    assert "多线程" in mixed_tokens
    assert "gpt-4o" in mixed_tokens or "gpt" in mixed_tokens
    assert "架构" in mixed_tokens
