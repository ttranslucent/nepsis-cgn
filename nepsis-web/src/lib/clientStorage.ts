const LEGACY_BROWSER_PROVIDER_KEY = "nepsis_openai_key";
export const LLM_CONNECTED_NOTICE_KEY = "nepsis_llm_connected_notice";

export function clearLegacyOpenAiKey(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    const hadKey = window.localStorage.getItem(LEGACY_BROWSER_PROVIDER_KEY) !== null;
    window.localStorage.removeItem(LEGACY_BROWSER_PROVIDER_KEY);
    window.localStorage.removeItem(LLM_CONNECTED_NOTICE_KEY);
    return hadKey;
  } catch {
    return false;
  }
}

export function consumeConnectedNotice(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    const hasNotice = window.localStorage.getItem(LLM_CONNECTED_NOTICE_KEY) === "1";
    if (hasNotice) {
      window.localStorage.removeItem(LLM_CONNECTED_NOTICE_KEY);
    }
    return hasNotice;
  } catch {
    return false;
  }
}
