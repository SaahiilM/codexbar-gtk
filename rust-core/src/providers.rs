//! Provider labels and accent colors ported from `codexbar_gtk/providers.py`.
//!
//! This catalog is authoritative in Rust opt-in mode; the Python copy remains
//! the default-mode reference until the native application cutover.

use crate::unicode_case;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProviderMetadata {
    pub id: &'static str,
    pub name: &'static str,
    pub short_name: &'static str,
    pub accent_color: &'static str,
}

/// Additional checked-in descriptor facts used to pin upstream compatibility
/// without putting provider fetching or configuration policy in this catalog.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProviderDescriptorDetails {
    pub id: &'static str,
    pub session_label: &'static str,
    pub weekly_label: &'static str,
    pub dashboard_url: &'static str,
    pub status_page_url: Option<&'static str>,
    pub balance_only: bool,
    pub history_available: bool,
    pub burndown_widget_selectable: bool,
    pub api_detail: bool,
    pub availability: Option<&'static str>,
    pub progress_color_style: Option<&'static str>,
    pub menu_bar_metrics: Option<&'static [&'static str]>,
}

/// Details newly verified against the v0.84.0 upstream provider descriptors.
/// Keep this list separate from display metadata because the native app renders
/// the CLI's generic payload and does not reimplement provider behavior.
pub const PROVIDER_DESCRIPTOR_DETAILS: &[ProviderDescriptorDetails] = &[
    ProviderDescriptorDetails {
        id: "opendesign",
        session_label: "Session",
        weekly_label: "Weekly",
        dashboard_url: "https://open-design.ai/cloud/dashboard",
        status_page_url: None,
        balance_only: false,
        history_available: false,
        burndown_widget_selectable: false,
        api_detail: false,
        availability: None,
        progress_color_style: Some("label"),
        menu_bar_metrics: Some(&["automatic", "primary", "secondary"]),
    },
    ProviderDescriptorDetails {
        id: "siliconflow",
        session_label: "Balance",
        weekly_label: "Balance",
        dashboard_url: "https://cloud.siliconflow.cn",
        status_page_url: None,
        balance_only: true,
        history_available: false,
        burndown_widget_selectable: false,
        api_detail: true,
        availability: Some("configuredKey"),
        progress_color_style: None,
        menu_bar_metrics: None,
    },
    ProviderDescriptorDetails {
        id: "tripo",
        session_label: "Credits",
        weekly_label: "Credits",
        dashboard_url: "https://developers.tripo3d.ai/en/billing",
        status_page_url: Some("https://tripo3d.statuspage.io"),
        balance_only: true,
        history_available: false,
        burndown_widget_selectable: false,
        api_detail: true,
        availability: Some("configuredKey"),
        progress_color_style: None,
        menu_bar_metrics: None,
    },
];

pub const FALLBACK_ACCENT_COLOR: &str = "#6366F1";

