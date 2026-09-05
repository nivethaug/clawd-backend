/*!
 * DreamAgent preview-bridge.js
 * Injected into project preview pages (nginx sub_filter) to power the
 * in-app visual design layer. Communicates with the DreamAgent app shell
 * (parent window) exclusively via postMessage.
 *
 * The script is a strict no-op when the page is visited normally
 * (window.parent === window) — real site visitors pay ~zero cost.
 */
(function () {
  'use strict';

  if (window.parent === window) return; // not embedded — do nothing

  // Parent origins allowed to control the bridge. Update on deploy if the
  // app shell moves. Incoming commands from other origins are dropped.
  var PARENT_ORIGINS = [
    'https://dreamagent.cloud',
    'http://localhost:8080',
    'http://localhost:5173',
    'http://localhost:3000',
  ];

  // Outgoing messages carry element metadata only (no secrets), so '*' is
  // acceptable as targetOrigin; commands INBOUND are origin-validated.
  var OUTGOING_ORIGIN = '*';

  var BRIDGE_MARK = 'daBridgeChrome'; // attribute marking our own overlay nodes

  var mode = 'off'; // 'off' | 'select' | 'text'
  var hoverLocked = false;
  var nextNodeId = 1;
  var nodeIds = new WeakMap(); // Element -> id
  var nodeRegistry = new Map(); // id -> Element
  var editingNode = null;
  var editingOriginalText = null;

  // ---------------------------------------------------------------- chrome

  function makeChrome(tag, styles) {
    var el = document.createElement(tag);
    el.setAttribute('data-' + BRIDGE_MARK, '1');
    el.style.position = 'absolute';
    el.style.pointerEvents = 'none';
    el.style.zIndex = '2147483646';
    for (var k in styles) el.style[k] = styles[k];
    document.documentElement.appendChild(el);
    return el;
  }

  var hoverBox = null;
  var selectionBoxes = []; // {el, labelEl, nodeId}

  function ensureHoverBox() {
    if (!hoverBox) {
      hoverBox = makeChrome('div', {
        border: '1.5px solid #22d3ee',
        background: 'rgba(34,211,238,0.08)',
        borderRadius: '2px',
        transition: 'all 0.05s linear',
      });
    }
    return hoverBox;
  }

  function boxRect(el) {
    var r = el.getBoundingClientRect();
    return {
      x: r.left + window.scrollX,
      y: r.top + window.scrollY,
      w: r.width,
      h: r.height,
    };
  }

  function placeBox(box, rect) {
    box.style.left = rect.x + 'px';
    box.style.top = rect.y + 'px';
    box.style.width = Math.max(rect.w, 2) + 'px';
    box.style.height = Math.max(rect.h, 2) + 'px';
    box.style.display = 'block';
  }

  function labelFor(node, rect) {
    var label = document.createElement('div');
    label.setAttribute('data-' + BRIDGE_MARK, '1');
    label.textContent = node.source && node.source.component
      ? node.source.component
      : node.tag.toLowerCase();
    label.style.cssText =
      'position:absolute;pointer-events:none;z-index:2147483647;' +
      'background:#6366f1;color:#fff;font:600 10px/1.4 ui-monospace,monospace;' +
      'padding:1px 5px;border-radius:3px;white-space:nowrap;';
    document.documentElement.appendChild(label);
    label.style.left = rect.x + 'px';
    label.style.top = Math.max(rect.y - 16, 0) + 'px';
    return label;
  }

  function clearChrome() {
    if (hoverBox) hoverBox.style.display = 'none';
  }

  function clearSelectionChrome() {
    selectionBoxes.forEach(function (b) {
      if (b.el.parentNode) b.el.parentNode.removeChild(b.el);
      if (b.labelEl && b.labelEl.parentNode) b.labelEl.parentNode.removeChild(b.labelEl);
      nodeRegistry.delete(b.nodeId);
    });
    selectionBoxes = [];
  }

  // ---------------------------------------------------------------- nodes

  function nodeIdFor(el) {
    var id = nodeIds.get(el);
    if (!id) {
      id = 'da-' + nextNodeId++;
      nodeIds.set(el, id);
      nodeRegistry.set(id, el);
    }
    return id;
  }

  function elementForNodeId(id) {
    var el = nodeRegistry.get(id);
    if (el && !el.isConnected) {
      nodeRegistry.delete(id);
      return null;
    }
    return el || null;
  }

  function cssSelector(el) {
    if (el.id) return '#' + CSS.escape(el.id);
    var parts = [];
    var depth = 0;
    var node = el;
    while (node && node.nodeType === 1 && depth < 5) {
      var part = node.tagName.toLowerCase();
      if (node.id) {
        parts.unshift('#' + CSS.escape(node.id));
        break;
      }
      var parent = node.parentNode;
      if (parent) {
        var sameTag = Array.prototype.filter.call(
          parent.children,
          function (c) { return c.tagName === node.tagName; }
        );
        if (sameTag.length > 1) part += ':nth-of-type(' + (sameTag.indexOf(node) + 1) + ')';
      }
      parts.unshift(part);
      node = node.parentNode;
      depth++;
    }
    return parts.join(' > ');
  }

  function parseDataDaSource(el) {
    var val = null;
    var node = el;
    while (node && node.nodeType === 1 && !val) {
      val = node.getAttribute && node.getAttribute('data-da-source');
      if (val) break;
      node = node.parentElement;
    }
    if (!val) return undefined;
    // format: "src/pages/Home.tsx:HeroSection" (component optional)
    var idx = val.lastIndexOf(':');
    if (idx === -1) return { file: val };
    return { file: val.slice(0, idx), component: val.slice(idx + 1) };
  }

  function serializeNode(el) {
    var cs = window.getComputedStyle(el);
    var rect = el.getBoundingClientRect();
    var source = parseDataDaSource(el);
    var className =
      typeof el.className === 'string' ? el.className : (el.getAttribute('class') || '');
    var ownText = '';
    for (var i = 0; i < el.childNodes.length; i++) {
      var n = el.childNodes[i];
      if (n.nodeType === 3 && n.textContent.trim()) ownText += n.textContent;
    }
    return {
      nodeId: nodeIdFor(el),
      tag: el.tagName,
      role: el.getAttribute('role') || undefined,
      textPreview: (ownText || el.innerText || '').trim().slice(0, 80) || undefined,
      selector: cssSelector(el),
      className: className || undefined,
      source: source,
      box: {
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        w: Math.round(rect.width),
        h: Math.round(rect.height),
      },
      computed: {
        color: cs.color,
        background: cs.backgroundColor,
        fontSize: cs.fontSize,
        fontWeight: cs.fontWeight,
        fontFamily: cs.fontFamily,
        padding: cs.padding,
        margin: cs.margin,
        borderRadius: cs.borderRadius,
        boxShadow: cs.boxShadow,
        display: cs.display,
        width: cs.width,
        height: cs.height,
        opacity: cs.opacity,
      },
    };
  }

  // ---------------------------------------------------------------- events

  function send(msg) {
    try {
      window.parent.postMessage(msg, OUTGOING_ORIGIN);
    } catch (e) {
      /* parent gone — ignore */
    }
  }

  function isOwnChrome(el) {
    return !!(el && el.closest && el.closest('[data-' + BRIDGE_MARK + ']'));
  }

  function meaningfulTarget(el) {
    if (!el || el.nodeType !== 1) return null;
    if (isOwnChrome(el)) return null;
    if (el === document.documentElement || el === document.body) return null;
    return el;
  }

  function onHoverMove(e) {
    if (mode !== 'select' || hoverLocked) return;
    var el = meaningfulTarget(e.target);
    if (!el) {
      clearChrome();
      return;
    }
    var raf = onHoverMove._raf;
    if (raf) cancelAnimationFrame(raf);
    onHoverMove._target = el;
    onHoverMove._raf = requestAnimationFrame(function () {
      var target = onHoverMove._target;
      if (!target || !target.isConnected) return;
      var node = serializeNode(target);
      placeBox(ensureHoverBox(), {
        x: node.box.x + window.scrollX,
        y: node.box.y + window.scrollY,
        w: node.box.w,
        h: node.box.h,
      });
      send({ type: 'HOVER', node: node });
    });
  }

  function onSelectClick(e) {
    if (mode !== 'select') return;
    var el = meaningfulTarget(e.target);
    if (!el) {
      // empty canvas click clears selection unless toggling
      if (!e.ctrlKey && !e.metaKey) {
        clearSelectionChrome();
        send({ type: 'SELECT', nodes: [] });
      }
      return;
    }
    e.preventDefault();
    e.stopPropagation();

    var node = serializeNode(el);
    var existing = selectionBoxes.filter(function (b) { return b.nodeId === node.nodeId; });
    if ((e.ctrlKey || e.metaKey) && existing.length) {
      // toggle off
      existing.forEach(function (b) {
        if (b.el.parentNode) b.el.parentNode.removeChild(b.el);
        if (b.labelEl && b.labelEl.parentNode) b.labelEl.parentNode.removeChild(b.labelEl);
      });
      selectionBoxes = selectionBoxes.filter(function (b) { return b.nodeId !== node.nodeId; });
    } else if (e.ctrlKey || e.metaKey) {
      addSelectionChrome(node);
    } else {
      clearSelectionChrome();
      addSelectionChrome(node);
    }
    send({
      type: 'SELECT',
      nodes: selectionBoxes.map(function (b) { return b.node; }),
    });
  }

  function addSelectionChrome(node) {
    var box = makeChrome('div', {
      border: '2px solid #6366f1',
      background: 'rgba(99,102,241,0.06)',
      borderRadius: '2px',
    });
    placeBox(box, {
      x: node.box.x + window.scrollX,
      y: node.box.y + window.scrollY,
      w: node.box.w,
      h: node.box.h,
    });
    var label = labelFor(node, {
      x: node.box.x + window.scrollX,
      y: node.box.y + window.scrollY,
    });
    selectionBoxes.push({ el: box, labelEl: label, nodeId: node.nodeId, node: node });
  }

  // ---------------------------------------------------------------- text mode

  function commitText(cancel) {
    if (!editingNode) return;
    var nodeId = nodeIdFor(editingNode);
    var text = (editingNode.innerText || '').replace(/\n+$/, '');
    var original = editingOriginalText;
    editingNode.removeAttribute('contenteditable');
    if (cancel) editingNode.innerText = editingOriginalText;
    var node = editingNode;
    editingNode = null;
    editingOriginalText = null;
    send({
      type: cancel ? 'TEXT_CANCEL' : 'TEXT_COMMIT',
      nodeId: nodeId,
      text: text,
      original: original,
      node: serializeNode(node),
    });
  }

  function onTextClick(e) {
    if (mode !== 'text') return;
    var el = meaningfulTarget(e.target);
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    if (editingNode && editingNode !== el) commitText(false);

    // Prefer an element that directly contains text
    var target = el;
    var directTextNodes = [];
    function ownTextNodes(node) {
      directTextNodes = [];
      for (var i = 0; i < node.childNodes.length; i++) {
        var n = node.childNodes[i];
        if (n.nodeType === 3 && n.textContent.trim()) directTextNodes.push(n);
      }
      return directTextNodes;
    }
    if (!ownTextNodes(target).length) {
      var parent = target.parentElement;
      while (parent && parent !== document.body) {
        if (ownTextNodes(parent).length) { target = parent; break; }
        parent = parent.parentElement;
      }
    }

    // Mixed content (text interleaved with child elements, e.g.
    // "earned <span>1,204 views</span> this week") has no single source
    // literal — refuse up front so the user routes it to the agent.
    var hasElementChildren = false;
    for (var k = 0; k < target.childNodes.length; k++) {
      if (target.childNodes[k].nodeType === 1) { hasElementChildren = true; break; }
    }
    if (hasElementChildren) {
      send({ type: 'ERROR', message: 'dynamic-text' });
      toastDynamic();
      return;
    }

    editingNode = target;
    editingOriginalText = directTextNodes.map(function (n) { return n.nodeValue; }).join('');
    target.setAttribute('contenteditable', 'true');
    target.style.outline = '2px solid #f59e0b';
    target.focus();
    try {
      var range = document.createRange();
      range.selectNodeContents(target);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    } catch (err) { /* focus is enough */ }
  }

  function toastDynamic() {
    // small in-iframe hint; the parent also shows its own toast
    var t = document.createElement('div');
    t.setAttribute('data-' + BRIDGE_MARK, '1');
    t.textContent = 'Dynamic text — describe the change in chat';
    t.style.cssText =
      'position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:2147483647;' +
      'background:#f59e0b;color:#fff;font:600 12px/1.4 system-ui,sans-serif;' +
      'padding:6px 14px;border-radius:9999px;box-shadow:0 4px 12px rgba(0,0,0,.25);';
    document.documentElement.appendChild(t);
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 2600);
  }

  function onKeyDown(e) {
    if (mode !== 'text' || !editingNode) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      commitText(true);
    } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      e.stopPropagation();
      commitText(false);
    }
  }

  function onBlurText(e) {
    if (mode === 'text' && editingNode && e.target === editingNode) {
      commitText(false);
    }
  }

  // ---------------------------------------------------------------- commands

  function applyTempStyle(nodeId, css) {
    var el = elementForNodeId(nodeId);
    if (!el) return;
    if (!el.dataset.daTempStyle) {
      el.dataset.daTempStyle = '1';
      el.dataset.daPrevInline = el.getAttribute('style') || '';
    }
    for (var prop in css) {
      if (Object.prototype.hasOwnProperty.call(css, prop)) {
        try { el.style.setProperty(kebab(prop), String(css[prop])); } catch (e) { /* skip */ }
      }
    }
  }

  function clearTempStyle(nodeId) {
    var els = nodeId ? [elementForNodeId(nodeId)].filter(Boolean) :
      document.querySelectorAll('[data-da-temp-style]');
    els.forEach(function (el) {
      el.setAttribute('style', el.dataset.daPrevInline || '');
      delete el.dataset.daTempStyle;
      delete el.dataset.daPrevInline;
    });
  }

  function kebab(s) {
    return s.replace(/[A-Z]/g, function (m) { return '-' + m.toLowerCase(); });
  }

  function setMode(newMode) {
    if (editingNode) commitText(false);
    mode = newMode;
    clearChrome();
    if (mode !== 'select') clearSelectionChrome();
    var interactive = mode === 'select' || mode === 'text';
    document.documentElement.style.cursor = interactive ? 'crosshair' : '';
    // swallow link/navigation while selecting without breaking layout
    document.documentElement.dataset.daMode = mode;
  }

  function onMessage(e) {
    if (PARENT_ORIGINS.indexOf(e.origin) === -1) return;
    var msg = e.data;
    if (!msg || typeof msg !== 'object') return;
    switch (msg.type) {
      case 'SET_MODE':
        setMode(msg.mode || 'off');
        break;
      case 'SET_HOVER_LOCK':
        hoverLocked = !!msg.locked;
        if (hoverLocked) clearChrome();
        break;
      case 'APPLY_TEMP_STYLE':
        applyTempStyle(msg.nodeId, msg.css || {});
        break;
      case 'CLEAR_TEMP_STYLE':
        clearTempStyle(msg.nodeId);
        break;
      case 'PING':
        send({ type: 'READY' });
        break;
      case 'REQUEST_SCREENSHOT':
        // Screenshot capture is server-side (headless chromium); the bridge
        // does not implement DOM rasterization.
        send({ type: 'ERROR', message: 'screenshot not supported in-bridge' });
        break;
      default:
        break;
    }
  }

  // suppress link navigation during select/text modes without unbinding handlers
  document.addEventListener('click', function (e) {
    if (mode === 'select') onSelectClick(e);
    else if (mode === 'text') onTextClick(e);
  }, true);
  document.addEventListener('mousemove', onHoverMove, true);
  document.addEventListener('keydown', onKeyDown, true);
  document.addEventListener('focusout', onBlurText, true);
  window.addEventListener('message', onMessage);
  window.addEventListener('scroll', function () {
    clearChrome();
    // reposition selection chrome on scroll
    selectionBoxes.forEach(function (b) {
      var el = elementForNodeId(b.nodeId);
      if (el) {
        var r = el.getBoundingClientRect();
        placeBox(b.el, { x: r.left + window.scrollX, y: r.top + window.scrollY, w: r.width, h: r.height });
        if (b.labelEl) {
          b.labelEl.style.left = (r.left + window.scrollX) + 'px';
          b.labelEl.style.top = Math.max(r.top + window.scrollY - 16, 0) + 'px';
        }
      }
    });
  }, true);

  // prevent browser default save dialog while editing text (Cmd+S)
  window.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && mode !== 'off') {
      e.preventDefault();
    }
  }, true);

  function boot() {
    send({ type: 'READY', href: window.location.href });
  }
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(boot, 0);
  } else {
    document.addEventListener('DOMContentLoaded', boot);
  }
})();
