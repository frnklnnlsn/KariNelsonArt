(() => {
  "use strict";
  const { csrf, saved } = window.KN_ADMIN;
  let recipient = window.KN_ADMIN.recipient || "";
  const onGallery = typeof artworks !== "undefined";
  const ART_PARTS = { "main-image": "image", "image-title": "title", "image-date": "date", "image-description": "description", "image-artist-statement": "artist_statement" };
  const ART_FIELDS = [
    ["title", "Title", "input"], ["date", "Date", "input"], ["description", "Description", "textarea"],
    ["category", "Category", "input"], ["artist_statement", "Artist statement", "textarea"],
  ];

  const original = {};      // text key -> starting value
  const textChanges = {};   // text key -> new value
  const artOriginal = new Map();  // filename -> starting fields
  const newImages = new Map();    // filename -> { file, url }
  let selectedEl = null;
  let addDraft = null;

  // ---- small helpers -------------------------------------------------------
  function make(tag, props = {}, ...children) {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...children);
    return node;
  }
  function field(label, input) { return make("label", { className: "kn-field" }, make("span", { textContent: label }), input); }
  function toast(message, bad) {
    document.querySelector(".kn-toast")?.remove();
    const node = make("div", { className: "kn-ui kn-toast" + (bad ? " kn-bad" : ""), textContent: message, role: "status" });
    document.body.append(node);
    if (!bad) setTimeout(() => node.remove(), 4000);
  }
  async function post(url, body) {
    let response;
    try {
      response = await fetch(url, { method: "POST", headers: { "X-CSRF-Token": csrf }, body });
    } catch { throw new Error("Couldn't reach the server. Check your connection and try again."); }
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) throw new Error(result.error || "Something went wrong. Please try again.");
    return result;
  }

  // ---- page text -----------------------------------------------------------
  const elementsFor = key => document.querySelectorAll(`[data-edit="${key}"]`);
  function readElement(el) {
    if (el.dataset.editType === "url") return el.getAttribute("href") || "";
    if (el.dataset.editType === "body") return [...el.children].map(c => c.textContent).join("\n\n") || el.textContent.trim();
    return el.textContent;
  }
  function showText(key, value) {
    elementsFor(key).forEach(el => {
      const type = el.dataset.editType;
      if (type === "url") return el.setAttribute("href", value);
      if (type === "body") return el.replaceChildren(...value.split(/\n\s*\n/).filter(p => p.trim()).map(p => make("p", { textContent: p.trim() })));
      el.textContent = value;
    });
  }
  function setText(key, value) {
    if (value === original[key]) delete textChanges[key]; else textChanges[key] = value;
    showText(key, value);
    refreshBar();
  }

  // ---- artwork -------------------------------------------------------------
  const currentArt = () => artworks[currentIndex];
  const mainImg = () => document.getElementById("main-image");
  function artDirty(art) {
    const start = artOriginal.get(art.filename);
    if (!start) return false;
    return newImages.has(art.filename) || ART_FIELDS.some(([f]) => (art[f] || "") !== (start[f] || ""));
  }
  const dirtyArtworks = () => (onGallery ? artworks.filter(artDirty) : []);
  const changeCount = () => Object.keys(textChanges).length + dirtyArtworks().length;

  function showArtField(name, value) {
    if (name === "title") document.getElementById("image-title").textContent = value || "—";
    if (name === "date") document.getElementById("image-date").textContent = value || "—";
    if (name === "description") document.getElementById("image-description").textContent = value || "—";
    if (name === "category") populateCategoryList();
    if (name === "artist_statement") {
      document.getElementById("image-artist-statement").textContent = value;
      document.getElementById("artist-statement-section").style.display = value.trim() ? "block" : "none";
    }
  }
  function imagePicker(onPick) {
    const input = make("input", { type: "file", accept: "image/jpeg,image/png,image/gif" });
    input.addEventListener("change", () => input.files[0] && onPick(input.files[0], URL.createObjectURL(input.files[0])));
    return input;
  }
  function categoryList() {
    return make("datalist", { id: "kn-categories" }, ...[...new Set(artworks.map(a => a.category).filter(Boolean))].map(value => make("option", { value })));
  }
  function artFields(values, onInput, focusName) {
    let focusTarget = null;
    const nodes = ART_FIELDS.map(([name, label, tag]) => {
      const input = make(tag, { value: values[name] || "" });
      if (name === "category") input.setAttribute("list", "kn-categories");
      if (name === "date") input.placeholder = "Year or full date";
      input.addEventListener("input", () => onInput(name, input.value));
      if (name === focusName) focusTarget = input;
      return field(label, input);
    });
    return { nodes, focusTarget };
  }

  // ---- side panel ----------------------------------------------------------
  const panel = make("aside", { className: "kn-ui kn-panel" });
  panel.addEventListener("keydown", e => e.stopPropagation()); // don't let arrows change artwork while typing

  function select(el) {
    document.querySelector(".kn-selected")?.classList.remove("kn-selected");
    selectedEl = el;
    el?.classList.add("kn-selected");
  }
  function showHint() {
    select(null);
    panel.replaceChildren(
      make("h2", { textContent: "Click anything to change it" }),
      make("p", { textContent: "Text, buttons and artwork with an outline can all be edited. You'll see your changes on the page as you make them." }),
      make("p", { textContent: "Visitors won't see anything until you press Publish." }),
    );
    if (location.pathname === "/all-works/") panel.append(make("hr", { className: "kn-divider" }), ...layoutSettings());
    if (location.pathname === "/contact/") panel.append(make("hr", { className: "kn-divider" }), ...messageSettings());
  }
  function layoutSettings() {
    const grid = document.getElementById("all-works-grid");
    const slider = (key, label, cssVar, min, max, unit) => {
      original[key] ??= key in saved ? saved[key] : grid.style.getPropertyValue(cssVar).replace("px", "").trim();
      const value = key in textChanges ? textChanges[key] : original[key];
      const output = make("span", { textContent: value + unit });
      const input = make("input", { type: "range", min, max, step: 1, value, className: "kn-range" });
      input.addEventListener("input", () => {
        output.textContent = input.value + unit;
        grid.style.setProperty(cssVar, input.value + unit);
        setText(key, input.value);
      });
      return make("label", { className: "kn-field" }, make("span", {}, label + ": ", output), input);
    };
    return [
      make("h2", { textContent: "Photo layout" }),
      slider("all_works_columns", "Photos in each row", "--columns", 1, 8, ""),
      slider("all_works_gap", "Space between photos", "--gap", 0, 80, "px"),
    ];
  }
  function messageSettings() {
    const input = make("input", { type: "email", value: recipient, placeholder: "name@example.com" });
    const save = make("button", { className: "kn-btn kn-primary", type: "button", textContent: "Save" });
    const test = make("button", { className: "kn-btn", type: "button", textContent: "Save and send a test" });
    async function submit(button, sendTest) {
      const body = new FormData();
      body.append("email", input.value);
      if (sendTest) body.append("test", "1");
      save.disabled = test.disabled = true;
      toast(sendTest ? "Sending a test email…" : "Saving…");
      try {
        await post("/_admin/api/contact-recipient", body);
        recipient = input.value.trim();
        toast(sendTest ? `Test sent to ${recipient}. Check that inbox.` : "Saved. New messages will go there.");
      } catch (e) { toast(e.message, true); }
      save.disabled = test.disabled = false;
    }
    save.addEventListener("click", () => submit(save, false));
    test.addEventListener("click", () => submit(test, true));
    return [
      make("h2", { textContent: "Where messages go" }),
      make("p", { textContent: "Messages from this form are sent to this email address. It isn't shown on your website." }),
      field("Send messages to", input),
      make("div", { className: "kn-actions" }, save, test),
    ];
  }
  function editElement(el) {
    select(el);
    const key = el.dataset.edit;
    const type = el.dataset.editType;
    const value = key in textChanges ? textChanges[key] : original[key];
    const input = make(type === "body" ? "textarea" : "input", { value });
    if (type === "url") input.placeholder = "https://";
    input.addEventListener("input", () => setText(key, input.value));
    panel.replaceChildren(
      make("h2", { textContent: el.dataset.editLabel || "Text" }),
      field(type === "url" ? "Where it goes" : type === "body" ? "Text (leave a blank line between paragraphs)" : "Text", input),
    );
    input.focus();
  }
  function editArtwork(focusName) {
    addDraft = null;
    const art = currentArt();
    select(mainImg());
    const { nodes, focusTarget } = artFields(art, (name, value) => {
      art[name] = value;
      showArtField(name, value);
      document.querySelectorAll(".thumbnail")[currentIndex].alt = art.title;
      refreshBar();
    }, focusName);
    const picker = imagePicker((file, url) => {
      newImages.set(art.filename, { file, url });
      showPendingImage();
      refreshBar();
    });
    const remove = make("button", { className: "kn-btn kn-danger", type: "button", textContent: "Delete this artwork" });
    remove.addEventListener("click", () => deleteArtwork(art));
    panel.replaceChildren(make("h2", { textContent: "Artwork" }), field("Replace the image", picker), ...nodes, categoryList(), make("hr", { className: "kn-divider" }), remove);
    if (focusName && focusTarget) focusTarget.focus();
  }

  function showPendingImage() {
    if (!onGallery || addDraft) return;
    const pending = newImages.get(currentArt().filename);
    if (pending && mainImg().src !== pending.url) mainImg().src = pending.url;
    newImages.forEach((image, filename) => {
      const thumb = document.querySelectorAll(".thumbnail")[artworks.findIndex(a => a.filename === filename)];
      if (thumb && thumb.src !== image.url) { thumb.removeAttribute("data-src"); thumb.src = image.url; }
    });
  }

  function startAdd() {
    if (changeCount()) return toast("Please publish or discard your changes first.", true);
    addDraft = { title: "", date: "", description: "", category: "", artist_statement: "", file: null };
    select(null);
    document.getElementById("gallery-container").style.display = "";
    mainImg().removeAttribute("src");
    ART_FIELDS.forEach(([name]) => showArtField(name, ""));
    document.getElementById("main-image-wrapper").classList.remove("loading");
    const { nodes } = artFields(addDraft, (name, value) => { addDraft[name] = value; showArtField(name, value); });
    const save = make("button", { className: "kn-btn kn-primary", type: "button", textContent: "Add to gallery" });
    const cancel = make("button", { className: "kn-btn", type: "button", textContent: "Cancel" });
    const picker = imagePicker((file, url) => { addDraft.file = file; mainImg().src = url; mainImg().classList.remove("fading"); });
    save.addEventListener("click", () => submitAdd(save));
    cancel.addEventListener("click", cancelAdd);
    panel.replaceChildren(make("h2", { textContent: "New artwork" }), field("Image", picker), ...nodes, categoryList(), make("div", { className: "kn-actions" }, save, cancel));
  }
  function cancelAdd() {
    addDraft = null;
    if (!artworks.length) return location.reload();
    updateDisplay();
    showHint();
  }
  async function submitAdd(button) {
    if (!addDraft.file) return toast("Please choose an image first.", true);
    if (!addDraft.title.trim()) return toast("Please give the artwork a title.", true);
    const body = new FormData();
    Object.entries(addDraft).forEach(([k, v]) => v !== null && body.append(k === "file" ? "image" : k, v));
    button.disabled = true;
    toast("Adding to your gallery…");
    try {
      const { filename } = await post("/_admin/api/artwork", body);
      sessionStorage.setItem("kn-focus", filename);
      sessionStorage.setItem("kn-message", "Added to your gallery.");
      location.reload();
    } catch (e) { button.disabled = false; toast(e.message, true); }
  }
  async function deleteArtwork(art) {
    if (changeCount()) return toast("Please publish or discard your changes first.", true);
    if (!confirm(`Delete “${art.title}” from your website? This can't be undone.`)) return;
    const body = new FormData();
    body.append("filename", art.filename);
    toast("Deleting…");
    try {
      await post("/_admin/api/artwork/delete", body);
      sessionStorage.setItem("kn-message", "Artwork deleted.");
      sessionStorage.removeItem("lastViewedImageIndex");
      location.reload();
    } catch (e) { toast(e.message, true); }
  }

  // ---- top bar and publishing ----------------------------------------------
  const status = make("span", { className: "kn-status" });
  const publishBtn = make("button", { className: "kn-btn kn-primary", type: "button", textContent: "Publish" });
  const discardBtn = make("button", { className: "kn-btn", type: "button", textContent: "Discard" });
  let publishing = false;

  function refreshBar() {
    const count = changeCount();
    status.textContent = count === 0 ? "No unpublished changes" : count === 1 ? "1 unpublished change" : `${count} unpublished changes`;
    publishBtn.disabled = count === 0 || publishing;
    discardBtn.disabled = count === 0 || publishing;
  }
  async function publish() {
    const art = {};
    const body = new FormData();
    dirtyArtworks().forEach((item, i) => {
      art[item.filename] = Object.fromEntries(ART_FIELDS.map(([f]) => [f, item[f] || ""]));
      const image = newImages.get(item.filename);
      if (image) { art[item.filename].file = `file_${i}`; body.append(`file_${i}`, image.file); }
    });
    body.append("changes", JSON.stringify({ text: textChanges, art }));
    publishing = true;
    refreshBar();
    toast("Publishing…");
    try {
      await post("/_admin/api/publish", body);
      Object.keys(textChanges).forEach(k => delete textChanges[k]);
      newImages.clear();
      artOriginal.clear();
      sessionStorage.setItem("kn-message", "Your website is updated.");
      if (onGallery && currentArt()) sessionStorage.setItem("kn-focus-index", currentIndex);
      location.reload();
    } catch (e) { publishing = false; refreshBar(); toast(e.message, true); }
  }
  function buildBar() {
    const here = location.pathname;
    const pages = [["/", "About"], ["/gallery/", "Gallery"], ["/all-works/", "All Works"], ["/contact/", "Contact"], ["/thank-you/", "Thank you"]];
    const nav = make("nav", { className: "kn-pages" }, ...pages.map(([href, textContent]) => {
      const link = make("a", { href, textContent });
      if (href === here) link.setAttribute("aria-current", "page");
      return link;
    }));
    const signOut = make("form", { method: "POST", action: "/_admin/logout" },
      make("input", { type: "hidden", name: "csrf", value: csrf }),
      make("button", { className: "kn-btn kn-signout", type: "submit", textContent: "Sign out" }));
    const parts = [nav, make("div", { className: "kn-spacer" })];
    if (onGallery) {
      const add = make("button", { className: "kn-btn", type: "button", textContent: "+ Add artwork" });
      add.addEventListener("click", startAdd);
      parts.push(add);
    }
    parts.push(status, discardBtn, publishBtn, signOut);
    publishBtn.addEventListener("click", publish);
    discardBtn.addEventListener("click", () => {
      if (!confirm("Throw away your unpublished changes?")) return;
      Object.keys(textChanges).forEach(k => delete textChanges[k]);
      newImages.clear();
      artOriginal.clear();
      location.reload();
    });
    document.body.append(make("div", { className: "kn-ui kn-bar" }, ...parts), panel);
  }

  // ---- clicks on the page --------------------------------------------------
  document.addEventListener("click", e => {
    if (e.target.closest(".kn-ui")) return;
    const el = e.target.closest("[data-edit]");
    if (el) {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (addDraft) return;
      return editElement(el);
    }
    const part = e.target.closest(".kn-art");
    if (part && onGallery) {
      if (addDraft) return;
      return editArtwork(ART_PARTS[part.id] === "image" ? null : ART_PARTS[part.id]);
    }
    if (!e.target.closest("a, button, input, textarea, .thumbnail, #thumbnail-container")) showHint();
  }, true);
  document.addEventListener("submit", e => {
    if (!e.target.closest(".kn-ui") && !e.target.matches('[action="/_admin/logout"]')) e.preventDefault();
  }, true);
  window.addEventListener("beforeunload", e => { if (!publishing && changeCount()) e.preventDefault(); });

  // ---- start ---------------------------------------------------------------
  function start() {
    buildBar();
    document.querySelectorAll("[data-edit]").forEach(el => {
      const key = el.dataset.edit;
      original[key] = key in saved ? saved[key] : readElement(el);
    });
    document.body.classList.add("kn-hints");
    if (onGallery) {
      artworks.forEach(a => artOriginal.set(a.filename, { ...a }));
      Object.keys(ART_PARTS).forEach(id => document.getElementById(id)?.classList.add("kn-art"));
      const showArtwork = window.updateDisplay;
      window.updateDisplay = () => {
        addDraft && (addDraft = null);
        showArtwork();
        showPendingImage();
        if (selectedEl === mainImg()) editArtwork(null);
      };
      new MutationObserver(showPendingImage).observe(mainImg(), { attributes: true, attributeFilter: ["src"] });
      const focusName = sessionStorage.getItem("kn-focus");
      const focusIndex = sessionStorage.getItem("kn-focus-index");
      sessionStorage.removeItem("kn-focus");
      sessionStorage.removeItem("kn-focus-index");
      const target = focusName ? artworks.findIndex(a => a.filename === focusName) : focusIndex !== null ? Number(focusIndex) : -1;
      if (target >= 0 && target < artworks.length) { currentIndex = target; updateDisplay(); }
    }
    showHint();
    refreshBar();
    const message = sessionStorage.getItem("kn-message");
    if (message) { sessionStorage.removeItem("kn-message"); toast(message); }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
