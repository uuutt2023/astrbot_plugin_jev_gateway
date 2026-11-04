# Jev 决策网关

把 Jev 的 Key、地址、模型集中登记在一处，多个插件共用。别的插件只要填
**代理地址 + 协议名**，就能拿到 Jev 的判定结果——换地址、换 Key 时只改网关，
不用挨个插件改配置。

```
┌──────────────┐   POST http://127.0.0.1:8770/jev/systemone   ┌──────────────────┐
│  其他插件     │ ───────────────────────────────────────────► │  Jev 决策网关     │
│ (angel_heart │                                            │  按协议名转发     │
│  soupai …)   │   ◄─────────────────────────────────────────── │  换鉴权/补模型    │
└──────────────┘              响应原样带回                     └────────┬─────────┘
                                                                    │ 按登记的入口
                                            ┌───────────────────────┼───────────────────────┐
                                            ▼                       ▼                       ▼
                                    https://jevmodel.org    api.typesafe.ai      jevtypesafeai.com
                                     /v1/systemone          /v1/systemone        /api/v1/decide
```

## 为什么

多个插件都要用 Jev 判定时，Key 和地址会散落在每个插件的设置栏里。换一个网关
就要改三四个地方，漏改一个就出故障。网关把这件事收成一处：

- 网关里登记若干 **API 入口**，每个入口有自己的协议名、地址、Key、模型。
- 其他插件填 `代理地址`（如 `http://127.0.0.1:8770`）和 `请求协议`（如
  `systemone`），请求原样转发给网关，网关按协议名找到对应入口再转给上游。
- 上游响应**原样带回**：状态码、错误体、余额字段都不改，客户端的解析逻辑不用动。

## 安装

把仓库放进 AstrBot 的 `data/plugins/` 目录，或在 WebUI 的插件市场里安装后启用。

依赖：`aiohttp`、`httpx`。

## 配置

### 网关侧（这个插件）

| 配置 | 说明 |
|---|---|
| 启用网关 | 关掉就不监听端口 |
| 监听地址 | 默认 `127.0.0.1`。改成 `0.0.0.0` 会暴露给局域网里的其他程序 |
| 监听端口 | 默认 `8770` |
| 访问令牌 | 客户端要带 `X-Jev-Gateway-Token` 头。留空不校验，纯本机使用够用 |
| API 入口 | 可登记多条，见下 |

每个入口是一行模板：

| 字段 | 说明 |
|---|---|
| 协议名 | 路由用的名字。客户端填什么就转到什么 |
| 接口地址 | 上游网关根地址，如 `https://jevmodel.org` |
| API Key | 上游的 Key。网关会用它替换掉客户端带来的 Authorization |
| 模型名 | 请求体里没带 `model` 时用它 |
| 端点路径 | 留空按协议类型取默认（`/v1/systemone`、`/v1/decisions`） |
| 超时 | 秒 |

内置三种模板：**SystemOne**（官方 Jev / TypeSafe）、**OpenAI Decisions**、
**自定义协议**（自己起协议名和端点路径）。

> 同一个协议名可以登记多条：第一条是主入口，上游返回 5xx 时自动切到下一条，
> 适合多 Key 轮换或主备网关。

### 客户端侧（其他插件）

在插件的 Jev 设置里填两项：

| 配置 | 说明 |
|---|---|
| 网关代理地址 | 如 `http://127.0.0.1:8770`。留空＝直连，行为跟以前一样 |
| 请求协议 | 网关里登记的协议名，如 `systemone` |

填了代理地址之后，插件自己的 `Jev API Key` 可以留空——鉴权由网关那侧负责。

## 端点

| 端点 | 说明 |
|---|---|
| `POST /jev/<协议名>` | 中转到该协议登记的入口 |
| `POST /v1/systemone` | `systemone` 协议的快捷入口 |
| `POST /v1/decisions` | `decisions` 协议的快捷入口 |
| `GET /jev` | 列出已登记的入口（Key 打码） |
| `GET /health` | 存活检查 |

客户端请求示例：

```bash
curl -X POST http://127.0.0.1:8770/jev/systemone \
  -H 'Content-Type: application/json' \
  -d '{"model":"jev-latest","questions":{"q":{"type":"noul","instructions":"Is it relevant?"}}}'
```

带访问令牌时加 `-H 'X-Jev-Gateway-Token: <token>'`。

未登记的协议返回 404，响应体里带已登记的协议名，方便排查。

## 指令

- `/jev网关` —— 看网关状态、代理地址和已登记的入口。

## 中间处理

请求进网关到响应回客户端之间，可以插入自定义处理。默认只有两件事：请求体
没带 `model` 时补上入口配置的模型；日志里不出现明文 Key。

要加自己的逻辑，在插件目录下放一个 `hooks_ext.py`：

```python
async def before_forward(entry, ctx):
    """ctx = {"method", "path", "headers", "body"}；返回 dict 覆盖字段。"""
    return None


async def after_response(entry, ctx):
    """ctx = {"status", "headers", "body"}；返回 dict 覆盖字段。"""
    return None
```

返回 `None` 表示不干预。改完在 WebUI 里重载插件即可生效。

## 已接入的插件

- [astrbot_plugin_angel_heart](https://github.com/uuutt2023/astrbot_plugin_angel_heart) —— 天使之心
- [astrbot_plugin_soupai](https://github.com/uuutt2023/astrbot_plugin_soupai) —— 海龟汤
- [astrbot_plugin_emoji_like](https://github.com/uuutt2023/astrbot_plugin_emoji_like) —— 智能贴表情

## 许可

MIT