/// Current provider ids and their user-facing metadata, sorted by id.
pub const PROVIDERS: &[ProviderMetadata] = &[
    ProviderMetadata {
        id: "abacus",
        name: "Abacus AI",
        short_name: "Abacus",
        accent_color: "#2563EB",
    },
    ProviderMetadata {
        id: "abliteration",
        name: "abliteration.ai",
        short_name: "abliteration.ai",
        accent_color: "#1B1B1B",
    },
    ProviderMetadata {
        id: "aerostack",
        name: "Aerostack",
        short_name: "Aerostack",
        accent_color: "#0EA5E9",
    },
    ProviderMetadata {
        id: "aiand",
        name: "ai&",
        short_name: "ai&",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "aixy",
        name: "Aixy",
        short_name: "Aixy",
        accent_color: "#0EA5E9",
    },
    ProviderMetadata {
        id: "alibaba",
        name: "Alibaba Coding Plan",
        short_name: "Alibaba",
        accent_color: "#FF6A00",
    },
    ProviderMetadata {
        id: "alibabatokenplan",
        name: "Alibaba Token Plan",
        short_name: "Ali TP",
        accent_color: "#FF6A00",
    },
    ProviderMetadata {
        id: "amp",
        name: "Amp",
        short_name: "Amp",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "antigravity",
        name: "Antigravity",
        short_name: "Antigrav",
        accent_color: "#7C3AED",
    },
    ProviderMetadata {
        id: "atlascloud",
        name: "Atlas Cloud",
        short_name: "Atlas",
        accent_color: "#0EA5E9",
    },
    ProviderMetadata {
        id: "augment",
        name: "Augment",
        short_name: "Augment",
        accent_color: "#F43F5E",
    },
    ProviderMetadata {
        id: "azureopenai",
        name: "Azure Open AI",
        short_name: "Azure",
        accent_color: "#0078D4",
    },
    ProviderMetadata {
        id: "bedrock",
        name: "AWS Bedrock",
        short_name: "Bedrock",
        accent_color: "#FF9900",
    },
    ProviderMetadata {
        id: "bifrost",
        name: "Bifrost",
        short_name: "Bifrost",
        accent_color: "#8B5CF6",
    },
    ProviderMetadata {
        id: "chatbox",
        name: "Chatbox AI",
        short_name: "Chatbox AI",
        accent_color: "#228BE6",
    },
    ProviderMetadata {
        id: "chutes",
        name: "Chutes",
        short_name: "Chutes",
        accent_color: "#7C3AED",
    },
    ProviderMetadata {
        id: "claude",
        name: "Claude",
        short_name: "Claude",
        accent_color: "#D97757",
    },
    ProviderMetadata {
        id: "claudeplatform",
        name: "Claude Platform",
        short_name: "Claude Plat",
        accent_color: "#D97757",
    },
    ProviderMetadata {
        id: "clawrouter",
        name: "ClawRouter",
        short_name: "Claw",
        accent_color: "#E11D48",
    },
    ProviderMetadata {
        id: "clinepass",
        name: "ClinePass",
        short_name: "Cline",
        accent_color: "#8B5CF6",
    },
    ProviderMetadata {
        id: "codebuff",
        name: "Codebuff",
        short_name: "Codebuff",
        accent_color: "#7C3AED",
    },
    ProviderMetadata {
        id: "coderabbit",
        name: "CodeRabbit",
        short_name: "CodeRabbit",
        accent_color: "#F97316",
    },
    ProviderMetadata {
        id: "codex",
        name: "Codex",
        short_name: "Codex",
        accent_color: "#10A37F",
    },
    ProviderMetadata {
        id: "commandcode",
        name: "Command Code",
        short_name: "Command",
        accent_color: "#F97316",
    },
    ProviderMetadata {
        id: "copilot",
        name: "Copilot",
        short_name: "Copilot",
        accent_color: "#24292F",
    },
    ProviderMetadata {
        id: "cosmic",
        name: "Cosmic AI",
        short_name: "Cosmic",
        accent_color: "#7C3AED",
    },
    ProviderMetadata {
        id: "cursor",
        name: "Cursor",
        short_name: "Cursor",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "deepgram",
        name: "Deepgram",
        short_name: "Deepgram",
        accent_color: "#0F172A",
    },
    ProviderMetadata {
        id: "deepinfra",
        name: "DeepInfra",
        short_name: "DeepInfra",
        accent_color: "#6366F1",
    },
    ProviderMetadata {
        id: "deepseek",
        name: "DeepSeek",
        short_name: "DeepSeek",
        accent_color: "#4D6BFE",
    },
    ProviderMetadata {
        id: "devin",
        name: "Devin",
        short_name: "Devin",
        accent_color: "#5B21B6",
    },
    ProviderMetadata {
        id: "devpass",
        name: "DevPass",
        short_name: "DevPass",
        accent_color: "#7C3AED",
    },
    ProviderMetadata {
        id: "doubao",
        name: "Doubao",
        short_name: "Doubao",
        accent_color: "#1D6EF5",
    },
    ProviderMetadata {
        id: "elevenlabs",
        name: "ElevenLabs",
        short_name: "ElevenLabs",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "exa",
        name: "Exa",
        short_name: "Exa",
        accent_color: "#6366F1",
    },
    ProviderMetadata {
        id: "factory",
        name: "Droid",
        short_name: "Droid",
        accent_color: "#111827",
    },
    ProviderMetadata {
        id: "fal",
        name: "fal",
        short_name: "fal",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "fireworks",
        name: "Fireworks",
        short_name: "Fireworks",
        accent_color: "#5019C5",
    },
    ProviderMetadata {
        id: "flora",
        name: "FLORA",
        short_name: "FLORA",
        accent_color: "#6366F1",
    },
    ProviderMetadata {
        id: "futureagi",
        name: "Future AGI",
        short_name: "FutureAGI",
        accent_color: "#6366F1",
    },
    ProviderMetadata {
        id: "gemini",
        name: "Gemini",
        short_name: "Gemini",
        accent_color: "#4285F4",
    },
    ProviderMetadata {
        id: "gitkraken",
        name: "GitKraken AI",
        short_name: "GitKraken",
        accent_color: "#2365D1",
    },
    ProviderMetadata {
        id: "grok",
        name: "Grok",
        short_name: "Grok",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "groq",
        name: "Groq",
        short_name: "Groq",
        accent_color: "#F55036",
    },
    ProviderMetadata {
        id: "helmcode",
        name: "Helmcode",
        short_name: "Helmcode",
        accent_color: "#2563EB",
    },
    ProviderMetadata {
        id: "huggingface",
        name: "Hugging Face",
        short_name: "HF",
        accent_color: "#FFD21E",
    },
    ProviderMetadata {
        id: "hyper",
        name: "Charm Hyper",
        short_name: "Hyper",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "ibmbob",
        name: "IBM Bob",
        short_name: "Bob",
        accent_color: "#0F62FE",
    },
    ProviderMetadata {
        id: "jetbrains",
        name: "JetBrains AI",
        short_name: "JB AI",
        accent_color: "#000000",
    },
    ProviderMetadata {
        id: "kilo",
        name: "Kilo",
        short_name: "Kilo",
        accent_color: "#7C3AED",
    },
    ProviderMetadata {
        id: "kimi",
        name: "Kimi Code",
        short_name: "Kimi",
        accent_color: "#1F1F1F",
    },
    ProviderMetadata {
        id: "kiro",
        name: "Kiro",
        short_name: "Kiro",
        accent_color: "#7B3FE4",
    },
    ProviderMetadata {
        id: "langdock",
        name: "Langdock",
        short_name: "Langdock",
        accent_color: "#2563EB",
    },
    ProviderMetadata {
        id: "linkup",
        name: "Linkup",
        short_name: "Linkup",
        accent_color: "#0EA5E9",
    },
    ProviderMetadata {
        id: "litellm",
        name: "LiteLLM",
        short_name: "LiteLLM",
        accent_color: "#0EA5E9",
    },
    ProviderMetadata {
        id: "lithosai",
        name: "LithosAI",
        short_name: "Lithos",
        accent_color: "#8B5CF6",
    },
    ProviderMetadata {
        id: "llmman",
        name: "llmman",
        short_name: "llmman",
        accent_color: "#8B5CF6",
    },
    ProviderMetadata {
        id: "llmproxy",
        name: "LLM Proxy",
        short_name: "Proxy",
        accent_color: "#64748B",
    },
    ProviderMetadata {
        id: "longcat",
        name: "LongCat",
        short_name: "LongCat",
        accent_color: "#0F172A",
    },
    ProviderMetadata {
        id: "manus",
        name: "Manus",
        short_name: "Manus",
        accent_color: "#FF5722",
    },
    ProviderMetadata {
        id: "mimo",
        name: "Xiaomi MiMo",
        short_name: "MiMo",
        accent_color: "#FF6900",
    },
    ProviderMetadata {
        id: "minimax",
        name: "MiniMax",
        short_name: "MiniMax",
        accent_color: "#F43F5E",
    },
    ProviderMetadata {
        id: "mistral",
        name: "Mistral",
        short_name: "Mistral",
        accent_color: "#FA500F",
    },
    ProviderMetadata {
        id: "moonshot",
        name: "Moonshot",
        short_name: "Moonshot",
        accent_color: "#0B5FFF",
    },
    ProviderMetadata {
        id: "munito",
        name: "Munito",
        short_name: "Munito",
        accent_color: "#2563EB",
    },
    ProviderMetadata {
        id: "muse",
        name: "Muse Code",
        short_name: "Muse",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "museai",
        name: "Muse (muse.ai)",
        short_name: "muse.ai",
        accent_color: "#7C3AED",
    },
    ProviderMetadata {
        id: "neuralwatt",
        name: "Neuralwatt",
        short_name: "Neuralwatt",
        accent_color: "#14B8A6",
    },
    ProviderMetadata {
        id: "notion",
        name: "Notion AI",
        short_name: "Notion",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "nous",
        name: "Nous Portal",
        short_name: "Nous",
        accent_color: "#6366F1",
    },
    ProviderMetadata {
        id: "ollama",
        name: "Ollama",
        short_name: "Ollama",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "openai",
        name: "OpenAI",
        short_name: "OpenAI",
        accent_color: "#412991",
    },
    ProviderMetadata {
        id: "opencode",
        name: "OpenCode",
        short_name: "OpenCode",
        accent_color: "#F59E0B",
    },
    ProviderMetadata {
        id: "opencodego",
        name: "OpenCode Go",
        short_name: "OC Go",
        accent_color: "#EC4899",
    },
    ProviderMetadata {
        id: "opendesign",
        name: "OpenDesign",
        short_name: "OpenDesign",
        accent_color: "#202020",
    },
    ProviderMetadata {
        id: "openrouter",
        name: "OpenRouter",
        short_name: "OpenRouter",
        accent_color: "#6467F2",
    },
    ProviderMetadata {
        id: "parallel",
        name: "Parallel",
        short_name: "Parallel",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "perplexity",
        name: "Perplexity",
        short_name: "Perplexity",
        accent_color: "#20808D",
    },
    ProviderMetadata {
        id: "pi",
        name: "Pi",
        short_name: "Pi",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "poe",
        name: "Poe",
        short_name: "Poe",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "qoder",
        name: "Qoder",
        short_name: "Qoder",
        accent_color: "#22C55E",
    },
    ProviderMetadata {
        id: "qwencloud",
        name: "Qwen Cloud",
        short_name: "Qwen",
        accent_color: "#615CED",
    },
    ProviderMetadata {
        id: "raycast",
        name: "Raycast",
        short_name: "Raycast",
        accent_color: "#FF6363",
    },
    ProviderMetadata {
        id: "replicate",
        name: "Replicate",
        short_name: "Replicate",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "sailresearch",
        name: "Sail Research",
        short_name: "Sail",
        accent_color: "#2563EB",
    },
    ProviderMetadata {
        id: "sakana",
        name: "Sakana AI",
        short_name: "Sakana",
        accent_color: "#0F766E",
    },
    ProviderMetadata {
        id: "siliconflow",
        name: "SiliconFlow",
        short_name: "SiliconFlow",
        accent_color: "#6E29F5",
    },
    ProviderMetadata {
        id: "sofya",
        name: "Sofya",
        short_name: "Sofya",
        accent_color: "#EC4899",
    },
    ProviderMetadata {
        id: "soniox",
        name: "Soniox",
        short_name: "Soniox",
        accent_color: "#253772",
    },
    ProviderMetadata {
        id: "stepfun",
        name: "StepFun",
        short_name: "StepFun",
        accent_color: "#2563EB",
    },
    ProviderMetadata {
        id: "sub2api",
        name: "sub2api",
        short_name: "sub2api",
        accent_color: "#64748B",
    },
    ProviderMetadata {
        id: "synthetic",
        name: "Synthetic",
        short_name: "Synthetic",
        accent_color: "#6366F1",
    },
    ProviderMetadata {
        id: "t3chat",
        name: "T3 Chat",
        short_name: "T3",
        accent_color: "#EC4899",
    },
    ProviderMetadata {
        id: "tavily",
        name: "Tavily",
        short_name: "Tavily",
        accent_color: "#2563EB",
    },
    ProviderMetadata {
        id: "tinyapi",
        name: "TinyApi",
        short_name: "TinyApi",
        accent_color: "#64748B",
    },
    ProviderMetadata {
        id: "traecn",
        name: "Trae CN",
        short_name: "Trae CN",
        accent_color: "#4D7CFE",
    },
    ProviderMetadata {
        id: "tripo",
        name: "Tripo",
        short_name: "Tripo",
        accent_color: "#F8CF00",
    },
    ProviderMetadata {
        id: "typesafe",
        name: "TypeSafe",
        short_name: "TypeSafe",
        accent_color: "#2563EB",
    },
    ProviderMetadata {
        id: "v0",
        name: "v0",
        short_name: "v0",
        accent_color: "#000000",
    },
    ProviderMetadata {
        id: "venice",
        name: "Venice",
        short_name: "Venice",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "vercel",
        name: "Vercel AI Gateway",
        short_name: "Vercel",
        accent_color: "#000000",
    },
    ProviderMetadata {
        id: "vertexai",
        name: "Vertex AI",
        short_name: "Vertex",
        accent_color: "#4285F4",
    },
    ProviderMetadata {
        id: "warp",
        name: "Warp",
        short_name: "Warp",
        accent_color: "#01A0C6",
    },
    ProviderMetadata {
        id: "wayfinder",
        name: "Wayfinder",
        short_name: "Wayfind",
        accent_color: "#0891B2",
    },
    ProviderMetadata {
        id: "windsurf",
        name: "Windsurf",
        short_name: "Windsurf",
        accent_color: "#0B9E8A",
    },
    ProviderMetadata {
        id: "workbuddy",
        name: "WorkBuddy",
        short_name: "WorkBuddy",
        accent_color: "#F97316",
    },
    ProviderMetadata {
        id: "xai",
        name: "xAI",
        short_name: "xAI",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "xapi",
        name: "X API",
        short_name: "X API",
        accent_color: "#111111",
    },
    ProviderMetadata {
        id: "xkiro",
        name: "xKiro",
        short_name: "xKiro",
        accent_color: "#7B3FE4",
    },
    ProviderMetadata {
        id: "zai",
        name: "z.ai / GLM",
        short_name: "z.ai",
        accent_color: "#2563EB",
    },
    ProviderMetadata {
        id: "zed",
        name: "Zed",
        short_name: "Zed",
        accent_color: "#084CCF",
    },
    ProviderMetadata {
        id: "zenmux",
        name: "ZenMux",
        short_name: "ZenMux",
        accent_color: "#7C3AED",
    },
    ProviderMetadata {
        id: "zoommate",
        name: "ZoomMate",
        short_name: "ZoomMate",
        accent_color: "#2563EB",
    },
];

