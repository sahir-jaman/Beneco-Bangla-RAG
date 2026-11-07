# Manual content

Files in this folder are indexed alongside the website and rank higher than website pages.

- `notices.md` — important notices (e.g. paused services). Check this on every update.
- `faq.md` — answers approved by Beneco, especially for questions the bot couldn't answer.
- `pricing.md` — only create this if Beneco allows prices. Set `show_prices: true` in `config/settings.yaml` too.

Every file starts with a small header:

```
---
title: ...
type: manual
last_updated: YYYY-MM-DD
---
```

After editing any file here, rebuild the index (the reindex script, built in a later section).
