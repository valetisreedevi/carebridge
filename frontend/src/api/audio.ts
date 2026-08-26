/** Making the family's voice play without asking an 82-year-old to tap.
 *
 * A phone will not make a sound a person did not ask for. The rule is per
 * page, not per sound: once one real tap has started audio on this page,
 * everything after it may play on its own, minutes later, unprompted.
 *
 * So the tap is spent by whoever sets the phone up — a son typing a pairing
 * code, standing in the room — and from then on every reminder plays by
 * itself. The elder is never asked to do anything.
 *
 * One element, reused. A fresh `new Audio()` per reminder is a fresh element
 * that was never unlocked, which is why the recording only ever played on the
 * phone of whoever had just pressed something.
 */

// A hundredth of a second of silence. Enough to spend the gesture on, short
// enough that nobody hears it happen.
const SILENCE =
  "data:audio/mpeg;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA" +
  "//tAwAAAAAAAAAAAAAAAAAAAAAAASW5mbwAAAA8AAAADAAABIADAwMDAwMDAwMDAwMDAwMDAwMDAwMDA" +
  "wMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA//sQxAADwAABpAAAACAAADSAAAAETEFN" +
  "RTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV";

let element: HTMLAudioElement | null = null;
let unlocked = false;

function shared(): HTMLAudioElement {
  if (!element) {
    element = new Audio();
    element.preload = "auto";
  }
  return element;
}

/**
 * Spends a real tap on permission to make noise later.
 *
 * Safe to call on every gesture: it does nothing once it has worked, and it
 * never throws. A phone that refuses simply falls back to the button, which
 * is why that button still exists.
 */
export function unlockAudio(): void {
  if (unlocked) return;

  const audio = shared();
  audio.muted = true;
  audio.src = SILENCE;

  audio
    .play()
    .then(() => {
      unlocked = true;
      audio.pause();
      audio.muted = false;
    })
    .catch(() => {
      // Not a gesture the browser accepted. The next one may be.
      audio.muted = false;
    });
}

export function audioUnlocked(): boolean {
  return unlocked;
}

/** Returns whether it actually played, so the screen can stop pretending. */
export async function playVoice(url: string): Promise<boolean> {
  const audio = shared();
  audio.muted = false;
  audio.src = url;

  try {
    await audio.play();
    unlocked = true;
    return true;
  } catch {
    return false;
  }
}

/** So the screen can show "playing" honestly rather than guessing. */
export function whenVoiceEnds(onEnd: () => void): () => void {
  const audio = shared();
  audio.addEventListener("ended", onEnd);
  return () => audio.removeEventListener("ended", onEnd);
}
