# 贡献指南

感谢你关注校园失物招领平台！欢迎以任何形式参与贡献：报告问题、修复缺陷、完善文档、新增功能。

## 贡献流程

1. **Fork** 本仓库到你的账号下；
2. 从 `main`（或默认分支）拉出功能分支，命名建议：
   - 功能：`feat/xxx`
   - 修复：`fix/xxx`
   - 文档：`docs/xxx`
3. 在分支上开发并提交；
4. 向本仓库发起 **Pull Request**，描述清楚改动内容、动机与自测情况；
5. 等待维护者 Review，根据反馈修改，合并后即可删除分支。

## 提交规范

提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)，格式：

```
<type>(<scope>?): <描述>
```

常用 type：

| type | 含义 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 文档变更 |
| `refactor` | 重构（不改行为） |
| `test` | 测试相关 |
| `chore` | 构建、依赖、配置等杂项 |

示例：

```
feat(chat): 支持会话级已读标记
fix(matching): 修复时间相似度衰减计算错误
docs: 补充环境变量说明
```

## 开发约定

- 修改代码前先在本地跑通：`.env` 配置 → `docker compose up -d` → 导入 `lost_and_found.sql` → `python run.py`；
- 不要提交 `.env`、真实密钥、日志文件；新增环境变量需同步更新 `.env.example` 与 README 的环境变量说明表；
- 涉及安全逻辑（鉴权、限流、密码、令牌）的改动请在 PR 中说明威胁模型与测试方式；
- 提交前确认 `git status` 中没有意外文件被暂存。

## 报告问题

- 功能缺陷请提 Issue，附上复现步骤、期望行为与实际行为、相关日志（**注意先脱敏**，不要粘贴密钥与真实个人信息）；
- 安全漏洞请不要在公开 Issue 中披露，参见 [SECURITY.md](SECURITY.md)。
