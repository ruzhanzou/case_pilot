from casepilot_agent.tasks import BufferedDeltaPublisher


def test_delta_publisher_keeps_first_token_and_coalesces_small_chunks() -> None:
    published: list[str] = []
    current_time = [10.0]
    publisher = BufferedDeltaPublisher(
        published.append,
        min_chars=6,
        min_interval=0.05,
        clock=lambda: current_time[0],
    )

    publisher.add("首")
    publisher.add("个")
    publisher.add("分")
    assert published == ["首"]

    current_time[0] += 0.06
    publisher.add("片")
    assert published == ["首", "个分片"]

    publisher.add("abcdef")
    publisher.add("尾")
    publisher.flush()
    assert published == ["首", "个分片", "abcdef", "尾"]
