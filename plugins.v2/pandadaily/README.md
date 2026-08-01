# PANDA Daily

MoviePilot V2 plugin for PANDA friend-trade daily tasks.

## 中文说明

这是一个 MoviePilot V2 插件，用来每天自动完成 PANDA 好友买卖日常：

- 每个佣人安排工作，默认 `greeting`，也就是“迎客”
- 每个佣人今日互动，默认 `pat`，也就是“摸头”
- 最后领取一次每日收益
- 默认每天早上 7 点运行：`0 7 * * *`
- 支持在插件配置页勾选“Run once now”立即运行一次

注意：Cookie 等同于网页登录态，请只保存在你自己的可信 NAS 上。

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
