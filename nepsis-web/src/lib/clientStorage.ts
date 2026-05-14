export const OPENAI_KEY_STORAGE_KEY = "nepsis_openai_key";
export const LLM_CONNECTED_NOTICE_KEY = "nepsis_llm_connected_notice";

export function getStoredOpenAiKey(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const value = window.localStorage.getItem(OPENAI_KEY_STORAGE_KEY)?.trim() ?? "";
    return value.length > 0 ? value : null;
  } catch {
    return null;
  }
}

export function hasStoredOpenAiKey(): boolean {
  return getStoredOpenAiKey() !== null;
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
