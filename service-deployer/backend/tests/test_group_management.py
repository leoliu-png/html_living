"""AI-2871: group lifecycle (incremental members, rename, delete) and audit reads."""

from sqlalchemy import select
from test_page_datasets import make_client
from test_sharing_followups import ADMIN, audit_actions, create_group, publish, user

from app.models import PageAsset
from app.models.sharing import GroupMember, PageGrant, SharingGroup

ALICE = "alice@feedmob.com"
BOB = "bob@feedmob.com"
CAROL = "carol@feedmob.com"
LEO = "leo_liu@feedmob.com"


def members_of(client, who, slug="team"):
    items = client.get("/api/groups", headers=user(who)).json()["data"]["items"]
    return next(g for g in items if g["slug"] == slug)


def test_patch_adds_and_removes_members_without_resending_the_list(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    create_group(client, members=[CAROL])
    response = client.patch(
        "/api/groups/team/members", headers=user(ALICE), json={"add_members": [LEO, BOB]}
    )
    assert response.status_code == 200, response.text
    state = members_of(client, ALICE)
    assert state["managers"] == [ALICE]
    assert state["members"] == sorted([ALICE, BOB, CAROL, LEO])
    # Adding an existing manager as a member keeps their role; remove works for anyone.
    client.patch(
        "/api/groups/team/members",
        headers=user(ALICE),
        json={"add_members": [ALICE], "remove": [BOB]},
    )
    state = members_of(client, ALICE)
    assert state["managers"] == [ALICE] and BOB not in state["members"]
    assert len(audit_actions(factory, "group_members_changed")) == 2


def test_patch_promotes_demotes_and_keeps_one_manager(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    create_group(client, members=[CAROL])
    assert (
        client.patch(
            "/api/groups/team/members", headers=user(ALICE), json={"add_managers": [CAROL]}
        ).status_code
        == 200
    )
    assert members_of(client, ALICE)["managers"] == sorted([ALICE, CAROL])
    # Demote Alice in one call: remove, then add back as plain member.
    assert (
        client.patch(
            "/api/groups/team/members",
            headers=user(CAROL),
            json={"remove": [ALICE], "add_members": [ALICE]},
        ).status_code
        == 200
    )
    assert members_of(client, ALICE)["managers"] == [CAROL]
    # The last manager cannot leave; nothing is changed by the refused call.
    refused = client.patch(
        "/api/groups/team/members",
        headers=user(CAROL),
        json={"remove": [CAROL], "add_members": [BOB]},
    )
    assert refused.status_code == 422
    state = members_of(client, CAROL)
    assert state["managers"] == [CAROL] and BOB not in state["members"]
    with factory() as db:
        assert db.scalars(select(GroupMember).where(GroupMember.role == "manager")).all()


def test_patch_requires_a_manager_valid_emails_and_a_change(monkeypatch):
    client, _, _ = make_client(monkeypatch)
    create_group(client, members=[CAROL])
    path = "/api/groups/team/members"
    assert client.patch(path, headers=user(BOB), json={"add_members": [BOB]}).status_code == 403
    assert client.patch(path, headers=user(CAROL), json={"add_members": [BOB]}).status_code == 403
    assert client.patch(path, headers=user(ALICE), json={}).status_code == 422
    assert (
        client.patch(path, headers=user(ALICE), json={"add_members": ["x@example.com"]}).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/groups/nope/members", headers=user(ALICE), json={"remove": [BOB]}
        ).status_code
        == 404
    )
    assert client.patch(path, headers=ADMIN, json={"add_members": [LEO]}).status_code == 200


def test_removed_member_loses_access_on_the_next_request(monkeypatch):
    client, _, _ = make_client(monkeypatch)
    create_group(client, members=[CAROL])
    publish(client, visibility="restricted", share_with={"groups": ["team"]})
    assert client.get("/p/reports/p1", headers=user(CAROL)).status_code == 200
    client.patch("/api/groups/team/members", headers=user(ALICE), json={"remove": [CAROL]})
    assert client.get("/p/reports/p1", headers=user(CAROL)).status_code == 404
    client.patch("/api/groups/team/members", headers=user(ALICE), json={"add_members": [CAROL]})
    assert client.get("/p/reports/p1", headers=user(CAROL)).status_code == 200


def test_rename_needs_a_manager_and_is_audited(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    create_group(client, members=[CAROL])
    assert (
        client.put("/api/groups/team", headers=user(CAROL), json={"name": "x"}).status_code == 403
    )
    response = client.put(
        "/api/groups/team", headers=user(ALICE), json={"name": "  Platform Team  "}
    )
    assert response.status_code == 200 and response.json()["data"]["name"] == "Platform Team"
    assert client.put("/api/groups/team", headers=user(ALICE), json={"name": ""}).status_code == 422
    assert len(audit_actions(factory, "group_renamed")) == 1


def test_delete_unused_group_and_permission_checks(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    create_group(client, members=[CAROL])
    assert client.delete("/api/groups/team", headers=user(CAROL)).status_code == 403
    assert client.delete("/api/groups/team", headers=user(BOB)).status_code == 403
    assert client.delete("/api/groups/nope", headers=user(ALICE)).status_code == 404
    response = client.delete("/api/groups/team", headers=user(ALICE))
    assert response.status_code == 200, response.text
    with factory() as db:
        assert db.get(SharingGroup, "team") is None
        assert db.scalars(select(GroupMember)).all() == []
    assert len(audit_actions(factory, "group_deleted")) == 1


def test_delete_refuses_a_group_in_use_unless_forced_and_then_purges_grants(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    create_group(client, members=[CAROL])
    page = publish(client, visibility="restricted", share_with={"groups": ["team"], "users": [BOB]})
    client.put(
        "/api/me/sharing-defaults",
        headers=user(ALICE),
        json={
            "default_visibility": "restricted",
            "default_grants": {"groups": ["team"], "users": []},
        },
    )
    client.put(
        "/api/namespaces/team/sharing-defaults",
        headers=user(ALICE),
        json={
            "default_visibility": "restricted",
            "default_grants": {"groups": ["team"], "users": []},
        },
    )
    with factory() as db:
        token_before = db.get(PageAsset, page["id"]).data_token
    refused = client.delete("/api/groups/team", headers=user(ALICE))
    assert refused.status_code == 409 and "1 page" in refused.json()["detail"]
    assert client.get("/p/reports/p1", headers=user(CAROL)).status_code == 200  # nothing changed

    response = client.delete("/api/groups/team?force=true", headers=user(ALICE))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["page_grants"] == 1
    assert client.get("/p/reports/p1", headers=user(CAROL)).status_code == 404
    assert client.get("/p/reports/p1", headers=user(BOB)).status_code == 200  # direct grant stays
    with factory() as db:
        assert db.get(PageAsset, page["id"]).data_token != token_before
        assert db.scalars(select(PageGrant).where(PageGrant.principal_type == "group")).all() == []
    defaults = client.get("/api/me/sharing-defaults", headers=user(ALICE)).json()["data"]
    assert defaults["default_grants"]["groups"] == []
    ns = client.get("/api/namespaces/team/sharing-defaults", headers=user(ALICE)).json()["data"]
    assert ns["default_grants"]["groups"] == []
    assert len(audit_actions(factory, "group_grant_removed")) == 1


def test_recreating_a_deleted_slug_does_not_inherit_old_access(monkeypatch):
    client, _, _ = make_client(monkeypatch)
    create_group(client, members=[CAROL])
    publish(client, visibility="restricted", share_with={"groups": ["team"]})
    client.delete("/api/groups/team?force=true", headers=user(ALICE))
    create_group(client, manager=BOB, members=[BOB])  # someone else takes the slug
    assert client.get("/p/reports/p1", headers=user(BOB)).status_code == 404
    assert client.get("/p/reports/p1", headers=user(CAROL)).status_code == 404


def test_page_audit_is_visible_to_the_owner_and_admin_only(monkeypatch):
    client, _, _ = make_client(monkeypatch)
    page = publish(client)
    client.put(
        f"/api/pages/{page['id']}/sharing", headers=user(ALICE), json={"visibility": "private"}
    )
    client.get("/p/reports/p1", headers=ADMIN)  # admin read is audited
    url = f"/api/pages/{page['id']}/audit"
    assert client.get(url, headers=user(BOB)).status_code == 404
    items = client.get(url, headers=user(ALICE)).json()["data"]["items"]
    actions = [item["action"] for item in items]
    assert "sharing_changed" in actions and "admin_read" in actions
    assert items[0]["page"] == "reports/p1"
    changed = next(i for i in items if i["action"] == "sharing_changed")
    assert changed["before"]["visibility"] == "org" and changed["after"]["visibility"] == "private"
    assert client.get(url, headers=ADMIN).status_code == 200


def test_admin_sharing_audit_filters_and_requires_admin(monkeypatch):
    client, _, _ = make_client(monkeypatch)
    create_group(client)
    page = publish(client)
    client.put(
        f"/api/pages/{page['id']}/sharing", headers=user(ALICE), json={"visibility": "private"}
    )
    assert client.get("/api/admin/sharing-audit", headers=user(ALICE)).status_code == 403
    assert client.get("/api/admin/sharing-audit").status_code == 401
    everything = client.get("/api/admin/sharing-audit", headers=ADMIN).json()["data"]["items"]
    assert {"group_created", "sharing_changed"} <= {i["action"] for i in everything}
    only = client.get("/api/admin/sharing-audit?action=group_created", headers=ADMIN).json()[
        "data"
    ]["items"]
    assert [i["action"] for i in only] == ["group_created"]
    by_page = client.get(f"/api/admin/sharing-audit?page_id={page['id']}", headers=ADMIN).json()[
        "data"
    ]["items"]
    assert by_page and all(i["page_id"] == page["id"] for i in by_page)
    by_actor = client.get(f"/api/admin/sharing-audit?actor={ALICE}", headers=ADMIN).json()["data"][
        "items"
    ]
    assert by_actor and all(i["actor"] == ALICE for i in by_actor)
