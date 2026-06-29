import { useEffect, useState } from "react";

/**
 * Reveal `text` character-by-character. Restarts when `text` changes.
 */
export function useTypewriter(text, { active = true, msPerChar = 18 } = {}) {
  const [output, setOutput] = useState("");

  useEffect(() => {
    if (!active || !text) {
      setOutput("");
      return undefined;
    }

    setOutput("");
    let index = 0;
    let timerId = null;
    let cancelled = false;

    const tick = () => {
      if (cancelled) return;
      index += 1;
      setOutput(text.slice(0, index));
      if (index < text.length) {
        timerId = setTimeout(tick, msPerChar);
      }
    };

    timerId = setTimeout(tick, msPerChar);

    return () => {
      cancelled = true;
      if (timerId) clearTimeout(timerId);
    };
  }, [text, active, msPerChar]);

  return output;
}
