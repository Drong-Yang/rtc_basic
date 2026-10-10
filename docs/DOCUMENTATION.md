# 文档使用与维护

## 阅读顺序

- 初次运行：根目录 [README](../README.md)，先运行本地文本演示。
- 接真实语音：[部署与配置](DEPLOYMENT.md)。
- 开发与提交：[贡献指南](../CONTRIBUTING.md)。
- 公开部署：[安全说明](../SECURITY.md)。
- 上游参考：[原始 README](UPSTREAM_README.md)，其中 Node 服务是旧示例路径，当前电商主后端为 `rag_llm_server`。

## 替换图片

README 已引用 `docs/assets/preview.svg`，这是带说明的占位图，不是项目运行截图。获得脱敏截图后，将其保存为 `docs/assets/demo-desktop.png`，并将 README 图片链接改为该路径。建议补充：桌面通话界面、移动端界面、检索来源展示。禁止截图包含后台凭据、完整 Token 或真实个人信息。

## Markdown 约定

使用相对路径连接仓库文档；目录锚点与标题保持一致；代码块标注 `bash`、`powershell`、`json` 等语言。用 `<details><summary>标题</summary>` 放置可选步骤，标签内部留空行，确保 GitHub 能解析 Markdown。Mermaid 图由 GitHub 渲染，必要时可导出为图片。

修改配置字段后同步更新 `.env.example`、README 和部署说明；新增入口时补充启动命令。示例只能包含占位值。自动化检查、文本评测与真实通话验收应分别记录，不能把文本关键词通过率作为语音准确率。

## 日常更新仓库

```bash
git status
git add README.md docs CONTRIBUTING.md SECURITY.md
git diff --cached
git commit -m "docs: update usage guide"
git push origin main
```

也可在 GitHub Desktop 中添加本地仓库、检查 Changes、提交并点击 Push origin。新增图片时将对应图片文件一并提交。
