from scripts.migrate_from_legacy_db import _legacy_group_target_names


def test_duplicate_legacy_group_names_keep_separate_stable_target_names():
    groups = [
        {"id": 12, "name": "Work"},
        {"id": 18, "name": "Work"},
        {"id": 23, "name": "Archive"},
    ]

    assert _legacy_group_target_names(groups) == {
        12: "Work (legacy group 12)",
        18: "Work (legacy group 18)",
        23: "Archive",
    }


def test_duplicate_group_names_respect_postgres_name_limit():
    long_name = "x" * 128
    names = _legacy_group_target_names([
        {"id": 1, "name": long_name},
        {"id": 2, "name": long_name},
    ])

    assert all(len(name) <= 128 for name in names.values())
    assert names[1] != names[2]
    assert names[1].endswith("(legacy group 1)")
    assert names[2].endswith("(legacy group 2)")
