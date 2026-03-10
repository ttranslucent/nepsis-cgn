export const OPENAI_KEY_STORAGE_KEY = "nepsis_openai_key";
export const LLM_CONNECTED_NOTICE_KEY = "nepsis_llm_connected_notice";

export function hasStoredOpenAiKey(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    const value = window.localStorage.getItem(OPENAI_KEY_STORAGE_KEY);
    return Boolean(value && value.trim().length > 0);
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
