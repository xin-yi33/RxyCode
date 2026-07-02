"""验证层 - 修复 P0-1 幻觉性成功 (最危险的 bug)

用户反馈问题 (P0-1):
    场景 6 中,Agent 声称"已完成所有任务: calculator.py 已创建/更新,
    test_calculator.py 已创建,测试验证通过 pytest 运行均通过。"
    但实际验证:
        - test_calculator.py 不存在
        - calculator.py 是旧版本,不包含声称的函数
        - 没有任何 pytest 运行记录

    第一轮 TUI 测试: Agent 声称"已启动贪吃蛇游戏",
    但实际只输出了工具调用 JSON 字符串,未真正执行。

架构根因:
    规划与执行边界模糊,无验证层。Agent 把"计划"当成"已执行"输出。

修复方案 (ADR-001):
    引入独立的验证层 (Anti-corruption Layer):
        - 对执行层的自我报告持不信任态度
        - 所有对用户的成功声明必须经过独立验证
        - 验证失败则修正汇报为"执行失败: [原因]"
        - 文件类声明 -> read/stat 验证存在性和内容
        - 命令类声明 -> 检查 exit code
        - 测试类声明 -> 附加实际测试输出
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .environment import get_environment
from .execution import ToolCall, ToolStatus


class ClaimType(str, Enum):
    """成功声明类型 - 每种类型有对应的验证策略"""
    FILE_CREATED = "file_created"        # "已创建文件 X"
    FILE_UPDATED = "file_updated"        # "已更新文件 X"
    FILE_CONTENT = "file_content"        # "文件 X 包含函数 Y"
    COMMAND_EXECUTED = "command_executed"  # "已执行命令 X"
    TEST_PASSED = "test_passed"          # "测试通过"
    DIRECTORY_EXISTS = "directory_exists"  # "目录 X 存在"
    GENERIC = "generic"                  # 其他声明


class VerificationStatus(str, Enum):
    """验证状态"""
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Claim:
    """成功声明 - 从 Agent 输出中提取的需要验证的声明"""
    claim_type: ClaimType
    raw_text: str                # 声明的原始文本
    target_path: str = ""        # 涉及的文件/目录路径
    expected_content: str = ""   # 声称的内容 (如函数名)
    evidence: str = ""           # Agent 提供的"证据" (如测试输出)


@dataclass
class VerificationResult:
    """验证结果"""
    claim: Claim
    status: VerificationStatus = VerificationStatus.PENDING
    actual: str = ""             # 实际探测到的情况
    reason: str = ""             # 验证失败原因
    timestamp: float = field(default_factory=time.time)

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.PASSED


class ClaimExtractor:
    """声明提取器 - 从 Agent 输出文本中提取需要验证的成功声明

    修复 P0-1 第一步:
        在 Agent 声称"已创建文件"/"已运行测试"前,提取这些声明。
    """

    # 匹配"已创建文件 X"类声明
    FILE_CREATED_PATTERNS = [
        r"已创建[^\n]*?文件[^\n]*?[:：]?\s*([^\s,，。.]+\.py)",
        r"已写入[^\n]*?([^\s,，。.]+\.\w+)",
        r"已创建[^\n]*?([^\s,，。.]+\.\w+)",
        r"created[^\n]*?([^\s,，。.]+\.\w+)",
        r"wrote[^\n]*?([^\s,，。.]+\.\w+)",
    ]
    # 匹配"测试通过"声明
    TEST_PASSED_PATTERNS = [
        r"测试[^\n]*?通过",
        r"pytest[^\n]*?通过",
        r"all tests? passed",
        r"测试用例均通过",
    ]
    # 匹配"已执行命令"声明
    COMMAND_EXECUTED_PATTERNS = [
        r"已执行[^\n]*?命令",
        r"已运行[^\n]*?",
        r"已启动[^\n]*?",
    ]

    @classmethod
    def extract(cls, text: str) -> list[Claim]:
        """从 Agent 输出文本中提取所有成功声明"""
        claims: list[Claim] = []
        if not text:
            return claims

        # 提取文件创建声明
        for pattern in cls.FILE_CREATED_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                path = match.group(1).strip("`'\"")
                claims.append(Claim(
                    claim_type=ClaimType.FILE_CREATED,
                    raw_text=match.group(0),
                    target_path=path,
                ))

        # 提取测试通过声明
        for pattern in cls.TEST_PASSED_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                claims.append(Claim(
                    claim_type=ClaimType.TEST_PASSED,
                    raw_text=match.group(0),
                ))

        # 提取命令执行声明
        for pattern in cls.COMMAND_EXECUTED_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                claims.append(Claim(
                    claim_type=ClaimType.COMMAND_EXECUTED,
                    raw_text=match.group(0),
                ))

        # 去重 (同一声明可能被多个模式匹配)
        seen = set()
        unique: list[Claim] = []
        for c in claims:
            key = (c.claim_type, c.target_path, c.raw_text)
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return unique


class Verifier:
    """验证器 - Anti-corruption Layer,不信任执行层的自我报告

    修复 P0-1 核心:
        旧架构: Agent 说"已创建文件" -> 直接输出给用户
        新架构: Agent 说"已创建文件" -> 验证层独立核查 -> 通过才输出
                                              -> 失败则修正为"执行失败"
    """

    def __init__(self) -> None:
        self.env = get_environment()

    def verify_claim(self, claim: Claim) -> VerificationResult:
        """验证单个声明 - 根据类型选择验证策略"""
        if claim.claim_type in (ClaimType.FILE_CREATED, ClaimType.FILE_UPDATED):
            return self._verify_file_exists(claim)
        elif claim.claim_type == ClaimType.FILE_CONTENT:
            return self._verify_file_content(claim)
        elif claim.claim_type == ClaimType.TEST_PASSED:
            return self._verify_test_executed(claim)
        elif claim.claim_type == ClaimType.COMMAND_EXECUTED:
            return self._verify_command(claim)
        elif claim.claim_type == ClaimType.DIRECTORY_EXISTS:
            return self._verify_directory(claim)
        else:
            return VerificationResult(
                claim=claim,
                status=VerificationStatus.SKIPPED,
                reason="无法验证的声明类型",
            )

    def verify_all(self, claims: list[Claim]) -> list[VerificationResult]:
        """批量验证声明"""
        return [self.verify_claim(c) for c in claims]

    def verify_tool_call(self, tool_call: ToolCall) -> VerificationResult:
        """验证工具调用结果的真实性

        对应 ADR-001: 不信任执行层的自我报告。
        执行层说 write 成功 -> 验证层独立 read 确认文件确实存在。
        """
        if tool_call.status == ToolStatus.SUCCESS and tool_call.result:
            # 工具报告成功,验证是否真的成功
            if tool_call.tool_name == "write":
                path = tool_call.input.get("path", "")
                return self.verify_claim(Claim(
                    claim_type=ClaimType.FILE_CREATED,
                    raw_text=f"write 工具报告已创建 {path}",
                    target_path=path,
                ))
            elif tool_call.tool_name == "read":
                # read 成功已由工具自身保证 (检查了存在性)
                return VerificationResult(
                    claim=Claim(claim_type=ClaimType.GENERIC, raw_text="read"),
                    status=VerificationStatus.PASSED,
                    actual="read 工具已验证文件存在",
                )
            elif tool_call.tool_name == "bash":
                # bash 成功已由 exit code 保证
                exit_code = tool_call.result.exit_code
                return VerificationResult(
                    claim=Claim(claim_type=ClaimType.COMMAND_EXECUTED, raw_text="bash"),
                    status=VerificationStatus.PASSED if exit_code == 0 else VerificationStatus.FAILED,
                    actual=f"exit code: {exit_code}",
                )
        elif tool_call.status in (ToolStatus.FAILED, ToolStatus.TIMEOUT):
            # 工具明确失败,不需要验证
            return VerificationResult(
                claim=Claim(claim_type=ClaimType.GENERIC, raw_text="工具失败"),
                status=VerificationStatus.SKIPPED,
                reason=f"工具状态为 {tool_call.status.value},无需验证成功声明",
            )
        return VerificationResult(
            claim=Claim(claim_type=ClaimType.GENERIC, raw_text="未知"),
            status=VerificationStatus.SKIPPED,
        )

    # ---------------------------------------------------------------
    # 具体验证策略
    # ---------------------------------------------------------------

    def _verify_file_exists(self, claim: Claim) -> VerificationResult:
        """验证文件是否存在 (修复 P0-1 场景 6 的核心)"""
        if not claim.target_path:
            return VerificationResult(
                claim=claim,
                status=VerificationStatus.FAILED,
                reason="声明未指定文件路径",
            )
        resolved = self.env.resolve_path(claim.target_path)
        if os.path.isfile(resolved):
            size = os.path.getsize(resolved)
            return VerificationResult(
                claim=claim,
                status=VerificationStatus.PASSED,
                actual=f"文件存在: {resolved} ({size} 字节)",
            )
        else:
            # 修复 P0-1: Agent 声称创建了文件但实际不存在
            return VerificationResult(
                claim=claim,
                status=VerificationStatus.FAILED,
                actual=f"文件不存在: {resolved}",
                reason="Agent 声称已创建文件,但实际文件不存在 - 幻觉性成功",
            )

    def _verify_file_content(self, claim: Claim) -> VerificationResult:
        """验证文件内容是否包含声称的内容"""
        if not claim.target_path:
            return VerificationResult(
                claim=claim, status=VerificationStatus.FAILED,
                reason="未指定文件路径",
            )
        resolved = self.env.resolve_path(claim.target_path)
        if not os.path.isfile(resolved):
            return VerificationResult(
                claim=claim, status=VerificationStatus.FAILED,
                reason=f"文件不存在: {resolved}",
            )
        try:
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if claim.expected_content and claim.expected_content in content:
                return VerificationResult(
                    claim=claim, status=VerificationStatus.PASSED,
                    actual=f"文件包含声称的内容: {claim.expected_content}",
                )
            return VerificationResult(
                claim=claim, status=VerificationStatus.FAILED,
                actual=f"文件内容不包含: {claim.expected_content}",
                reason="Agent 声称的内容在文件中不存在",
            )
        except OSError as e:
            return VerificationResult(
                claim=claim, status=VerificationStatus.FAILED,
                reason=f"读取失败: {e}",
            )

    def _verify_test_executed(self, claim: Claim) -> VerificationResult:
        """验证测试是否真的执行过 (修复 P0-1 场景 6 测试幻觉)"""
        # 测试声明需要 Agent 提供实际测试输出作为证据
        if not claim.evidence:
            return VerificationResult(
                claim=claim, status=VerificationStatus.FAILED,
                reason="Agent 声称测试通过,但未提供实际测试输出 - 无法验证",
            )
        # 检查证据中是否包含真实的 pytest 输出特征
        real_test_markers = ["passed", "failed", "error", "PASSED", "FAILED", "===="]
        if any(marker in claim.evidence for marker in real_test_markers):
            return VerificationResult(
                claim=claim, status=VerificationStatus.PASSED,
                actual="提供了实际测试输出",
            )
        return VerificationResult(
            claim=claim, status=VerificationStatus.FAILED,
            reason="测试证据不包含真实测试输出特征",
        )

    def _verify_command(self, claim: Claim) -> VerificationResult:
        """验证命令是否真的执行 (修复 P0-1 TUI 测试的 JSON 字符串问题)"""
        # 命令执行声明需要检查是否真的调用了工具
        # 如果只是输出了 JSON 字符串而未执行,应标记失败
        if "json" in claim.raw_text.lower() or "{{" in claim.raw_text:
            return VerificationResult(
                claim=claim, status=VerificationStatus.FAILED,
                reason="检测到工具调用 JSON 字符串被当作文本输出,未真正执行",
            )
        return VerificationResult(
            claim=claim, status=VerificationStatus.SKIPPED,
            reason="命令执行需配合工具调用记录验证",
        )

    def _verify_directory(self, claim: Claim) -> VerificationResult:
        """验证目录是否存在"""
        if not claim.target_path:
            return VerificationResult(
                claim=claim, status=VerificationStatus.FAILED,
                reason="未指定目录路径",
            )
        resolved = self.env.resolve_path(claim.target_path)
        if os.path.isdir(resolved):
            return VerificationResult(
                claim=claim, status=VerificationStatus.PASSED,
                actual=f"目录存在: {resolved}",
            )
        return VerificationResult(
            claim=claim, status=VerificationStatus.FAILED,
            actual=f"目录不存在: {resolved}",
            reason="Agent 声称的目录不存在",
        )


class ReportCorrector:
    """汇报修正器 - 根据验证结果修正 Agent 的成功声明

    修复 P0-1 的最终环节:
        验证失败时,将"已创建文件 X"修正为"执行失败: 文件 X 不存在"
    """

    @staticmethod
    def correct(response: str, results: list[VerificationResult]) -> str:
        """根据验证结果修正 Agent 回复

        策略:
            - 全部验证通过: 附加 [验证通过] 标记
            - 部分失败: 在失败声明处修正为失败原因
            - 全部失败: 在回复开头插入警告
        """
        if not results:
            return response

        failed = [r for r in results if r.status == VerificationStatus.FAILED]
        passed = [r for r in results if r.status == VerificationStatus.PASSED]

        if not failed:
            # 全部通过 - 附加验证标记,增强用户信任
            return f"{response}\n\n[验证通过: {len(passed)} 项声明已核实]"

        # 构建修正说明
        corrections = ["\n\n--- 验证层修正 ---"]
        for r in failed:
            corrections.append(
                f"⚠️ 声明「{r.claim.raw_text}」验证失败: {r.reason}\n"
                f"   实际情况: {r.actual}"
            )
        corrections.append(
            f"\n注: 以上 {len(failed)} 项声明经验证层独立核查不成立,"
            f"已从成功声明修正为失败。{len(passed)} 项声明验证通过。"
        )
        return response + "\n".join(corrections)


# 便捷函数
def verify_and_correct(
    agent_response: str,
    tool_calls: list[ToolCall] | None = None,
) -> str:
    """验证 Agent 回复并修正虚假声明 - 对外统一接口

    修复 P0-1 的完整流程:
        1. 从回复中提取成功声明
        2. 独立验证每个声明 (Anti-corruption Layer)
        3. 验证工具调用结果的真实性
        4. 修正虚假声明
    """
    extractor = ClaimExtractor()
    verifier = Verifier()
    corrector = ReportCorrector()

    # 提取文本声明
    claims = extractor.extract(agent_response)

    # 附加工具调用声明 (不信任工具的自我报告)
    tool_results: list[VerificationResult] = []
    if tool_calls:
        for tc in tool_calls:
            tool_results.append(verifier.verify_tool_call(tc))

    # 验证文本声明
    text_results = verifier.verify_all(claims)

    all_results = tool_results + text_results
    return corrector.correct(agent_response, all_results)
