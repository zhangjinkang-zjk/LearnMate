# -*- coding: utf-8 -*-
"""上传知识库这条链：后端一直活着，前端曾经整条消失。

`/knowledge_base/upload`、`/list`、`/{doc_id}`、`DELETE /{doc_id}` 和
`utils/knowledge_base.ingest`（切片 + BGE 逐段向量化）都还在，但 LearnMate 前端里
一个入口都没有 —— 全库搜「上传」只命中一句页面描述文案，学生根本没地方上传。
现在按知伴的 `StudyImportView.vue` 补回来了，这份测试钉的就是"补回来的这一版
和后端是同一套契约"。

钉这几件事是因为**写错了不会报错**：
- FormData 字段名写错 → 后端 `Form(...)` 拿默认值，请求 200、什么都没入库；
- 后缀白名单和后端不一致 → 前端放行、后端 400；
- 分类默认值不在前端选项里 → "默认类型"永远选不中；
- 上传走 httpClient 的默认 JSON 头 → axios 把 FormData 转成 JSON 字符串（见
  knowledgeApi.js 的注释），同样 200 且什么都没入库。
"""

import inspect
import re
from pathlib import Path

from backend.src.router import knowledge_router

ROOT = Path(__file__).resolve().parents[2]
API_JS = ROOT / "frontend" / "src" / "shared" / "api" / "knowledgeApi.js"
IMPORT_PAGE = ROOT / "frontend" / "src" / "pages" / "resources" / "KnowledgeImportPage.vue"
LIBRARY_PAGE = ROOT / "frontend" / "src" / "pages" / "resources" / "ResourceLibraryPage.vue"
ROUTER_JS = ROOT / "frontend" / "src" / "app" / "router" / "index.js"
HTTP_CLIENT = ROOT / "frontend" / "src" / "shared" / "api" / "httpClient.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _api_source() -> str:
    return _read(API_JS)


def _page_source() -> str:
    return _read(IMPORT_PAGE)


def _routes():
    """路由表里已经是带前缀的完整路径，正好拿来当前端要调的那个 URL 钉。"""
    return {
        (route.path, method)
        for route in knowledge_router.router.routes
        for method in (route.methods or set())
    }


def _form_default(name: str):
    """FastAPI 的 Form/File 默认值包了一层，取里面真正那个值。"""
    default = inspect.signature(knowledge_router.upload_document).parameters[name].default
    return getattr(default, "default", default)


# ── 后端契约（先钉住前端是对着谁写的） ────────────────────────────────────

def test_the_backend_still_serves_the_four_endpoints_the_page_uses():
    assert knowledge_router.router.prefix == "/knowledge_base"
    assert ("/knowledge_base/upload", "POST") in _routes()
    assert ("/knowledge_base/list", "GET") in _routes()
    assert ("/knowledge_base/{doc_id}", "GET") in _routes()
    assert ("/knowledge_base/{doc_id}", "DELETE") in _routes()


def test_the_paths_the_frontend_calls_are_the_paths_the_backend_serves():
    api = _api_source()
    assert "'/knowledge_base/upload'" in api
    assert "'/knowledge_base/list'" in api
    # 列表是拼出来的（encodeURIComponent），只钉前缀那一段
    assert "`/knowledge_base/${encodeURIComponent(docId)}`" in api


def test_upload_still_answers_with_chunk_counts():
    """入库结果只有这三个数字能说明"到底进去没有"。"""
    source = inspect.getsource(knowledge_router.upload_document)
    for key in ("total_chunks", "ingested", "skipped", "details"):
        assert f'"{key}"' in source, f"上传返回里少了 {key}"


# ── 字段名 ───────────────────────────────────────────────────────────────

def test_the_form_fields_are_exactly_the_ones_the_backend_declares():
    fields = set(re.findall(r"formData\.append\('([^']+)'", _page_source()))
    assert fields == {"file", "title", "visibility", "category"}

    # 每个字段都必须是 upload_document 的真实参数，否则后端收不到
    params = inspect.signature(knowledge_router.upload_document).parameters
    for field in fields:
        assert field in params, f"后端 upload_document 没有参数 {field}"


