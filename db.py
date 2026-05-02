"""
SQLite 数据库：模型/角色/场景/日志 持久化
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "data.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化所有表，首次从 JSON 文件导入"""
    conn = get_conn()

    # 模型表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS models (
            id TEXT PRIMARY KEY, label TEXT,
            api_type TEXT DEFAULT 'openai', api_base TEXT DEFAULT '',
            api_key TEXT DEFAULT '', max_tokens INTEGER DEFAULT 4096,
            is_active INTEGER DEFAULT 0
        )
    """)
    # 兼容旧字段
    try:
        conn.execute("ALTER TABLE models ADD COLUMN api_key TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    # 全局配置
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY, value TEXT
        )
    """)

    # 角色表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            name TEXT PRIMARY KEY, role TEXT, age INTEGER, occupation TEXT,
            personality_profile TEXT, catchphrases TEXT,
            schedule TEXT, relationships TEXT,
            emoji TEXT DEFAULT '', updated_at TEXT
        )
    """)
    try:
        conn.execute("ALTER TABLE characters ADD COLUMN emoji TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    # 场景模板表（用户保存的自定义场景）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, scene_key TEXT,
            time_override TEXT, location TEXT,
            characters TEXT, plot TEXT,
            created_at TEXT, updated_at TEXT
        )
    """)

    # 场景历史表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scene_key TEXT, time_str TEXT, location TEXT,
            characters TEXT, plot TEXT, content TEXT,
            model TEXT, created_at TEXT
        )
    """)

    # 聊天历史表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_name TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_char ON chat_history(character_name, created_at)")

    # 首次导入
    if conn.execute("SELECT COUNT(*) FROM models").fetchone()[0] == 0:
        _import_models(conn)
    if conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0] == 0:
        _import_characters(conn)

    defaults = {"temperature": "0.75", "max_tokens": "2000", "top_p": "0.9"}
    for k, v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v))
    # 家庭环境描述首次入库
    conn.execute(
        "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
        ("home_description", HOME_DESCRIPTION_DEFAULT),
    )

    conn.commit()
    conn.close()


def _import_models(conn: sqlite3.Connection):
    json_path = Path(__file__).parent / "models.json"
    if not json_path.exists():
        return
    with open(json_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    active_id = cfg.get("active", "")
    dt = cfg.get("api_type", "openai")
    db = cfg.get("api_base", "")
    dk = cfg.get("api_key_env", "")
    for mid, info in cfg.get("models", {}).items():
        conn.execute(
            "INSERT OR IGNORE INTO models (id,label,api_type,api_base,api_key,max_tokens,is_active) VALUES (?,?,?,?,?,?,?)",
            (mid, info.get("label", mid), info.get("api_type", dt),
             info.get("api_base", db), info.get("api_key", ""),
             info.get("max_tokens", 4096), 1 if mid == active_id else 0),
        )
    for k, v in cfg.get("options", {}).items():
        conn.execute("INSERT OR IGNORE INTO config (key,value) VALUES (?,?)", (k, str(v)))


def _import_characters(conn: sqlite3.Connection):
    chars_dir = Path(__file__).parent / "characters"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    emoji_map = {"爸爸": "👨", "妈妈": "👩", "姐姐": "👧", "弟弟": "👦"}
    for fname, role, age, occup in [
        ("dad.json", "爸爸", 45, "软件架构师"),
        ("mom.json", "妈妈", 42, "中学语文老师"),
        ("xiaoyue.json", "姐姐", 16, "高一学生"),
        ("xiaohua.json", "弟弟", 10, "小学四年级学生"),
    ]:
        fpath = chars_dir / fname
        if not fpath.exists():
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            d = json.load(f)
        conn.execute(
            """INSERT OR IGNORE INTO characters (name,role,age,occupation,personality_profile,catchphrases,schedule,relationships,emoji,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (d["name"], role, age, occup,
             d.get("personality_profile", ""),
             json.dumps(d.get("catchphrases", []), ensure_ascii=False),
             json.dumps(d.get("schedule", {}), ensure_ascii=False),
             json.dumps(d.get("relationships", {}), ensure_ascii=False),
             emoji_map.get(role, "👤"),
             now),
        )


