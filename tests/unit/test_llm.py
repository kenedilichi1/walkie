from walkie import llm


def test_extract_json_surrounding_noise():
    assert llm.extract_json('Sure! {"suggested_time": "17:00"} done') == {
        "suggested_time": "17:00"
    }


def test_extract_json_rejects_non_json():
    assert llm.extract_json("no json here") is None
    assert llm.extract_json("{broken") is None
    assert llm.extract_json("[1, 2]") is None
