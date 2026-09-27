// Speaking replies and hearing the user, with the voices built into the phone.
import { state } from "./state.js";
import { el, notify } from "./ui.js";

export function speak(text, { force = false, onEnd } = {}) {
  if ((!state.settings.speak && !force) || !("speechSynthesis" in window)) return false;
  try {
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(String(text).replace(/[*_#`>]/g, "").slice(0, 1500));
    const english = speechSynthesis.getVoices().filter((voice) => /^en/.test(voice.lang));
    const british = english.find((voice) => /GB/.test(voice.lang) && /Daniel|Arthur|male/i.test(voice.name)) || english.find((voice) => /GB/.test(voice.lang));
    if (british) utterance.voice = british;
    if (onEnd) utterance.onend = onEnd;
    speechSynthesis.speak(utterance);
    return true;
  } catch {
    return false;
  }
}

export const canListen = () => Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);

/** A 🎤 button that fills `input` with what it hears, then calls submit. */
export function micButton(input, submit, { label = "Speak" } = {}) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) return null;
  let listening = null;
  const button = el("button", { type: "button", class: "mic", text: "🎤", "aria-label": label });
  button.addEventListener("click", () => {
    if (listening) {
      listening.stop();
      return;
    }
    const recognition = new Recognition();
    recognition.lang = navigator.language || "en-US";
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      input.value = Array.from(event.results)
        .map((result) => result[0].transcript)
        .join(" ");
    };
    recognition.onend = () => {
      listening = null;
      button.textContent = "🎤";
      button.classList.remove("on");
      if (input.value.trim()) submit();
    };
    recognition.onerror = () => notify("Couldn't hear that. The keyboard's microphone works too.");
    listening = recognition;
    button.textContent = "■";
    button.classList.add("on");
    recognition.start();
  });
  return button;
}
