"""Static provider metadata: display names, short names and brand accent colors.

The CLI speaks provider ids (``azure-openai``, ``alibabatokenplan``, ...). The GUI needs
human labels plus a color per provider for meters and cards.
"""

from __future__ import annotations

# provider id -> (display name, short label, accent color)
PROVIDERS: dict[str, tuple[str, str, str]] = {
    "codex": ("Codex", "Codex", "#10A37F"),
    "openai": ("OpenAI", "OpenAI", "#412991"),
    "azure-openai": ("Azure OpenAI", "Azure", "#0078D4"),
    "claude": ("Claude", "Claude", "#D97757"),
    "clinepass": ("ClinePass", "Cline", "#8B5CF6"),
    "cursor": ("Cursor", "Cursor", "#111111"),
    "opencode": ("OpenCode", "OpenCode", "#F59E0B"),
    "opencodego": ("OpenCode Go", "OC Go", "#EC4899"),
    "alibaba-coding-plan": ("Alibaba Coding Plan", "Alibaba", "#FF6A00"),
    "alibaba-token-plan": ("Alibaba Token Plan", "Ali TP", "#FF6A00"),
    "qwen-cloud": ("Qwen Cloud", "Qwen", "#615CED"),
    "factory": ("Droid", "Droid", "#111827"),
    "fireworks": ("Fireworks", "Fireworks", "#5019C5"),
    "gemini": ("Gemini", "Gemini", "#4285F4"),
    "antigravity": ("Antigravity", "Antigrav", "#7C3AED"),
    "copilot": ("Copilot", "Copilot", "#24292F"),
    "devin": ("Devin", "Devin", "#5B21B6"),
    "zai": ("z.ai / GLM", "z.ai", "#2563EB"),
    "minimax": ("MiniMax", "MiniMax", "#F43F5E"),
    "manus": ("Manus", "Manus", "#FF5722"),
    "kimi": ("Kimi Code", "Kimi", "#1F1F1F"),
    "kilo": ("Kilo", "Kilo", "#7C3AED"),
    "kiro": ("Kiro", "Kiro", "#7B3FE4"),
    "vertexai": ("Vertex AI", "Vertex", "#4285F4"),
    "augment": ("Augment", "Augment", "#F43F5E"),
    "jetbrains": ("JetBrains AI", "JB AI", "#000000"),
    "moonshot": ("Moonshot", "Moonshot", "#0B5FFF"),
    "amp": ("Amp", "Amp", "#111111"),
    "t3chat": ("T3 Chat", "T3", "#EC4899"),
    "ollama": ("Ollama", "Ollama", "#111111"),
    "synthetic": ("Synthetic", "Synthetic", "#6366F1"),
    "openrouter": ("OpenRouter", "OpenRouter", "#6467F2"),
    "elevenlabs": ("ElevenLabs", "ElevenLabs", "#111111"),
    "warp": ("Warp", "Warp", "#01A0C6"),
    "windsurf": ("Windsurf", "Windsurf", "#0B9E8A"),
    "zed": ("Zed", "Zed", "#084CCF"),
    "perplexity": ("Perplexity", "Perplexity", "#20808D"),
    "mimo": ("Xiaomi MiMo", "MiMo", "#FF6900"),
    "doubao": ("Doubao", "Doubao", "#1D6EF5"),
    "sakana": ("Sakana AI", "Sakana", "#0F766E"),
    "abacusai": ("Abacus AI", "Abacus", "#2563EB"),
    "mistral": ("Mistral", "Mistral", "#FA500F"),
    "deepseek": ("DeepSeek", "DeepSeek", "#4D6BFE"),
    "deepinfra": ("DeepInfra", "DeepInfra", "#6366F1"),
    "codebuff": ("Codebuff", "Codebuff", "#7C3AED"),
    "venice": ("Venice", "Venice", "#111111"),
    "commandcode": ("Command Code", "Command", "#F97316"),
    "qoder": ("Qoder", "Qoder", "#22C55E"),
    "stepfun": ("StepFun", "StepFun", "#2563EB"),
    "bedrock": ("AWS Bedrock", "Bedrock", "#FF9900"),
    "grok": ("Grok", "Grok", "#111111"),
    "groqcloud": ("Groq", "Groq", "#F55036"),
    "llmproxy": ("LLM Proxy", "Proxy", "#64748B"),
    "litellm": ("LiteLLM", "LiteLLM", "#0EA5E9"),
    "bifrost": ("Bifrost", "Bifrost", "#8B5CF6"),
    "deepgram": ("Deepgram", "Deepgram", "#0F172A"),
    "poe": ("Poe", "Poe", "#111111"),
    "chutes": ("Chutes", "Chutes", "#7C3AED"),
    "neuralwatt": ("Neuralwatt", "Neuralwatt", "#14B8A6"),
    "helmcode": ("Helmcode", "Helmcode", "#2563EB"),
    "clawrouter": ("ClawRouter", "Claw", "#E11D48"),
    "longcat": ("LongCat", "LongCat", "#0F172A"),
    "sub2api": ("sub2api", "sub2api", "#64748B"),
    "wayfinder": ("Wayfinder", "Wayfind", "#0891B2"),
    "zenmux": ("ZenMux", "ZenMux", "#7C3AED"),
    "aiand": ("ai&", "ai&", "#111111"),
    "zoommate": ("ZoomMate", "ZoomMate", "#2563EB"),
    "xai": ("xAI", "xAI", "#111111"),
    "notion": ("Notion AI", "Notion", "#111111"),
    "ibmbob": ("IBM Bob", "Bob", "#0F62FE"),
    "nous": ("Nous Portal", "Nous", "#6366F1"),
    "muse": ("Muse Code", "Muse", "#111111"),
    "museai": ("Muse (muse.ai)", "muse.ai", "#7C3AED"),
    "coderabbit": ("CodeRabbit", "CodeRabbit", "#F97316"),
    "replicate": ("Replicate", "Replicate", "#111111"),
    "huggingface": ("Hugging Face", "HF", "#FFD21E"),
    "raycast": ("Raycast", "Raycast", "#FF6363"),
    "pi": ("Pi", "Pi", "#111111"),
    "v0": ("v0", "v0", "#000000"),
    "typesafe": ("TypeSafe", "TypeSafe", "#2563EB"),
    "hyper": ("Charm Hyper", "Hyper", "#111111"),
    "gitkraken": ("GitKraken AI", "GitKraken", "#2365D1"),
    "devpass": ("DevPass", "DevPass", "#7C3AED"),
    "atlascloud": ("Atlas Cloud", "Atlas", "#0EA5E9"),
    "vercel": ("Vercel AI Gateway", "Vercel", "#000000"),
    "xkiro": ("xKiro", "xKiro", "#7B3FE4"),
    "langdock": ("Langdock", "Langdock", "#2563EB"),
    "xapi": ("X API", "X API", "#111111"),
    "futureagi": ("Future AGI", "FutureAGI", "#6366F1"),
    "lithosai": ("LithosAI", "Lithos", "#8B5CF6"),
    "workbuddy": ("WorkBuddy", "WorkBuddy", "#F97316"),
    "tavily": ("Tavily", "Tavily", "#2563EB"),
    "linkup": ("Linkup", "Linkup", "#0EA5E9"),
    "tinyapi": ("TinyApi", "TinyApi", "#64748B"),
    "exa": ("Exa", "Exa", "#6366F1"),
    "cosmic": ("Cosmic AI", "Cosmic", "#7C3AED"),
    "aerostack": ("Aerostack", "Aerostack", "#0EA5E9"),
    "sailresearch": ("Sail Research", "Sail", "#2563EB"),
    "sofya": ("Sofya", "Sofya", "#EC4899"),
    "fal": ("fal", "fal", "#111111"),
    "flora": ("FLORA", "FLORA", "#6366F1"),
    "parallel": ("Parallel", "Parallel", "#111111"),
    "claudeplatform": ("Claude Platform", "Claude Plat", "#D97757"),
    "munito": ("Munito", "Munito", "#2563EB"),
}


def display_name(provider_id: str) -> str:
    entry = PROVIDERS.get(provider_id)
    if entry:
        return entry[0]
    return provider_id.replace("-", " ").replace("_", " ").title()


def short_name(provider_id: str) -> str:
    entry = PROVIDERS.get(provider_id)
    if entry:
        return entry[1]
    return display_name(provider_id)


def accent_color(provider_id: str) -> str:
    entry = PROVIDERS.get(provider_id)
    if entry:
        return entry[2]
    return "#6366F1"


def all_provider_ids() -> list[str]:
    return list(PROVIDERS.keys())
