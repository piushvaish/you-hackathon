# Project agent instructions

- The One CLI (`one`) is installed globally on this machine.
- For third-party platforms and external services, use the available `one` skill and One CLI rather than direct API credentials or SDKs.
- Follow One's required sequence: list connections, search for an action, read that action's knowledge, then execute it.
- GitHub access for this project must go through One. Never use a GitHub PAT directly in application code.
- Never print, commit, or copy credentials into runtime artifacts.
