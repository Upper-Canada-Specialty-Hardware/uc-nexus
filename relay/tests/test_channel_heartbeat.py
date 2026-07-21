"""The backend's application-level heartbeat (issue #277): a {"type": "ping"} data message the relay
answers with {"type": "pong"} so the backend can reap a dead relay from its registry within ~a minute.
Distinct from the websockets client's protocol ping (proxy keepalive), which the library auto-answers."""

from ucnexus_relay import channel


def test_ping_control_message_is_answered_with_a_pong():
    assert channel._heartbeat_reply({"type": "ping"}) == {"type": "pong"}


def test_job_messages_are_not_treated_as_heartbeat():
    job = {"id": "abc", "op": "list_vendors", "company": "TUBC", "payload": {}}
    assert channel._heartbeat_reply(job) is None


def test_pong_and_non_dict_messages_are_not_treated_as_heartbeat():
    assert channel._heartbeat_reply({"type": "pong"}) is None
    assert channel._heartbeat_reply("not-a-dict") is None
    assert channel._heartbeat_reply(None) is None