def test_skipping_the_optional_cover_is_allowed():
    """前端不截视频首帧，所以不传 cover —— 那它必须真的是可选的。"""
    assert _form_default("cover") is None
    assert _form_default("title") is None
    assert "formData.append('cover'" not in _page_source()


def test_the_page_does_not_offer_a_field_the_backend_never_reads():
    """知伴那边有个「资料说明」输入框，填了但 FormData 里根本没 append —— 那个坑不要搬。"""
    assert "description" not in inspect.signature(knowledge_router.upload_document).parameters
    assert "materialDescription" not in _page_source()


# ── 白名单与枚举 ─────────────────────────────────────────────────────────

def test_the_accept_list_matches_the_backend_whitelist():
    matched = re.search(r"KNOWLEDGE_ACCEPT = '([^']+)'", _api_source())
    assert matched, "knowledgeApi.js 里找不到 KNOWLEDGE_ACCEPT"
    extensions = {item.strip() for item in matched.group(1).split(",") if item.strip()}
    assert extensions == set(knowledge_router.ALLOWED_EXTENSIONS)


def test_the_default_category_can_actually_be_picked():
    """后端默认 knowledge_point：它必须落在前端选项里，否则默认类型在前端选不中。"""
    backend_default = _form_default("category")
    assert backend_default == "knowledge_point"

    values = re.findall(r"\{ value: '([a-z_]+)', label:", _api_source())
    assert backend_default in values
    assert len(values) == 6

    page = _page_source()
    assert f"const category = ref('{backend_default}')" in page


def test_visibility_values_stay_inside_what_the_backend_accepts():
    page = _page_source()
    values = set(re.findall(r"\{ value: '(private|public)', label:", page))
    assert values == {"private", "public"}
    # 公开上传要管理员权限，前端必须说清楚，否则学生以为点了就公开了
    assert "管理员" in page


# ── 上传必须走 multipart ─────────────────────────────────────────────────

def test_the_upload_overrides_the_json_content_type():
    """httpClient 全局是 application/json，axios 看到 FormData + JSON 头会把它转成 JSON 字符串。"""
    assert "'Content-Type': 'multipart/form-data'" in _api_source()
    assert "application/json" in _read(HTTP_CLIENT), "httpClient 的默认头变了，这条覆盖要重新确认"


def test_the_upload_does_not_rely_on_the_global_fifteen_second_timeout():
    """落盘 + 切片 + 逐段向量化在一次请求里做完，15 秒不够。"""
    assert re.search(r"timeout:\s*UPLOAD_TIMEOUT_MS", _api_source())
    matched = re.search(r"const UPLOAD_TIMEOUT_MS = (\d+)", _api_source())
    assert matched and int(matched.group(1)) >= 300000


# ── 删除与列表 ───────────────────────────────────────────────────────────

def test_deleting_a_document_removes_every_chunk():
    """后端 delete 一次只删一行，一篇文档切成 N 段就要删 N 次。"""
    assert "await record.delete()" in inspect.getsource(
        __import__("backend.src.utils.knowledge_base", fromlist=["delete"]).delete
    )
    assert "removeAll" in _page_source()
    assert "entry.doc_ids" in _page_source()
    assert "for (const docId of docIds)" in _api_source()


def test_the_grouped_list_still_exposes_the_fields_the_page_renders():
    from backend.src.utils import knowledge_base as kb

    source = inspect.getsource(kb.list_grouped)
    for key in ("doc_ids", "chunks", "total_chars", "visibility", "created_at"):
        assert f'"{key}"' in source, f"list_grouped 里没有 {key}，前端那一列会渲染成空"


# ── 能不能走到 ───────────────────────────────────────────────────────────

def test_the_page_is_routed_and_linked_from_the_resource_library():
    router_source = _read(ROUTER_JS)
    assert "{ path: '/resources/knowledge'" in router_source
    assert "KnowledgeImportPage" in router_source

    library = _read(LIBRARY_PAGE)
    assert 'to="/resources/knowledge"' in library
    assert "上传知识库" in library
