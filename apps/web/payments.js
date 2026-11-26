
import { api } from "./api-client.js";

/**
 * Initialize a payment using the backend's actual Flutterwave route.
 *
 * The backend creates the payment record and returns the checkout URL.
 * Access must only be activated after the backend verifies payment.
 */
export async function checkout(plan_code, currency = "USD") {
  if (!plan_code || typeof plan_code !== "string") {
    throw new Error("A valid subscription plan is required.");
  }

  const result = await api("/api/payments/flutterwave/initialize", {
    method: "POST",
    body: JSON.stringify({
      plan_code: plan_code.trim(),
      currency: String(currency).toUpperCase(),
    }),
  });

  if (!result || typeof result.checkout_url !== "string") {
    throw new Error("Payment provider did not return a checkout URL.");
  }

  let checkoutUrl;

  try {
    checkoutUrl = new URL(result.checkout_url);
  } catch {
    throw new Error("Payment provider returned an invalid checkout URL.");
  }

  if (checkoutUrl.protocol !== "https:") {
    throw new Error("Payment checkout must use a secure HTTPS URL.");
  }

  return {
    tx_ref: result.tx_ref,
    checkout_url: checkoutUrl.href,
  };
}

/**
 * Start checkout and redirect the customer to the payment provider.
 *
 * This redirect does not activate the licence.
 * The backend must verify the transaction and activate access.
 */
export async function startCheckout(plan_code, currency = "USD") {
  const result = await checkout(plan_code, currency);

  window.location.assign(result.checkout_url);

  return result;
}
