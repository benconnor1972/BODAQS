# Triage labels

Use the upstream default vocabulary locally. These mappings describe intended
GitHub labels; they do not claim that the remote labels already exist.

| Role | GitHub label | Meaning |
| --- | --- | --- |
| `bug` | `bug` | Existing behavior is broken |
| `enhancement` | `enhancement` | New feature or improvement |
| `needs-triage` | `needs-triage` | Maintainer needs to evaluate |
| `needs-info` | `needs-info` | Waiting for information |
| `ready-for-agent` | `ready-for-agent` | Specified for agent implementation |
| `ready-for-human` | `ready-for-human` | Requires human implementation |
| `wontfix` | `wontfix` | Will not be actioned |

For an authorized triage operation, aim for one category and one state label.
Inspect existing labels first; flag conflicting state labels before changing them.
If a required remote label is missing, report it and request authorization for its
creation as part of a concrete proposal. Do not create labels during installation.

The tracker write rules in `issue-tracker.md` take precedence over skill defaults.
In particular, recommending `wontfix` does not authorize closing the issue, and
finishing implementation does not authorize closing it either. Read-only requests
such as asking what needs attention do not authorize comments or label changes.
