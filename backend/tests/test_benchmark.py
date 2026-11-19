import httpx

from evaluation.benchmark import rows_match, run_case


def test_row_equivalence_ignores_order_but_counts_duplicates():
    assert rows_match([("paid", 4), ("pending", 2)], [["pending", 2], ["paid", "4.0"]])
    assert not rows_match([(1,), (1,)], [[1]])
    assert not rows_match([(True,)], [[1]])


def test_benchmark_distinguishes_rejection_and_mismatch():
    case = {"id": "case", "question": "Quantos pedidos?", "expected_status": "generated"}
    client = httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(lambda _: httpx.Response(422, json={
            "stages": [{"name": "validation", "status": "failed"}],
        })),
    )
    with client:
        assert run_case(client, case, "model", 1, [(1,)])["outcome"] == "sql_rejected"
    with httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            "generation": {"status": "generated"},
            "result": {"rows": [[2]], "truncated": False},
        })),
    ) as client:
        assert run_case(client, case, "model", 1, [(1,)])["outcome"] == "result_mismatch"
