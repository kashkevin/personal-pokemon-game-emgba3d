"""KNOWN_ISSUES MS-141c: the host's wireless minigame groups and their protocol (minigame_groups.py,
minigame_protocol.py)."""
import pytest

from emerald_multiplayer.minigame_groups import MinigameGroups
from emerald_multiplayer.minigame_protocol import (
    closed_frame, link_frame, link_player, parse_game_frame, started_frame, validate_minigame_push,
    validate_minigame_reply, validate_minigame_request)
from emerald_multiplayer.protocol import PROTOCOL_VERSION, ProtocolError

NAMES = {"a": "ALICE", "b": "BEN", "c": "CARA", "d": "DAN", "e": "EVE"}
EPOCHS = {p: 7 for p in NAMES}
REQ = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"


def player(name="AB", gender=0):
    raw = bytes([0xBB, 0xBC] + [0xFF] * 6) + bytes([gender, 2, 0x03, 0x40, 1, 2, 3, 4])
    assert len(raw) == 16
    return raw


def test_open_join_start_pushes_every_players_start_in_order():
    groups = MinigameGroups()
    view, pushes = groups.open("a", "berry_crush", player(), NAMES)
    assert view["players"][0]["player_id"] == "a" and view["index"] == 0 and not view["started"] and pushes == []
    gid = view["group_id"]
    assert groups.status("b", "berry_crush", NAMES)["groups"] == [
        {"group_id": gid, "leader_name": "ALICE", "players": 1, "minimum": 2}]
    assert groups.status("b", "pokemon_jump", NAMES)["groups"] == []           # another game's groups are not listed
    view, _ = groups.join("b", gid, player(gender=1), NAMES)
    assert [p["player_id"] for p in view["players"]] == ["a", "b"] and view["index"] == 1
    with pytest.raises(ProtocolError) as error:
        groups.start("b", gid, EPOCHS, NAMES)
    assert error.value.code == "minigame_not_leader"
    view, pushes = groups.start("a", gid, EPOCHS, NAMES)
    assert view["started"]
    assert [(p, m["index"]) for p, m in pushes] == [("a", 0), ("b", 1)]
    assert all(m["type"] == "minigame_started" and m["link_players"] == [player().hex(), player(gender=1).hex()]
               for _, m in pushes)
    for _, message in pushes:
        validate_minigame_push(message, 7)
    assert groups.status("c", "berry_crush", NAMES)["groups"] == []          # a started group is no longer open


def test_minimum_players_and_full_groups():
    groups = MinigameGroups(max_players=4)
    gid = groups.open("a", "dodrio", player(), NAMES)[0]["group_id"]
    groups.join("b", gid, player(), NAMES)
    with pytest.raises(ProtocolError) as error:
        groups.start("a", gid, EPOCHS, NAMES)                                  # Dodrio Berry Picking takes 3
    assert error.value.code == "minigame_too_few"
    groups.join("c", gid, player(), NAMES)
    groups.join("d", gid, player(), NAMES)
    with pytest.raises(ProtocolError) as error:
        groups.join("e", gid, player(), NAMES)
    assert error.value.code == "minigame_full"
    assert groups.start("a", gid, EPOCHS, NAMES)[0]["started"]


def test_link_relay_leader_to_members_member_to_leader():
    groups = MinigameGroups()
    gid = groups.open("a", "pokemon_jump", player(), NAMES)[0]["group_id"]
    groups.join("b", gid, player(), NAMES)
    groups.join("c", gid, player(), NAMES)
    assert groups.link("a", gid, b"", EPOCHS) == []                            # not started: nothing relayed
    groups.start("a", gid, EPOCHS, NAMES)
    frame = bytes(range(70))
    out = groups.link("a", gid, frame, EPOCHS)
    assert [(p, m["source"], m["data"]) for p, m in out] == [("b", 0, frame.hex()), ("c", 0, frame.hex())]
    assert [(p, m["source"]) for p, m in groups.link("a", gid, b"", EPOCHS)] == [("b", 0), ("c", 0)]   # empty frames too
    command = bytes(range(14))
    out = groups.link("c", gid, command, EPOCHS)
    assert [(p, m["source"], m["data"]) for p, m in out] == [("a", 2, command.hex())]
    for _, message in out:
        validate_minigame_push(message, 7)
    with pytest.raises(ProtocolError):
        groups.link("b", gid, frame, EPOCHS)                                    # a member never sends a whole frame
    with pytest.raises(ProtocolError):
        groups.link("a", gid, command, EPOCHS)                                  # nor the leader a lone command
    assert groups.link("e", gid, command, EPOCHS) == []                         # an outsider's frame is dropped


