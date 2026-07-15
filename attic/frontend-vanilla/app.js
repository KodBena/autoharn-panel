// >>> PROVENANCE-STAMP >>> (auto; tools/hooks/stamp_provenance.py — do not hand-edit)
//   first-seen : 2026-07-15T01:02:13Z
//   last-change: 2026-07-15T01:02:13Z
//   contributors: a857c93d/main
// <<< PROVENANCE-STAMP <<<

// panel/frontend/app.js
//
// Vanilla, self-contained SPA against the frozen API contract (BUILD SPEC v2 sec 4, r5/round-4).
// No CDN, no build step, no external fetch beyond same-origin /api/*. Owned by WP-2.
//
// Frozen wire shapes this file depends on (do not hand-restate elsewhere — read live instead):
//   GET /api/health        -> {ok, deployment, stamp_secret_armed, maintainer_principal, verdicts, independence_values}
//   GET /api/commissions   -> [{row_id, statement, actor_name, ts, item_count}]
//   GET /api/commission/{row} -> {commission_row, commission, items:[Item]}
//     Item = {row_id, item_id, label, status, cosign, witnesses:[Witness], ambiguous_row_ids}
//     status in OPEN|WITNESSED|PARTIAL|COSIGNED|AMBIGUOUS
//     Witness = {ref_kind, ref, resolved, substantive, cosign_target_row, cosign}
//     cosign  = {cosigned, by, review_id, verdict}
//   GET /api/ledger/recent?n=
//   GET /api/work
//   GET /api/review-gap
//   GET /api/questions
//   GET /api/watermark -> {max_id, max_ts, count}
//   GET /api/events (SSE) -> {type:"ledger-change", watermark}
//   POST /api/cosign {row_id, verdict, independence, basis} -> {ok, exit_code, stdout, stderr, review_id}

