# CI Diagnosis — PR #7

## Failure 1: Unit Tests

| Field        | Value                                                                                                                                                                                                    |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Failure      | Tests / Unit Tests                                                                                                                                                                                       |
| Job          | unit-tests in ci-tests.yml                                                                                                                                                                               |
| Evidence     | `ImportError while loading conftest '/home/runner/work/ufawkesdora/ufawkesdora/tests/unit/conftest.py'. tests/unit/conftest.py:5: in <module> import yaml E ModuleNotFoundError: No module named 'yaml'` |
| Likely Cause | `ci-tests.yml` install step (`Install test dependencies`) does not include `pyyaml`. The `conftest.py` imports `yaml` for parsing workflow YAML files.                                                   |
| Confidence   | HIGH                                                                                                                                                                                                     |

## Failure 2: Integration Tests

| Field        | Value                                                                                                                                                                                                                                                                 |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Failure      | Tests / Integration Tests                                                                                                                                                                                                                                             |
| Job          | integration-tests in ci-tests.yml                                                                                                                                                                                                                                     |
| Evidence     | `ERROR at setup of TestMetricsIntegration.test_all_five_metrics_computed: ModuleNotFoundError: No module named 'tests.unit.test_schema'`                                                                                                                              |
| Likely Cause | `test_metrics_integration.py` imports helper functions (`execute_sql_file`, `split_sql_statements`, `_bootstrap_databases_and_roles`) from `tests.unit.test_schema`. The `PYTHONPATH` doesn't include the project root, so the `tests.unit` package isn't resolvable. |
| Confidence   | HIGH                                                                                                                                                                                                                                                                  |
