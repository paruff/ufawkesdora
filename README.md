# uFawkesDORA (Archived)

**This repository is archived.** Its compute plane, docs, and collector patterns have been
consolidated into [uFawkesObs](https://github.com/paruff/uFawkesObs), per
[ADR-007](https://github.com/paruff/uFawkesObs/blob/main/docs/adr/ADR-007-dora-consolidation.md).

## Where things moved

| Was here | Now here (uFawkesObs) |
| --- | --- |
| `docs/spec/`, `docs/design/`, `docs/decisions/`, `docs/discovery/` | [`docs/dora/`](https://github.com/paruff/uFawkesObs/tree/main/docs/dora) |
| Ingestion API, worker, compute, event schemas | [`dora/`](https://github.com/paruff/uFawkesObs/tree/main/dora) |
| `collectors/{generic,github,manual-incident,woodpecker}` | [`dora/collectors/`](https://github.com/paruff/uFawkesObs/tree/main/dora/collectors) |
| Grafana dashboards | [`dashboards/platform/`](https://github.com/paruff/uFawkesObs/tree/main/dashboards/platform) (`dora-*` files) |
| Prometheus alerting rules | [`config/prometheus/rules/`](https://github.com/paruff/uFawkesObs/tree/main/config/prometheus/rules) (`ufawkesobs-dora-*.yml`) |

If you were consuming the GitHub Actions collectors via
`uses: paruff/ufawkesdora/collectors/github/...@v1`, update to
`uses: paruff/uFawkesObs/dora/collectors/github/...@v1`.

No further development happens in this repository. Please open issues and PRs against
[uFawkesObs](https://github.com/paruff/uFawkesObs) instead.
