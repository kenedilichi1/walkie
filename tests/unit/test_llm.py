from walkie import llm


def test_extract_json_surrounding_noise():
    assert llm.extract_json('Sure! {"suggested_time": "17:00"} done') == {
        "suggested_time": "17:00"
    }


def test_extract_json_rejects_non_json():
    assert llm.extract_json("no json here") is None
    assert llm.extract_json("{broken") is None
    assert llm.extract_json("[1, 2]") is None


def test_complete_sends_system_then_user_message(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, host=None):
            pass

        def chat(self, model, messages, options):
            captured["messages"] = messages
            return {"message": {"content": "ok"}}

    monkeypatch.setattr(llm.ollama, "Client", FakeClient)
    out = llm.complete("user says", system="be brief", host="h", model="m")
    assert out == "ok"
    assert captured["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "user says"},
    ]


def test_complete_without_system_sends_only_user_message(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, host=None):
            pass

        def chat(self, model, messages, options):
            captured["messages"] = messages
            return {"message": {"content": "ok"}}

    monkeypatch.setattr(llm.ollama, "Client", FakeClient)
    llm.complete("user says", host="h", model="m")
    assert captured["messages"] == [{"role": "user", "content": "user says"}]
