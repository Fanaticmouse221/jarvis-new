from jarvis.storage import Store


def test_conversation_lifecycle(store: Store):
    conv = store.create_conversation("First")
    assert store.get_conversation(conv["id"])["title"] == "First"

    store.add_message(conv["id"], "user", "Hello")
    reply = store.add_message(conv["id"], "assistant", "Good evening.", model="fake:echo")
    assert reply["model"] == "fake:echo"

    messages = store.get_messages(conv["id"])
    assert [(m["role"], m["content"]) for m in messages] == [("user", "Hello"), ("assistant", "Good evening.")]

    assert store.rename_conversation(conv["id"], "Renamed")
    assert store.get_conversation(conv["id"])["title"] == "Renamed"

    assert store.delete_conversation(conv["id"])
    assert store.get_conversation(conv["id"]) is None
    assert store.get_messages(conv["id"]) == []  # cascade delete


def test_list_orders_by_most_recent_activity(store: Store):
    a = store.create_conversation("A")
    b = store.create_conversation("B")
    store.add_message(a["id"], "user", "bump A")
    listed = store.list_conversations()
    assert [c["title"] for c in listed] == ["A", "B"]
    assert listed[0]["message_count"] == 1 and listed[1]["message_count"] == 0
    assert b["id"] in {c["id"] for c in listed}


def test_missing_ids_return_false(store: Store):
    assert not store.rename_conversation("nope", "x")
    assert not store.delete_conversation("nope")


def test_data_persists_across_instances(store: Store):
    conv = store.create_conversation("Persistent")
    store.add_message(conv["id"], "user", "Remember me")
    reopened = Store(store.path)  # simulates restarting JARVIS
    assert reopened.get_messages(conv["id"])[0]["content"] == "Remember me"
