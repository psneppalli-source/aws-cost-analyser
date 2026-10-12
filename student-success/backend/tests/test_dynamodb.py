"""The DynamoDB backend against simulated AWS (moto): conditional writes, transactions,
GSI pagination, and a full write -> recalculate -> list flow."""

import os

import pytest

moto = pytest.importorskip("moto")


@pytest.fixture
def dynamo(monkeypatch):
    import boto3
    from moto import mock_aws

    from app import db
    from app.store import DynamoTable
    from app.tools.table_spec import create_table
    for k, v in dict(AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="eu-west-2").items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_CA_BUNDLE", raising=False)
    with mock_aws():
        create_table(boto3.client("dynamodb", region_name="eu-west-2"), "ssp-test")
        old = db._table
        t = DynamoTable("ssp-test", "eu-west-2")
        db.set_table(t)
        try:
            yield t
        finally:
            db.set_table(old)


def test_conditional_writes_and_transactions(dynamo):
    from app.store import C, ConditionFailed, Delete, Put
    dynamo.put({"pk": "A", "sk": "1", "version": 1, "score": 61.5, "tags": ["x"], "nested": {"a": 1.25}}, C.not_exists())
    assert dynamo.get("A", "1")["score"] == 61.5 and dynamo.get("A", "1")["nested"]["a"] == 1.25
    with pytest.raises(ConditionFailed):
        dynamo.put({"pk": "A", "sk": "1", "version": 2}, C.version(7))
    with pytest.raises(ConditionFailed):
        dynamo.transact([Put({"pk": "A", "sk": "2", "version": 1}), Put({"pk": "A", "sk": "1", "version": 2}, C.version(9))])
    assert dynamo.get("A", "2") is None
    dynamo.transact([Put({"pk": "A", "sk": "1", "version": 2}, C.version(1)), Delete("A", "2")])
    assert dynamo.get("A", "1")["version"] == 2
    seedish = C.any(C.not_exists(), C.all(C.eq("source", "seed"), C.lt("seed_version", 3)))
    dynamo.put({"pk": "S", "sk": "1", "source": "manual", "seed_version": 1})
    with pytest.raises(ConditionFailed):
        dynamo.put({"pk": "S", "sk": "1", "source": "seed", "seed_version": 3}, seedish)


def test_gsi_pagination(dynamo):
    for i in range(23):
        dynamo.put({"pk": f"P#{i}", "sk": "X", "gsi1pk": "G", "gsi1sk": f"{i:03d}"})
    seen, cursor = [], None
    while True:
        items, cursor = dynamo.query("G", index="gsi1", limit=10, cursor=cursor)
        seen += [i["gsi1sk"] for i in items]
        if not cursor:
            break
    assert seen == [f"{i:03d}" for i in range(23)]


def test_end_to_end_on_dynamodb(dynamo):
    from app import accounts, insights, interventions, recordsvc
    from app.auth import clear_principal_cache, load_principal
    from app.policy import Principal
    sysp = Principal("system", "system", "system")
    for user, roles in (("admin.t", [{"role": "college_admin"}]), ("mentor.t", [{"role": "mentor"}])):
        u = accounts.create_user(sysp, user, user, sub=f"sub-{user}", system=True)
        accounts.set_roles(sysp, u["sub"], roles, u["version"], system=True)
    clear_principal_cache()
    admin = load_principal("sub-admin.t")
    recordsvc.create_master(admin, {"student_id": "CSE24555", "name": "Dynamo Student", "department": "CSE", "year": 3, "dataset": "real"})
    m = recordsvc.get_master("real", "CSE24555")
    accounts.assign_mentor(admin, "real", "CSE24555", "sub-mentor.t", m["version"])
    accounts.assign_subject(admin, "sub-mentor.t", "CSE", 3, "Operating Systems")
    clear_principal_cache()
    mentor = load_principal("sub-mentor.t")
    assert ("real", "CSE24555") in mentor.mentees
    r = recordsvc.upsert(mentor, "real", "CSE24555", "attendance", "2026-09",
                         {"subject": "Operating Systems", "classes_held": 20, "classes_attended": 19})
    assert r["status"] == "created"
    rows = insights.listing("real", "CSE")
    assert rows and rows[0]["student_id"] == "CSE24555" and rows[0]["recalc_status"] == "current"
    iv = interventions.create(mentor, "real", "CSE24555", {"title": "Check-in", "category": "wellbeing", "reviewed": True,
                                                           "due_date": "2026-11-01", "review_date": "2026-11-10"})
    mine, _ = interventions.listing(mentor, "real", owner=mentor.sub)
    assert [i["intervention_id"] for i in mine] == [iv["intervention_id"]]
    with pytest.raises(recordsvc.Conflict):
        interventions.update(mentor, "real", "CSE24555", iv["intervention_id"], {"status": "In Progress", "version": 99})


def test_capacity_matches_template():
    from pathlib import Path

    from app.tools.table_spec import GSI_CAPACITY, TABLE_CAPACITY
    tpl = (Path(__file__).resolve().parents[2] / "infra" / "template.yaml")
    if not tpl.exists():
        pytest.skip("infra template not written yet")
    text = tpl.read_text()
    assert f"Default: {TABLE_CAPACITY['read']}" in text and f"Default: {GSI_CAPACITY['read']}" in text
