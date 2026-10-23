import assert from "node:assert/strict";
import test from "node:test";
import { clipboardImages, isImageAttachment } from "../lib/image-attachments";

test("clipboard paste extracts images while leaving ordinary text alone", () => {
  const screenshot = new File(["pixels"], "screenshot.png", { type: "image/png" });
  const data = { items: [
    { kind: "string", type: "text/plain", getAsFile: () => null },
    { kind: "file", type: "image/png", getAsFile: () => screenshot },
    { kind: "file", type: "image/gif", getAsFile: () => new File([], "animation.gif") },
    { kind: "file", type: "application/pdf", getAsFile: () => new File([], "doc.pdf") },
  ] } as unknown as DataTransfer;
  assert.deepEqual(clipboardImages(data), [screenshot]);
  assert.deepEqual(clipboardImages({ items: [] } as unknown as DataTransfer), []);
  assert.equal(isImageAttachment({ name: "Screenshot.JPG" }), true);
  assert.equal(isImageAttachment({ name: "clipboard", mime_type: "image/png" }), true);
  assert.equal(isImageAttachment({ name: "rules.pdf" }), false);
});
