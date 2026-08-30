"use strict";
globalThis.UPC_ORDER_MODEL = (() => {
  function sortedBlocks(blocks) { return blocks.map((block, index) => ({ block, index })).sort((a, b) => b.block.priority - a.block.priority || a.index - b.index).map(({ block }) => block); }
  function moveBlock(blocks, blockId, offset) { const ordered = sortedBlocks(blocks); const from = ordered.findIndex((block) => block.id === blockId); const to = Math.max(0, Math.min(ordered.length - 1, from + offset)); if (from < 0 || from === to) return ordered; const [moved] = ordered.splice(from, 1); ordered.splice(to, 0, moved); return ordered; }
  function prioritiesForOrder(blocks) { if (blocks.length > 2001) throw new Error("Zu viele Blocks für eine eindeutige Prioritätsreihenfolge."); const top = Math.floor((blocks.length - 1) / 2); return blocks.map((block, index) => ({ id: block.id, priority: top - index })); }
  return { sortedBlocks, moveBlock, prioritiesForOrder };
})();
