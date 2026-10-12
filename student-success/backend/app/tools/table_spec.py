"""DynamoDB table definition shared by tests and local tooling.
Keep in sync with infra/template.yaml (a test checks the capacities match)."""

TABLE_CAPACITY = {"read": 8, "write": 8}
GSI_CAPACITY = {"read": 3, "write": 3}


def create_table(client, name: str) -> None:
    client.create_table(
        TableName=name,
        BillingMode="PROVISIONED",
        ProvisionedThroughput={"ReadCapacityUnits": TABLE_CAPACITY["read"], "WriteCapacityUnits": TABLE_CAPACITY["write"]},
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a in ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk")],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        GlobalSecondaryIndexes=[{
            "IndexName": ix, "KeySchema": [{"AttributeName": f"{ix}pk", "KeyType": "HASH"}, {"AttributeName": f"{ix}sk", "KeyType": "RANGE"}],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": GSI_CAPACITY["read"], "WriteCapacityUnits": GSI_CAPACITY["write"]},
        } for ix in ("gsi1", "gsi2")],
    )
