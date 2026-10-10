# 手动发布到 GitHub

推荐仓库名：`voice-commerce-assistant`。

推荐简介：`Real-time voice customer service for 3C commerce, powered by React, FastAPI, RTC and RAG.`

## GitHub Desktop

1. 选择 **File → Add local repository**，选中本项目根目录（含 `package.json` 与 `README.md` 的目录）。项目已初始化 Git。
2. 在 Changes 中检查文件；如果已有本地初始提交，可直接下一步。若有新增改动，先 Commit to main。
3. 点击 **Publish repository**，填写名称与简介。
4. **取消勾选 Keep this code private**，点击 Publish repository，公开发布。
5. 在 GitHub 页面确认 README、LICENSE、源码、配置模板与 Actions 流程均已显示。
6. 建议添加 topics：`voice-assistant`、`rag`、`rtc`、`fastapi`、`react`、`customer-service`。

## 浏览器上传

工作区中另提供 `项目1-GitHub开源上传包.zip`，只包含 Git 跟踪的安全文件。

1. 解压上传包，在 GitHub 新建 Public 仓库。不要额外勾选生成 README、LICENSE 或 .gitignore，包中已有。
2. 点击 **uploading an existing file**，上传解压后的文件和文件夹，保留目录结构，不要直接上传 ZIP。
3. 浏览器通常隐藏点号文件，请确认 `.gitignore`、`.github/workflows/ci.yml` 与 `rag_llm_server/.env.example` 也已上传。
4. 若界面限制一次文件数量，分批上传；更推荐使用 GitHub Desktop 保留完整目录。

不要将正在运行的项目原目录整体拖入网页；网页上传不应用 `.gitignore`，原目录含本地密钥和依赖。使用上传包或 GitHub Desktop。

## 发布后文档维护

截图替换见 [文档说明](DOCUMENTATION.md)。Actions 状态徽章可在发布后从实际仓库复制到 README，避免仓库名称变更导致链接失效。BSD-3-Clause 许可证和第三方声明须一并保留。