# ═══ 模型 CRUD ═══════════════════════════════════════

def list_models() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM models ORDER BY is_active DESC, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_active_model() -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM models WHERE is_active=1").fetchone()
    conn.close()
    return dict(row) if row else None


def set_active_model(model_id: str) -> bool:
    conn = get_conn()
    if not conn.execute("SELECT id FROM models WHERE id=?", (model_id,)).fetchone():
        conn.close()
        return False
    conn.execute("UPDATE models SET is_active=0")
    conn.execute("UPDATE models SET is_active=1 WHERE id=?", (model_id,))
    conn.commit()
    conn.close()
    return True


def update_model(model_id: str, data: dict) -> bool:
    conn = get_conn()
    allowed = {"api_base", "api_key"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        conn.close()
        return False
    sets = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE models SET {sets} WHERE id=?", list(updates.values()) + [model_id])
    conn.commit()
    conn.close()
    return True


def get_model_api_key() -> str:
    """获取当前激活模型的 api_key"""
    m = get_active_model()
    return m.get("api_key", "") if m else ""


# ═══ 配置 CRUD ═══════════════════════════════════════

def get_config() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM config").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def update_config(data: dict):
    conn = get_conn()
    for k, v in data.items():
        conn.execute("INSERT OR REPLACE INTO config (key,value) VALUES (?,?)", (k, str(v)))
    conn.commit()
    conn.close()


# ═══ 角色 CRUD ══════════════════════════════════════

def list_characters() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM characters ORDER BY age DESC").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for f in ("catchphrases", "schedule", "relationships"):
            try:
                d[f] = json.loads(d.get(f, "[]"))
            except (json.JSONDecodeError, TypeError):
                d[f] = [] if f == "catchphrases" else {}
        result.append(d)
    return result


def get_character(name: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM characters WHERE name=?", (name,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for f in ("catchphrases", "schedule", "relationships"):
        try:
            d[f] = json.loads(d.get(f, "[]"))
        except (json.JSONDecodeError, TypeError):
            d[f] = [] if f == "catchphrases" else {}
    return d


def update_character(name: str, data: dict):
    conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 基础属性
    base_fields = {}
    for f in ("role", "age", "occupation"):
        if f in data:
            base_fields[f] = data[f] if f == "role" or f == "occupation" else int(data[f])
    # 人设字段
    json_fields = {
        "personality_profile": data.get("personality_profile", ""),
        "catchphrases": json.dumps(data.get("catchphrases", []), ensure_ascii=False),
        "schedule": json.dumps(data.get("schedule", {}), ensure_ascii=False),
        "relationships": json.dumps(data.get("relationships", {}), ensure_ascii=False),
        "updated_at": now,
    }
    all_fields = {**base_fields, **json_fields}
    if "emoji" in data:
        all_fields["emoji"] = data["emoji"]
    sets = ", ".join(f"{k}=?" for k in all_fields)
    conn.execute(f"UPDATE characters SET {sets} WHERE name=?", list(all_fields.values()) + [name])
    conn.commit()
    conn.close()


def get_system_user() -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM characters WHERE is_system_user=1").fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for f in ("catchphrases", "schedule", "relationships"):
        try:
            d[f] = json.loads(d.get(f, "[]"))
        except (json.JSONDecodeError, TypeError):
            d[f] = [] if f == "catchphrases" else {}
    return d


# ═══ 场景模板 CRUD ══════════════════════════════════

def list_scene_templates() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM scene_templates ORDER BY updated_at DESC").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["characters"] = json.loads(d.get("characters", "[]"))
        except (json.JSONDecodeError, TypeError):
            d["characters"] = []
        result.append(d)
    return result


def save_scene_template(data: dict) -> int:
    conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        """INSERT INTO scene_templates (title,scene_key,time_override,location,characters,plot,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (data.get("title", ""), data.get("scene_key", ""),
         data.get("time_override", ""), data.get("location", ""),
         json.dumps(data.get("characters", []), ensure_ascii=False),
         data.get("plot", ""), now, now),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def delete_scene_template(tid: int):
    conn = get_conn()
    conn.execute("DELETE FROM scene_templates WHERE id=?", (tid,))
    conn.commit()
    conn.close()


# ═══ 场景历史 CRUD ══════════════════════════════════

def save_scene_history(scene_data: dict):
    conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO scene_history (scene_key,time_str,location,characters,plot,content,model,created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (scene_data.get("scene_key", ""), scene_data.get("time", ""),
         scene_data.get("location", ""),
         json.dumps(scene_data.get("present", []), ensure_ascii=False),
         scene_data.get("plot", ""), scene_data.get("content", ""),
         scene_data.get("model", ""), now),
    )
    conn.commit()
    conn.close()


def list_scene_history(limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM scene_history ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["present"] = json.loads(d.get("characters", "[]"))
        except (json.JSONDecodeError, TypeError):
            d["present"] = []
        d["time"] = d.pop("time_str", "")
        result.append(d)
    return result


# ═══ 聊天历史 CRUD ══════════════════════════════════

def save_chat_message(character: str, role: str, content: str):
    conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO chat_history (character_name, role, content, created_at) VALUES (?,?,?,?)",
        (character, role, content, now),
    )
    conn.commit()
    conn.close()


def list_chat_history(character: str, limit: int = 20, before_id: int = None) -> list[dict]:
    conn = get_conn()
    if before_id:
        rows = conn.execute(
            """SELECT * FROM chat_history WHERE character_name=? AND id < ?
               ORDER BY id DESC LIMIT ?""",
            (character, before_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM chat_history WHERE character_name=? ORDER BY id DESC LIMIT ?",
            (character, limit),
        ).fetchall()
    conn.close()
    result = [dict(r) for r in rows]
    result.reverse()
    return result


# ═══ 家庭环境描述 ────────────────────────────────────
HOME_DESCRIPTION_DEFAULT = """## 家庭环境

这是一个三室两厅的温馨小家，位于城市的一个普通小区里。

- **客厅**：不算大但布置得很温馨。米色的布艺沙发（小华最喜欢在上面跳），茶几上永远堆着各种东西——遥控器、零食、小华的乐高零件。电视是55寸的，爸爸坚持要买"性价比最高的"。
- **餐厅**：和客厅连通，一张六人餐桌实际只用四把椅子。餐边柜上摆着妈妈养的两盆绿萝，长得很好因为只有妈妈记得浇水。
- **厨房**：妈妈的"领地"。收拾得很干净，调料瓶按大小排列。冰箱门上贴满了小华的奖状和小月的课程表。
- **书房**：爸爸的"避难所"。书架上塞满了技术书籍和管理类书籍，但角落里藏着一套金庸全集。桌上永远有三台显示器，小华觉得这很酷。
- **主卧**：爸妈的房间。简洁干净，床头的结婚照已经挂了17年，相框有些褪色。
- **小月的房间**：门上贴着"请敲门"的便条。房间里有淡淡的香薰味，墙上贴着K-pop海报和她的插画作品。书桌收拾得意外地整齐。
- **小华的房间**：最乱的一个房间（妈妈每天都在收拾）。床上堆着乐高和恐龙模型，枕头底下藏着旧旧的小熊玩偶。墙上贴着世界地图，小华在上面用红笔标注了"长大后要去的地方"。
- **阳台**：爸爸的茶台和妈妈的花花草草共享这片小小的空间。周末早上这里是最抢手的地方。"""


def get_config_value(key: str, default: str = "") -> str:
    conn = get_conn()
    row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def get_home_description() -> str:
    return get_config_value("home_description", HOME_DESCRIPTION_DEFAULT)


def update_home_description(text: str):
    update_config({"home_description": text})


# ═══ 场景预设（从DB读取）═════════════════════════════
def get_scene_presets() -> dict:
    """从 scene_templates 读取预设场景，返回兼容旧 SCENES 格式"""
    templates = list_scene_templates()
    result = {}
    for t in templates:
        if t.get("scene_key"):
            result[t["scene_key"]] = {
                "time": t.get("time_override", ""),
                "location": t.get("location", ""),
                "description": t.get("plot", ""),
                "typical_present": t.get("characters", []),
                "vibe": "",
            }
    return result


# ═══ 启动初始化 ═════════════════════════════════════
init_db()
