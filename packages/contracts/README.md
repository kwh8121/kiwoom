# Shared contract cases

`packages/contracts/cases/validate.json` shape:

```json
{"cases":[{"name":"valid","definition":{},"conditions":{"cond-a":{"profileId":"profile-a","active":true}},"issues":[]}]}
```

- `name`: stable case name
- `definition`: strategy definition payload with `schemaVersion: 1`, `exchange: "K"`
- `conditions`: condition metadata keyed by condition id
- `issues`: sorted validation issue codes

`packages/contracts/cases/evaluate.json` shape:

```json
{"cases":[{"name":"and","expr":{},"sets":{"A":["001"]},"expected":{"codes":["001"],"matches":{"001":["A"]},"excluded":[]}}]}
```

- `name`: stable case name
- `expr`: strategy expression payload
- `sets`: leaf condition members keyed by condition id
- `expected.codes`: sorted resulting codes
- `expected.matches`: DFS-ordered leaf ids that matched each result code
- `expected.excluded`: sorted excluded codes collected from exclude nodes
