# astrbot_plugin_meme_wiki

梗 Wiki 是一个 AstrBot 插件，让 AI 在对话中学习社区里的网络梗、缩写和黑话。

当模型遇到不熟悉的表达时，可以调用 `lookup_meme`。插件会先查询持久化词典；没有命中时，再搜索当前会话历史和配置的网页地址。模型核实资料后调用 `remember_meme` 保存含义、使用方式、例句和别名。之后每轮请求只会注入当前消息命中的少量词条，避免把整本词典塞进上下文。

## 安装

将本目录放入 AstrBot 的 `data/plugins/astrbot_plugin_meme_wiki/`，安装 `requirements.txt` 中的依赖，然后在 WebUI 中重载插件。AstrBot 需要 `4.9.2` 或更高版本。

词条保存在 AstrBot 的 `data/plugin_data/astrbot_plugin_meme_wiki/meme_wiki.json`，更新或重装插件不会覆盖它。

## 人工命令

```text
/梗wiki 查询 <梗>
/梗wiki 学习 <梗> | <含义> | <用法> | <例句（可选）>
/梗wiki 删除 <梗>
/梗wiki 列表
```

`/meme_wiki` 和 `/meme` 是等价的命令别名。萌娘百科搜索可以在插件配置中关闭；关闭后未知梗仍会从当前会话历史中检索。

## 搜索配置

`search_endpoints` 按优先级排列搜索地址，默认使用萌娘百科：

```text
https://zh.moegirl.org.cn/index.php?search=
```

可以每行配置一个地址。地址支持 `{query}` 占位符，也支持保留一个空查询参数（例如 `?search=` 或 `?q=`），插件会自动填入并编码关键词。每个地址搜索后会进行标题、摘要和 URL 匹配度评分；达到 `search_match_threshold` 就停止，否则继续调用下一个地址。网络错误、超时或无结果也会自动回退。若所有地址都没有达到阈值，会返回评分最高的结果供模型核实。

## 设计说明

- `on_llm_request` 使用 `extra_user_content_parts` 注入临时上下文，不污染会话历史。
- `lookup_meme` 和 `remember_meme` 分离，搜索结果不会在未经模型核实的情况下自动写入词典。
- 网络请求使用 `aiohttp`，按配置顺序访问搜索地址；失败、超时或搜索引擎不可用都不会阻塞正常聊天。
- 词条文件采用同目录临时文件加原子替换写入，避免进程中断造成半写文件。

开发接口依据 [AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)、[AI 调用](https://docs.astrbot.app/dev/star/guides/ai.html)、[处理消息事件](https://docs.astrbot.app/dev/star/guides/listen-message-event.html) 和 [插件存储](https://docs.astrbot.app/dev/star/guides/storage.html)。
