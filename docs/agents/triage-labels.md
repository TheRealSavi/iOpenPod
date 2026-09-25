# Triage Labels

Private work-item state is recorded with the following exact values.

| Canonical role | Local status | Meaning |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | The maintainer needs to evaluate the item. |
| `needs-info` | `needs-info` | More information or a decision is required. |
| `ready-for-agent` | `ready-for-agent` | The item is specified well enough for an agent to implement without additional context. |
| `ready-for-human` | `ready-for-human` | The item requires human implementation or judgment. |
| `wontfix` | `wontfix` | The item will not be actioned. |

Use one of these strings after the `Status:` label in a local item. Change this
mapping only if the project's vocabulary changes deliberately.
