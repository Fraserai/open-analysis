const CREATORS: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  google: "Google",
  xiaomi: "Xiaomi",
  xai: "xAI",
  deepseek: "DeepSeek",
  zai: "Z.ai",
  alibaba: "Alibaba",
  meta: "Meta",
  mistral: "Mistral",
  minimax: "MiniMax",
  moonshotai: "Moonshot",
  kimi: "Moonshot",
  stepfun: "StepFun",
  nvidia: "NVIDIA",
  "ibm-granite": "IBM",
  ibm: "IBM",
  inclusionai: "inclusionAI",
  reflection: "Reflection",
  upstage: "Upstage",
};

const PROVIDERS: Record<string, string> = {
  bedrock: "AWS Bedrock",
  vertex: "Google Vertex",
  vertexAnthropic: "Google Vertex",
  azure: "Microsoft Azure",
  anthropic: "Anthropic",
  openai: "OpenAI",
};

const REGIONS: Record<string, string> = {
  "ap-southeast-2": "Sydney",
  "ap-southeast-4": "Melbourne",
  australiaeast: "Sydney",
  australiasoutheast: "Melbourne",
  "australia-southeast1": "Sydney",
  "australia-southeast2": "Melbourne",
  AU: "Australia",
  au: "Australia",
};

export function deployment(provider: string, region: string): string {
  return `${PROVIDERS[provider] ?? provider} (${REGIONS[region] ?? region})`;
}

export function creator(slug: string): string {
  return CREATORS[slug] ?? slug.charAt(0).toUpperCase() + slug.slice(1);
}

export function aud(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 100) return `A$${value.toFixed(0)}`;
  if (value >= 0.1) return `A$${value.toFixed(2)}`;
  return `A$${value.toFixed(3)}`;
}

export function multiple(value: number): string {
  return value >= 10 ? `${Math.round(value)}×` : `${value.toFixed(1)}×`;
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function longDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-AU", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function shortDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-AU", { day: "numeric", month: "short" });
}
