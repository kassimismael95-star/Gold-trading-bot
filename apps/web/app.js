
"use strict";

let token = localStorage.getItem("gold_token") || "";
let refreshToken = sessionStorage.getItem("gold_refresh_token") || "";

const el = (id) => document.getElementById(id);

async function api(path, opts = {}) {
  const send = (access) => fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(access ? { Authorization: "Bearer " + access } : {}),
      ...(opts.headers || {})
    }
  });

  let response = await send(token);

  if (
    response.status === 401 &&
    refreshToken &&
    !path.endsWith("/auth/refresh") &&
    !path.endsWith("/auth/logout")
  ) {
    try {
      const refreshed = await fetch("/api/auth/refresh", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + refreshToken,
          "Content-Type": "application/json"
        },
        body: "{}"
      });

      if (refreshed.ok) {
        const data = await refreshed.json();
        token = data.access_token;
        localStorage.setItem("gold_token", token);
        response = await send(token);
      } else {
        refreshToken = "";
        sessionStorage.removeItem("gold_refresh_token");
      }
    } catch {
      // The original response is returned if refresh fails.
    }
  }

  return response;
}

function ensureAccountModeControl() {
  const labelInput = el("label");
  if (!labelInput) return;

  const section = labelInput.closest("section");
  if (!section) return;

  const heading = section.querySelector("h2");
  if (heading) heading.textContent = "Register an MT5 account";

  if (!el("accountMode")) {
    const grid = section.querySelector(".grid");
    if (grid) {
      const wrapper = document.createElement("div");
      wrapper.innerHTML = `
        <label for="accountMode">Account type</label>
        <select id="accountMode">
          <option value="demo">Demo account</option>
          <option value="live">Real money account</option>
        </select>
        <p class="muted">
          Real-money trading requires server authorization, EA live-trading
          permission, broker permission and your separate confirmation.
        </p>
      `;
      grid.appendChild(wrapper);
    }
  }

  const addButton = section.querySelector("button");
  if (addButton) addButton.textContent = "Register MT5 account";
}

async function check() {
  try {
    const response = await fetch("/api/health/live");
    if (el("apiState")) {
      el("apiState").textContent = response.ok ? "API online" : "API issue";
    }
  } catch {
    if (el("apiState")) el("apiState").textContent = "API offline";
  }
}

async function auth(kind) {
  const email = el("email")?.value.trim() || "";
  const password = el("password")?.value || "";

  const response = await api("/api/auth/" + kind, {
    method: "POST",
    body: JSON.stringify({ email, password })
  });

  const data = await response.json();

  if (el("authMsg")) {
    el("authMsg").textContent =
      data.error ||
      data.message ||
      (data.access_token ? "Signed in." : "Check your email for the verification code.");
  }

  if (response.ok && data.access_token) {
    token = data.access_token;
    localStorage.setItem("gold_token", token);

    refreshToken = data.refresh_token || refreshToken;
    if (refreshToken) {
      sessionStorage.setItem("gold_refresh_token", refreshToken);
    }

    await loadAccounts();
    await loadLicence();
    await loadSubscriptionStatus();
    await checkAdmin();
  }
}

async function addAccount() {
  const mode = el("accountMode")?.value || "demo";

  if (mode === "live") {
    const confirmed = confirm(
      "You are registering a REAL MONEY MT5 account.\n\n" +
      "Real trades can lose money. Registration does not guarantee " +
      "that live trading is enabled.\n\nContinue?"
    );

    if (!confirmed) return;
  }

  const data = {
    label: el("label")?.value.trim() || "",
    login: el("login")?.value.trim() || "",
    server: el("server")?.value.trim() || "",
    mt5_password: el("mt5Password")?.value || "",
    symbol: el("symbol")?.value.trim() || "AUTO",
    mode
  };

  if (
    !data.label ||
    !data.login ||
    !data.server ||
    !data.mt5_password
  ) {
    alert("Complete the account label, MT5 login, server and trading password.");
    return;
  }

  const response = await api("/api/accounts", {
    method: "POST",
    body: JSON.stringify(data)
  });

  const result = await response.json();

  if (response.ok) {
    if (el("mt5Password")) el("mt5Password").value = "";

    const tokenValue = result.ea_token || "";

    if (tokenValue) {
      prompt(
        "Your EA account token is shown only once. Copy it into InpAccountToken in the EA settings.",
        tokenValue
      );
    }

    alert(
      mode === "live"
        ? "Real-money account registered. Live trading is not started automatically. Complete the EA and server authorization steps first."
        : "Demo account registered. Copy the EA token into the EA settings."
    );

    await loadAccounts();
  } else {
    alert(result.error || "Account registration failed.");
  }
}