(function () {
  "use strict";

  const state = {
    health: null,
    currentCommissionRow: null,
    watermark: null,
    sse: null,
    pollTimer: null,
  };

  // ---------- small utilities ----------

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === "class") node.className = attrs[k];
        else if (k === "text") node.textContent = attrs[k];
        else if (k.startsWith("on") && typeof attrs[k] === "function") node.addEventListener(k.slice(2), attrs[k]);
        else node.setAttribute(k, attrs[k]);
      }
    }
    (children || []).forEach((c) => {
      if (c === null || c === undefined) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function fmtTs(ts) {
    if (!ts) return "";
    return String(ts).replace("T", " ").replace(/\.\d+Z?$/, "").replace("Z", "");
  }

  async function api(path, opts) {
    const resp = await fetch(path, opts);
    let body = null;
    try {
      body = await resp.json();
    } catch (e) {
      // non-JSON body (should not happen for this API) -- surface the status instead of silently
      // swallowing it.
      throw new Error(`${path}: HTTP ${resp.status}, non-JSON response`);
    }
    if (!resp.ok && !("ok" in (body || {}))) {
      // most endpoints return a JSON error body with `detail`; surface it plainly.
      const detail = (body && (body.detail || body.error)) || resp.statusText;
      throw new Error(`${path}: HTTP ${resp.status} — ${detail}`);
    }
    return body;
  }

  function showGlobalError(msg) {
    const box = document.getElementById("global-error");
    box.innerHTML = "";
    if (!msg) return;
    box.appendChild(el("div", { class: "error-banner", text: msg }));
  }

  // ---------- health ----------

  async function loadHealth() {
    const h = await api("/api/health");
    state.health = h;
    document.getElementById("health-schema").textContent =
      `${h.deployment.schema}@${h.deployment.host_resolved ? "resolved" : "UNRESOLVED"} · db ${h.deployment.db}`;
    document.getElementById("health-stamp").textContent =
      `stamp secret: ${h.stamp_secret_armed ? "armed" : "NOT armed"} · maintainer: ${h.maintainer_principal}`;
    return h;
  }

  // ---------- commission picker + view ----------

  async function loadCommissions() {
    const list = await api("/api/commissions");
    const sel = document.getElementById("commission-select");
    sel.innerHTML = "";
    if (!list.length) {
      sel.appendChild(el("option", { text: "(no commissions found)" }));
      document.getElementById("commission-picker-note").textContent = "";
      return list;
    }
    list.forEach((c) => {
      const label = `#${c.row_id} — ${c.item_count} item(s) — ${truncate(c.statement, 70)}`;
      sel.appendChild(el("option", { value: String(c.row_id), text: label }));
    });
    document.getElementById("commission-picker-note").textContent = `${list.length} commission row(s)`;
    // default: keep current selection if present, else first in list, preferring the seeded 680
    // if it exists (a convenience default, not a hardcoded scope — the picker still lists all).
    const preferred = list.find((c) => c.row_id === 680) || list[0];
    if (state.currentCommissionRow && list.some((c) => c.row_id === state.currentCommissionRow)) {
      sel.value = String(state.currentCommissionRow);
    } else {
      sel.value = String(preferred.row_id);
      state.currentCommissionRow = preferred.row_id;
    }
    return list;
  }

  function truncate(s, n) {
    if (!s) return "";
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  async function loadCommissionView(rowId) {
    const body = document.getElementById("commission-body");
    if (rowId === null || rowId === undefined) {
      body.innerHTML = "";
      body.appendChild(el("p", { class: "empty-note", text: "Pick a commission above." }));
      return;
    }
    const data = await api(`/api/commission/${rowId}`);
    renderCommission(data);
  }

  function renderCommission(data) {
    const body = document.getElementById("commission-body");
    body.innerHTML = "";
    if (!data.commission) {
      body.appendChild(el("p", { class: "empty-note", text: `Commission row ${data.commission_row} not found.` }));
      return;
    }
    const meta = el("div", { class: "item-meta" }, [
      `row ${data.commission.id} · ${data.commission.actor_name || "(unknown actor)"} · ${fmtTs(data.commission.ts)}`,
    ]);
    body.appendChild(meta);
    body.appendChild(el("div", { class: "commission-text", text: data.commission.statement }));

    const list = el("div", { class: "item-list" });
    if (!data.items.length) {
      list.appendChild(el("p", { class: "empty-note", text: "No decomposition items authored for this commission yet." }));
    } else {
      data.items.forEach((item) => list.appendChild(renderItem(item)));
    }
    body.appendChild(list);
  }

  // ---------- item rendering ----------

  function badge(status) {
    return el("span", { class: `badge badge-${status}`, text: status });
  }

  function renderItem(item) {
    if (item.status === "AMBIGUOUS") {
      return renderAmbiguousItem(item);
    }
    const row = el("div", { class: "item-row" });
    const head = el("div", { class: "item-head" }, [
      el("span", { class: "item-id", text: item.item_id }),
      badge(item.status),
      el("span", { class: "item-label", text: item.label || "" }),
      el("span", { class: "item-meta" }, [`row ${item.row_id}${item.actor_name ? " · " + item.actor_name : ""}${item.ts ? " · " + fmtTs(item.ts) : ""}`]),
    ]);
    row.appendChild(head);

    // item-row fast-path co-sign control
    row.appendChild(cosignBlock(item.row_id, item.cosign, "co-sign this item (fast path)"));

    // witnesses
    if (item.witnesses && item.witnesses.length) {
      const wl = el("div", { class: "witness-list" });
      item.witnesses.forEach((w) => wl.appendChild(renderWitness(w)));
      row.appendChild(wl);
    }

    return row;
  }

  function renderWitness(w) {
    const wrap = el("div", { class: "witness-row" });
    const facts = el("div", { class: "witness-facts" }, [
      el("span", { class: "tag", text: `${w.ref_kind}:${w.ref}` }),
      el("span", { text: w.resolved ? "resolves" : "does not resolve" }),
      el("span", { text: w.substantive ? "substantive" : "not substantive" }),
    ]);
    wrap.appendChild(facts);
    if (w.cosign_target_row !== null && w.cosign_target_row !== undefined) {
      wrap.appendChild(cosignBlock(w.cosign_target_row, w.cosign, "co-sign this witness"));
    } else {
      wrap.appendChild(el("span", { class: "muted", text: "(no target row yet — witness not resolved to a co-signable row)" }));
    }
    return wrap;
  }

  function renderAmbiguousItem(item) {
    const row = el("div", { class: "item-row ambiguous" });
    row.appendChild(el("div", { class: "item-head" }, [
      el("span", { class: "item-id", text: item.item_id }),
      badge("AMBIGUOUS"),
      el("span", { class: "item-label", text: "identity collision — two or more non-superseding rows claim this item id" }),
    ]));
    row.appendChild(el("p", { class: "muted", text:
      "The panel does not pick a winner. Each candidate row below is independently co-signable; " +
      "resolve the collision itself with a ledger --supersedes outside the panel." }));
    const wl = el("div", { class: "witness-list" });
    (item.ambiguous_row_ids || []).forEach((rid) => {
      const candWrap = el("div", { class: "witness-row" });
      candWrap.appendChild(el("div", { class: "witness-facts" }, [el("span", { class: "tag", text: `row:${rid}` })]));
      candWrap.appendChild(cosignBlock(rid, { cosigned: false, by: null, review_id: null, verdict: null }, "co-sign this candidate row"));
      wl.appendChild(candWrap);
    });
    row.appendChild(wl);
    return row;
  }

  // ---------- co-sign control ----------

  function cosignBlock(rowId, cosign, label) {
    const wrap = el("div", {});
    const status = cosign && cosign.cosigned
      ? el("div", { class: "cosign-inline" }, [
          el("span", { class: "badge badge-COSIGNED", text: "co-signed" }),
          el("span", { class: "muted mono", text: `by ${cosign.by || "?"} · review ${cosign.review_id} · ${cosign.verdict}` }),
        ])
      : cosignForm(rowId, label);
    wrap.appendChild(status);
    return wrap;
  }

  function cosignForm(rowId, label) {
    const container = el("div", { class: "cosign-inline" });
    const openBtn = el("button", { text: label || `co-sign row ${rowId}` });
    container.appendChild(openBtn);

    openBtn.addEventListener("click", () => {
      openBtn.style.display = "none";
      const h = state.health || { verdicts: ["self-review", "attest"], independence_values: ["self-review"], stamp_secret_armed: false };
      const verdictSel = el("select", {}, h.verdicts.map((v) => el("option", { value: v, text: v })));
      const indepSel = el("select", {}, h.independence_values.map((v) => el("option", { value: v, text: v })));
      if (h.independence_values.indexOf("self-review") !== -1) indepSel.value = "self-review";
      const basisInput = el("input", { type: "text", placeholder: "basis statement (why you are co-signing)" });
      const submitBtn = el("button", { class: "primary", text: "submit" });
      const cancelBtn = el("button", { text: "cancel" });
      const resultBox = el("div", {});

      const note = el("div", { class: "cosign-note", text:
        `technical/managerial/financial require a verified interception stamp; this deployment's stamp ` +
        `secret is ${h.stamp_secret_armed ? "armed" : "NOT armed"}. Your independence as maintainer is ` +
        `carried by the actor field (maintainer ≠ author), which is also what discharges the review ` +
        `obligation. A stamp-unprovable independence claim will be refused by the kernel — you will see ` +
        `the refusal verbatim below, not a paved-over success.` });

      const form = el("div", { class: "cosign-form" }, [
        el("label", { text: "verdict:" }), verdictSel,
        el("label", { text: "independence:" }), indepSel,
        basisInput,
        submitBtn, cancelBtn,
        note,
        resultBox,
      ]);
      container.appendChild(form);

      cancelBtn.addEventListener("click", () => {
        form.remove();
        openBtn.style.display = "";
      });

      submitBtn.addEventListener("click", async () => {
        submitBtn.disabled = true;
        resultBox.innerHTML = "";
        try {
          const body = {
            row_id: rowId,
            verdict: verdictSel.value,
            independence: indepSel.value,
            basis: basisInput.value || "(no basis text entered)",
          };
          const resp = await api("/api/cosign", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          const cls = resp.ok ? "ok" : "refused";
          resultBox.appendChild(el("div", { class: `cosign-result ${cls}` }, [
            `exit_code=${resp.exit_code}\n` +
            (resp.stdout ? `stdout:\n${resp.stdout}\n` : "") +
            (resp.stderr ? `stderr:\n${resp.stderr}\n` : "") +
            (resp.review_id ? `review_id=${resp.review_id}\n` : ""),
          ]));
          if (resp.ok) {
            // a successful co-sign changes ledger state -- refresh the open commission view so the
            // fast path / witness / candidate this control targeted reflects its new status. The SSE
            // watermark listener will also catch this, but refreshing immediately avoids a stale UI
            // in the window before the next poll/event fires.
            refreshOpenViews();
          }
        } catch (e) {
          resultBox.appendChild(el("div", { class: "cosign-result refused", text: String(e.message || e) }));
        } finally {
          submitBtn.disabled = false;
        }
      });
    });

    return container;
  }

  // ---------- ancillary views ----------

  async function loadLedgerRecent() {
    const rows = await api("/api/ledger/recent?n=50");
    const tbody = document.querySelector("#ledger-table tbody");
    tbody.innerHTML = "";
    rows.forEach((r) => {
      tbody.appendChild(el("tr", {}, [
        el("td", { class: "mono", text: String(r.id) }),
        el("td", { text: r.kind }),
        el("td", { text: r.actor_name || "" }),
        el("td", { class: "mono", text: fmtTs(r.ts) }),
        el("td", { text: r.stamp_verified ? "verified" : "unverified" }),
        el("td", { text: truncate(r.statement, 140) }),
      ]));
    });
  }

  async function loadWork() {
    const rows = await api("/api/work");
    const tbody = document.querySelector("#work-table tbody");
    tbody.innerHTML = "";
    rows.forEach((r) => {
      tbody.appendChild(el("tr", {}, [
        el("td", { class: "mono", text: r.slug || "" }),
        el("td", { text: r.state || "" }),
        el("td", { text: r.actor_name || "" }),
        el("td", { class: "mono", text: fmtTs(r.ts) }),
        el("td", { text: truncate(r.statement || "", 140) }),
      ]));
    });
  }

  async function loadReviewGap() {
    const rows = await api("/api/review-gap");
    const tbody = document.querySelector("#review-gap-table tbody");
    tbody.innerHTML = "";
    if (!rows.length) {
      tbody.appendChild(el("tr", {}, [el("td", { colspan: "5", class: "empty-note", text: "No review gaps." })]));
      return;
    }
    rows.forEach((r) => {
      tbody.appendChild(el("tr", {}, [
        el("td", { class: "mono", text: String(r.id) }),
        el("td", { text: r.kind || "" }),
        el("td", { text: r.actor_name || "" }),
        el("td", { class: "mono", text: fmtTs(r.ts) }),
        el("td", { text: truncate(r.statement || "", 140) }),
      ]));
    });
  }

  async function loadQuestions() {
    const rows = await api("/api/questions");
    const tbody = document.querySelector("#questions-table tbody");
    tbody.innerHTML = "";
    rows.forEach((r) => {
      tbody.appendChild(el("tr", {}, [
        el("td", { class: "mono", text: String(r.id) }),
        el("td", { text: r.status || "" }),
        el("td", { text: r.actor_name || "" }),
        el("td", { class: "mono", text: fmtTs(r.ts) }),
        el("td", { text: truncate(r.statement || "", 140) }),
      ]));
    });
  }

  async function refreshOpenViews() {
    const rowId = state.currentCommissionRow;
    const tasks = [
      loadCommissionView(rowId).catch((e) => showGlobalError(String(e.message || e))),
      loadCommissions().catch(() => {}),
      loadLedgerRecent().catch(() => {}),
      loadWork().catch(() => {}),
      loadReviewGap().catch(() => {}),
      loadQuestions().catch(() => {}),
    ];
    await Promise.all(tasks);
  }

  // ---------- live update: SSE with polling fallback ----------

  function setLiveStatus(mode) {
    const dot = document.getElementById("live-dot");
    const label = document.getElementById("live-label");
    dot.className = "dot " + mode;
    label.textContent = mode === "live" ? "live (SSE)" : mode === "polling" ? "polling (~2s)" : "disconnected";
  }

  function startSSE() {
    try {
      const src = new EventSource("/api/events");
      state.sse = src;
      src.addEventListener("open", () => setLiveStatus("live"));
      src.addEventListener("message", (ev) => {
        setLiveStatus("live");
        try {
          const payload = JSON.parse(ev.data);
          if (payload && payload.type === "ledger-change") {
            refreshOpenViews();
          }
        } catch (e) {
          // a malformed SSE payload is not fatal to the view -- log and keep the connection.
          console.warn("panel: unparseable SSE payload", ev.data);
        }
      });
      src.addEventListener("error", () => {
        setLiveStatus("polling");
        src.close();
        state.sse = null;
        startPolling();
      });
    } catch (e) {
      setLiveStatus("polling");
      startPolling();
    }
  }

  function startPolling() {
    if (state.pollTimer) return;
    setLiveStatus("polling");
    state.pollTimer = setInterval(async () => {
      try {
        const wm = await api("/api/watermark");
        if (!state.watermark || wm.max_id !== state.watermark.max_id || wm.count !== state.watermark.count) {
          state.watermark = wm;
          refreshOpenViews();
        }
      } catch (e) {
        setLiveStatus("down");
      }
    }, 2000);
  }

  // ---------- wiring ----------

  document.getElementById("commission-select").addEventListener("change", (ev) => {
    state.currentCommissionRow = Number(ev.target.value);
    loadCommissionView(state.currentCommissionRow).catch((e) => showGlobalError(String(e.message || e)));
  });

  document.getElementById("refresh-commission-btn").addEventListener("click", () => {
    refreshOpenViews();
  });

  async function boot() {
    try {
      await loadHealth();
      await loadCommissions();
      await loadCommissionView(state.currentCommissionRow);
      await Promise.all([loadLedgerRecent(), loadWork(), loadReviewGap(), loadQuestions()]);
      setLiveStatus("polling");
      startSSE();
    } catch (e) {
      showGlobalError(`Failed to load panel: ${e.message || e}`);
    }
  }

  boot();
})();
