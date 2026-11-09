# WooCommerce shopping and payment integration

The retail storefront can use a real WooCommerce store instead of the ACME fixtures.
`shopping_agent.woocommerce.WooCommerceBackend` calls the bundled WordPress plugin
`integrations/woocommerce/agent-commerce-bridge.php`. Each backend instance has its own
store URL, merchant id, and bridge secret. Credentials and cart ownership handles stay
on the server and never enter model results.

## Connect a store

1. Install and activate WooCommerce and configure the store's products, shipping zones,
   tax settings, coupons, and payment gateway. Connect the merchant's PayPal account in
   **WooCommerce > Settings > Payments > PayPal** using the installed PayPal gateway's
   onboarding. Test with that gateway's sandbox mode first.
2. Put `agent-commerce-bridge.php` in
   `wp-content/plugins/agent-commerce-bridge/agent-commerce-bridge.php` and activate
   **Agent Commerce Bridge**. The plugin supports simple and variable products; product
   bundles and subscription extensions need their own cart integration.
3. Generate a unique random bridge secret, for example with
   `openssl rand -hex 32`, and add it to `wp-config.php`:

   ```php
   define('AGENT_COMMERCE_SECRET', 'your-random-secret');
   ```

4. Configure the agent's root `.env`:

   ```dotenv
   COMMERCE_PLATFORM=woocommerce
   COMMERCE_MERCHANT_ID=my-store
   WOOCOMMERCE_URL=https://shop.example.com
   WOOCOMMERCE_BRIDGE_SECRET=the-same-random-secret
   ```

5. Start `python scripts/run_demo.py retail`. It also passes the non-secret platform flag
   to the web app. For manually started Next.js processes, set
   `NEXT_PUBLIC_COMMERCE_PLATFORM=woocommerce` before starting/building the web app.
   Do **not** put the bridge secret or PayPal secret in a `NEXT_PUBLIC_*` variable.

The WooCommerce path ignores the host's optional direct PayPal checkout configuration.
Only WooCommerce's configured gateway creates/captures the payment. There is no second
capture by the AI host and no second commerce order created after checkout.

## Shopper flow

1. Catalog reads and cart changes use signed requests to the WooCommerce plugin. Cart
   lines live in the WordPress database; the store validates current stock and quantities.
2. Checkout creates a short-lived single-use link. Opening it shows a confirmation page;
   clicking Continue loads the assistant cart into the shopper's WooCommerce browser cart.
   The confirmation explains that an existing browser cart will be replaced.
3. WooCommerce checkout collects addresses, calculates its authoritative final shipping,
   tax and discount total, validates stock, and uses its configured payment gateway.
4. WooCommerce creates the order and runs its normal payment and fulfillment hooks. The
   bridge records the shopper ownership handle as private order metadata. It clears the
   assistant cart on payment only if no cart edits have happened since the handoff.
5. Returning to the storefront refreshes Orders and the cart. Before the next chat turn,
   the host reads paid orders and queues a deduplicated application event. The assistant
   can now confirm the actual order id and final amount, including checkout adjustments.

The order sync reads WooCommerce directly rather than depending on browser redirects or
webhook arrival. Unpaid orders are not reported as successful. Refund status is reflected
on a subsequent read. WooCommerce's `completed` status is not described as delivered:
delivery tracking requires a shipping integration that can supply that evidence.

## Identity and deployment boundaries

Bridge requests use HMAC-SHA256 over method, route, timestamp, nonce and exact body.
The plugin enforces a five-minute clock window and atomically rejects nonce replay.
Configure WordPress cron so nonce and handoff records are cleaned up. Cart mutations use
database advisory locks; checkout handoffs expire in 30 minutes. Use a unique bridge
secret for each store, and keep host and WordPress clocks synchronized.

The example host remains a local guest storefront. Each guest receives an unguessable
session and separate memory; demo profile ids cannot claim another customer's WooCommerce
orders. Reloading/resetting the example creates a new guest session. For stable order
history across devices and restarts, an authenticated production host should persist its
sessions and construct `WooCommerceBackend(..., authenticated_customers=True)` only after
binding `session.user_id` to a verified principal. Never enable this mode with the demo's
caller-selected profile ids. The demo merchant portal is not mounted against a live store.

For several merchants, the host resolves the merchant from its authenticated route/session
and injects the corresponding backend instance. The model cannot choose the store URL,
bridge secret or merchant id. The optional [merchant control service](merchant-platform.md)
includes an invitation-gated administration UI and durable shopper sessions.

## What this integration delegates

Tax, shipping, coupons, stock validation/reservation and fulfillment run through the store's
native checkout and installed extensions. Refunds are administered through WooCommerce and
its gateway. The optional [merchant control service](merchant-platform.md) also provides
owner-approved gateway refunds, shipment tracking, manual fraud review, and PayPal
dispute-evidence notes. Enable merchant operations explicitly as described there.
The control service can pull paid-order/refund journals and export CSV; posting to the
merchant's external accounting system still requires that integration. The bridge does not
install a tax, fraud, dispute, warehouse or accounting service, and does not grant those
permissions to the shopping model.

## Verification

Automated tests exercise signed requests, ownership isolation, handoff URL validation,
order sync deduplication and the shared host's order-to-next-turn path. The PHP plugin can
be linted with `php -l integrations/woocommerce/agent-commerce-bridge.php`.

Before using a store, complete a sandbox checkout with that store's gateway, including a
variant, coupon, tax/shipping change, cancellation, declined payment and refund. Confirm
that only one WooCommerce order/payment exists and the final total appears in Orders and
the next assistant reply. Local HTTP fixtures and syntax checks do not replace this test.

References: [WooCommerce payment gateway lifecycle](https://developer.woocommerce.com/docs/features/payments/payment-gateway-api/)
and [WooCommerce order API](https://woocommerce.github.io/code-reference/classes/WC-Order.html).
