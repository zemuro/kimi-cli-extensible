# `kimi info` Subcommand

`kimi info` displays version and protocol information for Consilium CLI.

```sh
kimi info [--json]
```

## Options

| Option | Description |
|--------|-------------|
| `--json` | Output in JSON format |

## Output

| Field | Description |
|-------|-------------|
| `consilium_version` | Consilium CLI version number |
| `agent_spec_versions` | List of supported agent spec versions |
| `wire_protocol_version` | Wire protocol version |
| `python_version` | Python runtime version |

## Examples

**Text output**

```sh
$ kimi info
consilium version: 1.20.0
agent spec versions: 1
wire protocol: 1.10
python version: 3.13.1
```

**JSON output**

```sh
$ kimi info --json
{"consilium_version": "1.20.0", "agent_spec_versions": ["1"], "wire_protocol_version": "1.10", "python_version": "3.13.1"}
```
