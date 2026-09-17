"""换端点必须同时换 key。

`.env` 里现在同时躺着两个 key：`AI_API_KEY` 是当前文本端点的，`api_key` 是项目原有的
DeepSeek key。两边都非空时按固定顺序取一定会配错一种情况 —— 而配错的表现不是
"你的 key 配错了"，是 401 / invalid api_key，和"key 过期""余额不足"一模一样。
所以这里按端点选 key，并且把"这次用的是哪个变量"写进启动日志。
"""
from backend.src.ai_core import llm_config

MIMO = "https://api.xiaomimimo.com/v1"
DEEPSEEK = "https://api.deepseek.com/v1"
DEEPSEEK_ROOT = "https://api.deepseek.com"  # 不带 /v1 也要认得出来

MIMO_KEY = "sk-mimo-000"
VISION_KEY = "sk-vision-000"
DEEPSEEK_KEY = "sk-deepseek-000"


class TestEndpointDetection:
    def test_a_deepseek_endpoint_is_recognised_with_or_without_the_v1_suffix(self):
        assert llm_config._is_deepseek_endpoint(DEEPSEEK)
        assert llm_config._is_deepseek_endpoint(DEEPSEEK_ROOT)
        assert llm_config._is_deepseek_endpoint(DEEPSEEK.upper())

    def test_the_mimo_endpoint_is_not_a_deepseek_endpoint(self):
        assert not llm_config._is_deepseek_endpoint(MIMO)
        assert not llm_config._is_deepseek_endpoint(None)
        assert not llm_config._is_deepseek_endpoint("")


class TestPickTextApiKey:
    def test_the_deepseek_endpoint_takes_the_project_deepseek_key(self):
        """端点是 DeepSeek 时，AI_API_KEY 里那个 MiMo 的 key 不能被发过去。"""
        assert llm_config._pick_text_api_key(DEEPSEEK, MIMO_KEY, VISION_KEY, DEEPSEEK_KEY) == (
            DEEPSEEK_KEY,
            "api_key",
        )

    def test_the_mimo_endpoint_takes_the_text_key_first(self):
        assert llm_config._pick_text_api_key(MIMO, MIMO_KEY, VISION_KEY, DEEPSEEK_KEY) == (
            MIMO_KEY,
            "AI_API_KEY",
        )

    def test_without_the_text_key_the_mimo_endpoint_falls_back_to_the_vision_key(self):
        assert llm_config._pick_text_api_key(MIMO, None, VISION_KEY, DEEPSEEK_KEY) == (
            VISION_KEY,
            "VISION_API_KEY",
        )

    def test_the_deepseek_endpoint_falls_back_to_whatever_key_exists(self):
        """没有 DeepSeek key 时也把别的 key 用上 —— 报 401 也比"没配 key"好定位。"""
        assert llm_config._pick_text_api_key(DEEPSEEK, MIMO_KEY, None, None) == (MIMO_KEY, "AI_API_KEY")
        assert llm_config._pick_text_api_key(DEEPSEEK, None, VISION_KEY, None) == (VISION_KEY, "VISION_API_KEY")

    def test_no_key_at_all_is_reported_as_not_configured(self):
        key, source = llm_config._pick_text_api_key(DEEPSEEK, None, None, None)
        assert key is None
        assert source

    def test_an_empty_string_is_not_a_key(self):
        """.env 里写了变量名但没填值，不该被当成配好了。"""
        assert llm_config._first_set(("AI_API_KEY", ""), ("api_key", DEEPSEEK_KEY)) == (
            DEEPSEEK_KEY,
            "api_key",
        )


class TestStartupLog:
    def test_the_line_names_the_model_the_endpoint_and_the_key_source(self):
        line = llm_config._model_line("文本", "deepseek-flash", DEEPSEEK, "api_key")
        assert "deepseek-flash" in line
        assert DEEPSEEK in line
        assert "api_key" in line

    def test_the_line_never_carries_a_key(self):
        """key 不能进日志 —— 日志会被贴进聊天框和截图。"""
        assert "sk-" not in llm_config._model_line("文本", "deepseek-flash", DEEPSEEK, "api_key")

    def test_the_live_configuration_reports_a_source_for_whatever_key_it_picked(self):
        """模块级那两个值必须自洽：取到了 key 就一定说得出它来自哪个变量。"""
        if llm_config.api_key:
            assert llm_config._TEXT_KEY_SOURCE in {"AI_API_KEY", "VISION_API_KEY", "api_key"}
        else:
            assert llm_config._TEXT_KEY_SOURCE

    def test_the_vision_model_keeps_its_own_key(self):
        """视觉模型默认还在 MiMo，它的 key 不该被文本端点的切换带跑。"""
        if llm_config._vision_api_key:
            assert llm_config._VISION_KEY_SOURCE in {"VISION_API_KEY", "AI_API_KEY", "api_key"}
