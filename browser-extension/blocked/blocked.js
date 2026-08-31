"use strict";

(() => {
  const api = globalThis.browser ?? globalThis.chrome;
  const source = document.querySelector("#block-source");
  const sourceName = document.querySelector("#block-source-name");
  const blockId = new URLSearchParams(location.search).get("block");

  api.runtime.sendMessage({ type: "get_block_info", block_id: blockId }).then((response) => {
    if (!response?.ok || !response.result?.name) return;
    sourceName.textContent = response.result.name;
    source.hidden = false;
  }).catch(() => {
    // The generic block message remains sufficient if the background worker
    // is temporarily unavailable or the identifier is no longer active.
  });
})();