async function loadAccounts() {
  const box = el("accounts");
  if (!box) return;

  try {
    const response = await api("/api/accounts");
    const result = await response.json();

    if (!response.ok) {
      box.innerHTML = "<p class='muted'>Sign in first.</p>";
      return;
    }

    const accounts = result.accounts || [];

    if (!accounts.length) {
      box.innerHTML = "<p>No accounts registered.</p>";
      return;
    }

    box.innerHTML = accounts.map(account => {
      const mode = String(account.mode || "demo").toLowerCase();
      const telemetry = account.telemetry || {};
      const deleted = Boolean(account.is_deleted);

      const accountStatus = `
        <p>
          Desired: ${escapeHtml(account.desired_state || "UNKNOWN")}
          |
          Actual: ${escapeHtml(account.actual_state || "UNKNOWN")}
        </p>
        <p>
          ${telemetry.connected_to_broker
            ? "Broker connected"
            : "Broker disconnected"}
        </p>
        <p>
          Balance: ${escapeHtml(telemetry.balance ?? "—")}
          · Equity: ${escapeHtml(telemetry.equity ?? "—")}
          · Floating P/L: ${escapeHtml(telemetry.floating_pnl ?? "—")}
          · Positions: ${escapeHtml(telemetry.open_positions_count ?? "—")}
        </p>
      `;

      const removalMessage = `
        <p class="muted">
          New entries are disabled. The assigned EA must continue managing
          existing positions until the account is flat and safely disconnected.
        </p>
        <button class="secondary"
          onclick="command(${account.id}, 'CLOSE_ALL')">
          Close all positions
        </button>
      `;

      const controls = `
        <button onclick="command(${account.id}, 'START')">
          Start ${mode === "live" ? "REAL" : "DEMO"}
        </button>

        <button class="secondary"
          onclick="command(${account.id}, 'STOP')">
          Stop new entries
        </button>

        <button class="secondary"
          onclick="command(${account.id}, 'CLOSE_ALL')">
          Close all & stop
        </button>

        <button class="secondary"
          onclick="command(${account.id}, 'EMERGENCY_STOP')">
          Emergency stop
        </button>

        <button class="secondary"
          onclick="command(${account.id}, 'EMERGENCY_RESET')">
          Reset emergency stop
        </button>

        <button class="secondary"
          onclick="editRisk(${account.id})">
          Risk settings
        </button>

        <button class="secondary"
          onclick="updateCredential(${account.id})">
          Update MT5 password
        </button>

        <button class="secondary"
          onclick="regenerateToken(${account.id})">
          Regenerate EA token
        </button>

        <button class="secondary"
          onclick="removeAccount(${account.id})">
          Remove account
        </button>
      `;

      return `
        <article class="account">
          <h3>
            ${escapeHtml(account.label)}
            · ${mode === "live" ? "REAL MONEY" : "DEMO"}
            ${deleted ? " · REMOVING" : ""}
          </h3>

          <p>API account ID: ${account.id}</p>

          <p>
            MT5 ${escapeHtml(account.login)}
            · ${escapeHtml(account.server)}
            · ${escapeHtml(account.symbol)}
          </p>

          ${accountStatus}

          ${deleted ? removalMessage : controls}
        </article>
      `;
    }).join("");
  } catch {
    box.innerHTML = "<p class='muted'>Could not load accounts. Check the API connection.</p>";
  }
}

