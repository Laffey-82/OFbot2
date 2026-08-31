"""OFbot2 插件测试工具（假适配器 / 子进程机器人夹具）。"""

from .harness import FakeBotHarness, extract_text, make_group_payload

__all__ = ["FakeBotHarness", "extract_text", "make_group_payload"]