const ALIASES: [(&str, &str); 7] = [
    ("azure-openai", "azureopenai"),
    ("abacusai", "abacus"),
    ("alibaba-coding-plan", "alibaba"),
    ("alibaba-token-plan", "alibabatokenplan"),
    ("qwen-cloud", "qwencloud"),
    ("groqcloud", "groq"),
    ("open-design", "opendesign"),
];

/// Resolve a configuration ID to the current ID used in usage payloads.
pub fn canonical_id(provider_id: &str) -> &str {
    ALIASES
        .iter()
        .find_map(|(alias, canonical)| (*alias == provider_id).then_some(*canonical))
        .unwrap_or(provider_id)
}

pub fn provider(provider_id: &str) -> Option<&'static ProviderMetadata> {
    let provider_id = canonical_id(provider_id);
    PROVIDERS
        .binary_search_by(|entry| entry.id.cmp(provider_id))
        .ok()
        .map(|index| &PROVIDERS[index])
}

pub fn descriptor_details(provider_id: &str) -> Option<&'static ProviderDescriptorDetails> {
    let provider_id = canonical_id(provider_id);
    PROVIDER_DESCRIPTOR_DETAILS
        .iter()
        .find(|details| details.id == provider_id)
}

pub fn display_name(provider_id: &str) -> String {
    provider(provider_id)
        .map(|entry| entry.name.to_owned())
        .unwrap_or_else(|| title_fallback(canonical_id(provider_id)))
}