async function command(id, name) {
  if (name === "START") {
    const accountsResponse = await api("/api/accounts");
    const accountsData = await accountsResponse.json();

    const account = (accountsData.accounts || []).find(a => a.id === id);
    if (!account) {
      alert("Account not found. Refresh the account list.");
      return;
    }

    if (String(account.mode).toLowerCase() === "live") {
      const confirmed = confirm(
        "LIVE TRADING CONFIRMATION\n\n" +
        "This account uses REAL MONEY.\n" +
        "The EA may open real trades after all server and EA checks pass.\n" +
        "Losses are possible.\n\n" +
        "Confirm that you intentionally want to start this live account."
      );

      if (!confirmed) return;

      const secondConfirmation = prompt(
        "Type START LIVE to confirm real-money trading:"
      );

      if (secondConfirmation !== "START LIVE") {
        alert("Live start cancelled.");
        return;
      }
    } else {
      if (!confirm("Start trading on this demo account?")) return;
    }
  }

  if (name === "CLOSE_ALL") {
    if (!confirm(
      "Close all open positions on this account and stop new entries?"
    )) return;
  }

  if (name === "EMERGENCY_STOP") {
    if (!confirm(
      "Emergency stop will stop new entries. The EA should continue managing existing positions. Continue?"
    )) return;
  }

  if (name === "EMERGENCY_RESET") {
    if (!confirm(
      "Reset the emergency stop latch?\n\n" +
      "This does not start trading. You must separately press START."
    )) return;
  }

  if (name === "STOP" && !confirm("Stop new entries on this account?")) {
    return;
  }

  const response = await api(`/api/accounts/${id}/commands`, {
    method: "POST",
    body: JSON.stringify({ command: name })
  });

  const result = await response.json();

  if (response.ok) {
    alert(`${name} command queued. The EA must receive and acknowledge it.`);
  } else {
    alert(result.error || `Could not queue ${name}.`);
  }

  await loadAccounts();
}

async function removeAccount(id) {
  if (!confirm(
    "Remove this MT5 account?\n\n" +
    "New entries will stop. If positions remain open, the assigned EA " +
    "must keep managing them until the account is flat and connected."
  )) return;

  const response = await api(`/api/accounts/${id}`, {
    method: "DELETE"
  });

  const result = await response.json();

  if (response.ok) {
    alert(
      result.removal_pending
        ? "Removal is pending. Existing positions must remain managed until flat."
        : "Account removed from your active account list."
    );
  } else {
    alert(result.error || "Account removal failed.");
  }

  await loadAccounts();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[character]);
}

async function plans() {
  try {
    const response = await fetch("/api/plans");
    const result = await response.json();
    const box = el("plans");

    if (!box) return;

    if (!response.ok || !Array.isArray(result.plans)) {
      box.textContent = "Plans are currently unavailable.";
      return;
    }

    box.innerHTML = result.plans.map(plan => `
      <div class="plan">
        <b>$${escapeHtml(plan.amount)} USD</b>
        <p>${escapeHtml(plan.duration_days)} days</p>
        <button onclick="buy('${escapeHtml(plan.code)}')">Subscribe</button>
      </div>
    `).join("");
  } catch {
    if (el("plans")) el("plans").textContent = "Could not load plans.";
  }
}

async function buy(code) {
  const response = await api("/api/payments/flutterwave/initialize", {
    method: "POST",
    body: JSON.stringify({
      plan_code: code,
      currency: "USD"
    })
  });

  const result = await response.json();

  if (response.ok && result.checkout_url) {
    location.href = result.checkout_url;
  } else {
    alert(result.error || "Could not initialize payment.");
  }
}

