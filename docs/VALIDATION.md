# 2026-10-31 验证记录

后端 unittest：17/17 通过；前端 Jest：5/5 通过。
默认 147 题本地模拟关键词回归：136/147 通过；未通过 ID 为 76、84、85、103、114、117、121、125、139、141、147。
这些结果属于 sample_retrieval_only，不能当作真实模型事实准确率。未通过项需要进一步区分模拟答复、检索覆盖和规则误判；未为通过率放宽测试。
当前 evaluate_commerce.py 输出统计，未将关键词未通过转换为非零退出码，CI 中此步骤用于生成报告。
本次未调用真实 RTC、云知识库、文本与语音服务。

## 2026-11-02 Milvus 接入验证

- Milvus Server 2.4.4，独立 voice_commerce_v1 集合，有效记录89条。旧 demo_v1 集合未改动。
- Embedding：方舟 doubao-embedding-vision-251215，纯文本输入，2048维；COSINE + FLAT。不是本地BGE-M3或离线模型，也未接入稀疏混合检索、Reranker。
- 真实检索开发样例：拆封退货命中包装已打开条款；退款到账命中到账章节；天气、菜谱、量子问题均无结果；具体SKU精确匹配、未知SKU拒答。
- 实际HTTP检查：health/knowledge_ready均为true，debug/knowledge确认集合及89条记录；4个检索场景通过。真实豆包文本问答1次、带鉴权的真实模型SSE回调1次通过。未在本次重新人工验收麦克风、ASR/TTS、插话与长时间通话。
- 147题全量检查：真实Milvus与Embedding + 模拟生成，135/147；模式为milvus_retrieval_mock_llm，不能当成真实模型回答准确率。用例文件SHA256 f8cdef70e5aeb092dc8f3f3df63d08002804f7a3566568531c483432e7525365。
- 未通过ID：76、84、85、103、112、114、117、121、125、139、141、146。未为通过率修改断言或调整门限。
- 与此前sample检索136/147相比，112、146由通过变未通过，147由未通过变通过。147题的当前通过答案实际上是缺证据答复（含“人工”而被关键词断言判定通过），不能宣称完成了电池鼓包安全处置。这说明关键词评测存在假阳性，仍需人工语义核查。
- 原始报告在忽略的 .runtime/milvus-live-validation.json、milvus-e2e-validation.json、ecommerce-eval-sample-milvus.json 中。此次迁移证明后端可用，尚未证明优于托管云知识库。

本次最终自动化检查：26/26 通过（含9项 Milvus 协议、隔离、兼容性和就绪状态测试）。

## 2026-11-02 回退后的重新核验

首次Milvus提交ae6ffef曾被0f0d4d6完整撤销。本轮按文件恢复实现，保留原README结构补充Milvus配置，并将个人演示口播及简历交接保留在仓库外。

- 后端unittest 26/26、前端Jest 5/5通过；生产构建成功，仍有既有ESLint/格式、旧Browserslist及包体积警告。
- 实际运行模式milvus，非mock，knowledge_ready=true；当前版本89条，2048维，COSINE。
- 实际HTTP四种路由通过：SC-PB27型号精确匹配、拆封问题Milvus检索、菜谱无结果、未知SC-PB999拒答。
- 真实豆包文本问答及带鉴权SSE回调通过，回调含assistant角色帧和[DONE]。检查允许合理的回答措辞变化，不将特定关键词当成完整事实准确率。
- 新的本机证据在忽略的 `.runtime/milvus-e2e-recheck-2026-11-02.json`。上文147题135/147属于首次迁移的历史报告，本轮未重新执行全量，也未重新人工验收音频。
