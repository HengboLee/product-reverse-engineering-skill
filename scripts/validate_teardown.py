#!/usr/bin/env python3
"""校验产品逆向拆解报告的证据边界、固定结构、交互和模板完整性。"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


SECTION_IDS = {
    "journey": ["scope", "unknown", "evidence", "journey", "emotion", "issues", "opportunities", "notes"],
    "agent-contract": ["scope", "agents", "contracts", "tools", "context", "relations", "flow", "ledger", "verify"],
    "functional-prompt": ["evidence", "inputs", "outputs", "tools", "states", "rules", "prompt", "trace", "tests", "unknown"],
    "architecture": [
        "summary", "evidence", "domains", "e2e", "layers", "agent-map", "context", "knowledge", "models",
        "technology", "entities", "sequence", "panorama", "asis", "tobe", "risks", "trace", "unknowns",
    ],
}

PROFILE_FOR_MODE = {
    "journey": "journey",
    "agent-contract": "agent-contract",
    "functional-prompt": "functional-prompt",
    "architecture": "architecture",
}

ORDER_FOR_MODE = {
    "journey": "1",
    "agent-contract": "2",
    "functional-prompt": "3",
    "architecture": "4",
}

PACKAGE_CONTRACTS = (
    ("01-", "journey"),
    ("02-", "agent-contract"),
    ("03-", "functional-prompt"),
    ("04-", "architecture"),
)

MARKDOWN_TERMS = {
    "evidence": ("查看范围", "来源清单", "证据台账", "冲突", "覆盖矩阵", "停止边界"),
    "journey": ("查看范围", "无法", "用户旅程证据表", "用户旅程图", "痛点", "产品机会"),
    "agent-contract": ("查看范围", "Agent", "I/O", "工具总表", "全局上下文", "生产者", "消费者", "未知"),
    "functional-prompt": ("证据范围", "输入契约", "输出契约", "工具契约", "状态机", "System Prompt", "证据追溯", "测试"),
    "architecture": ("执行摘要", "证据来源", "核心功能域", "端到端", "分层架构", "As-Is", "To-Be", "风险", "证据追溯"),
}

CANONICAL_EVIDENCE_RE = re.compile(r"\bEV-[A-Z0-9]+-\d{3,}\b")
CANONICAL_SOURCE_RE = re.compile(r"\bSRC-\d{3,}\b")
DISPLAY_EVIDENCE_RE = re.compile(r"\b(?:E-[A-Z0-9]+-\d{3,}|E\d{2,3}|S\d{2,3})\b")
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")


class ReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.text_parts: list[str] = []
        self.report_sections: list[str] = []
        self.nav_hrefs: list[str] = []
        self.classes: Counter[str] = Counter()
        self.attrs_by_name: dict[str, list[str]] = {}
        self.body_profile = ""
        self.body_order = ""
        self.body_priority = ""
        self.upstream_reports = ""
        self.html_lang = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        self.tags.append((tag, values))
        for key, value in values.items():
            self.attrs_by_name.setdefault(key, []).append(value)
        for token in values.get("class", "").split():
            self.classes[token] += 1
        if tag == "html":
            self.html_lang = values.get("lang", "")
        if tag == "body":
            self.body_profile = values.get("data-report-profile", "")
            self.body_order = values.get("data-report-order", "")
            self.body_priority = values.get("data-report-priority", "")
            self.upstream_reports = values.get("data-upstream-reports", "")
        if tag == "section" and values.get("data-report-section"):
            self.report_sections.append(values.get("id", ""))
        if tag == "a" and values.get("href", "").startswith("#"):
            self.nav_hrefs.append(values["href"][1:])

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text_parts.append(data)

    @property
    def text(self) -> str:
        return "\n".join(self.text_parts)

    def tags_named(self, name: str) -> list[dict[str, str]]:
        return [attrs for tag, attrs in self.tags if tag == name]

    def attr_values(self, name: str) -> list[str]:
        return self.attrs_by_name.get(name, [])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="报告文件；package 模式可传目录")
    parser.add_argument("--mode", choices=("evidence", "journey", "agent-contract", "functional-prompt", "architecture", "package"), default="evidence")
    parser.add_argument("--ledger", type=Path, help="独立证据台账")
    parser.add_argument("--manifest", type=Path, help="来源清单 CSV 或 JSON")
    parser.add_argument("--template", action="store_true", help="校验带占位符的模板结构")
    parser.add_argument("--allow-markdown", action="store_true", help="仅快速模式允许 Markdown 主报告")
    parser.add_argument("--allow-legacy", action="store_true", help="迁移旧报告时允许紧凑证据编号")
    return parser.parse_args()


def read_path(path: Path) -> tuple[str, list[Path]]:
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace"), [path]
    if path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.casefold() in {".md", ".html", ".htm", ".csv"})
        return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in files), files
    raise FileNotFoundError(path)


def load_manifest_ids(path: Path) -> set[str]:
    if path.suffix.casefold() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(row.get("source_id")) for row in data if row.get("source_id")}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["source_id"] for row in csv.DictReader(handle) if row.get("source_id")}


def has_tag(parser: ReportParser, tag: str, attr: str | None = None) -> bool:
    for tag_name, attrs in parser.tags:
        if tag_name == tag and (attr is None or attr in attrs):
            return True
    return False


def class_count(parser: ReportParser, class_name: str) -> int:
    return parser.classes[class_name]


def validate_section_contract(parser: ReportParser, mode: str, errors: list[str]) -> None:
    expected = SECTION_IDS[mode]
    if parser.report_sections != expected:
        errors.append(
            "主章节顺序不符合模板：期望 " + " → ".join(expected) + "；实际 " + " → ".join(parser.report_sections)
        )
    nav_subset = [item for item in parser.nav_hrefs if item in expected]
    if nav_subset != expected:
        errors.append("页内导航顺序与固定章节不一致")


def validate_common_html(path: Path, parser: ReportParser, mode: str, template: bool, errors: list[str], warnings: list[str]) -> None:
    if parser.html_lang != "zh-CN":
        errors.append(f"{path.name} 必须设置 lang=zh-CN")
    if parser.body_profile != PROFILE_FOR_MODE[mode]:
        errors.append(f"data-report-profile 应为 {PROFILE_FOR_MODE[mode]}")
    if parser.body_order != ORDER_FOR_MODE[mode]:
        errors.append(f"data-report-order 应为 {ORDER_FOR_MODE[mode]}")
    if mode == "architecture":
        if parser.body_priority != "primary":
            errors.append("04 架构报告必须设置 data-report-priority=primary")
        if parser.upstream_reports != "01,02,03":
            errors.append("04 架构报告必须声明整合 data-upstream-reports=01,02,03")
    if not has_tag(parser, "h1") or not has_tag(parser, "h2"):
        errors.append("缺少语义化 h1/h2")
    if not has_tag(parser, "nav"):
        errors.append("缺少语义化页内导航")
    if not parser.attr_values("data-stop-boundary"):
        errors.append("页脚缺少 data-stop-boundary 停止边界")
    if not template and PLACEHOLDER_RE.search(parser.text):
        errors.append("最终报告仍有未替换的 {{PLACEHOLDER}}")
    if not template and not parser.attr_values("data-evidence-id"):
        errors.append("最终报告没有 data-evidence-id，关键结论无法稳定追溯")

    labels = {
        "journey": ("页面事实", "合理推断", "尚未确认"),
        "agent-contract": ("已确认", "合理推断", "未知"),
        "functional-prompt": ("事实规则", "推断规则", "建议规则", "未知"),
        "architecture": ("已确认", "合理推断", "建议设计", "未知"),
    }[mode]
    for label in labels:
        if label not in parser.text:
            errors.append(f"缺少证据或规则标签：{label}")

    for tag, attrs in parser.tags:
        if tag not in {"link", "script", "img"}:
            continue
        value = attrs.get("href") or attrs.get("src") or ""
        if value.startswith(("http://", "https://", "//")):
            errors.append(f"存在外部资源依赖：{value}")
        if value and not value.startswith(("#", "data:")) and not urlparse(value).scheme:
            target = (path.parent / value).resolve()
            if not target.exists():
                errors.append(f"相对资源不存在：{value}")

    validate_section_contract(parser, mode, errors)


def validate_journey(parser: ReportParser, template: bool, errors: list[str], warnings: list[str]) -> None:
    paths = set(parser.attr_values("data-path-kind"))
    if paths != {"normal", "correction", "failure"}:
        errors.append("用户旅程必须包含 normal、correction、failure 三类路径")
    if len(parser.tags_named("textarea")) < 3:
        errors.append("补充区必须包含三个 textarea")
    for attr in ("data-notes-save", "data-notes-export", "data-notes-clear"):
        if not parser.attr_values(attr):
            errors.append(f"补充区缺少交互：{attr}")
    if not template:
        if class_count(parser, "decision") < 3:
            errors.append("三类路径合计至少需要三个明确判断节点")
        if len(parser.attr_values("data-emotion-stage")) < 3:
            errors.append("至少需要三个带 data-emotion-stage 的情绪节点")
        if len(parser.attr_values("data-ux-issue")) != 3:
            errors.append("第 6 章必须恰好包含三个 data-ux-issue")


def validate_agent_contract(parser: ReportParser, template: bool, errors: list[str], warnings: list[str]) -> None:
    cards = len(parser.attr_values("data-contract-card"))
    if cards < 1:
        errors.append("至少需要一张 data-contract-card")
    sections = Counter(parser.attr_values("data-contract-section"))
    for number in map(str, range(1, 11)):
        if sections[number] != cards:
            errors.append(f"每张契约卡都必须且只能有一段 data-contract-section={number}")
    for attr in ("data-contract-search", "data-contract-open-all", "data-contract-close-all"):
        if not parser.attr_values(attr):
            errors.append(f"Agent 契约缺少交互：{attr}")
    filters = set(parser.attr_values("data-filter"))
    if not {"all", "fact", "inference", "unknown"}.issubset(filters):
        errors.append("Agent 契约缺少全部/事实/推断/未知筛选")
    if not template:
        sources = ("用户当前输入", "用户长期信息", "项目全局上下文", "上游 Agent 输出", "平台公共", "工具或运行时结果")
        for source in sources:
            if source not in parser.text:
                warnings.append(f"六类输入中未找到：{source}")


def validate_functional_prompt(parser: ReportParser, template: bool, errors: list[str], warnings: list[str]) -> None:
    if len(parser.attr_values("data-boundary-question")) != 10:
        errors.append("目标 Agent 边界必须恰好包含十问")
    rule_classes = set(parser.attr_values("data-rule-class"))
    if rule_classes != {"fact", "inference", "recommendation", "unknown"}:
        errors.append("规则必须完整分为 fact、inference、recommendation、unknown")
    prompt_sections = Counter(parser.attr_values("data-prompt-section"))
    for number in map(str, range(1, 16)):
        if prompt_sections[number] != 1:
            errors.append(f"System Prompt 必须且只能有一个 data-prompt-section={number}")
    if len(parser.attr_values("data-test-case")) < 6:
        errors.append("最小测试集不得少于六条")
    copy_targets = set(parser.attr_values("data-copy-target"))
    if not {"stateCode", "systemPrompt"}.issubset(copy_targets):
        errors.append("缺少状态图或 System Prompt 复制按钮")
    if "state" not in parser.attr_values("data-diagram-kind"):
        errors.append("缺少状态图源码 data-diagram-kind=state")


def validate_architecture(parser: ReportParser, template: bool, errors: list[str], warnings: list[str]) -> None:
    diagram_kinds = set(parser.attr_values("data-diagram-kind"))
    not_applicable = set(parser.attr_values("data-not-applicable-for"))
    for kind in ("er", "sequence", "panorama"):
        if kind not in diagram_kinds and kind not in not_applicable:
            errors.append(f"缺少 {kind} 图源码或 data-not-applicable-for={kind} 的说明")
    filters = set(parser.attr_values("data-filter"))
    if not {"all", "confirmed", "inference", "recommendation", "unknown"}.issubset(filters):
        errors.append("架构追溯缺少四类证据筛选")
    risks = len(parser.attr_values("data-risk"))
    if risks < 3:
        errors.append("关键架构风险不得少于三项")
    elif risks < 5:
        warnings.append("参考级架构报告建议至少五项排序后的风险")


def validate_html_file(path: Path, mode: str, template: bool, errors: list[str], warnings: list[str]) -> None:
    parser = ReportParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    validate_common_html(path, parser, mode, template, errors, warnings)
    if mode == "journey":
        validate_journey(parser, template, errors, warnings)
    elif mode == "agent-contract":
        validate_agent_contract(parser, template, errors, warnings)
    elif mode == "functional-prompt":
        validate_functional_prompt(parser, template, errors, warnings)
    elif mode == "architecture":
        validate_architecture(parser, template, errors, warnings)


def validate_package(path: Path, template: bool, errors: list[str], warnings: list[str]) -> None:
    if not path.is_dir():
        errors.append("package 模式必须传入完整交付目录")
        return

    html_files = sorted(item for item in path.glob("*.html") if item.is_file())
    if len(html_files) != 4:
        errors.append(f"完整交付目录必须恰好包含四份顶层 HTML，当前为 {len(html_files)} 份")
    expected_prefixes = tuple(prefix for prefix, _ in PACKAGE_CONTRACTS)
    unexpected = [item.name for item in html_files if not item.name.startswith(expected_prefixes)]
    if unexpected:
        errors.append("发现不属于 01—04 的顶层 HTML：" + ", ".join(unexpected))
    package_reports: list[Path] = []
    for prefix, mode in PACKAGE_CONTRACTS:
        matches = [item for item in html_files if item.name.startswith(prefix)]
        if not matches:
            errors.append(f"完整交付缺少 {prefix.rstrip('-')} 主报告（profile={mode}）")
            continue
        if len(matches) > 1:
            errors.append(f"完整交付存在多个 {prefix.rstrip('-')} 主报告：" + ", ".join(item.name for item in matches))
            continue
        report = matches[0]
        package_reports.append(report)
        validate_html_file(report, mode, template, errors, warnings)

    if len(package_reports) == 4:
        actual = [item.name[:3] for item in package_reports]
        if actual != ["01-", "02-", "03-", "04-"]:
            errors.append("完整交付必须按 01→02→03→04 编号")


def validate_markdown(text: str, mode: str, errors: list[str]) -> None:
    terms = MARKDOWN_TERMS.get(mode, ())
    for term in terms:
        if term not in text:
            errors.append(f"快速 Markdown 缺少关键内容：{term}")


def main() -> int:
    args = parse_args()
    report_path = args.report.resolve()
    errors: list[str] = []
    warnings: list[str] = []

    try:
        text, files = read_path(report_path)
    except FileNotFoundError:
        print(f"错误：找不到报告：{report_path}")
        return 2

    if args.mode == "package":
        validate_package(report_path, args.template, errors, warnings)
    elif args.mode == "evidence":
        validate_markdown(text, "evidence", errors)
    else:
        html_files = [path for path in files if path.suffix.casefold() in {".html", ".htm"}]
        if not html_files:
            if args.allow_markdown:
                validate_markdown(text, args.mode, errors)
            else:
                errors.append("参考级阶段报告必须是 HTML；只有明确快速模式才能使用 --allow-markdown")
        for html_path in html_files:
            validate_html_file(html_path, args.mode, args.template, errors, warnings)

    evidence_refs = set(CANONICAL_EVIDENCE_RE.findall(text))
    source_refs = set(CANONICAL_SOURCE_RE.findall(text))
    if not args.template and args.mode != "evidence" and not evidence_refs:
        if args.allow_legacy and DISPLAY_EVIDENCE_RE.search(text):
            warnings.append("只发现紧凑证据编号；建议在 data-evidence-id 中保留规范 EV-* 编号")
        else:
            errors.append("没有找到规范 EV-<阶段>-<三位序号> 证据编号")

    if args.ledger:
        ledger = args.ledger.resolve()
        if not ledger.is_file():
            errors.append(f"找不到证据台账：{ledger}")
        else:
            ledger_ids = set(CANONICAL_EVIDENCE_RE.findall(ledger.read_text(encoding="utf-8", errors="replace")))
            missing = evidence_refs - ledger_ids
            if missing:
                errors.append("报告引用了台账中不存在的证据：" + ", ".join(sorted(missing)))

    if args.manifest:
        manifest = args.manifest.resolve()
        if not manifest.is_file():
            errors.append(f"找不到来源清单：{manifest}")
        else:
            try:
                manifest_ids = load_manifest_ids(manifest)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                errors.append(f"无法读取来源清单：{exc}")
            else:
                missing = source_refs - manifest_ids
                if missing:
                    errors.append("报告引用了清单中不存在的来源：" + ", ".join(sorted(missing)))

    risky_patterns = {
        "读取到隐藏思维链": "不得声称读取隐藏思维链",
        "官方 System Prompt 如下": "不得把功能等价 Prompt 冒充官方原文",
        "已确认使用 PostgreSQL": "数据库类型需要官方直接证据",
        "已确认使用 Kafka": "消息队列类型需要官方直接证据",
        "随机误判": "安全或模型失败原因需要证据",
    }
    for phrase, reason in risky_patterns.items():
        if phrase in text:
            warnings.append(f"高风险表述“{phrase}”：{reason}")

    if re.search(r"页面(?:没有|未显示).{0,20}(?:所以|因此).{0,20}不存在", text):
        warnings.append("可能把‘页面未显示’错误推成‘不存在’")

    for warning in dict.fromkeys(warnings):
        print(f"警告：{warning}")
    for error in dict.fromkeys(errors):
        print(f"错误：{error}")

    if errors:
        print(f"未通过：{len(set(errors))} 个错误，{len(set(warnings))} 个警告")
        return 1
    print(f"通过：模式={args.mode}，检查文件={len(files)}，{len(set(warnings))} 个警告")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
