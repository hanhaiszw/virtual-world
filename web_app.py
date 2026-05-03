#!/usr/bin/env python3
"""
模拟人生 - Web 服务
FastAPI 后端 + 线程池处理 LLM 调用
"""

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator

from config import AVAILABLE_MODELS, SimulationConfig, get_model_config
from simulation import FamilySimulation
import db

# ─── 日志 ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── 全局状态 ─────────────────────────────────────────
sim: Optional[FamilySimulation] = None
_executor = ThreadPoolExecutor(max_workers=1)
_BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))



# ─── 生命周期 ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global sim
    try:
        sim = FamilySimulation()
        logger.info(f"模拟器初始化 | {sim.cfg.api_type} | {sim.cfg.model}")
    except SystemExit:
        sim = None
        logger.warning("模拟器未初始化: 未设置 API Key")
    except Exception as e:
        sim = None
        logger.error(f"模拟器初始化失败: {e}")
    yield
    _executor.shutdown(wait=False)


app = FastAPI(lifespan=lifespan, title="模拟人生", root_path="/virtual-world")
app.mount("/img", StaticFiles(directory=str(_BASE_DIR / "img")), name="img")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ─── Pydantic 模型 ────────────────────────────────────
class ChatRequest(BaseModel):
    character: str
    message: str
    history: list[dict] = []

class GenerateRequest(BaseModel):
    scene_key: Optional[str] = None
    scene_description: Optional[str] = None
    context: Optional[str] = None
    model: Optional[str] = None
    # 自定义场景参数
    time_override: Optional[str] = None
    location: Optional[str] = None
    characters: Optional[list[str]] = None
    plot: Optional[str] = None

    @field_validator("scene_key")
    @classmethod
    def check_scene_key(cls, v):
        if v is not None and v not in db.get_scene_presets():
            raise ValueError(f"未知场景: {v}")
        return v


# ─── 页面路由 ─────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    init_error = None
    if sim is None:
        init_error = "未配置 API Key，请在「⚙️ 模型配置」中设置 API Key"

    return templates.TemplateResponse(request, "index.html", {
        "request": request,
        "has_api_key": sim is not None,
        "init_error": init_error,
        "scenes": db.get_scene_presets(),
    })


# ─── 角色管理 API (DB) ─────────────────────────────────
@app.get("/api/characters")
async def get_characters():
    chars = db.list_characters()
    result = {}
    for c in chars:
        result[c["name"]] = {
            "name": c["name"], "role": c["role"], "age": c["age"],
            "occupation": c["occupation"], "personality_profile": c["personality_profile"],
            "catchphrases": c["catchphrases"], "schedule": c["schedule"],
            "relationships": c["relationships"],
            "is_system_user": bool(c.get("is_system_user")),
        }
    return {"characters": result}


@app.put("/api/characters/{name}")
async def update_character(name: str, data: dict):
    if not db.get_character(name):
        raise HTTPException(status_code=404, detail=f"角色不存在: {name}")
    db.update_character(name, data)
    # 同步 JSON 文件
    chars_dir = Path(__file__).parent / "characters"
    filename_map = {"王建国": "dad.json", "李梅": "mom.json", "王小月": "xiaoyue.json", "王小华": "xiaohua.json"}
    filename = filename_map.get(name)
    if filename:
        char = db.get_character(name)
        if char:
            file_data = {k: char[k] for k in ["name","role","age","occupation","personality_profile","catchphrases","schedule","relationships"]}
            with open(chars_dir / filename, "w", encoding="utf-8") as f:
                json.dump(file_data, f, ensure_ascii=False, indent=2)
    logger.info(f"角色更新: {name}")
    return {"ok": True, "name": name}


# ─── 场景模板 API (DB) ─────────────────────────────────
@app.get("/api/scene-templates")
async def get_scene_templates():
    return {"templates": db.list_scene_templates()}


@app.post("/api/scene-templates")
async def create_scene_template(data: dict):
    tid = db.save_scene_template(data)
    return {"ok": True, "id": tid}


