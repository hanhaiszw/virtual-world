#!/usr/bin/env python3
"""
虚拟家庭模拟器 - Virtual Family Simulator

模拟一家四口（爸爸、妈妈、姐姐小月、弟弟小华）的日常生活场景。
利用大语言模型生成自然、生动的家庭互动对话和场景。

支持模型提供商: Anthropic Claude / DeepSeek / OpenAI 兼容接口
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text
from rich import box

from config import SimulationConfig, AVAILABLE_MODELS, default_config
import db

# ─── 日志配置 ─────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

scene_logger = logging.getLogger("family_scene")
scene_logger.setLevel(logging.INFO)
scene_log_handler = logging.FileHandler(
    LOG_DIR / f"scenes_{datetime.now().strftime('%Y%m%d')}.log",
    encoding="utf-8"
)
scene_log_handler.setFormatter(logging.Formatter(
    "\n" + "=" * 60 + "\n"
    "[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))
scene_logger.addHandler(scene_log_handler)
# 防止重复添加 handler
scene_logger.propagate = False

console = Console()

# ─── 场景预设 & 家庭环境（从 DB 读取）─────────────────

def _get_scenes() -> dict:
    return db.get_scene_presets()

def _get_home_description() -> str:
    return db.get_home_description()


class FamilySimulation:
    """虚拟家庭模拟器 - 多模型提供商支持"""

    def __init__(self, config: SimulationConfig = None, api_key: Optional[str] = None):
        self.cfg = config or default_config
        self.characters = {}
        self.scene_history = []
        self.home_description = _get_home_description()

        # API Key 直接从 DB 读取
        api_key = self.cfg.api_key
        if not api_key:
            console.print(
                "[red]错误: 未配置 API Key[/red]\n"
                "请在 Web 界面「⚙️ 模型配置」中设置 API Key"
            )
            sys.exit(1)

        self._init_client(api_key)

        # 配置验证
        warnings = self.cfg.validate()
        if warnings:
            for w in warnings:
                console.print(f"  [yellow]⚠ {w}[/yellow]")

        self.load_characters()

    def _init_client(self, api_key: str):
        """根据 api_type 初始化对应的 API 客户端"""
        base_url = self.cfg.resolve_base_url()

        if self.cfg.api_type == "anthropic":
            import anthropic
            kwargs = {"api_key": api_key}
            if base_url != "https://api.anthropic.com":
                kwargs["base_url"] = base_url
            self.client = anthropic.Anthropic(**kwargs)

        else:  # openai 兼容格式（默认）
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key, base_url=base_url)

        console.print(f"[dim]📡 API 类型: {self.cfg.api_type} | {base_url} | 模型: {self.cfg.model}[/dim]")

    def load_characters(self):
        """加载所有角色人设（从 DB）"""
        for c in db.list_characters():
            self.characters[c["name"]] = c

        if len(self.characters) < 4:
            console.print(f"[yellow]警告: 只加载了 {len(self.characters)} 个角色[/yellow]")

    def _build_character_profiles_text(self, active_names: list[str]) -> str:
        """构建活跃角色的详细人设文本"""
        sections = []

        for name in active_names:
            if name not in self.characters:
                continue
            char = self.characters[name]
            section = f"""### {char['role']} - {char['name']}（{char['age']}岁，{char['occupation']}）

{char['personality_profile']}

**口头禅**：{', '.join(char['catchphrases'][:5])}

**与其他家庭成员的关系**："""
            for rel_name, rel_desc in char.get("relationships", {}).items():
                if rel_name in active_names and rel_name != name:
                    section += f"\n- 对{rel_name}：{rel_desc}"

            sections.append(section)

        return "\n\n---\n\n".join(sections)

    def build_system_prompt(self, active_characters: list[str]) -> str:
        """构建完整的系统提示词"""
        profiles = self._build_character_profiles_text(active_characters)
        min_w = self.cfg.scene_min_words
        max_w = self.cfg.scene_max_words
        return f"""# 虚拟家庭模拟器

你是一个专业的家庭生活场景模拟器。你将根据详细的角色人设，生成一个中国四口之家的日常生活场景。

{self.home_description}

---

## 角色人设

{profiles}

---

## 生成规则

