# Milvus 检索后端

项目支持 `KB_MODE=sample|cloud|milvus`。具体商品型号保留本地精确匹配；`milvus` 模式的其他问题调用 Embedding API，再检索本地 Milvus。资料不足时拒答，服务故障明确报错，不会静默切回云知识库。

## 当前验证方案

- Milvus Server 2.4.4，使用 REST v2，经现有 httpx 调用，无需额外安装 PyMilvus。
- 独立集合 `voice_commerce_v1`，89 个知识单元；不读取或修改 EduRAG 的集合。
- 方舟 `doubao-embedding-vision-251215`，通过 `/embeddings/multimodal` 发送纯文本，2048维；使用 COSINE + FLAT 索引，为小规模语料建立精确搜索基线。
- 本地 JSON 保留为原始知识及型号匹配数据，向量与文本、章节、来源元数据写入 Milvus。
- 这不是全离线方案：Embedding、豆包生成与 RTC 仍使用云服务。

## 配置

在 `rag_llm_server/.env` 设置下列项，凭据仅放后端，模板见 `.env.example`：

```dotenv
KB_MODE=milvus
MILVUS_URI=http://127.0.0.1:19530
MILVUS_DATABASE=default
MILVUS_COLLECTION=voice_commerce_v1
MILVUS_TOKEN=
MILVUS_MIN_SCORE=0.45
EMBEDDING_MODEL=doubao-embedding-vision-251215
EMBEDDING_API_PATH=/embeddings/multimodal
EMBEDDING_DIMENSIONS=2048
```

`EMBEDDING_API_KEY` 为空时复用 `ARK_API_KEY`；`EMBEDDING_BASE_URL` 默认复用 `ARK_BASE_URL`。也可对接 OpenAI 风格 `/embeddings`，返回 `data[0].embedding`。查询与入库必须使用相同的模型、接口与维度。

模型更换时建议使用新集合。2048维方舟向量不能直接混入旧 EduRAG 的1024维 BGE-M3 集合。代码同时使用语料哈希及 Embedding 配置指纹过滤，防止旧版本或不同模型的向量参与查询。

## 首次导入与知识更新

先启动 Milvus Server 及对应依赖，在 `rag_llm_server` 激活虚拟环境后执行：

```bash
python sync_milvus.py
python sync_milvus.py --check
python main.py
```

首次导入会调用 Embedding API 并产生服务用量。相同语料和模型再次执行会直接报告 `already_current`，不重复向量化。更新 Markdown 时也要更新 `knowledge/corpus.json`，再重新导入、重启后端。脚本只创建/加载集合和 upsert，不执行 drop/delete；旧版本保留但不参与当前版本检索。

## 录制演示

- `http://localhost:3001/docs`：后端接口。
- `http://localhost:3001/debug/knowledge`：模式、集合、模型、维度及有效记录数，不返回凭据。
- `/debug/rag?query=SC-PB27多重`：`catalog_exact`，具体型号精确匹配。
- `/debug/rag?query=拆开盒子以后不想要了还能退吗`：`milvus`，展示来源、章节、COSINE 分数及检索正文。
- `/debug/rag?query=怎么做红烧肉`：当前验证为 `no_results`；不能把任何 Top-K 结果都当作有效证据。

`MILVUS_MIN_SCORE=0.45` 是当前小规模演示的初始阈值，未证明为最优阈值。分数不等于回答正确概率，后续应使用独立验证集校准。

## 验证

```bash
python -m unittest test_reproduction test_commerce test_evaluate_commerce test_milvus -v
# 真实 Milvus / Embedding + 模拟回答，不调用真实生成模型
python evaluate_commerce.py --backend milvus
# 真实检索与生成，会产生云 API 用量
python evaluate_commerce.py --live --backend milvus --ids 1 11
```

不同后端的评测报告使用独立文件名，保存在仓库根目录 `.runtime/`。已有147题是关键词检查，不是完整事实准确率；更换后端后需要重新验证，不能沿用旧结果。

本实现是稠密向量检索，没有接入 EduRAG 的稀疏混合检索和 BGE 重排模型。检索前不使用字面重合门控，避免同义问法被提前拦截；云端旧路径及 sample 模式保持独立。

## Attu 管理页面

本机可访问 http://localhost:8081 ，Attu 2.4.12 通过 Docker 网络连接 Milvus 2.4.4。连接地址为 milvus-standalone:19530，数据库 default，集合 voice_commerce_v1。进入 Schema 查看89条记录、FloatVector(2048)、FLAT/COSINE；进入“数据”查看向量及动态元数据（正文、来源、章节等在 $meta 中）。

当前6379端口对应Redis服务，不能作为Milvus网页打开。旧Attu容器原映射30000端口；当前为项目1另设8081入口。Embedding配置由后端.env管理，Attu连接成功不需要重新选择Embedding模型；切换模型需重新向量化并使用兼容的新集合。
