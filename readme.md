# 虚拟家庭模拟器 — 项目概览

## 项目功能

模拟一个四口之家（爸爸王建国、妈妈李梅、姐姐王小月、弟弟王小华）的日常生活。利用大语言模型，根据每个角色的详细人设，生成自然的家庭互动场景和人物对话。

### 核心功能

| 功能 | 说明 |
|------|------|
| **场景生成** | 8 个预设场景（早餐、晚餐、写作业、周末早晨等）+ 自定义场景描述 |
| **一日模拟** | 按时间线自动推进（早餐→写作业→晚餐→饭后），上下文连贯 |
| **人物对话** | 选择任意家人 1v1 聊天，角色严格按人设回复 |
| **人物管理** | 可视化编辑四人的性格人设、口头禅、生活轨迹、家庭关系，即时生效 |
| **运行日志** | 每次生成自动保存到 `logs/`，记录时间、场景、人物、完整内容 |
| **多模型支持** | 支持 Anthropic Claude / DeepSeek / OpenAI 兼容接口，一键切换 |

### 四人设定

| 角色 | 年龄 | 职业 | 性格关键词 |
|------|------|------|-----------|
| 👔 王建国（爸爸） | 45 | 软件架构师 | 理性稳重、不善表达、爱讲道理、内心温暖 |
| 👩‍🏫 李梅（妈妈） | 42 | 中学语文老师 | 温柔掌控、无微不至、习惯唠叨、家庭CEO |
| 🎧 王小月（姐姐） | 16 | 高一学生 | 外冷内热、嘴硬心软、有自己的小世界 |
| ⚽ 王小华（弟弟） | 10 | 小学四年级 | 精力充沛、好奇心强、情感外露、小聪明多 |

---

## 项目架构

```
浏览器 (index.html)
    │
    ▼
FastAPI Web 服务 (web_app.py)  ── 提供 REST API + 静态资源
    │
    ├── /api/generate   ──→  场景生成引擎 (simulation.py)
    ├── /api/chat       ──→  角色扮演对话
    ├── /api/characters ──→  人设读写 (characters/*.json)
    ├── /api/status     ──→  状态查询
    ├── /api/history    ──→  历史记录
    └── /img/*          ──→  角色头像静态文件
              │
              ▼
        LLM API (DeepSeek / Anthropic / OpenAI)
```

### 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 前端 | 纯 HTML/CSS/JS | 单页应用，琥珀色暖系 UI，无框架 |
| Web 框架 | FastAPI + Jinja2 | 异步路由，模板渲染 |
| LLM SDK | anthropic + openai | 支持多提供商切换 |
| 终端 | rich | CLI 版美化输出 |
| 配置 | Python dataclass | 集中管理模型/温度/token 等参数 |
| 日志 | Python logging | 按日切割，记录所有运行结果 |

### API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/` | 主页面 |
| GET | `/api/scenes` | 预设场景列表 |
| GET | `/api/status` | 提供商/模型/角色信息 |
| GET | `/api/history` | 场景生成历史 |
| POST | `/api/generate` | 生成场景 |
| POST | `/api/chat` | 与角色对话 |
| GET | `/api/characters` | 获取所有人设 |
| PUT | `/api/characters/{name}` | 更新角色人设 |

---

## 项目文件目录

```
virtual-world/
├── 项目概览.md            # 本文档
├── requirements.txt       # Python 依赖
├── config.py              # 模型/API 配置中心
├── simulation.py          # 核心模拟引擎 + CLI 入口
├── web_app.py             # FastAPI Web 服务入口
│
├── characters/            # 角色人设 JSON
│   ├── dad.json           #   爸爸 王建国
│   ├── mom.json           #   妈妈 李梅
│   ├── xiaoyue.json       #   姐姐 王小月
│   └── xiaohua.json       #   弟弟 王小华
│
├── templates/
│   └── index.html         # 前端单页应用（内嵌 CSS + JS）
│
├── img/                   # 角色头像图片
│   ├── 爸爸.png
│   ├── 妈妈.png
│   ├── 王小月.png
│   └── 王小华.png
│
└── logs/                  # 运行日志（自动生成）
    └── scenes_YYYYMMDD.log
```

### 文件说明

**config.py** — 模型与模拟参数配置
- 支持 Anthropic/DeepSeek/OpenAI 三种提供商
- 模型快捷别名（opus/sonnet/haiku/ds-chat/ds-reasoner）
- 可调参数：temperature、max_tokens、top_p、prompt caching
- API Key 自动从环境变量读取

**simulation.py** — 核心引擎
- `FamilySimulation` 类：角色加载、prompt 构建、场景生成
- 8 个预设场景 + 自定义场景支持
- CLI 交互界面（rich 美化输出）
- 运行日志自动写入 `logs/`

**web_app.py** — Web 服务
- FastAPI 应用，线程池处理阻塞 LLM 调用
- RESTful API：场景生成、角色对话、人设管理
- uvicorn 热加载开发模式
- 启动：`python web_app.py` → http://127.0.0.1:8080

**templates/index.html** — 前端界面
- 暖琥珀色设计系统，CSS 变量管理
- 左侧场景列表 + 自定义输入
- 右侧场景展示区（时间徽章、角色头像、对话高亮）
- 顶栏：模型状态 + 对话按钮 + 人物管理按钮
- 底部历史记录条
- 右侧滑出聊天面板
- 弹窗式人物编辑器

**characters/*.json** — 角色数据
- `personality_profile`：完整人设描述（注入 LLM prompt）
- `catchphrases`：口头禅列表
- `schedule`：一日生活轨迹
- `relationships`：与其他家人的关系描述

---

## 使用方式

```bash
# 安装
pip install -r requirements.txt

# CLI 模式
python simulation.py              # 交互式
python simulation.py -s dinner    # 单个场景
python simulation.py -d           # 一日模拟

# Web 模式
python web_app.py                 # 启动 → http://127.0.0.1:8080

# 模型切换
python simulation.py --ds-chat    # DeepSeek Chat
python simulation.py --opus       # Claude Opus
python web_app.py                 # 默认使用 config.py 中的 provider 设置
```
