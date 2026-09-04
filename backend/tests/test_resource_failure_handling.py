from backend.src.service.resource.persistence import is_failed_generation_content


def test_failed_generation_markers_are_not_treated_as_resource_content():
    assert is_failed_generation_content("[生成失败: The read operation timed out]")
    assert is_failed_generation_content("The read operation timed out")
    assert is_failed_generation_content("[generation failed: upstream timeout]")
    assert is_failed_generation_content("# 文档切分\n\n- 生成失败")
    assert not is_failed_generation_content("ASCII、BCD 和奇偶校验的思维导图")
    assert not is_failed_generation_content("## 生成失败：常见原因与排查\n\n这里讲解如何定位上游超时。")