pub fn short_name(provider_id: &str) -> String {
    provider(provider_id)
        .map(|entry| entry.short_name.to_owned())
        .unwrap_or_else(|| display_name(provider_id))
}

pub fn accent_color(provider_id: &str) -> &'static str {
    provider(provider_id)
        .map(|entry| entry.accent_color)
        .unwrap_or(FALLBACK_ACCENT_COLOR)
}

pub fn all_provider_ids() -> Vec<&'static str> {
    PROVIDERS.iter().map(|entry| entry.id).collect()
}

fn title_fallback(provider_id: &str) -> String {
    let normalized = provider_id.replace(['-', '_'], " ");
    let characters: Vec<char> = normalized.chars().collect();
    let mut capitalize = true;
    let mut previous_cased = false;
    let mut title = String::with_capacity(normalized.len());
    for (index, character) in characters.iter().copied().enumerate() {
        if unicode_case::is_cased(character) {
            if capitalize {
                title.push_str(&python_titlecase(character));
            } else if character == 'Σ'
                && previous_cased
                && !characters[index + 1..]
                    .iter()
                    .copied()
                    .find(|next| !unicode_case::is_case_ignorable(*next))
                    .is_some_and(unicode_case::is_cased)
            {
                // Python applies Unicode's context-sensitive final-sigma
                // mapping while lowercasing the rest of a title-cased word.
                title.push('ς');
            } else {
                title.push_str(&unicode_case::lowercase(character));
            }
            capitalize = false;
            previous_cased = true;
        } else {
            title.push(character);
            capitalize = true;
            if !unicode_case::is_case_ignorable(character) {
                previous_cased = false;
            }
        }
    }
    title
}