async function activateLicence() {
  const code = el("licenseCode")?.value.trim() || "";

  if (!code) {
    if (el("licenceState")) {
      el("licenceState").textContent = "Enter a licence code.";
    }
    return;
  }

  const response = await api("/api/licences/activate", {
    method: "POST",
    body: JSON.stringify({ code })
  });

  const result = await response.json();

  if (el("licenceState")) {
    el("licenceState").textContent = response.ok
      ? `Licence active: ${result.code || code}${result.expires_at ? " · expires " + result.expires_at : ""}`
      : (result.error || "Activation failed.");
  }
}

async function loadLicence() {
  const response = await api("/api/licences/status");
  const result = await response.json();

  if (!el("licenceState")) return;

  el("licenceState").textContent = response.ok
    ? (
      result.active
        ? `Active: ${result.code}${result.expires_at ? " · expires " + result.expires_at : ""}`
        : `No active licence · trial uses ${result.trial_uses || 0}/2`
    )
    : (result.error || "Sign in first.");
}

async function loadSubscriptionStatus() {
  const response = await api("/api/subscriptions/status");
  const result = await response.json();
  const box = el("subscriptionState");

  if (!box) return;

  box.textContent = response.ok
    ? (
      result.active
        ? `${result.subscription.plan_code} · expires ${result.subscription.expires_at} · ${result.subscription.days_remaining} days left`
        : "No paid subscription active"
    )
    : (result.error || "Sign in first.");
}

async function regenerateToken(id) {
  if (!confirm(
    "Regenerating the EA token invalidates the old token. Continue?"
  )) return;

  const response = await api(
    `/api/accounts/${id}/ea-token/regenerate`,
    {
      method: "POST",
      body: "{}"
    }
  );

  const result = await response.json();

  if (response.ok) {
    prompt(
      "New EA token. Replace InpAccountToken in the EA settings:",
      result.ea_token
    );
  } else {
    alert(result.error || "Could not regenerate token.");
  }
}

async function verifyEmail() {
  const response = await api("/api/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({
      email: el("email")?.value || "",
      code: el("verifyCode")?.value.trim() || ""
    })
  });

  const result = await response.json();

  if (el("authMsg")) {
    el("authMsg").textContent = result.error || "Email verified.";
  }

  if (response.ok && result.access_token) {
    token = result.access_token;
    localStorage.setItem("gold_token", token);

    refreshToken = result.refresh_token || refreshToken;
    if (refreshToken) {
      sessionStorage.setItem("gold_refresh_token", refreshToken);
    }

    await loadAccounts();
    await loadLicence();
    await loadSubscriptionStatus();
    await checkAdmin();
  }
}

async function resendVerification() {
  const response = await api("/api/auth/verification/resend", {
    method: "POST",
    body: JSON.stringify({
      email: el("email")?.value || ""
    })
  });

  const result = await response.json();

  if (el("authMsg")) {
    el("authMsg").textContent = result.error || result.message || "";
  }
}

async function requestPasswordReset() {
  const response = await api("/api/auth/password-reset/request", {
    method: "POST",
    body: JSON.stringify({
      email: el("email")?.value || ""
    })
  });

  const result = await response.json();

  if (el("authMsg")) {
    el("authMsg").textContent = result.message || result.error || "";
  }
}

async function confirmPasswordReset() {
  const response = await api("/api/auth/password-reset/confirm", {
    method: "POST",
    body: JSON.stringify({
      email: el("email")?.value || "",
      code: el("resetCode")?.value.trim() || "",
      new_password: el("newPassword")?.value || ""
    })
  });

  const result = await response.json();

  if (el("authMsg")) {
    el("authMsg").textContent = result.message || result.error || "";
  }
}

async function loadPaymentsHistory() {
  const response = await api("/api/dashboard/payments");
  const result = await response.json();
  const box = el("paymentHistory");

  if (!box) return;

  box.textContent = response.ok
    ? JSON.stringify(result, null, 2)
    : (result.error || "Sign in to view payment history.");
}

