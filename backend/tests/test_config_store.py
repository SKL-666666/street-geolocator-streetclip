"""测试：多 API 配置存储（增删/切换/脱敏/旧配置迁移）+ 路由。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.llm import config_store
from app.main import app


@pytest.fixture()
def store_env(monkeypatch, tmp_path):
    """隔离配置存储（临时文件）。"""
    monkeypatch.setattr(settings, "llm_configs_file", tmp_path / "llm_configs.json")
    monkeypatch.setattr(settings, "llm_key_file", tmp_path / "llm_key.json")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_provider", "openai")
    yield tmp_path
    # 清理 settings 内存（防污染其他测试）
    settings.llm_api_key = ""


class TestConfigStore:
    def test_add_and_active(self, store_env):
        configs, added = config_store.add_config("智谱", "key-1", "https://a/v1", "glm-x")
        assert added is True
        assert len(configs) == 1
        assert configs[0]["active"] is True
        # 添加第二个 → 第一个自动取消激活
        configs, added = config_store.add_config("豆包", "key-2", "https://b/v1", "doubao-x")
        assert added is True
        assert sum(1 for c in configs if c["active"]) == 1
        assert configs[1]["active"] is True
        # 持久化
        data = json.loads((store_env / "llm_configs.json").read_text(encoding="utf-8"))
        assert len(data) == 2

    def test_duplicate_not_added(self, store_env):
        """相同 key+模型+地址 → 不新增，激活已有（added=False）。"""
        configs, added = config_store.add_config("A", "same-key", "https://a/v1", "glm-x")
        assert added is True
        configs, added = config_store.add_config("B", "same-key", "https://a/v1", "glm-x")
        assert added is False
        assert len(configs) == 1
        assert configs[0]["active"] is True  # 已自动切换到已有那条
        # 不同模型 → 视为新配置
        configs, added = config_store.add_config("B", "same-key", "https://a/v1", "glm-y")
        assert added is True
        assert len(configs) == 2

    def test_duplicate_name_gets_suffix(self, store_env):
        """重名配置自动加序号（不同 key 同名）。"""
        config_store.add_config("智谱 GLM · glm-4v-flash", "k1", "https://a/v1", "glm-4v-flash")
        configs, _ = config_store.add_config("智谱 GLM · glm-4v-flash", "k2", "https://a/v1", "glm-4v-flash")
        assert configs[1]["name"] == "智谱 GLM · glm-4v-flash (2)"
        configs, _ = config_store.add_config("智谱 GLM · glm-4v-flash", "k3", "https://a/v1", "glm-4v-flash")
        assert configs[2]["name"] == "智谱 GLM · glm-4v-flash (3)"

    def test_activate_switch(self, store_env):
        config_store.add_config("A", "k1")
        configs, _ = config_store.add_config("B", "k2")
        aid = configs[0]["id"]
        configs = config_store.activate_config(aid)
        assert configs[0]["active"] is True
        assert configs[1]["active"] is False

    def test_delete_active_falls_back_to_first(self, store_env):
        config_store.add_config("A", "k1")
        configs, _ = config_store.add_config("B", "k2")  # B active
        configs = config_store.delete_config(configs[1]["id"])  # 删掉激活的 B
        assert len(configs) == 1
        assert configs[0]["active"] is True  # A 自动激活

    def test_delete_all(self, store_env):
        configs, _ = config_store.add_config("A", "k1")
        configs = config_store.delete_config(configs[0]["id"])
        assert configs == []
        assert config_store.active_config([]) is None

    def test_mask_key(self):
        assert config_store.mask_key("1234567890abcdef1234567890abcdef.abcd") == "1234***abcd"
        assert config_store.mask_key("short") == "***"
        assert config_store.mask_key("") == ""

    def test_public_configs_masked(self, store_env):
        config_store.add_config("A", "secret-key-1234567890")
        pubs = config_store.public_configs()
        assert "secret-key" not in json.dumps(pubs)
        assert pubs[0]["masked_key"] == "secr***7890"
        assert pubs[0]["active"] is True

    def test_legacy_migration(self, store_env, monkeypatch):
        """旧 llm_key.json → llm_configs.json 自动迁移。"""
        (store_env / "llm_key.json").write_text(json.dumps(
            {"api_key": "old-key", "base_url": "https://old/v1",
             "model": "old-model", "provider": "openai"}), encoding="utf-8")
        configs = config_store.load_configs()
        assert len(configs) == 1
        assert configs[0]["api_key"] == "old-key"
        assert configs[0]["model"] == "old-model"
        # 迁移已固化
        assert (store_env / "llm_configs.json").is_file()
        # 可 apply 到 settings
        assert config_store.apply_active_to_settings(configs) is True
        assert settings.llm_api_key == "old-key"


class TestLLMConfigRoutes:
    def test_crud_flow(self, store_env):
        with TestClient(app) as client:
            # 空列表
            r = client.get("/api/llm-configs")
            assert r.status_code == 200
            assert r.json()["configs"] == []

            # 添加
            r = client.post("/api/llm-configs", data={
                "name": "智谱", "api_key": "real-key-abc123", "base_url": "https://a/v1", "model": "glm-x"})
            assert r.status_code == 200
            configs = r.json()["configs"]
            assert len(configs) == 1
            assert configs[0]["name"] == "智谱"
            assert "real-key" not in json.dumps(configs)  # 脱敏
            cid = configs[0]["id"]

            # 再添加一个 → 新的激活
            r = client.post("/api/llm-configs", data={
                "name": "豆包", "api_key": "key2", "base_url": "https://b/v1", "model": "doubao"})
            configs = r.json()["configs"]
            assert configs[1]["active"] is True
            cid2 = configs[1]["id"]

            # 切换回第一个
            r = client.post(f"/api/llm-configs/{cid}/activate")
            configs = r.json()["configs"]
            assert configs[0]["active"] is True
            assert configs[1]["active"] is False
            # 切换后 settings 热加载
            assert settings.llm_api_key == "real-key-abc123"

            # 删除激活项 → 剩一个并自动激活
            r = client.delete(f"/api/llm-configs/{cid}")
            assert r.status_code == 200
            configs = r.json()["configs"]
            assert len(configs) == 1
            assert configs[0]["active"] is True
            assert configs[0]["id"] == cid2

            # 404
            assert client.delete(f"/api/llm-configs/{cid}").status_code == 404
            assert client.post("/api/llm-configs/nonexist/activate").status_code == 404

    def test_empty_key_400(self, store_env):
        with TestClient(app) as client:
            r = client.post("/api/llm-configs", data={"api_key": "  "})
            assert r.status_code == 400

    def test_legacy_setup_still_works(self, store_env):
        """旧 /api/setup 兼容：添加"默认配置"并激活。"""
        with TestClient(app) as client:
            r = client.post("/api/setup", data={"api_key": "setup-key", "base_url": "https://s/v1", "model": "m"})
            assert r.status_code == 200
            assert r.json()["ok"] is True
            configs = client.get("/api/llm-configs").json()["configs"]
            assert len(configs) == 1
            assert configs[0]["name"] == "默认配置"