fn python_titlecase(character: char) -> String {
    unicode_case::titlecase(character)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn catalog_is_sorted_and_all_ids_resolve() {
        assert_eq!(PROVIDERS.len(), 113);
        assert!(PROVIDERS.windows(2).all(|pair| pair[0].id < pair[1].id));
        let ids = all_provider_ids();
        assert_eq!(ids.len(), PROVIDERS.len());
        for id in ids {
            assert!(provider(id).is_some(), "missing provider metadata for {id}");
            assert!(accent_color(id).starts_with('#'));
        }
    }

    #[test]
    fn aliases_resolve_to_canonical_metadata() {
        let cases = [
            ("azure-openai", "azureopenai"),
            ("abacusai", "abacus"),
            ("alibaba-coding-plan", "alibaba"),
            ("alibaba-token-plan", "alibabatokenplan"),
            ("qwen-cloud", "qwencloud"),
            ("groqcloud", "groq"),
            ("open-design", "opendesign"),
        ];
        for (alias, expected) in cases {
            assert_eq!(canonical_id(alias), expected);
            assert_eq!(provider(alias).unwrap().id, expected);
        }
    }

    #[test]
    fn v084_provider_descriptor_details_match_the_tagged_contract() {
        let opendesign = descriptor_details("open-design").unwrap();
        assert_eq!(opendesign.id, "opendesign");
        assert_eq!(
            opendesign.dashboard_url,
            "https://open-design.ai/cloud/dashboard"
        );
        assert_eq!(opendesign.status_page_url, None);
        assert_eq!(opendesign.session_label, "Session");
        assert_eq!(opendesign.weekly_label, "Weekly");
        assert!(!opendesign.balance_only);
        assert!(!opendesign.history_available);
        assert!(!opendesign.burndown_widget_selectable);
        assert!(!opendesign.api_detail);
        assert_eq!(
            opendesign.menu_bar_metrics,
            Some(["automatic", "primary", "secondary"].as_slice())
        );
        assert_eq!(opendesign.availability, None);
        assert_eq!(opendesign.progress_color_style, Some("label"));

        let siliconflow = descriptor_details("siliconflow").unwrap();
        assert_eq!(siliconflow.session_label, "Balance");
        assert_eq!(siliconflow.weekly_label, "Balance");
        assert_eq!(siliconflow.dashboard_url, "https://cloud.siliconflow.cn");
        assert_eq!(siliconflow.availability, Some("configuredKey"));
        assert!(siliconflow.balance_only && siliconflow.api_detail);
        assert!(!siliconflow.history_available && !siliconflow.burndown_widget_selectable);

        let tripo = descriptor_details("tripo").unwrap();
        assert_eq!(tripo.session_label, "Credits");
        assert_eq!(tripo.weekly_label, "Credits");
        assert_eq!(
            tripo.dashboard_url,
            "https://developers.tripo3d.ai/en/billing"
        );
        assert_eq!(tripo.status_page_url, Some("https://tripo3d.statuspage.io"));
        assert_eq!(tripo.availability, Some("configuredKey"));
        assert!(tripo.balance_only && tripo.api_detail);
        assert!(!tripo.history_available && !tripo.burndown_widget_selectable);
        assert!(descriptor_details("codex").is_none());
    }

    #[test]
    fn returns_expected_names_colors_and_unknown_fallbacks() {
        assert_eq!(display_name("codex"), "Codex");
        assert_eq!(short_name("azure-openai"), "Azure");
        assert_eq!(accent_color("claude"), "#D97757");
        assert_eq!(display_name("unknown-provider_id"), "Unknown Provider Id");
        assert_eq!(short_name("unknown-provider_id"), "Unknown Provider Id");
        assert_eq!(accent_color("unknown-provider_id"), FALLBACK_ACCENT_COLOR);
        assert_eq!(canonical_id("not-known"), "not-known");
    }

    #[test]
    fn unicode_unknown_provider_titles_use_titlecase_expansions() {
        assert_eq!(display_name("ß-provider"), "Ss Provider");
        assert_eq!(display_name("ǆ-provider"), "ǅ Provider");
        assert_eq!(display_name("λ-provider"), "Λ Provider");
        assert_eq!(display_name("provider-猫"), "Provider 猫");
        assert_eq!(display_name("ΟΣ-provider"), "Ος Provider");
        assert_eq!(display_name("ΟΣΑ-provider"), "Οσα Provider");
        assert_eq!(display_name("aΣ\u{0301}a"), "Aσ\u{0301}A");
        assert_eq!(display_name("ΟΣ\u{0301}Α"), "Οσ\u{0301}Α");
        assert_eq!(display_name("AΣ.B"), "Aσ.B");
        assert_eq!(display_name("fooʼbar"), "FooʼBar");
    }
}
