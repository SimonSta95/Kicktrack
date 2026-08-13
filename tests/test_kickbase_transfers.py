from app.kickbase import KickbaseClient


def test_manager_transfer_history_paginates_and_deduplicates_without_looping():
    client = KickbaseClient()
    calls = []

    page1 = [{"pi": str(i), "tty": 1, "trp": i, "dt": f"2026-08-01T00:{i:02d}:00Z"} for i in range(20)]
    page2 = [{"pi": "20", "tty": 2, "trp": 99, "dt": "2026-08-02T00:00:00Z"}]

    def fake_get(path, *, params=None):
        calls.append(params)
        if not params:
            return {"u": "m1", "it": page1}
        if params.get("start") == 20:
            return {"u": "m1", "it": page2}
        return {"u": "m1", "it": []}

    client._get_json = fake_get
    result = client.manager_transfers("l1", "m1")
    client.close()

    assert len(result["it"]) == 21
    assert calls == [None, {"start": 20}]
