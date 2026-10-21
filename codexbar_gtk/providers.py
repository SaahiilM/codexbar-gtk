"""Static provider metadata: display names, short names and brand accent colors.

The CLI speaks provider ids (``azure-openai``, ``alibabatokenplan``, ...). The GUI needs
human labels plus a color per provider for meters and cards.
"""

from __future__ import annotations

# provider id -> (display name, short label, accent color)
PROVIDERS: dict[str, tuple[str, str, str]] = {
    "abacus": ("Abacus AI", "Abacus", "#2563EB"),
    "aerostack": ("Aerostack", "Aerostack", "#0EA5E9"),
    "aiand": ("ai&", "ai&", "#111111"),
    "aixy": ("Aixy", "Aixy", "#0EA5E9"),
    "alibaba": ("Alibaba Coding Plan", "Alibaba", "#FF6A00"),
    "alibabatokenplan": ("Alibaba Token Plan", "Ali TP", "#FF6A00"),
    "amp": ("Amp", "Amp", "#111111"),
    "antigravity": ("Antigravity", "Antigrav", "#7C3AED"),
    "atlascloud": ("Atlas Cloud", "Atlas", "#0EA5E9"),
    "augment": ("Augment", "Augment", "#F43F5E"),
    "azureopenai": ("Azure Open AI", "Azure", "#0078D4"),
    "bedrock": ("AWS Bedrock", "Bedrock", "#FF9900"),
    "bifrost": ("Bifrost", "Bifrost", "#8B5CF6"),
    "chutes": ("Chutes", "Chutes", "#7C3AED"),
    "claude": ("Claude", "Claude", "#D97757"),
    "claudeplatform": ("Claude Platform", "Claude Plat", "#D97757"),
    "clawrouter": ("ClawRouter", "Claw", "#E11D48"),
    "clinepass": ("ClinePass", "Cline", "#8B5CF6"),
    "codebuff": ("Codebuff", "Codebuff", "#7C3AED"),
    "coderabbit": ("CodeRabbit", "CodeRabbit", "#F97316"),
    "codex": ("Codex", "Codex", "#10A37F"),
    "commandcode": ("Command Code", "Command", "#F97316"),
    "copilot": ("Copilot", "Copilot", "#24292F"),
    "cosmic": ("Cosmic AI", "Cosmic", "#7C3AED"),
    "cursor": ("Cursor", "Cursor", "#111111"),
    "deepgram": ("Deepgram", "Deepgram", "#0F172A"),
    "deepinfra": ("DeepInfra", "DeepInfra", "#6366F1"),
    "deepseek": ("DeepSeek", "DeepSeek", "#4D6BFE"),
    "devin": ("Devin", "Devin", "#5B21B6"),
    "devpass": ("DevPass", "DevPass", "#7C3AED"),
    "doubao": ("Doubao", "Doubao", "#1D6EF5"),
    "elevenlabs": ("ElevenLabs", "ElevenLabs", "#111111"),
    "exa": ("Exa", "Exa", "#6366F1"),
    "factory": ("Droid", "Droid", "#111827"),
    "fal": ("fal", "fal", "#111111"),
    "fireworks": ("Fireworks", "Fireworks", "#5019C5"),
    "flora": ("FLORA", "FLORA", "#6366F1"),
    "futureagi": ("Future AGI", "FutureAGI", "#6366F1"),
    "gemini": ("Gemini", "Gemini", "#4285F4"),
    "gitkraken": ("GitKraken AI", "GitKraken", "#2365D1"),
    "grok": ("Grok", "Grok", "#111111"),
    "groq": ("Groq", "Groq", "#F55036"),
    "helmcode": ("Helmcode", "Helmcode", "#2563EB"),
    "huggingface": ("Hugging Face", "HF", "#FFD21E"),
    "hyper": ("Charm Hyper", "Hyper", "#111111"),
    "ibmbob": ("IBM Bob", "Bob", "#0F62FE"),
    "jetbrains": ("JetBrains AI", "JB AI", "#000000"),
    "kilo": ("Kilo", "Kilo", "#7C3AED"),
    "kimi": ("Kimi Code", "Kimi", "#1F1F1F"),
    "kiro": ("Kiro", "Kiro", "#7B3FE4"),
    "langdock": ("Langdock", "Langdock", "#2563EB"),
    "linkup": ("Linkup", "Linkup", "#0EA5E9"),
    "litellm": ("LiteLLM", "LiteLLM", "#0EA5E9"),
    "lithosai": ("LithosAI", "Lithos", "#8B5CF6"),
    "llmman": ("llmman", "llmman", "#8B5CF6"),
    "llmproxy": ("LLM Proxy", "Proxy", "#64748B"),
    "longcat": ("LongCat", "LongCat", "#0F172A"),
    "manus": ("Manus", "Manus", "#FF5722"),
    "mimo": ("Xiaomi MiMo", "MiMo", "#FF6900"),
    "minimax": ("MiniMax", "MiniMax", "#F43F5E"),
    "mistral": ("Mistral", "Mistral", "#FA500F"),
    "moonshot": ("Moonshot", "Moonshot", "#0B5FFF"),
    "munito": ("Munito", "Munito", "#2563EB"),
    "muse": ("Muse Code", "Muse", "#111111"),
    "museai": ("Muse (muse.ai)", "muse.ai", "#7C3AED"),
    "neuralwatt": ("Neuralwatt", "Neuralwatt", "#14B8A6"),
    "notion": ("Notion AI", "Notion", "#111111"),
    "nous": ("Nous Portal", "Nous", "#6366F1"),
    "ollama": ("Ollama", "Ollama", "#111111"),
    "openai": ("OpenAI", "OpenAI", "#412991"),
    "opencode": ("OpenCode", "OpenCode", "#F59E0B"),
    "opencodego": ("OpenCode Go", "OC Go", "#EC4899"),
    "openrouter": ("OpenRouter", "OpenRouter", "#6467F2"),
    "parallel": ("Parallel", "Parallel", "#111111"),
    "perplexity": ("Perplexity", "Perplexity", "#20808D"),
    "pi": ("Pi", "Pi", "#111111"),
    "poe": ("Poe", "Poe", "#111111"),
    "qoder": ("Qoder", "Qoder", "#22C55E"),
    "qwencloud": ("Qwen Cloud", "Qwen", "#615CED"),
    "raycast": ("Raycast", "Raycast", "#FF6363"),
    "replicate": ("Replicate", "Replicate", "#111111"),
    "sailresearch": ("Sail Research", "Sail", "#2563EB"),
    "sakana": ("Sakana AI", "Sakana", "#0F766E"),
    "sofya": ("Sofya", "Sofya", "#EC4899"),
    "stepfun": ("StepFun", "StepFun", "#2563EB"),
    "sub2api": ("sub2api", "sub2api", "#64748B"),
    "synthetic": ("Synthetic", "Synthetic", "#6366F1"),
    "t3chat": ("T3 Chat", "T3", "#EC4899"),
    "tavily": ("Tavily", "Tavily", "#2563EB"),
    "tinyapi": ("TinyApi", "TinyApi", "#64748B"),
    "typesafe": ("TypeSafe", "TypeSafe", "#2563EB"),
    "v0": ("v0", "v0", "#000000"),
    "venice": ("Venice", "Venice", "#111111"),
    "vercel": ("Vercel AI Gateway", "Vercel", "#000000"),
    "vertexai": ("Vertex AI", "Vertex", "#4285F4"),
    "warp": ("Warp", "Warp", "#01A0C6"),
    "wayfinder": ("Wayfinder", "Wayfind", "#0891B2"),
    "windsurf": ("Windsurf", "Windsurf", "#0B9E8A"),
    "workbuddy": ("WorkBuddy", "WorkBuddy", "#F97316"),
    "xai": ("xAI", "xAI", "#111111"),
    "xapi": ("X API", "X API", "#111111"),
    "xkiro": ("xKiro", "xKiro", "#7B3FE4"),
    "zai": ("z.ai / GLM", "z.ai", "#2563EB"),
    "zed": ("Zed", "Zed", "#084CCF"),
    "zenmux": ("ZenMux", "ZenMux", "#7C3AED"),
    "zoommate": ("ZoomMate", "ZoomMate", "#2563EB"),
}

