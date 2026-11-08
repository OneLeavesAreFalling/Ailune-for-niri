/**
 * Optional Live2D Cubism runtime integration point.
 *
 * The Cubism SDK is not vendored in this repository because its license is
 * separate from Ailune's. To enable real Live2D rendering, build a small
 * adapter that exposes `window.AiluneLive2D.create(options)` (or modify this
 * module), then rebuild the renderer per renderer/README.md.
 *
 * The adapter receives the local model URL served by the pet shell:
 *   { canvas, modelUrl, modelEntry, name }
 *
 * Expected methods on the returned object:
 *   setExpression(name), playMotion(group, index), setMouth(value),
 *   setSpeaking(bool), setLook(x, y), draw(now), destroy()
 */

export async function createLive2DRenderer(options) {
  const vendor = globalThis.AiluneLive2D;
  if (!vendor || typeof vendor.create !== "function") {
    return null;
  }
  try {
    return await vendor.create(options);
  } catch (error) {
    console.error("[ailune] Live2D adapter failed; using placeholder", error);
    return null;
  }
}
