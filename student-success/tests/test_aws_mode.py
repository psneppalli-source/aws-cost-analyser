"""AWS-mode storage and identity against simulated AWS (moto). Skipped if moto isn't installed.

    pip install "moto[s3,dynamodb,cognitoidp]"
    python -m unittest tests.test_aws_mode -v
"""

import os
import unittest

try:
    import boto3
    from moto import mock_aws
except ImportError:  # pragma: no cover
    mock_aws = None


@unittest.skipIf(mock_aws is None, "moto not installed")
class TestAwsMode(unittest.TestCase):
    def setUp(self):
        os.environ.update(AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="ap-south-1",
                          AWS_REGION="ap-south-1")
        os.environ.pop("AWS_CA_BUNDLE", None)
        self.mock = mock_aws()
        self.mock.start()
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(Bucket="ssp-data", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})
        boto3.client("dynamodb", region_name="ap-south-1").create_table(
            TableName="ssp-app", BillingMode="PROVISIONED", ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}])
        idp = boto3.client("cognito-idp", region_name="ap-south-1")
        pool = idp.create_user_pool(PoolName="p", Schema=[{"Name": "dept", "AttributeDataType": "String", "Mutable": True},
                                                          {"Name": "student_id", "AttributeDataType": "String", "Mutable": True}])["UserPool"]["Id"]
        for g in ("admin", "hod", "mentor", "placement", "student"):
            idp.create_group(UserPoolId=pool, GroupName=g)
        from ssp import settings, storage
        settings.MODE, settings.DATA_BUCKET, settings.TABLE_NAME, settings.USER_POOL_ID = "aws", "ssp-data", "ssp-app", pool
        settings.AWS_REGION = "ap-south-1"
        storage.set_store(None)
        self.storage, self.settings = storage, settings

    def tearDown(self):
        self.mock.stop()
        self.settings.MODE = "local"
        self.storage.set_store(None)

    def test_blob_table_and_lock(self):
        st = self.storage.get_store()
        self.assertIsInstance(st.blobs, self.storage.S3Blobs)
        st.put_json("records/x.json.gz", {"a": 1})
        self.assertEqual(st.get_json("records/x.json.gz"), {"a": 1})
        self.assertEqual(st.blobs.list("records/"), ["records/x.json.gz"])
        for i in range(3):
            st.table.put("INT", f"k{i}", {"i": i})
        self.assertEqual([x["i"] for x in st.table.query("INT", newest_first=True)], [2, 1, 0])
        self.assertEqual(len(st.table.query("INT", limit=2)), 2)
        with st.lock("records"):
            with self.assertRaises(self.storage.Conflict):
                with st.lock("records"):
                    pass
        with st.lock("records"):  # released after the block
            pass

    def test_cognito_directory(self):
        from ssp.auth import directory
        directory.create("hod.cse", "Dr HOD", "hod", dept="CSE", password="Strong@Pass123")
        directory.create("23cse001", "A Student", "student", student_id="23CSE001", password="Strong@Pass123")
        users = {u["username"]: u for u in directory.list()}
        self.assertEqual(users["hod.cse"]["role"], "hod")
        self.assertEqual(users["hod.cse"]["dept"], "CSE")
        self.assertEqual(users["23cse001"]["student_id"], "23CSE001")
        directory.set_active("hod.cse", False)
        self.assertFalse({u["username"]: u for u in directory.list()}["hod.cse"]["active"])

    def test_import_and_score_on_aws_storage(self):
        from ssp import engine, importer, records, settings
        from ssp.auth import Principal
        admin = Principal("admin", "Admin", "admin")
        cur = settings.SAMPLE_DIR / "current"
        for name, cat in (("01_roster.csv", "students"), ("02_academic_results_2026-ODD.csv", "academic"),
                          ("04_attendance_2026-ODD.csv", "attendance")):
            s = importer.validate(cat, name, (cur / name).read_bytes(), "2026-ODD", admin)
            importer.commit(s["id"], admin, recalc=False)
        self.assertEqual(len(records.roster()), 660)
        run = engine.recalculate(admin, "aws test")
        snap = engine.snapshot("2026-ODD")["students"]
        self.assertEqual(len(snap), run["students"]["2026-ODD"])
        some = next(iter(snap.values()))
        self.assertEqual(some["score"]["status"], "provisional")  # only 2 of 7 sources loaded: flagged, not zero-filled


if __name__ == "__main__":
    unittest.main()
