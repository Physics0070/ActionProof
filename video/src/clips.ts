// Offsets (seconds) into the recorded footage (video/public/footage/*.mp4, converted from Playwright's webm).
// Tuned by looking at extracted frames; see docs/VIDEO.md.
export const CLIPS = {
  gate: { src: "footage/gate.mp4", intercept: 21.5, review: 42.5 },
  console: { src: "footage/console.mp4" },
};