async function logout() {
  try {
    const response = await api("/api/auth/logout", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken })
    });

    if (!response.ok && refreshToken) {
      await fetch("/api/auth/logout-refresh", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + refreshToken,
          "Content-Type": "application/json"
        },
        body: "{}"
      });
    }
  } catch {
    // Clear local session even if the API is unavailable.
  }

  token = "";
  refreshToken = "";

  localStorage.removeItem("gold_token");
  sessionStorage.removeItem("gold_refresh_token");

  if (el("accounts")) {
    el("accounts").innerHTML = "<p class='muted'>Signed out.</p>";
  }

  if (el("adminPanel")) el("adminPanel").hidden = true;
}

async function loadTradeHistory() {
  const response = await api("/api/dashboard/trades");
  const result = await response.json();
  const box = el("paymentHistory");

  if (!box) return;

  box.textContent = response.ok
    ? JSON.stringify(result, null, 2)
    : (result.error || "Sign in to view trades.");
}

async function editRisk(id) {
  const accountsResponse = await api("/api/accounts");
  const accountsData = await accountsResponse.json();

  if (!accountsResponse.ok) {
    alert(accountsData.error || "Could not load account settings.");
    return;
  }

  const account = (accountsData.accounts || []).find(a => a.id === id);

  if (!account) {
    alert("Account not found.");
    return;
  }

  const defaults = {
    max_positions: 0,
    one_entry_per_m1_bar: false
  };

  const current = {
    ...defaults,
    ...(account.risk_settings || {})
  };

  const raw = prompt(
    "Enter settings as JSON.\n\n" +
    "Supported settings:\n" +
    "max_positions: integer from 0 to 18\n" +
    "one_entry_per_m1_bar: true or false\n\n" +
    "Use 0 for no additional position-count limit.\n\n" +
    "Current settings:",
    JSON.stringify(current, null, 2)
  );

  if (raw === null) return;

  let payload;

  try {
    payload = JSON.parse(raw);
  } catch {
    alert("Invalid JSON.");
    return;
  }

  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload)
  ) {
    alert("Settings must be a JSON object.");
    return;
  }

  const allowed = ["max_positions", "one_entry_per_m1_bar"];
  const unsupported = Object.keys(payload).filter(
    key => !allowed.includes(key)
  );

  if (unsupported.length) {
    alert("Unsupported settings: " + unsupported.join(", "));
    return;
  }

  if (
    payload.max_positions !== undefined &&
    (
      !Number.isInteger(payload.max_positions) ||
      payload.max_positions < 0 ||
      payload.max_positions > 18
    )
  ) {
    alert("max_positions must be an integer from 0 to 18.");
    return;
  }

  if (
    payload.one_entry_per_m1_bar !== undefined &&
    typeof payload.one_entry_per_m1_bar !== "boolean"
  ) {
    alert("one_entry_per_m1_bar must be true or false.");
    return;
  }

  const response = await api(`/api/accounts/${id}/commands`, {
    method: "POST",
    body: JSON.stringify({
      command: "SETTINGS",
      payload
    })
  });

  const result = await response.json();

  alert(
    response.ok
      ? "Settings command queued. The EA must receive and acknowledge it."
      : (result.error || "Could not update settings.")
  );

  await loadAccounts();
}

async function updateCredential(id) {
  const password = prompt(
    "Enter the new MT5 trading password. It will be encrypted by the API."
  );

  if (password === null) return;

  if (!password || password.length > 512) {
    alert("Enter a valid MT5 password.");
    return;
  }

  const response = await api(`/api/accounts/${id}/credentials`, {
    method: "PUT",
    body: JSON.stringify({ mt5_password: password })
  });

  const result = await response.json();

  alert(
    response.ok
      ? "Credential updated. The account is stopped. Review the account and start it again when ready."
      : (result.error || "Credential update failed.")
  );

  await loadAccounts();
}

async function initializeApp() {
  ensureAccountModeControl();
  await check();
  await plans();

  if (token) {
    await loadAccounts();
    await loadLicence();
    await loadSubscriptionStatus();
    await checkAdmin();
  }

  setInterval(() => {
    if (token) {
      loadAccounts();
      loadLicence();
      loadSubscriptionStatus();
    }
  }, 15000);
}

initializeApp();
