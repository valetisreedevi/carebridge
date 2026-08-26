/** Web Speech API wrappers.
 *
 *  Speech recognition is Chrome/Edge only, so every caller must still work
 *  when `speechSupported` is false - the big buttons are the fallback.
 */

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: { results: { transcript: string }[][] }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

type SpeechWindow = Window & {
  SpeechRecognition?: new () => SpeechRecognitionLike;
  webkitSpeechRecognition?: new () => SpeechRecognitionLike;
};

function recognitionClass() {
  const w = window as SpeechWindow;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
}

export const speechSupported = Boolean(recognitionClass());

/** Why listening stopped, as an i18n key rather than a sentence: the words the
 *  elder reads have to be in their own language, and this file does not know
 *  what that is. */
export type ListenFailure = "cannotListen" | "micBlocked" | "didNotCatch";

export function listen(
  lang: string,
  onResult: (transcript: string) => void,
  onError: (failure: ListenFailure) => void,
): () => void {
  const Recognition = recognitionClass();
  if (!Recognition) {
    onError("cannotListen");
    return () => {};
  }

  const recognition = new Recognition();
  recognition.lang = lang;
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    if (transcript) onResult(transcript);
  };

  recognition.onerror = (event) => {
    onError(event.error === "not-allowed" ? "micBlocked" : "didNotCatch");
  };

  recognition.start();
  return () => recognition.abort();
}

/** Speaks slowly, which matters more than it sounds for this audience. */
export function speak(text: string, lang: string): void {
  if (!("speechSynthesis" in window) || !text) return;

  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  utterance.rate = 0.9;
  utterance.volume = 1;
  window.speechSynthesis.speak(utterance);
}

export function stopSpeaking(): void {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

const LANGUAGE_TAGS: Record<string, string> = {
  en: "en-IN",
  te: "te-IN",
  hi: "hi-IN",
  ta: "ta-IN",
  kn: "kn-IN",
};

export function speechTag(preferredLanguage: string): string {
  return LANGUAGE_TAGS[preferredLanguage] ?? "en-IN";
}
