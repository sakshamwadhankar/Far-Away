export interface ParsedSnippet {
  provider: string;
  model: string;
  baseUrl?: string;
  apiKey?: string;
  temperature?: number;
  maxTokens?: number;
  endpointRef: string;
}

/**
 * Parse Python requests code, cURL commands, or JSON payloads into Komvos endpoint configurations.
 */
export function parseApiSnippet(snippet: string): ParsedSnippet | null {
  if (!snippet || typeof snippet !== 'string') return null;
  const raw = snippet.trim();
  if (!raw) return null;

  let url = '';
  let model = '';
  let apiKey = '';
  let temperature: number | undefined;
  let maxTokens: number | undefined;

  // 1. Extract URL (Python variable, requests/fetch call, or cURL target)
  const urlMatch =
    raw.match(/(?:invoke_url|base_url|url|endpoint)\s*=\s*["']([^"']+)["']/i) ||
    raw.match(/(?:requests\.(?:post|get)|fetch|axios\.(?:post|get))\s*\(\s*["']([^"']+)["']/i) ||
    raw.match(/curl(?:\.exe)?\s+(?:-[A-Za-z]+\s+)*["']?(https?:\/\/[^\s"']+)["']?/i) ||
    raw.match(/https?:\/\/[^\s"']+/i);

  if (urlMatch) {
    url = urlMatch[1] || urlMatch[0];
  }

  // 2. Extract Model Name
  const modelMatch =
    raw.match(/["']model["']\s*:\s*["']([^"']+)["']/i) ||
    raw.match(/model\s*=\s*["']([^"']+)["']/i) ||
    raw.match(/--model\s+["']?([^"'\s]+)["']?/i);

  if (modelMatch) {
    model = modelMatch[1].trim();
  }

  // 3. Extract API Key if present in Authorization header
  const authMatch =
    raw.match(/Bearer\s+([A-Za-z0-9_\-\.]{15,})/i) ||
    raw.match(/(?:api_key|apiKey)\s*[:=]\s*["']([A-Za-z0-9_\-\.]{15,})["']/i);

  if (authMatch) {
    const candidate = authMatch[1];
    // Filter out common placeholder names
    if (!candidate.startsWith('$') && !candidate.includes('YOUR_') && !candidate.includes('API_KEY')) {
      apiKey = candidate;
    }
  }

  // 4. Extract Temperature
  const tempMatch = raw.match(/["']?temperature["']?\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)/i);
  if (tempMatch) {
    const t = parseFloat(tempMatch[1]);
    if (!isNaN(t)) temperature = t;
  }

  // 5. Extract Max Tokens
  const tokensMatch = raw.match(/["']?max_tokens["']?\s*[:=]\s*([0-9]+)/i);
  if (tokensMatch) {
    const tok = parseInt(tokensMatch[1], 10);
    if (!isNaN(tok)) maxTokens = tok;
  }

  // 6. Detect Provider from URL, Model name, or snippet text
  let provider = 'openai_compatible';
  const lowerUrl = url.toLowerCase();
  const lowerSnippet = raw.toLowerCase();
  const lowerModel = model.toLowerCase();

  if (lowerUrl.includes('integrate.api.nvidia.com') || lowerModel.startsWith('nvidia/') || lowerSnippet.includes('nvidia_api_key')) {
    provider = 'nvidia';
  } else if (lowerUrl.includes('api.openai.com') || lowerModel.startsWith('gpt-') || lowerModel.startsWith('o1-') || lowerModel.startsWith('o3-')) {
    provider = 'openai';
  } else if (lowerUrl.includes('api.anthropic.com') || lowerModel.startsWith('claude-')) {
    provider = 'anthropic';
  } else if (lowerUrl.includes('generativelanguage.googleapis.com') || lowerModel.startsWith('gemini-')) {
    provider = 'google';
  } else if (lowerUrl.includes('api.groq.com')) {
    provider = 'groq';
  } else if (lowerUrl.includes('openrouter.ai')) {
    provider = 'openrouter';
  } else if (lowerUrl.includes('open.bigmodel.cn') || lowerModel.startsWith('glm-')) {
    provider = 'zhipu';
  } else if (lowerUrl.includes('11434') || lowerSnippet.includes('ollama')) {
    provider = 'ollama';
  }

  if (!model && provider === 'nvidia') {
    model = 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning';
  }

  if (!model) {
    return null;
  }

  const endpointRef = `${provider}:${model}`;

  return {
    provider,
    model,
    baseUrl: url || undefined,
    apiKey: apiKey || undefined,
    temperature,
    maxTokens,
    endpointRef,
  };
}
