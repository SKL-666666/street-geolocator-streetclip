"""测试：无 Key 待配置态 + /api/setup 保存与热加载（打包分发场景）。"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app


def _tiny_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 12), (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离：Key 文件指向临时目录，清空内存 Key（模拟打包版首次启动）。"""
    monkeypatch.setattr(settings, "llm_key_file", tmp_path / "llm_key.json")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_model", "")
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_configs_file", tmp_path / "llm_configs.json")
    with TestClient(app) as c:
        yield c


def test_analyze_without_key_503(client):
    r = client.post("/api/analyze",
                    files={"file": ("t.jpg", _tiny_jpeg(), "image/jpeg")})
    assert r.status_code == 503
    assert "API Key" in r.json()["detail"]


def test_config_needs_setup(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["needs_setup"] is True


def test_setup_saves_and_reloads(client, tmp_path):
    r = client.post("/api/setup", data={
        "api_key": "test-key-123",
        "base_url": "https://example.com/v1",
        "model": "glm-x",
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # Key 文件已写入（含 provider=openai）
    # 已写入多配置存储（llm_configs.json）
    configs = json.loads((tmp_path / "llm_configs.json").read_text(encoding="utf-8"))
    assert len(configs) == 1
    assert configs[0]["api_key"] == "test-key-123"
    assert configs[0]["base_url"] == "https://example.com/v1"
    assert configs[0]["model"] == "glm-x"
    # 内存配置已更新（热加载，无需重启）
    assert settings.llm_api_key == "test-key-123"
    assert settings.llm_model == "glm-x"
    # 配置接口不再提示设置
    assert client.get("/api/config").json()["needs_setup"] is False


def test_setup_empty_key_400(client):
    r = client.post("/api/setup", data={"api_key": "   "})
    assert r.status_code == 400


def test_active_config_applied_via_store(monkeypatch, tmp_path):
    """激活配置由 config_store.apply_active_to_settings 写入 settings（模块加载后执行）。"""
    from app.llm import config_store
    (tmp_path / "llm_configs.json").write_text(json.dumps([{
        "id": "abc", "name": "配置A", "provider": "openai",
        "api_key": "file-key", "model": "GLM-4.6V-FlashX",
        "base_url": "https://file.example/v1", "active": True,
    }]), encoding="utf-8")
    monkeypatch.setattr(settings, "llm_configs_file", tmp_path / "llm_configs.json")
    old = (settings.llm_api_key, settings.llm_model,
           settings.llm_base_url, settings.llm_provider)
    try:
        assert config_store.apply_active_to_settings(config_store.load_configs()) is True
        assert settings.llm_api_key == "file-key"
        assert settings.llm_model == "GLM-4.6V-FlashX"
        assert settings.llm_base_url == "https://file.example/v1"
    finally:
        (settings.llm_api_key, settings.llm_model,
         settings.llm_base_url, settings.llm_provider) = old
