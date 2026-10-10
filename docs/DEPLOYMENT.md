# 部署与配置

## 配置字段

从 `rag_llm_server/.env.example` 复制为 `.env`。所有凭据只保存在后端。

- `ARK_API_KEY`、`ARK_ENDPOINT_ID`：模型调用凭据与接入点；`ARK_BASE_URL` 默认北京区域。
- `VOLC_ACCESS_KEY`、`VOLC_SECRET_KEY`：RTC 与云知识库签名使用的 AK/SK。
- `RTC_APP_ID`、`RTC_APP_KEY`：RTC 应用与 Token 签名密钥。
- `SERVER_URL`：云端可访问的 HTTPS 回调域名。
- `CALLBACK_API_KEY`：自定义高强度随机密钥，用于回调鉴权。
- `KB_MODE`：`sample` 本地资料；`cloud` 云端规则检索。精确商品型号优先本地。
- `VOLC_ACCOUNT_ID`、`KB_COLLECTION_NAME`、`KB_PROJECT_NAME`：云知识库账户、集合与项目。
- `MOCK_MODE`：`true` 为模拟文本，真实语音使用 `false`。

## 回调网关

```bash
# 终端一：rag_llm_server，已激活虚拟环境
python main.py
# 终端二：根目录
node scripts/callback-gateway.cjs
# 终端三：根目录
npm run dev
```

后端绑定 `127.0.0.1:3001`，网关绑定 `127.0.0.1:3002`。用自己的 HTTPS 代理/隧道将域名转发到 3002。网关仅支持 `POST /api/chat_callback`、`POST /api/rtc_events` 与四份演示 Markdown；其他路径返回 404。

将域名填入 `SERVER_URL` 并重启后端。复制 `voice_config.example.json` 为 `voice_config.json`，按已开通的 ASR/TTS 资源核对参数。公网不要直接转发 3001。

若前端放在远程 HTTPS 域名，须修改 `src/config/index.ts` 默认 HTTP 控制面地址，并同步调整 CORS；公开控制面前增加身份认证与限流。默认方案用于本机演示。

## 云知识库

创建自己的文本集合，设置 `KB_MODE=cloud` 与相关账户字段，确认公网可下载 `/knowledge/ecommerce_demo_v1_0.md` 至 `_3.md`。在后端执行：

```bash
python sync_knowledge.py --upload
python sync_knowledge.py
```

上传使用 corpus 中四个管理文档 ID；目标集合已有同名 ID 时，先确认可以更新。检查返回状态和切片数，等待索引完成，再运行 `python evaluate_commerce.py --live`。提交上传成功不代表索引就绪。

旧文档或未知 ID 不在检索白名单；云端检索失败会报错。更新知识时同步修改 Markdown 与 `knowledge/corpus.json`，重启清除本地缓存。仓库已提供审核资料，无需原工作区生成器。

## 验收与部署限制

配置检查、文本检索、真实模型输出、语音识别与打断应分别验收。`/health` 不验证外部云服务可用性。会话在进程内保存，重启失效，不能直接开启多 worker。生产部署要求见 [安全说明](../SECURITY.md)。