1. **严格遵循人设**：每个角色的言行必须严格符合其性格特征、语言风格和年龄设定。不要OOC（脱离角色）。
2. **叙事+对话混合**：用叙事体描述场景，穿插自然的人物对话。对话要口语化、生活化。
3. **细节丰富**：加入动作描写、神态描写、环境细节，让场景生动有画面感。
4. **冲突与温情**：家人之间可以有小的摩擦和吐槽，但整体基调应该是温暖的。不要写大冲突。
5. **长度控制**：每个场景{min_w}-{max_w}字，不要太短也不要太长。
6. **格式**：直接输出场景内容，不要加任何前缀说明或后缀评论。就像在写一个生活剧的剧本片段。
7. **语言**：全部使用中文。对话用中文引号「」或直接分行表示。
8. **不要让角色说和当前场景无关的话**：如果某个角色不在场，不要写ta的对话。
9. **自然衔接**：如果有前情提要，要自然地衔接上。
"""

    def generate_scene(
        self,
        scene_key: str = None,
        scene_description: str = None,
        active_characters: list[str] = None,
        time_override: str = None,
        context: str = None,
        model: str = None,
    ) -> str:
        """生成一个家庭互动场景"""
        if scene_key and scene_key in _get_scenes():
            scene = _get_scenes()[scene_key]
            time_str = time_override or scene["time"]
            location = scene["location"]
            description = scene["description"]
            if active_characters is None:
                active_characters = scene["typical_present"]
        elif scene_description:
            time_str = time_override or "某个时间"
            location = "家中"
            description = scene_description
            if active_characters is None:
                active_characters = list(self.characters.keys())
        else:
            raise ValueError("必须指定 scene_key 或 scene_description")

        active = [n for n in active_characters if n in self.characters]
        if not active:
            raise ValueError("没有有效的在场角色")

        system_prompt = self.build_system_prompt(active)

        present_list = "、".join(active)
        user_message = f"""【当前场景】
🕐 时间：{time_str}
📍 地点：{location}
👥 在场：{present_list}

