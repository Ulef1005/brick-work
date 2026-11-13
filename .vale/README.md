# Vale styles for the docs

The rules `scripts/vale.py check` runs over `docs/` through `/.vale.ini` (App Docs Standard: User Docs § Vale).

| Folder | What | Source | Licence |
|---|---|---|---|
| `styles/Microsoft/` | The Microsoft Writing Style Guide rules, for the user docs | [errata-ai/Microsoft](https://github.com/errata-ai/Microsoft) release v0.15.1 (`Microsoft.zip`, SHA-256 `0b37660b244a9399d7f10225895773291d27b2967ed0d239a1d379b633e8cd16`) | MIT |
| `styles/Google/` | The Google developer documentation style guide rules, for `docs/developer/` | [errata-ai/Google](https://github.com/errata-ai/Google) release v0.7.1 (`Google.zip`, SHA-256 `4b67fca1f2a88595b2a578ab98bbf3017a23af677b04f93e862843f3ea1a9a0b`) | MIT |
| `styles/BrickWork/` | This app's own rules (a sentence of more than 30 words) | written here | the app's |
| `styles/config/vocabularies/BrickWork/` | The app's own terms: `accept.txt` is spelled right, `reject.txt` is not | written here | the app's |

The two packs are copied unchanged and committed, so Vale never syncs over the network. Moving to a newer pack is a deliberate change: copy the new release, update the version and checksum here and run the docs checks. The Vale binary is pinned in `scripts/vale.py`. A retired name goes into `scripts/docs_terms.toml`.