def test_leaving_before_and_after_the_start():
    groups = MinigameGroups()
    gid = groups.open("a", "berry_crush", player(), NAMES)[0]["group_id"]
    groups.join("b", gid, player(), NAMES)
    groups.join("c", gid, player(), NAMES)
    assert groups.leave("c", gid, EPOCHS) == ({"left": True}, [])              # a member leaves an unstarted group
    result, pushes = groups.leave("a", gid, EPOCHS)                             # its leader ends it: members are told
    assert result == {"left": True}
    assert [(p, m["type"], m["reason"]) for p, m in pushes] == [("b", "minigame_closed", "leader_ended")]
    assert groups.group_of("b") is None
    # started: a player whose game closed the link leaves quietly; the group goes with its last player
    gid = groups.open("a", "berry_crush", player(), NAMES)[0]["group_id"]
    groups.join("b", gid, player(), NAMES)
    groups.start("a", gid, EPOCHS, NAMES)
    assert groups.leave("b", gid, EPOCHS) == ({"left": True}, [])
    assert groups.link("a", gid, bytes(70), EPOCHS) == []                       # nothing goes to a member who left
    assert groups.leave("a", gid, EPOCHS) == ({"left": True}, [])
    assert groups.group_of("a") is None and gid not in groups._groups


def test_a_game_gone_from_a_started_group_ends_it_for_the_others():
    groups = MinigameGroups()
    gid = groups.open("a", "dodrio", player(), NAMES)[0]["group_id"]
    groups.join("b", gid, player(), NAMES)
    groups.join("c", gid, player(), NAMES)
    # before the start a lost leave is a leave
    assert groups.leave("c", gid, EPOCHS, lost=True) == ({"left": True}, [])
    groups.join("c", gid, player(), NAMES)
    groups.start("a", gid, EPOCHS, NAMES)
    # a member's game closed the link at its end: quiet; then the leader's game is lost: the one still in is told
    assert groups.leave("b", gid, EPOCHS) == ({"left": True}, [])
    result, pushes = groups.leave("a", gid, EPOCHS, lost=True)
    assert result == {"left": True}
    assert [(p, m["type"], m["reason"]) for p, m in pushes] == [("c", "minigame_closed", "player_lost")]
    assert gid not in groups._groups and groups.group_of("c") is None
    # a lost leave of a group already gone does nothing
    assert groups.leave("c", gid, EPOCHS, lost=True) == ({"left": False}, [])


def test_a_disconnect_ends_a_started_group_for_the_others():
    groups = MinigameGroups()
    gid = groups.open("a", "pokemon_jump", player(), NAMES)[0]["group_id"]
    groups.join("b", gid, player(), NAMES)
    groups.join("c", gid, player(), NAMES)
    groups.start("a", gid, EPOCHS, NAMES)
    pushes = groups.disconnected("b", EPOCHS)
    assert sorted((p, m["reason"]) for p, m in pushes) == [("a", "player_lost"), ("c", "player_lost")]
    assert groups.group_of("a") is None
    # unstarted: a member's disconnect is a leave, a leader's ends the group
    gid = groups.open("a", "berry_crush", player(), NAMES)[0]["group_id"]
    groups.join("b", gid, player(), NAMES)
    assert groups.disconnected("b", EPOCHS) == []
    assert groups.disconnected("a", EPOCHS) == []
    assert gid not in groups._groups


