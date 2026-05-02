"""
模型与模拟配置中心

所有配置从 SQLite 读取，API Key 直接存储在数据库中。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import db


def get_active_model_id() -> str:
    m = db.get_active_model()
    return m["id"] if m else "deepseek-chat"


def get_model_config(model_id: str = None) -> dict:
    """获取模型完整配置（从 SQLite）"""
    if model_id is None:
        m = db.get_active_model()
        model_id = m["id"] if m else "deepseek-chat"
    else:
        all_models = {m["id"]: m for m in db.list_models()}
        m = all_models.get(model_id, {})

    db_config = db.get_config()

    return {
        "model": model_id,
        "label": m.get("label", model_id) if m else model_id,
        "api_type": m.get("api_type", "openai") if m else "openai",
        "api_base": m.get("api_base", "") if m else "",
        "api_key": m.get("api_key", "") if m else "",
        "max_tokens": m.get("max_tokens", 4096) if m else 4096,
        "temperature": float(db_config.get("temperature", 0.75)),
        "max_tokens_out": int(db_config.get("max_tokens", 2000)),
        "top_p": float(db_config.get("top_p", 0.9)),
    }


def get_api_key() -> str:
    """直接从 DB 读取当前激活模型的 API Key"""
    return db.get_model_api_key()


AVAILABLE_MODELS = {
    m["id"]: {"id": m["id"], "label": m["label"], "api_type": m["api_type"], "provider": m["api_type"]}
    for m in db.list_models()
}


@dataclass
class SimulationConfig:
    """模拟器全局配置（从 SQLite 读取）"""

    model: str = field(default_factory=get_active_model_id)
    api_type: str = field(default_factory=lambda: get_model_config()["api_type"])
    api_key: str = field(default_factory=get_api_key)
    fallback_model: Optional[str] = None

    api_base: str = field(default_factory=lambda: get_model_config()["api_base"])

    temperature: float = field(default_factory=lambda: get_model_config()["temperature"])
    max_tokens: int = field(default_factory=lambda: get_model_config()["max_tokens_out"])
    top_p: float = field(default_factory=lambda: get_model_config()["top_p"])

    enable_prompt_caching: bool = False

    scene_max_words: int = 600
    scene_min_words: int = 300
    context_truncate_chars: int = 400

    show_token_usage: bool = True
    verbose_errors: bool = True

    @property
    def provider(self) -> str:
        return self.api_type

    def resolve_api_key(self) -> str:
        return self.api_key or get_api_key()

    def resolve_base_url(self) -> str:
        return self.api_base

    def validate(self) -> list[str]:
        warnings = []
        if not self.api_key:
            warnings.append("未配置 API Key，请在模型配置中设置")
        if self.temperature > 0.9:
            warnings.append("temperature > 0.9，角色行为可能不稳定")
        if self.max_tokens < 1000:
            warnings.append("max_tokens < 1000，可能被截断")
        return warnings


PROVIDER_DEFAULTS = {
    "anthropic": {"base_url": "https://api.anthropic.com"},
    "deepseek": {"base_url": "https://api.deepseek.com"},
    "openai": {"base_url": "https://api.openai.com/v1"},
}

default_config = SimulationConfig()
