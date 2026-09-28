/* Private action utility: visible feedback never changes exact copied values. */
async (button, text, signal) => {
  const feedback = button.parentNode.querySelector(".copy-feedback");
  if (!feedback || button.disabled) return;
  const doc = button.ownerDocument, win = doc.defaultView;
  const previous = button.getRootNode().activeElement;
  let restoreFocus = false;
  button.disabled = true; feedback.textContent = "Copying…";
  let copied = false;
  try {
    if (win.navigator.clipboard && win.isSecureContext) await win.navigator.clipboard.writeText(text);
    else {
      const area = doc.createElement("textarea");
      area.value = text; area.setAttribute("aria-label", "Exact identity copy buffer");
      area.style.cssText = "position:fixed;left:0;top:0;width:1px;height:1px;opacity:0";
      button.parentNode.append(area);
      try { area.select(); copied = doc.execCommand("copy"); }
      finally { restoreFocus = button.getRootNode().activeElement === area; area.remove(); }
      if (!copied) throw new Error("Clipboard unavailable");
    }
    copied = true;
  } catch (_) { copied = false; }
  finally {
    if (!signal?.aborted && button.isConnected && feedback.isConnected) {
      button.disabled = false;
      if (restoreFocus && previous?.isConnected) previous.focus({preventScroll: true});
      feedback.textContent = copied ? "Copied" : "Failed";
      feedback.dataset.outcome = copied ? "success" : "failure";
    }
  }
}