@app.put("/api/scene-templates/{tid}")
async def update_scene_template(tid: int, data: dict):
    conn = db.get_conn()
    now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """UPDATE scene_templates SET title=?, scene_key=?, time_override=?, location=?,
           characters=?, plot=?, updated_at=? WHERE id=?""",
        (data.get("title", ""), data.get("scene_key", ""),
         data.get("time_override", ""), data.get("location", ""),
         __import__("json").dumps(data.get("characters", []), ensure_ascii=False),
         data.get("plot", ""), now, tid),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/scene-templates/{tid}")
async def delete_scene_template(tid: int):
    db.delete_scene_template(tid)
    return {"ok": True}


# ─── 场景历史 API (DB) ─────────────────────────────────
@app.get("/api/history")
async def get_history():
    return {"history": db.list_scene_history(limit=5)}


# ─── 模型配置 API ─────────────────────────────────────
@app.get("/api/models")
async def get_models():
    """获取所有模型及当前配置"""
    models = db.list_models()
    active = db.get_active_model()
    config = db.get_config()

    # 脱敏：不返回明文 api_key
    safe_models = []
    for m in models:
        m = dict(m)
        m["has_api_key"] = bool(m.pop("api_key", None))
        safe_models.append(m)

    if active:
        active = dict(active)
        active["has_api_key"] = bool(active.pop("api_key", None))

    return {
        "models": safe_models,
        "active_id": active["id"] if active else "",
        "config": config,
    }


@app.put("/api/models/activate")
async def activate_model(data: dict):
    """切换激活模型"""
    model_id = data.get("model_id", "")
    if not db.set_active_model(model_id):
        raise HTTPException(status_code=404, detail=f"模型不存在: {model_id}")

    # 更新 SimulationConfig
    sim.cfg.model = model_id
    m = db.get_active_model()
    if m:
        sim.cfg.api_type = m["api_type"]
        sim.cfg.api_base = m["api_base"] or ""
        sim.cfg.api_key = m.get("api_key", "")

    # 重建客户端
    if sim.cfg.api_key:
        sim._init_client(sim.cfg.api_key)

    logger.info(f"模型切换: {model_id}")
    return {"ok": True, "model": model_id}


@app.put("/api/models/{model_id}")
async def update_model_config(model_id: str, data: dict):
    """更新模型 api_base / api_key，不存在则创建"""
    api_key = data.get("api_key", "").strip()
    updates = {"api_base": data.get("api_base", "").strip()}
    # 只有输入了新的 api_key 才更新
    if api_key:
        updates["api_key"] = api_key

    conn = db.get_conn()
    exists = conn.execute("SELECT id FROM models WHERE id=?", (model_id,)).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO models (id, label, api_type, api_base, api_key, max_tokens, is_active) VALUES (?,?,?,?,?,?,0)",
            (model_id, data.get("label", model_id), "openai",
             data.get("api_base", ""), api_key, 8192),
        )
    conn.close()
    db.update_model(model_id, updates)
    return {"ok": True}


