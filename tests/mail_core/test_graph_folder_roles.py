"""R01 regression: Graph special folders classified by well-known endpoint IDs.

Real Graph mailFolder resources have no role/wellKnownName properties, so a
localized (e.g. Chinese) mailbox used to persist Sent/Drafts/Trash/Junk/
Archive as "other". list_folders now resolves each well-known folder's ID
through its endpoint and classifies by ID. Fixtures below use only real
mailFolder resource fields (id/displayName/childFolderCount/...).
"""

from __future__ import annotations

from mail_core.providers.graph import GraphProvider

_WELL_KNOWN = {
    "inbox": ("fid-inbox", "收件箱"),
    "sentitems": ("fid-sent", "已发送邮件"),
    "drafts": ("fid-drafts", "草稿"),
    "deleteditems": ("fid-trash", "已删除邮件"),
    "junkemail": ("fid-junk", "垃圾邮件"),
    "archive": ("fid-archive", "存档"),
}


def _transport(method, path, params):
    assert method == "GET"
    for name, (fid, display) in _WELL_KNOWN.items():
        if path == f"/me/mailFolders/{name}":
            return {
                "id": fid,
                "displayName": display,
                "parentFolderId": "root",
                "childFolderCount": 0,
                "unreadItemCount": 0,
                "totalItemCount": 0,
            }
    if path == "/me/mailFolders":
        return {
            "value": [
                {"id": fid, "displayName": display, "childFolderCount": 0}
                for fid, display in _WELL_KNOWN.values()
            ]
            + [{"id": "fid-custom", "displayName": "项目", "childFolderCount": 0}]
        }
    return {}


def test_list_folders_classifies_special_folders_by_endpoint_id():
    folders = GraphProvider(credential_ref="x", transport=_transport).list_folders()
    roles = {f.remote_id: f.role for f in folders}
    assert roles == {
        "fid-inbox": "inbox",
        "fid-sent": "sent",
        "fid-drafts": "drafts",
        "fid-trash": "trash",
        "fid-junk": "junk",
        "fid-archive": "archive",
        "fid-custom": "other",
    }


def test_list_folders_survives_missing_well_known_endpoint():
    def transport(method, path, params):
        if path == "/me/mailFolders/archive":
            raise RuntimeError("archive not present")
        return _transport(method, path, params)

    folders = GraphProvider(credential_ref="x", transport=transport).list_folders()
    roles = {f.remote_id: f.role for f in folders}
    assert roles["fid-archive"] == "other"
    assert roles["fid-sent"] == "sent"
