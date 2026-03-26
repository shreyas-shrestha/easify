from app.utils.live_enrich_blocklist import should_skip_live_enrich_token


def test_blocks_common_words() -> None:
    assert should_skip_live_enrich_token("the") is True
    assert should_skip_live_enrich_token("hello") is False
