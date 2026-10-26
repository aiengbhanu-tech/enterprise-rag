# Build validation — 26 October 2026

| Check | Observed result |
|---|---|
| Ruff configured correctness checks | Passed |
| Pytest | 40 passed in approximately 1.4 seconds |
| Actual Uvicorn/HTTP smoke | Passed startup, bearer auth, indexing, cited answer, deletion and subsequent abstention |
| Factorial experiment | 8 configurations × 29 test questions; 26 answerable questions per retrieval average |
| CI smoke regression budgets | Passed, including individual ACL/injection abstention cases |
| Python wheel packaging | Built successfully with no dependency installation |
| Pretrained embedding / cross-encoder inference | Not run |
| Live Drive / Notion / Slack credentials | Not used; adapter tests used mocked payloads |
| Docker/Compose execution | Not run; no container engine available |
| Independent human answer review | Not run; blinded export/import workflow provided |
| Real organization corpus / concurrent load | Not run |

The test run emitted one dependency deprecation warning about Starlette's HTTPX test transport. It did not affect the tests or the separate real HTTP check. The tested dependency versions are in `requirements-tested.txt`.

Reproduce from the repository root:

```bash
python -m pip install -c requirements-tested.txt '.[dev]'
python -m ruff check rag eval tests scripts
python -m pytest -q
python scripts/http_smoke.py
python -m eval.run --profile smoke
python -m eval.gate eval/results/smoke/results.json eval/budgets.json
```

These checks establish the stated reference behavior. They do not certify enterprise rollout readiness; `READINESS.md` names the remaining implementation and validation gaps.