# Older CodexBar releases used dashed provider ids; map them onto the ids the
# current CLI reports so cached payloads still resolve.
ALIASES: dict[str, str] = {
    "azure-openai": "azureopenai",
    "abacusai": "abacus",
    "alibaba-coding-plan": "alibaba",
    "alibaba-token-plan": "alibabatokenplan",
    "qwen-cloud": "qwencloud",
    "groqcloud": "groq",
}


def canonical_id(provider_id: str) -> str:
    """Resolve a configuration id to the id used in the usage payload."""
    return ALIASES.get(provider_id, provider_id)


def display_name(provider_id: str) -> str:
    provider_id = canonical_id(provider_id)
    entry = PROVIDERS.get(provider_id)
    if entry:
        return entry[0]
    return provider_id.replace("-", " ").replace("_", " ").title()


def short_name(provider_id: str) -> str:
    provider_id = canonical_id(provider_id)
    entry = PROVIDERS.get(provider_id)
    if entry:
        return entry[1]
    return display_name(provider_id)


def accent_color(provider_id: str) -> str:
    provider_id = canonical_id(provider_id)
    entry = PROVIDERS.get(provider_id)
    if entry:
        return entry[2]
    return "#6366F1"


def all_provider_ids() -> list[str]:
    return list(PROVIDERS.keys())
