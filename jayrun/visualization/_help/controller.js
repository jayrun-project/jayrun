/* Private build-time expression, embedded identically in each consumer. */
(() => {
  "use strict";
  const entries = __JAYRUN_HELP_CONTENT__;
  const CSS = __JAYRUN_HELP_STYLE__;
  function catalog(extension = []) {
    const result = new Map();
    const copy = value => {
      if (!value || typeof value.brief !== "string" || !value.brief.trim() || value.brief.length > 320 ||
          typeof value.detail !== "string" || !value.detail.trim() || value.detail.length > 2000)
        throw new TypeError("Help requires bounded brief and detail text");
      return Object.freeze({brief: value.brief, detail: value.detail});
    };
    for (const [key, value] of [...entries, ...extension]) {
      if (!/^[a-z][a-z0-9.-]+$/.test(key) || result.has(key)) throw new TypeError("Invalid or duplicate help key: " + key);
      const base = copy(value), variants = new Map();
      for (const [state, text] of Object.entries(value.variants || {})) variants.set(state, copy(text));
      result.set(key, {text: base, variants});
    }
    return (key, state = "") => {
      const value = result.get(key);
      if (!value) throw new TypeError("Missing help key: " + key);
      if (state && !value.variants.has(state)) throw new TypeError("Missing help variant: " + key + "/" + state);
      return state ? value.variants.get(state) : value.text;
    };
  }
  function mount(root, extension = [], required = []) {
    const resolve = catalog(extension);
    for (const key of required) resolve(key);
    const doc = root.ownerDocument || root, win = doc.defaultView;
    const container = root === doc ? doc.body : root;
    const events = new AbortController();
    let active = null, pointerOwner = null, focusOwner = null, suppressed = null, disposed = false;
    let panel = null, text = null, close = null, id = "context-help", suffix = 1;
    while (root.querySelector("#" + id)) id = "context-help-" + (++suffix);
    const make = (tag, content, attrs = {}) => {
      const node = doc.createElement(tag);
      if (content != null) node.textContent = content;
      for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
      return node;
    };
    const style = make("style", CSS);
    const nonce = root.host?.getAttribute("nonce") || doc.currentScript?.nonce;
    if (nonce) style.nonce = nonce;
    container.append(style);
    const listen = (target, name, fn, options = {}) => target.addEventListener(name, fn, {...options, signal: events.signal});
    const own = event => {
      const first = event.composedPath().find(node => node?.nodeType === 1);
      // A document controller must never consume another shadow viewer's event.
      return first && first.getRootNode() === root;
    };
    const source = event => own(event) ? event.composedPath().find(node =>
      node?.getRootNode?.() === root && node?.hasAttribute?.("data-help")) : null;
    const available = owner => {
      if (!owner?.isConnected || owner.getRootNode() !== root) return false;
      for (let node = owner; node; node = node.parentElement || node.getRootNode()?.host) {
        if (node.hidden || node.inert || node.getAttribute("aria-hidden") === "true") return false;
        const computed = win.getComputedStyle(node);
        if (computed.display === "none" || computed.visibility === "hidden") return false;
      }
      return owner.getClientRects().length > 0;
    };
    const description = (owner, add) => {
      const tokens = (owner.getAttribute("aria-describedby") || "").split(/\s+/).filter(token => token && token !== id);
      if (add) tokens.push(id);
      if (tokens.length) owner.setAttribute("aria-describedby", tokens.join(" "));
      else owner.removeAttribute("aria-describedby");
    };
    const observer = new MutationObserver(() => {
      if (!active) return;
      if (!available(active.owner)) { dismiss(); return; }
      const content = resolve(active.owner.dataset.help, active.owner.dataset.helpVariant || "");
      const next = active.pinned ? content.brief + "\n\n" + content.detail : content.brief;
      if (text.textContent !== next) text.textContent = next;
      place();
    });
    const watch = owner => {
      observer.disconnect();
      observer.observe(root, {subtree: true, childList: true, attributes: true,
        attributeFilter: ["hidden", "inert", "aria-hidden", "class", "style", "open", "data-help", "data-help-variant"]});
      // Host ancestors are outside a shadow root, but can hide its whole workspace.
      for (let node = root.host; node; node = node.parentElement) observer.observe(node, {
        attributes: true, attributeFilter: ["hidden", "inert", "aria-hidden", "class", "style"], childList: true
      });
    };
    function place() {
      if (!active || !available(active.owner)) { dismiss(); return; }
      const viewport = win.visualViewport, x = viewport?.offsetLeft || 0, y = viewport?.offsetTop || 0;
      const width = viewport?.width || win.innerWidth, height = viewport?.height || win.innerHeight;
      const maxWidth = Math.max(0, Math.min(380, width - 16)) + "px", maxHeight = Math.max(0, height - 16) + "px";
      if (panel.style.maxWidth !== maxWidth) panel.style.maxWidth = maxWidth;
      if (panel.style.maxHeight !== maxHeight) panel.style.maxHeight = maxHeight;
      const anchor = active.owner.getBoundingClientRect(), bounds = panel.getBoundingClientRect();
      const left = Math.max(x + 8, Math.min(x + width - bounds.width - 8, anchor.left));
      const below = anchor.bottom + 8, above = anchor.top - bounds.height - 8;
      const top = below + bounds.height <= y + height - 8 ? below : above >= y + 8 ? above : y + 8;
      // Avoid observing our own identical style writes forever.
      if (panel.style.left !== left + "px") panel.style.left = left + "px";
      if (panel.style.top !== top + "px") panel.style.top = top + "px";
    }
    function dismiss(restore = false) {
      if (!active) return;
      const previous = active;
      active = null; observer.disconnect();
      description(previous.owner, false);
      if (panel.isConnected && typeof panel.hidePopover === "function") panel.hidePopover();
      panel.hidden = true;
      if (restore && previous.pinned && available(previous.owner)) {
        suppressed = previous.owner;
        previous.owner.focus({preventScroll: true});
      }
    }
    function show(owner, pinned = false) {
      if (disposed || !available(owner)) return;
      const content = resolve(owner.dataset.help, owner.dataset.helpVariant || "");
      if (active?.owner === owner && active.pinned === pinned) return;
      dismiss(); suppressed = null;
      if (!panel) {
        panel = make("div", null, {id, class: "context-help", hidden: ""});
        if (typeof panel.showPopover === "function") panel.setAttribute("popover", "manual");
        text = make("p"); close = make("button", "Close", {type: "button", "aria-label": "Close help"});
        listen(close, "click", () => dismiss(true)); panel.append(close, text); container.append(panel);
      }
      active = {owner, pinned};
      panel.setAttribute("role", pinned ? "dialog" : "tooltip");
      if (pinned) panel.setAttribute("aria-label", owner.getAttribute("aria-label") || "Contextual help");
      else panel.removeAttribute("aria-label");
      panel.classList.toggle("help-pinned", pinned); close.hidden = !pinned;
      text.textContent = pinned ? content.brief + "\n\n" + content.detail : content.brief;
      panel.hidden = false;
      if (typeof panel.showPopover === "function") panel.showPopover();
      description(owner, true); place(); watch(owner);
      if (pinned) close.focus({preventScroll: true});
    }
    function showOwner() {
      if (active?.pinned) return;
      if (focusOwner && !available(focusOwner)) focusOwner = null;
      if (pointerOwner && !available(pointerOwner)) pointerOwner = null;
      // A newly hovered concept takes precedence over a still-focused action
      // (for example Refresh); keyboard-only focus remains the fallback.
      // Pointer-click focus must not resurrect that action's tooltip while the
      // pointer moves across unrelated content. Focus help is for keyboard focus.
      const next = pointerOwner || (focusOwner?.matches(":focus-visible") ? focusOwner : null);
      if (next && next !== suppressed) show(next); else dismiss();
    }
    listen(root, "pointerover", event => {
      if (event.pointerType === "touch" || !own(event)) return;
      pointerOwner = source(event);
      // A fresh pointer entry ends click/Escape suppression, even if this
      // control still holds focus. Moving between its children does not.
      if (pointerOwner === suppressed && !pointerOwner?.contains(event.relatedTarget)) suppressed = null;
      showOwner();
    });
    listen(root, "pointerout", event => {
      if (!own(event) || pointerOwner?.contains(event.relatedTarget)) return;
      if (suppressed === pointerOwner && focusOwner !== pointerOwner) suppressed = null;
      pointerOwner = null; showOwner();
    });
    listen(root, "focusin", event => {
      if (!own(event) || panel?.contains(event.target)) return;
      focusOwner = source(event); showOwner();
    });
    listen(root, "focusout", event => {
      if (!own(event) || focusOwner?.contains(event.relatedTarget)) return;
      if (suppressed === focusOwner && pointerOwner !== focusOwner) suppressed = null;
      focusOwner = null; if (!active?.pinned) showOwner();
    });
    listen(root, "click", event => {
      if (!own(event) || panel?.contains(event.target)) return;
      const owner = source(event);
      if (owner?.hasAttribute("data-help-button")) {
        event.preventDefault(); event.stopPropagation();
        if (active?.owner === owner && active.pinned) dismiss(true); else show(owner, true);
      } else { suppressed = owner; dismiss(); }
      // A primary action is never prevented, replayed, or submitted by help.
    }, {capture: true});
    listen(root, "keydown", event => {
      if (!own(event) || event.key !== "Escape" || !active) return;
      suppressed = active.owner; dismiss(true);
      event.preventDefault(); event.stopImmediatePropagation();
    }, {capture: true});
    listen(root, "scroll", place, {capture: true, passive: true});
    listen(win, "resize", place, {passive: true});
    listen(win, "scroll", place, {passive: true});
    if (win.visualViewport) {
      listen(win.visualViewport, "resize", place, {passive: true});
      listen(win.visualViewport, "scroll", place, {passive: true});
    }
    return {
      dismiss,
      info(key, label, variant = "") {
        resolve(key, variant);
        return make("button", "i", {type: "button", class: "help-button", "data-help": key,
          "data-help-variant": variant, "data-help-button": "", "aria-label": label});
      },
      reconcile(target, source) {
        // Stable dashboard polling owns all other attributes; retain only our token.
        if (active?.owner === target) description(source, true);
      },
      dispose() {
        if (disposed) return;
        disposed = true; dismiss(); events.abort(); observer.disconnect();
        panel?.remove(); style.remove(); pointerOwner = focusOwner = suppressed = null;
      }
    };
  }
  return {catalog, mount};
})()
