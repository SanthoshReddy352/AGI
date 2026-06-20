import { useEffect, useRef, useState } from "react";

// Strip markdown so the TTS reads words, not symbols ("asterisk asterisk").
function toPlainText(md) {
  return (md || "")
    .replace(/```[\s\S]*?```/g, ". code block. ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/[*_>#]/g, "")
    .replace(/^\s*[-•]\s+/gm, "")
    .replace(/\n{2,}/g, ". ")
    .replace(/\s+/g, " ")
    .trim();
}

// Read a message aloud using the BROWSER's built-in TTS (Web Speech API).
// No Piper, no server, no dependency. Toggles play/stop.
export default function ReadAloud({ text }) {
  const [speaking, setSpeaking] = useState(false);
  const speakingRef = useRef(false);
  const supported = typeof window !== "undefined" && "speechSynthesis" in window;

  useEffect(() => () => {
    // Only stop our own speech on unmount (speechSynthesis is global).
    if (supported && speakingRef.current) window.speechSynthesis.cancel();
  }, [supported]);

  if (!supported || !text) return null;

  function toggle() {
    const synth = window.speechSynthesis;
    if (speakingRef.current) {
      synth.cancel();
      speakingRef.current = false;
      setSpeaking(false);
      return;
    }
    synth.cancel(); // stop anything else first
    const u = new SpeechSynthesisUtterance(toPlainText(text));
    u.rate = 1.02;
    u.onend = () => { speakingRef.current = false; setSpeaking(false); };
    u.onerror = () => { speakingRef.current = false; setSpeaking(false); };
    speakingRef.current = true;
    setSpeaking(true);
    synth.speak(u);
  }

  return (
    <button onClick={toggle} title={speaking ? "Stop reading" : "Read aloud"}
            className={`inline-flex items-center gap-1 hover:text-ink dark:hover:text-night-ink transition ${speaking ? "text-brand-deep" : ""}`}>
      {speaking ? <StopIcon /> : <SpeakerIcon />}
    </button>
  );
}

const SpeakerIcon = () => (<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 5 6 9H2v6h4l5 4V5Z" /><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a9 9 0 0 1 0 14" /></svg>);
const StopIcon = () => (<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>);