def test_opening_or_joining_leaves_an_unstarted_group_first():
    groups = MinigameGroups()
    first = groups.open("a", "berry_crush", player(), NAMES)[0]["group_id"]
    groups.join("b", first, player(), NAMES)
    second, pushes = groups.open("a", "pokemon_jump", player(), NAMES)          # the leader's old group ends
    assert [(p, m["reason"]) for p, m in pushes] == [("b", "leader_ended")]
    groups.open("c", "pokemon_jump", player(), NAMES)
    groups.join("b", second["group_id"], player(), NAMES)
    groups.start("a", second["group_id"], EPOCHS, NAMES)
    with pytest.raises(ProtocolError) as error:
        groups.open("a", "dodrio", player(), NAMES)                              # still linked: refused
    assert error.value.code == "minigame_busy"
    assert groups.stop(EPOCHS) and groups._groups == {}


def test_requests_replies_and_game_frames():
    request = {"type": "minigame_open", "session_epoch": 3, "request_id": REQ, "activity": "berry_crush",
               "link_player": player().hex()}
    assert validate_minigame_request(request, 3)["activity"] == "berry_crush"
    for bad in ({**request, "activity": "chess"}, {**request, "session_epoch": 4}, {**request, "extra": 1},
                {**request, "link_player": player().hex()[:-2]}, {**request, "link_player": player().hex().upper()}):
        with pytest.raises(ProtocolError):
            validate_minigame_request(bad, 3)
    leave = {"type": "minigame_leave", "session_epoch": 3, "request_id": REQ, "group_id": 0, "lost": False}
    assert validate_minigame_request(leave, 3)["lost"] is False
    for bad in ({**leave, "lost": 0}, {k: v for k, v in leave.items() if k != "lost"}):
        with pytest.raises(ProtocolError):
            validate_minigame_request(bad, 3)
    link = {"type": "minigame_link", "session_epoch": 3, "group_id": 5, "data": bytes(14).hex()}
    assert validate_minigame_request(link, 3)["group_id"] == 5
    with pytest.raises(ProtocolError):
        validate_minigame_request({**link, "data": bytes(15).hex()}, 3)
    with pytest.raises(ProtocolError):
        link_player((bytes([0xBB] * 8) + bytes([2, 2]) + bytes(6)).hex())        # gender 2
    groups = MinigameGroups()
    view = groups.open("a", "berry_crush", player(), NAMES)[0]
    reply = {"type": "minigame_result", "protocol": PROTOCOL_VERSION, "session_epoch": 3, "request_id": REQ,
             "operation": "open", "result": view}
    assert validate_minigame_reply(reply, "a", 3, request)["result"]["group_id"] == view["group_id"]
    with pytest.raises(ProtocolError):
        validate_minigame_reply(reply, "b", 3, request)                           # the view names its reader
    status = {**reply, "operation": "status", "result": groups.status("a", "berry_crush", NAMES)}
    validate_minigame_reply(status, "a", 3)
    # the game's frames
    hello = bytes([2, 1, 10]) + player()
    assert parse_game_frame(hello) == ("hello", ("berry_crush", player()))
    assert [parse_game_frame(bytes([2, 2, reason])) for reason in (0, 1, 2)] == [("leave", 0), ("leave", 1), ("leave", 2)]
    assert parse_game_frame(bytes([1]) + bytes(14)) == ("link", bytes(14))
    assert parse_game_frame(bytes([1])) == ("link", b"")
    for bad in (b"", bytes([1]) + bytes(13), bytes([2, 1, 99]) + player(), bytes([3, 1]), bytes([2, 2]),
                bytes([2, 2, 3])):
        with pytest.raises(ValueError):
            parse_game_frame(bad)
    frame = started_frame("pokemon_jump", 1, [player(), player(gender=1)])
    assert frame[:5] == bytes([2, 1, 9, 2, 1]) and len(frame) == 5 + 32
    assert link_frame(2, bytes(14)) == bytes([1, 2]) + bytes(14)
    assert closed_frame("player_lost")[:2] == bytes([2, 2])
