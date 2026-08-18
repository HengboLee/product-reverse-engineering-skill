# Product Reverse Engineering Skill

一个面向 Codex 的证据驱动型产品逆向拆解 Skill。它从真实页面、截图、录屏、聊天记录、状态、资产和错误信息中，还原产品的用户旅程、Agent 协作方式与产品架构。

## 主要输出

完整模式会依次生成四份中文 HTML 报告：

1. 用户旅程与页面取证
2. Agent / 自动化 I/O 契约
3. 单 Agent 功能等价 System Prompt
4. 产品全景架构（核心总报告）

报告严格区分页面事实、合理推断、建议设计和未知事项，并保留证据追溯关系。

## 安装

```bash
git clone https://github.com/HengboLee/product-reverse-engineering-skill.git \
  ~/.codex/skills/product-reverse-engineering
```

## 使用

在 Codex 中输入类似指令：

```text
使用 $product-reverse-engineering，基于这些产品截图完成一次完整的产品逆向拆解。
```

也可以只要求用户旅程、Agent 契约、功能等价 Prompt 或产品架构中的某个阶段。

## 设计原则

- 以页面证据为准，不把 Agent 的口头声明当成实际完成。
- 不声称读取隐藏思维链、官方 System Prompt 或内部 API。
- 明确记录聊天、任务、状态与资产之间的冲突。
- 完整模式必须生成 01—04 四份 HTML，04 最后生成。

## License

[MIT](LICENSE)