@app.put("/api/config")
async def update_sim_config(data: dict):
    """更新全局配置（temperature/max_tokens/top_p）"""
    allowed = {"temperature", "max_tokens", "top_p"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if updates:
        db.update_config(updates)
        # 同步到运行时
        if "temperature" in updates:
            sim.cfg.temperature = float(updates["temperature"])
        if "max_tokens" in updates:
            sim.cfg.max_tokens = int(updates["max_tokens"])
        if "top_p" in updates:
            sim.cfg.top_p = float(updates["top_p"])
    return {"ok": True, "updated": list(updates.keys())}


# ─── 聊天历史 API ─────────────────────────────────────
@app.get("/api/chat/history/{character}")
async def get_chat_history(character: str, before: int = None):
    return {"history": db.list_chat_history(character, limit=20, before_id=before)}


# ─── 对话 API ─────────────────────────────────────────
@app.post("/api/chat")
async def chat_with_character(req: ChatRequest):
    """与指定角色 1v1 对话"""
    if sim is None:
        raise HTTPException(status_code=503, detail="模拟器未初始化")
    if req.character not in sim.characters:
        raise HTTPException(status_code=404, detail=f"角色不存在: {req.character}")

    char = sim.characters[req.character]

    # 获取系统用户信息
    sys_user = db.get_system_user()
    sys_info = ""
    if sys_user:
        sys_rel = ""
        if "relationships" in sys_user and char["name"] in sys_user["relationships"]:
            sys_rel = f"\n他对你的了解：{sys_user['relationships'][char['name']]}"
        sys_info = f"""

## 正在和你聊天的人
现在和你聊天的人是瀚海，17岁，{sys_user['occupation']}。{sys_rel if sys_rel else ''}

你一定要记住瀚海是谁，用符合你和他关系的态度来聊天。"""

    # 获取全家成员信息（防幻觉）
    all_chars = db.list_characters()
    family_info = "\n## 你的家庭成员（务必记住这些名字，不能编造）\n"
    for c in all_chars:
        if c["name"] != char["name"] and not c.get("is_system_user"):
            rel = ""
            rels = char.get("relationships", {})
            if isinstance(rels, dict) and c["name"] in rels:
                rel = f" — {rels[c['name']][:50]}"
            family_info += f"- {c['name']}（{c['role']}，{c['age']}岁）{rel}\n"

    # 构建角色扮演 system prompt
    system_prompt = f"""你是{char['name']}，{char['age']}岁，{char['occupation']}。你在家里的角色是{char['role']}。

## 你的性格和说话方式
{char['personality_profile']}
{family_info}
{sys_info}

## 重要规则
1. 你必须始终以{char['name']}的身份说话，不要跳出角色。
2. 使用符合你年龄和性格的语言风格，包括你的口头禅。
3. 回答要自然、口语化、生活化，像是在家里聊天。
4. 你的回答应该简短精炼（50-150字），像真实的聊天对话。
5. 家里的名字必须严格使用上面列出的，绝对不能自己编造名字。
6. 你是在家里和家人/朋友聊天，场景是日常家庭生活。
7. 用中文回答，语气符合你的角色设定。
"""

    # 构建对话消息
    messages = []
    for h in req.history[-10:]:
        role = "assistant" if h["role"] == "character" else "user"
        content = h["content"]
        if role == "user":
            content = f"[瀚海对你说] {content}"
        messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": f"[瀚海对你说] {req.message}"})

    # 保存用户消息
    db.save_chat_message(req.character, "user", req.message)

    logger.info(f"对话: {req.character} | 消息: {req.message[:30]}...")

    try:
        loop = asyncio.get_event_loop()
        if sim.cfg.api_type == "anthropic":
            resp = await loop.run_in_executor(
                _executor,
                lambda: sim.client.messages.create(
                    model=sim.cfg.model,
                    max_tokens=500,
                    temperature=0.8,
                    system=system_prompt,
                    messages=messages,
                )
            )
            reply = resp.content[0].text.strip()
            db.save_chat_message(req.character, "character", reply)
        else:
            # OpenAI 兼容 (DeepSeek)
            openai_messages = [{"role": "system", "content": system_prompt}]
            for h in req.history[-10:]:
                role = "assistant" if h["role"] == "character" else "user"
                openai_messages.append({"role": role, "content": h["content"]})
            openai_messages.append({"role": "user", "content": req.message})

            resp = await loop.run_in_executor(
                _executor,
                lambda: sim.client.chat.completions.create(
                    model=sim.cfg.model,
                    max_tokens=500,
                    temperature=0.8,
                    messages=openai_messages,
                )
            )
            reply = resp.choices[0].message.content.strip()

        # 保存 AI 回复
        db.save_chat_message(req.character, "character", reply)

        return {"reply": reply, "character": req.character}

    except Exception as e:
        logger.error(f"对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"对话失败: {e}")


# ─── 场景 API ─────────────────────────────────────────
@app.get("/api/scenes")
async def get_scenes():
    """返回所有预设场景"""
    result = []
    for key, s in db.get_scene_presets().items():
        result.append({
            "key": key,
            "time": s["time"],
            "location": s["location"],
            "description": s["description"],
            "typical_present": s["typical_present"],
            "vibe": s["vibe"],
        })
    return {"scenes": result}


@app.get("/api/status")
async def get_status():
    """返回当前状态信息"""
    if sim is None:
        raise HTTPException(
            status_code=503,
            detail="模拟器未初始化，请检查 API Key 配置"
        )

    characters_info = {}
    for name, data in sim.characters.items():
        characters_info[name] = {
            "role": data["role"],
            "age": data["age"],
            "occupation": data["occupation"],
        }

    return {
        "api_type": sim.cfg.api_type,
        "model": sim.cfg.model,
        "available_models": [
            {"key": k, "id": v["id"], "label": v["label"], "provider": v.get("provider", sim.cfg.api_type)}
            for k, v in AVAILABLE_MODELS.items()
        ],
        "characters": characters_info,
        "temperature": sim.cfg.temperature,
        "max_tokens": sim.cfg.max_tokens,
        "scene_count": len(db.get_scene_presets()),
        "history_count": len(sim.scene_history),
    }


@app.get("/api/history")
async def get_history():
    """返回场景生成历史"""
    if sim is None:
        return {"history": []}
    return {"history": sim.scene_history}


@app.post("/api/generate")
async def generate_scene(req: GenerateRequest):
    """生成一个家庭场景（在线程池中执行）"""
    if sim is None:
        raise HTTPException(status_code=503, detail="模拟器未初始化（缺少 API Key）")

    if not req.scene_key and not req.scene_description:
        raise HTTPException(
            status_code=400,
            detail="请选择预设场景或输入自定义场景描述"
        )

    logger.info(
        f"生成场景: {req.scene_key or '自定义'}"
        f"{' | ' + req.plot[:30] if req.plot else ''}"
    )

    history_before = len(sim.scene_history)

    try:
        loop = asyncio.get_event_loop()
        scene_text = await loop.run_in_executor(
            _executor,
            sim.generate_scene,
            req.scene_key,
            req.scene_description or req.plot,  # 优先用 plot
            req.characters,    # active_characters
            req.time_override,
            req.context,
            req.model,
        )
    except Exception as e:
        logger.error(f"生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成场景时出错: {e}")

    # 检查是否成功生成（失败时 generate_scene 返回错误字符串，不追加到 history）
    if len(sim.scene_history) == history_before:
        raise HTTPException(status_code=500, detail=scene_text)

    latest = sim.scene_history[-1]
    # 写入 DB 历史
    latest["plot"] = req.scene_description or ""
    latest["scene_key"] = req.scene_key or ""
    db.save_scene_history(latest)

    logger.info(
        f"生成完成: {latest['time']} | "
        f"{len(latest['content'])} 字 | "
        f"模型: {latest.get('model', '?')}"
    )

    return {
        "scene": latest,
        "history_count": db.list_scene_history(limit=1)[0]["id"] if db.list_scene_history(limit=1) else 0,
    }


# ─── 启动入口 ─────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    print()
    print("🏠 模拟人生 Web 服务")
    print("━" * 48)

    if sim is not None:
        print(f"  📡 API:     {sim.cfg.api_type} | {sim.cfg.resolve_base_url()}")
        print(f"  🧠 模型:    {sim.cfg.model}")
        print(f"  👥 角色:    {', '.join(sim.characters.keys())}")
    else:
        print("  ⚠️  模拟器未初始化（缺少 API Key）")

    print(f"  🎬 场景:    {len(db.get_scene_presets())} 个预设")
    print(f"  🌐 地址:    http://127.0.0.1:12300")
    print(f"  📝 API:     http://127.0.0.1:12300/docs")
    print("━" * 48)
    print()

    uvicorn.run(
        "web_app:app",
        host="127.0.0.1",
        port=12300,
        reload=False,
        log_level="warning",
    )
