# PANDA Daily

MoviePilot V2 plugin for PANDA friend-trade daily tasks.

## Features

- Set servant work to `greeting`
- Set daily interaction to `pat`
- Claim daily income once after work and interaction tasks
- Schedule with cron, default `0 7 * * *`
- Supports "run once now"
- Optional MoviePilot notification

## Configuration

- Enable plugin
- Send notification
- Run once now
- Cron schedule
- PANDA Cookie from a logged-in `pandapt.net` browser session

The Cookie is equivalent to your logged-in session. Store it only on a trusted NAS.

## Custom Plugin Repository

Place this directory at:

```text
plugins.v2/pandadaily/
```

Add the `PandaDaily` entry to `package.v2.json`.
