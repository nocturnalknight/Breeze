const appState = {
  dashboard: null,
};

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  loadDashboard();
});

function bindEvents() {
  document.getElementById("profile-form").addEventListener("submit", onProfileSubmit);
  document.getElementById("watchlist-form").addEventListener("submit", onWatchlistSubmit);
  document.getElementById("order-form").addEventListener("submit", onOrderSubmit);
  document.getElementById("alert-form").addEventListener("submit", onAlertSubmit);
  document.getElementById("refresh-watchlist").addEventListener("click", onRefreshWatchlist);
  document.getElementById("reset-paper").addEventListener("click", onResetPaper);
  document.body.addEventListener("click", onBodyClick);
}

async function request(path, options = {}) {
  const config = {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  };
  const response = await fetch(path, config);
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : null;
  if (!response.ok) {
    throw new Error(payload?.detail || `Request failed with status ${response.status}`);
  }
  return payload;
}

async function loadDashboard(message = "Desk refreshed.") {
  try {
    const dashboard = await request("/api/dashboard");
    appState.dashboard = dashboard;
    renderDashboard(dashboard);
    setStatus(message, "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function renderDashboard(dashboard) {
  renderBrokerStatus(dashboard);
  renderOverview(dashboard.profile, dashboard.portfolio);
  renderProfile(dashboard.profile);
  renderWatchlist(dashboard.watchlist);
  renderAlerts(dashboard.alerts);
  renderPositions(dashboard.portfolio.positions);
  renderOrders(dashboard.portfolio.recent_orders);
}

function renderBrokerStatus(dashboard) {
  const pill = document.getElementById("broker-pill");
  const copy = document.getElementById("broker-copy");
  if (dashboard.broker_configured) {
    pill.textContent = "Live broker ready";
    copy.textContent = "Live quote refresh is enabled through Breeze. Orders remain paper-only in this scaffold.";
  } else {
    pill.textContent = "Paper mode only";
    copy.textContent = "Manual watchlist prices and simulated execution are active. Add Breeze credentials when you want live quote refresh.";
  }
}

function renderOverview(profile, portfolio) {
  const cards = [
    ["Cash Balance", formatMoney(portfolio.cash_balance)],
    ["Account Value", formatMoney(portfolio.account_value)],
    ["Open Positions", String(portfolio.open_positions_count)],
    ["Max Position", formatMoney(profile.max_position_value)],
    ["Drawdown", formatMoney(portfolio.drawdown), portfolio.drawdown > 0 ? "negative" : ""],
    ["Total P&L", formatSignedMoney(portfolio.total_pnl), portfolio.total_pnl >= 0 ? "positive" : "negative"],
    ["Unrealized", formatSignedMoney(portfolio.total_unrealized_pnl), portfolio.total_unrealized_pnl >= 0 ? "positive" : "negative"],
    ["Realized", formatSignedMoney(portfolio.total_realized_pnl), portfolio.total_realized_pnl >= 0 ? "positive" : "negative"],
  ];

  document.getElementById("overview-cards").innerHTML = cards
    .map(
      ([label, value, tone]) => `
        <article class="metric-card">
          <span>${escapeHtml(label)}</span>
          <strong class="${tone || ""}">${escapeHtml(value)}</strong>
        </article>
      `
    )
    .join("");
}

function renderProfile(profile) {
  const form = document.getElementById("profile-form");
  form.display_name.value = profile.display_name || "";
  form.trading_style.value = profile.trading_style || "";
  form.preferred_exchange.value = profile.preferred_exchange || "NSE";
  form.default_order_quantity.value = profile.default_order_quantity || 1;
  form.max_open_positions.value = profile.max_open_positions || 1;
  form.max_position_value.value = profile.max_position_value || 0;
  form.max_drawdown_limit.value = profile.max_drawdown_limit || 0;
  form.paper_starting_cash.value = profile.paper_starting_cash || 0;
  form.notes.value = profile.notes || "";

  const orderForm = document.getElementById("order-form");
  if (!orderForm.quantity.value) {
    orderForm.quantity.value = profile.default_order_quantity || 1;
  }
}

function renderWatchlist(items) {
  const tbody = document.getElementById("watchlist-body");
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state">No watchlist symbols yet. Add the instruments you actually trade.</div></td></tr>`;
    return;
  }

  tbody.innerHTML = items
    .map((item) => {
      const lastPrice = item.last_price == null ? "Set manually or refresh live" : formatMoney(item.last_price);
      return `
        <tr>
          <td>
            <button
              class="symbol-button"
              type="button"
              data-action="prefill-ticket"
              data-symbol="${escapeHtml(item.symbol)}"
              data-exchange="${escapeHtml(item.exchange)}"
              data-product-type="${escapeHtml(item.product_type)}"
              data-price="${escapeHtml(item.last_price ?? "")}"
            >
              ${escapeHtml(item.symbol)}
            </button>
            <span class="subtext">${escapeHtml(item.exchange)} / ${escapeHtml(item.product_type)}</span>
          </td>
          <td>${escapeHtml(lastPrice)}</td>
          <td>${escapeHtml(item.notes || "-")}</td>
          <td>${escapeHtml(formatTimestamp(item.last_synced_at))}</td>
          <td>
            <div class="actions-row">
              <button class="button button-ghost button-inline" type="button" data-action="set-price" data-id="${item.id}">Set price</button>
              <button class="button button-ghost button-inline" type="button" data-action="refresh-item" data-id="${item.id}">Refresh</button>
              <button class="button button-ghost button-inline" type="button" data-action="delete-watch" data-id="${item.id}">Remove</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderAlerts(alerts) {
  const container = document.getElementById("alerts-list");
  if (!alerts.length) {
    container.innerHTML = `<div class="empty-state">No alerts yet. Add price levels that map to your setups.</div>`;
    return;
  }

  container.innerHTML = alerts
    .map((alert) => {
      const latest = alert.latest_price == null ? "No tracked price yet" : formatMoney(alert.latest_price);
      return `
        <article class="alert-card ${alert.triggered ? "triggered" : ""}">
          <div>
            <strong>${escapeHtml(alert.symbol)} ${escapeHtml(alert.exchange)} / ${escapeHtml(alert.product_type)}</strong>
            <p class="subtext">
              Trigger when price moves ${escapeHtml(alert.trigger_type)} ${escapeHtml(formatMoney(alert.trigger_price))}.
            </p>
            <p class="subtext">Latest tracked price: ${escapeHtml(latest)}</p>
            <p class="subtext">${escapeHtml(alert.note || "No note")}</p>
          </div>
          <div class="actions-row">
            ${
              alert.triggered
                ? `<span class="pill">Triggered</span>`
                : ""
            }
            <button class="button button-ghost button-inline" type="button" data-action="delete-alert" data-id="${alert.id}">
              Remove
            </button>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderPositions(positions) {
  const tbody = document.getElementById("positions-body");
  if (!positions.length) {
    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state">No open paper positions.</div></td></tr>`;
    return;
  }

  tbody.innerHTML = positions
    .map(
      (position) => `
        <tr>
          <td>
            <button
              class="symbol-button"
              type="button"
              data-action="prefill-ticket"
              data-symbol="${escapeHtml(position.symbol)}"
              data-exchange="${escapeHtml(position.exchange)}"
              data-product-type="${escapeHtml(position.product_type)}"
              data-price="${escapeHtml(position.mark_price)}"
            >
              ${escapeHtml(position.symbol)}
            </button>
            <span class="subtext">${escapeHtml(position.exchange)} / ${escapeHtml(position.product_type)}</span>
          </td>
          <td>${escapeHtml(String(position.quantity))}</td>
          <td>${escapeHtml(formatMoney(position.avg_price))}</td>
          <td>${escapeHtml(formatMoney(position.mark_price))}</td>
          <td class="${position.unrealized_pnl >= 0 ? "positive" : "negative"}">${escapeHtml(formatSignedMoney(position.unrealized_pnl))}</td>
          <td>${escapeHtml(formatMoney(position.market_value))}</td>
        </tr>
      `
    )
    .join("");
}

function renderOrders(orders) {
  const tbody = document.getElementById("orders-body");
  if (!orders.length) {
    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state">No paper orders executed yet.</div></td></tr>`;
    return;
  }

  tbody.innerHTML = orders
    .map(
      (order) => `
        <tr>
          <td>${escapeHtml(formatTimestamp(order.created_at))}</td>
          <td>${escapeHtml(order.symbol)} <span class="subtext">${escapeHtml(order.exchange)} / ${escapeHtml(order.product_type)}</span></td>
          <td class="${order.side === "buy" ? "positive" : "negative"}">${escapeHtml(order.side.toUpperCase())}</td>
          <td>${escapeHtml(String(order.quantity))}</td>
          <td>${escapeHtml(formatMoney(order.price))}</td>
          <td class="${order.realized_pnl >= 0 ? "positive" : "negative"}">${escapeHtml(formatSignedMoney(order.realized_pnl))}</td>
        </tr>
      `
    )
    .join("");
}

async function onProfileSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    display_name: form.display_name.value,
    trading_style: form.trading_style.value,
    preferred_exchange: form.preferred_exchange.value,
    default_order_quantity: Number(form.default_order_quantity.value),
    max_open_positions: Number(form.max_open_positions.value),
    max_position_value: Number(form.max_position_value.value),
    max_drawdown_limit: Number(form.max_drawdown_limit.value),
    paper_starting_cash: Number(form.paper_starting_cash.value),
    notes: form.notes.value,
  };
  try {
    await request("/api/profile", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    await loadDashboard("Profile updated.");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function onWatchlistSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    symbol: form.symbol.value,
    exchange: form.exchange.value,
    product_type: form.product_type.value,
    notes: form.notes.value,
  };
  try {
    await request("/api/watchlist", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    form.reset();
    form.exchange.value = appState.dashboard?.profile?.preferred_exchange || "NSE";
    form.product_type.value = "cash";
    await loadDashboard("Watchlist updated.");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function onOrderSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    symbol: form.symbol.value,
    exchange: form.exchange.value,
    product_type: form.product_type.value,
    side: form.side.value,
    quantity: Number(form.quantity.value),
    price: Number(form.price.value),
    notes: form.notes.value,
  };
  try {
    await request("/api/paper/orders", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    form.notes.value = "";
    await loadDashboard("Paper order executed.");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function onAlertSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    symbol: form.symbol.value,
    exchange: form.exchange.value,
    product_type: form.product_type.value,
    trigger_type: form.trigger_type.value,
    trigger_price: Number(form.trigger_price.value),
    note: form.note.value,
  };
  try {
    await request("/api/alerts", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    form.reset();
    form.exchange.value = appState.dashboard?.profile?.preferred_exchange || "NSE";
    form.product_type.value = "cash";
    form.trigger_type.value = "above";
    await loadDashboard("Alert created.");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function onRefreshWatchlist() {
  try {
    await request("/api/watchlist/refresh", {
      method: "POST",
    });
    await loadDashboard("Watchlist quotes refreshed.");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function onResetPaper() {
  const confirmed = window.confirm("Reset the paper account and clear positions and order history?");
  if (!confirmed) {
    return;
  }
  try {
    await request("/api/paper/reset", {
      method: "POST",
    });
    await loadDashboard("Paper account reset.");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function onBodyClick(event) {
  const target = event.target.closest("[data-action]");
  if (!target) {
    return;
  }

  const action = target.dataset.action;
  try {
    if (action === "delete-watch") {
      await request(`/api/watchlist/${target.dataset.id}`, { method: "DELETE" });
      await loadDashboard("Watchlist item removed.");
    } else if (action === "refresh-item") {
      await request(`/api/watchlist/${target.dataset.id}/refresh`, { method: "POST" });
      await loadDashboard("Quote refreshed.");
    } else if (action === "set-price") {
      const value = window.prompt("Enter the latest price");
      if (!value) {
        return;
      }
      await request(`/api/watchlist/${target.dataset.id}/price`, {
        method: "POST",
        body: JSON.stringify({ price: Number(value) }),
      });
      await loadDashboard("Watchlist price updated.");
    } else if (action === "delete-alert") {
      await request(`/api/alerts/${target.dataset.id}`, { method: "DELETE" });
      await loadDashboard("Alert removed.");
    } else if (action === "prefill-ticket") {
      prefillTicket(target.dataset);
      setStatus(`Ticket loaded for ${target.dataset.symbol}.`, "success");
    }
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function prefillTicket(dataset) {
  const orderForm = document.getElementById("order-form");
  orderForm.symbol.value = dataset.symbol || "";
  orderForm.exchange.value = dataset.exchange || appState.dashboard?.profile?.preferred_exchange || "NSE";
  orderForm.product_type.value = dataset.productType || "cash";
  if (dataset.price) {
    orderForm.price.value = dataset.price;
  }

  const alertForm = document.getElementById("alert-form");
  alertForm.symbol.value = dataset.symbol || "";
  alertForm.exchange.value = dataset.exchange || appState.dashboard?.profile?.preferred_exchange || "NSE";
  alertForm.product_type.value = dataset.productType || "cash";
}

function setStatus(message, tone = "info") {
  const bar = document.getElementById("status-bar");
  bar.textContent = message;
  bar.className = `status-bar status-${tone}`;
}

function formatMoney(value) {
  return Number(value).toLocaleString(undefined, {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  });
}

function formatSignedMoney(value) {
  const amount = Number(value);
  const prefix = amount > 0 ? "+" : "";
  return `${prefix}${formatMoney(amount)}`;
}

function formatTimestamp(value) {
  if (!value) {
    return "Not synced";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
