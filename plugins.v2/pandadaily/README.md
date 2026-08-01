# PANDA 每日任务

MoviePilot V2 插件，用来每天自动完成 PANDA 好友买卖日常。

## 中文说明

这是一个 MoviePilot V2 插件，用来每天自动完成 PANDA 好友买卖日常：

- 每个佣人安排工作，可在配置页用中文下拉选择
- 每个佣人今日互动，可在配置页用中文下拉选择
- 最后领取一次每日收益
- 默认每天早上 7 点运行：`0 7 * * *`
- 支持在插件配置页勾选“立即运行一次”马上测试
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
- 执行周期
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
