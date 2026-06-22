from app.agent.answer_builder import build_final_answer


def test_append_answer_uses_continuous_numbering_and_hides_internal_fields() -> None:
    answer = build_final_answer(
        "search_papers",
        [
            {"id": 6, "title": "Paper 6", "url": "https://arxiv.org/abs/6"},
            {"id": 7, "title": "Paper 7", "url": "https://arxiv.org/abs/7"},
        ],
        arguments={
            "append_mode": True,
            "result_offset": 5,
            "max_results": 2,
            "exclude_urls": ["https://arxiv.org/abs/1"],
        },
    )

    assert "6. Paper 6" in answer
    assert "7. Paper 7" in answer
    assert "exclude_urls" not in answer
    assert "append_mode" not in answer
    assert "routing_method" not in answer


def test_append_answer_does_not_repeat_old_results_when_no_new_results() -> None:
    answer = build_final_answer(
        "search_papers",
        [],
        arguments={"append_mode": True, "result_offset": 5, "max_results": 5},
    )

    assert "没有找到更多新的匹配结果" in answer