📝 场景描述：{description}"""

        if context:
            user_message += f"\n\n📋 前情提要：{context}"

        user_message += "\n\n请生成接下来的家庭互动场景。"

        model_id = model or self.cfg.model

        try:
            result = self._call_api(system_prompt, user_message, model_id)
        except Exception as e:
            return f"[red]生成场景时出错: {e}[/red]"

        scene_text = result["text"]
        usage = result["usage"]
        actual_model = result["model"]

        if self.cfg.show_token_usage and usage:
            cache_hit = usage.get("cache_hit", 0)
            cache_str = f"缓存命中 {cache_hit} | " if cache_hit else ""
            console.print(
                f"  [dim]📊 tokens: {cache_str}"
                f"输入 {usage['input']} | 输出 {usage['output']} "
                f"| 🧠 {actual_model}[/dim]"
            )

        self.scene_history.append({
            "time": time_str,
            "location": location,
            "present": active,
            "content": scene_text,
            "model": actual_model,
        })

        # 记录日志
        scene_logger.info(
            f"场景: {scene_key or '自定义'} | "
            f"时间: {time_str} | 地点: {location} | "
            f"人物: {', '.join(active)} | "
            f"模型: {actual_model}\n"
            f"{scene_text}\n"
            f"{'-' * 60}"
        )

        return scene_text

    def _call_api(self, system_prompt: str, user_message: str, model_id: str) -> dict:
        """调用 API，处理不同提供商的格式差异。

        Returns:
            {"text": str, "usage": dict, "model": str}
        """
        if self.cfg.api_type == "anthropic":
            return self._call_anthropic(system_prompt, user_message, model_id)
        else:
            return self._call_openai_compatible(system_prompt, user_message, model_id)

    def _call_anthropic(self, system_prompt: str, user_message: str, model_id: str) -> dict:
        """Anthropic Messages API"""
        import anthropic

        kwargs = {
            "model": model_id,
            "max_tokens": self.cfg.max_tokens,
            "temperature": self.cfg.temperature,
            "top_p": self.cfg.top_p,
            "messages": [{"role": "user", "content": user_message}],
        }

        # Prompt 缓存 (仅 Anthropic 支持)
        if self.cfg.enable_prompt_caching:
            kwargs["system"] = [
                {"type": "text", "text": system_prompt,
                 "cache_control": {"type": "ephemeral"}},
            ]
        else:
            kwargs["system"] = system_prompt

        try:
            resp = self.client.messages.create(**kwargs)
            return {
                "text": resp.content[0].text.strip(),
                "usage": {
                    "input": resp.usage.input_tokens,
                    "output": resp.usage.output_tokens,
                    "cache_hit": getattr(resp.usage, 'cache_read_input_tokens', 0),
                },
                "model": resp.model,
            }
        except anthropic.APIError as e:
            if self.cfg.fallback_model and model_id != self.cfg.fallback_model:
                console.print(f"  [yellow]⚠ {model_id} 失败，尝试 {self.cfg.fallback_model}[/yellow]")
                return self._call_anthropic(system_prompt, user_message, self.cfg.fallback_model)
            raise e

    def _call_openai_compatible(self, system_prompt: str, user_message: str, model_id: str) -> dict:
        """OpenAI 兼容 API (DeepSeek / OpenAI / 其他)"""
        try:
            resp = self.client.chat.completions.create(
                model=model_id,
                max_tokens=self.cfg.max_tokens,
                temperature=self.cfg.temperature,
                top_p=self.cfg.top_p,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )

            usage = {}
            if resp.usage:
                usage = {
                    "input": resp.usage.prompt_tokens,
                    "output": resp.usage.completion_tokens,
                    "cache_hit": getattr(
                        resp.usage, 'prompt_tokens_details', {}
                    ).cached_tokens if hasattr(resp.usage, 'prompt_tokens_details') else 0,
                }

            return {
                "text": resp.choices[0].message.content.strip(),
                "usage": usage,
                "model": resp.model,
            }

        except Exception as e:
            if self.cfg.fallback_model and model_id != self.cfg.fallback_model:
                console.print(f"  [yellow]⚠ {model_id} 失败，尝试 {self.cfg.fallback_model}[/yellow]")
                return self._call_openai_compatible(system_prompt, user_message, self.cfg.fallback_model)
            raise e

    def display_scene(self, scene_text, title="", time_str="", present=None):
        """美化显示场景内容"""
        if not title:
            title = "家庭场景"
        if time_str:
            title = f"{title} · {time_str}"

        present_str = "  ".join(f"[bold]{n}[/bold]" for n in (present or []))

        console.print()
        console.print(Panel(Text(title, style="bold cyan"), box=box.HEAVY, border_style="cyan"))
        if present_str:
            console.print(f"  👥 {present_str}")
        console.print()
        console.print(Panel(Markdown(scene_text), box=box.ROUNDED, border_style="green", padding=(1, 2)))
        console.print()

    def run_daily_simulation(self, model: str = None):
        """运行一天的生活模拟"""
        day_scenes = ["breakfast", "homework", "dinner", "after_dinner"]

        console.clear()
        console.print()
        console.print(Panel(
            "[bold yellow]🏠 虚拟家庭 - 一日生活模拟[/bold yellow]\n按时间顺序展示一家人一天的互动场景",
            box=box.DOUBLE, border_style="yellow"
        ))

        context = None
        for i, scene_key in enumerate(day_scenes):
            scene = _get_scenes()[scene_key]
            with console.status(f"[cyan]生成: {scene['time']} {scene_key}...[/cyan]", spinner="dots"):
                scene_text = self.generate_scene(
                    scene_key=scene_key, context=context, model=model
                )
            self.display_scene(scene_text, title=f"场景 {i+1}", time_str=scene["time"], present=scene["typical_present"])
            context = scene_text[:self.cfg.context_truncate_chars]

            if i < len(day_scenes) - 1:
                console.print("  [dim]按 Enter 继续...[/dim]", end="")
                input()
                console.print()

        console.print(Panel("[bold green]✨ 一日生活模拟结束[/bold green]", box=box.DOUBLE, border_style="green"))

    def run_interactive(self, model: str = None):
        """交互式模拟模式"""
        console.clear()

        while True:
            console.print()
            console.print(Panel(
                "[bold yellow]🏠 虚拟家庭模拟器[/bold yellow]\n"
                f"[dim]提供商: {self.cfg.api_type} | 模型: {self.cfg.model} | 交互模式[/dim]",
                box=box.DOUBLE, border_style="yellow"
            ))

            table = Table(title="📋 预设场景", box=box.ROUNDED, border_style="blue")
            table.add_column("编号", style="cyan", width=6)
            table.add_column("场景", style="green", width=20)
            table.add_column("时间", style="yellow", width=14)
            table.add_column("人物", style="magenta", width=24)
            table.add_column("简介", style="white", width=40)

            scene_keys = list(_get_scenes().keys())
            for i, key in enumerate(scene_keys, 1):
                s = _get_scenes()[key]
                table.add_row(str(i), key, s["time"], ", ".join(s["typical_present"]), s["vibe"])

            console.print(table)
            console.print()
            console.print("  [dim]输入场景编号（1-8）或直接输入自定义场景描述[/dim]")
            console.print("  [dim]输入 'day' 运行一日模拟 | 'quit' 退出[/dim]")
            console.print()

            choice = console.input("[bold cyan]👉 [/bold cyan]").strip()

            if choice.lower() == "quit":
                console.print("[green]再见！🏠[/green]")
                break
            if choice.lower() == "day":
                self.run_daily_simulation(model=model)
                continue

            try:
                idx = int(choice) - 1
                if 0 <= idx < len(scene_keys):
                    scene_key = scene_keys[idx]
                    scene = _get_scenes()[scene_key]
                    with console.status("[cyan]生成场景中...[/cyan]", spinner="dots"):
                        scene_text = self.generate_scene(scene_key=scene_key, model=model)
                    self.display_scene(scene_text, title=scene_key, time_str=scene["time"], present=scene["typical_present"])
                    console.print("  [dim]按 Enter 继续...[/dim]", end="")
                    input()
                    continue
            except ValueError:
                pass

            if choice:
                with console.status("[cyan]生成自定义场景中...[/cyan]", spinner="dots"):
                    scene_text = self.generate_scene(scene_description=choice, model=model)
                self.display_scene(scene_text, title="自定义场景")
                console.print("  [dim]按 Enter 继续...[/dim]", end="")
                input()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="🏠 虚拟家庭模拟器 - 模拟一家四口的日常生活")
    parser.add_argument("--scene", "-s", type=str, help=f"指定场景: {', '.join(_get_scenes().keys())}")
    parser.add_argument("--day", "-d", action="store_true", help="运行一日完整模拟")

    # 提供商
    parser.add_argument("--provider", "-p", type=str, default=None,
                        choices=["anthropic", "deepseek", "openai"],
                        help=f"模型提供商 (默认: {default_config.provider})")

    # 模型选择
    model_group = parser.add_mutually_exclusive_group()
    model_group.add_argument("--model", "-m", type=str, default=None, help="指定模型 ID")
    model_group.add_argument("--opus", action="store_true", help="Anthropic Opus 4.7")
    model_group.add_argument("--sonnet", action="store_true", help="Anthropic Sonnet 4.6")
    model_group.add_argument("--haiku", action="store_true", help="Anthropic Haiku 4.5")
    model_group.add_argument("--ds-chat", action="store_true", help="DeepSeek Chat")
    model_group.add_argument("--ds-reasoner", action="store_true", help="DeepSeek Reasoner")

    # 其他参数
    parser.add_argument("--api-key", "-k", type=str, help="API Key")
    parser.add_argument("--base-url", type=str, help="自定义 API 地址")
    parser.add_argument("--temperature", "-t", type=float, default=None,
                        help=f"生成温度 (默认: {default_config.temperature})")
    parser.add_argument("--no-cache", action="store_true", help="禁用 prompt 缓存")
    parser.add_argument("--no-usage", action="store_true", help="不显示 token 用量")

    args = parser.parse_args()

    # 构建配置
    cfg = SimulationConfig()

    if args.provider:
        cfg.provider = args.provider
    if args.api_key:
        cfg.api_key = args.api_key
    if args.base_url:
        cfg.base_url = args.base_url
    if args.temperature is not None:
        cfg.temperature = args.temperature
    if args.no_cache:
        cfg.enable_prompt_caching = False
    if args.no_usage:
        cfg.show_token_usage = False

    # 模型选择
    if args.opus:
        cfg.provider = "anthropic"
        cfg.model = AVAILABLE_MODELS["opus"]["id"]
    elif args.sonnet:
        cfg.provider = "anthropic"
        cfg.model = AVAILABLE_MODELS["sonnet"]["id"]
    elif args.haiku:
        cfg.provider = "anthropic"
        cfg.model = AVAILABLE_MODELS["haiku"]["id"]
    elif args.ds_chat:
        cfg.provider = "deepseek"
        cfg.model = AVAILABLE_MODELS["ds-chat"]["id"]
    elif args.ds_reasoner:
        cfg.provider = "deepseek"
        cfg.model = AVAILABLE_MODELS["ds-reasoner"]["id"]
    elif args.model:
        cfg.model = args.model

    sim = FamilySimulation(config=cfg)

    if args.day:
        sim.run_daily_simulation()
    elif args.scene:
        if args.scene not in _get_scenes():
            console.print(f"[red]未知场景: {args.scene}[/red]")
            console.print(f"可用场景: {', '.join(_get_scenes().keys())}")
            sys.exit(1)
        with console.status("[cyan]生成场景中...[/cyan]", spinner="dots"):
            scene_text = sim.generate_scene(scene_key=args.scene)
        scene = _get_scenes()[args.scene]
        sim.display_scene(scene_text, title=args.scene, time_str=scene["time"], present=scene["typical_present"])
    else:
        sim.run_interactive()


if __name__ == "__main__":
    main()
