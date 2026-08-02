"""OpenAI provider —— 同时也是所有未识别模型的兜底。

刻意不覆写 BaseProvider 的任何方法：基类的默认实现就是 Phase A 之前的
行为，这保证了改造的零回归性。
"""

from core.providers.base import BaseProvider


class OpenAIProvider(BaseProvider):
    name = "openai"

    def matches(self, base_url: str, model_name: str) -> bool:
        # 兜底 provider 不参与匹配，由注册表在全部落空时直接选用。
        return False
