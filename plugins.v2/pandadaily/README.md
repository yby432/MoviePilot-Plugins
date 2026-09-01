# PANDA 每日任务

MoviePilot V2 插件，用来每天自动完成 PANDA 好友买卖日常。

当前版本兼容新版 `friendTradeBootstrapHome` 与旧版 `home` 页面数据结构。

## 中文说明

这是一个 MoviePilot V2 插件，用来每天自动完成 PANDA 好友买卖日常：

- 每个佣人安排工作，可在配置页用中文下拉选择
- 每个佣人今日互动，可在配置页用中文下拉选择
- 最后领取一次每日收益
- 执行周期格式对齐“站点自动签到”插件
- 支持在插件配置页勾选“立即运行一次”马上测试
- 任务执行失败时自动重试，可配置重试次数和间隔
- 支持新版全部工作选项，并自动跳过尚未解锁该工作的佣人
- 可自动领取已完成的事务所委托，并按收益与推荐属性智能组队派遣
- 优先读取 MoviePilot 站点管理里的 PANDA Cookie，插件 Cookie 仅作为备用

注意：Cookie 等同于网页登录态，请只保存在你自己的可信 NAS 上。

## 可选工作

- 打扫：`clean`
- 跑腿：`errand`
- 休息：`rest`
- 整理：`tidy`
- 迎客：`greeting`
- 陪聊：`chat`
- 洗头按摩：`hair_massage`
- 贴身照料：`close_care`
- 护主值守：`guard`
- 理财看账：`accounting`
- 私密差遣：`private_task`
- 外联应酬：`social`
- 大保健：`special_care`
- 暖侍加班：`overtime`
- 默契协作：`tacit_cooperation`

## 可选互动

- 夸夸：`praise`
- 投喂：`feed`
- 摸头：`pat`
- 悄悄话：`whisper`
- 小奖励：`reward`
- 深入交流：`deep_communication`

## 配置说明

- 启用插件
- 发送通知
- 立即运行一次
- 失败重试次数，默认 `2`（不含首次执行；填 `0` 表示不重试）
- 重试间隔秒数，默认 `60`
- 自动派遣事务所，默认开启
- 执行周期，支持 5 位 cron、间隔小时、留空自动随机
- MoviePilot 站点域名，默认 `pandapt.net`
- 安排工作
- 今日互动
- 备用 PANDA Cookie，通常留空

## 自定义插件仓库

插件目录位置：

```text
plugins.v2/pandadaily/
```

并在 `package.v2.json` 中保留 `PandaDaily` 条目。

## 执行周期

- `0 7 * * *`：每天 07:00 执行一次
- `2.3`：每隔 2.3 小时执行一次
- `2.3/9-23`：每天 9 点到 23 点之间，每隔 2.3 小时执行一次
- 留空：默认 9 点到 23 点之间随机执行 1 次
