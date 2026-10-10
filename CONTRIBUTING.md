# 参与贡献

欢迎提交缺陷报告、文档改进和代码贡献。

1. Fork 仓库，从 `main` 创建分支。
2. 按 [README](README.md#快速开始) 安装依赖，只使用自己的本地配置。
3. 提交改动前运行：

```bash
npm test -- --watchAll=false --runInBand
npm run build
cd rag_llm_server
python -m unittest test_reproduction test_commerce -v
python evaluate_commerce.py
```

4. Pull Request 说明问题、变更和验证结果；涉及语音行为时附人工验收步骤。

商品资料必须标注演示性质，更新 Markdown 时同步修改 `knowledge/corpus.json` 的知识单元、来源与校验信息，并补充回归题。请勿提交密钥、真实订单、客户语音、账户截图或日志正文。公开 Issue 中仅提供脱敏后的错误类型与复现步骤。

贡献采用本仓库 BSD-3-Clause 许可证；保留已有版权声明和第三方归属。
