<?php
/**
 * Plugin Name: Agent Commerce Bridge
 * Description: Authenticated catalog/cart bridge and native WooCommerce checkout for Commerce AI Agent OS.
 * Version: 0.1.0
 * Requires Plugins: woocommerce
 */
defined('ABSPATH') || exit;

// Configure a unique random 32+ character secret in wp-config.php:
// define('AGENT_COMMERCE_SECRET', '...'); never place it in this plugin or a browser.

function ac_bridge_auth($request) {
    if (!defined('AGENT_COMMERCE_SECRET') || strlen(AGENT_COMMERCE_SECRET) < 32 || !class_exists('WooCommerce')) {
        return new WP_Error('not_configured', 'Bridge is not configured.', ['status' => 503]);
    }
    $time = $request->get_header('X-Agent-Time');
    $nonce = $request->get_header('X-Agent-Nonce');
    if (!ctype_digit($time) || abs(time() - intval($time)) > 300 || !preg_match('/^[a-f0-9]{32}$/', $nonce)) {
        return new WP_Error('unauthorized', 'Invalid request.', ['status' => 401]);
    }
    $path = substr($request->get_route(), strlen('/agent-commerce/v1'));
    $signed = implode("\n", [$request->get_method(), $path, $time, $nonce, $request->get_body()]);
    if (!hash_equals(hash_hmac('sha256', $signed, AGENT_COMMERCE_SECRET), $request->get_header('X-Agent-Signature'))) {
        return new WP_Error('unauthorized', 'Invalid request.', ['status' => 401]);
    }
    // add_option is atomic (unique key). Retain nonces across PHP workers.
    $key = 'ac_nonce_' . $nonce;
    if (!add_option($key, time(), '', false)) {
        return new WP_Error('replay', 'Request already received.', ['status' => 409]);
    }
    wp_schedule_single_event(time() + 610, 'ac_delete_option', [$key]);
    return true;
}
add_action('ac_delete_option', 'delete_option');

function ac_owner($value) {
    if (!is_string($value) || !preg_match('/^[a-f0-9]{64}$/', $value)) {
        throw new Exception('Invalid cart owner.');
    }
    return $value;
}

function ac_locked($owner, $operation) {
    global $wpdb;
    $key = 'ac_' . substr(hash('sha256', $owner), 0, 50);
    if (intval($wpdb->get_var($wpdb->prepare('SELECT GET_LOCK(%s, 5)', $key))) !== 1) {
        throw new Exception('Cart is busy. Please retry.');
    }
    try { return $operation(); }
    finally { $wpdb->get_var($wpdb->prepare('SELECT RELEASE_LOCK(%s)', $key)); }
}

function ac_product($product, $details = false) {
    $image = wp_get_attachment_image_url($product->get_image_id(), 'medium');
    $result = [
        'product_id' => strval($product->get_id()), 'title' => $product->get_name(),
        'price' => floatval($product->get_price()), 'currency' => get_woocommerce_currency(),
        'in_stock' => $product->is_in_stock(), 'image_url' => $image ?: null,
        'short_description' => wp_strip_all_tags($product->get_short_description()),
    ];
    if ($product->is_type('variation')) {
        $result['variant_of'] = strval($product->get_parent_id());
        $result['option_values'] = (object) $product->get_variation_attributes();
    }
    if ($product->is_type('variable')) {
        $result['options'] = (object) $product->get_variation_attributes();
        if ($details) {
            $result['variants'] = [];
            foreach ($product->get_children() as $id) {
                $variant = wc_get_product($id);
                if ($variant && $variant->variation_is_visible()) $result['variants'][] = ac_product($variant);
            }
        }
    }
    if ($details) $result['long_description'] = wp_strip_all_tags($product->get_description());
    return $result;
}

function ac_cart_payload($lines) {
    $items = [];
    foreach ($lines as $id => $quantity) {
        $p = wc_get_product($id);
        if (!$p) continue;
        $item = ac_product($p);
        $items[] = ['product_id' => strval($id), 'title' => $p->get_name(),
                    'price' => floatval($p->get_price()), 'quantity' => $quantity,
                    'image_url' => $item['image_url'],
                    'variant_of' => $item['variant_of'] ?? null,
                    'option_values' => $item['option_values'] ?? new stdClass()];
    }
    return ['items' => $items, 'currency' => get_woocommerce_currency()];
}

function ac_bridge_call($request) {
    $data = $request->get_json_params() ?: [];
    $path = substr($request->get_route(), strlen('/agent-commerce/v1'));
    try {
        if ($path === '/accounting') {
            if (!defined('AGENT_COMMERCE_OPERATIONS_ENABLED') || !AGENT_COMMERCE_OPERATIONS_ENABLED) {
                throw new Exception('Merchant operations are disabled.');
            }
            $page = max(1, intval($data['page'] ?? 1));
            $orders = wc_get_orders(['limit' => 50, 'page' => $page, 'paginate' => true,
                'orderby' => 'ID', 'order' => 'ASC', 'meta_query' => [['key' => '_ac_owner', 'compare' => 'EXISTS']]]);
            $result = [];
            foreach ($orders->orders as $order) {
                if (!$order->get_meta('_ac_owner') || !$order->get_date_paid()) continue;
                $refunds = [];
                foreach ($order->get_refunds() as $refund) {
                    // An administrator can record a manual refund without sending
                    // money. Do not post that as a confirmed gateway refund.
                    if ($refund->get_refunded_payment()) $refunds[] = ['id' => strval($refund->get_id()), 'amount' => $refund->get_amount()];
                }
                $result[] = ['id' => strval($order->get_id()), 'total' => $order->get_total(),
                    'currency' => $order->get_currency(), 'refunds' => $refunds];
            }
            return ['orders' => $result, 'next_page' => $page < $orders->max_num_pages ? $page + 1 : null];
        }
        if ($path === '/operations') {
            // Separately enabled by the store operator: existing catalog bridge
            // installations do not silently acquire refund authority on upgrade.
            if (!defined('AGENT_COMMERCE_OPERATIONS_ENABLED') || !AGENT_COMMERCE_OPERATIONS_ENABLED) {
                throw new Exception('Merchant operations are disabled.');
            }
            $id = $data['operation_id'] ?? '';
            if (!preg_match('/^[a-f0-9]{32}$/', $id)) throw new Exception('Invalid operation id.');
            return ac_locked('operation-' . $id, function() use ($data, $id) {
                $key = 'ac_operation_' . $id;
                $hash = hash('sha256', wp_json_encode($data));
                $existing = get_option($key);
                if ($existing) {
                    if ($existing['hash'] !== $hash) throw new Exception('Operation payload changed.');
                    return $existing['result'];
                }
                $order = wc_get_order(absint($data['order_id'] ?? 0));
                if (!$order || !$order->get_meta('_ac_owner') || !$order->get_date_paid()) throw new Exception('Unknown paid assistant order.');
                $payload = $data['payload'] ?? [];
                $kind = $data['kind'] ?? '';
                if (!in_array($kind, ['shipment', 'refund'], true)) throw new Exception('Unknown operation.');
                // Persist before calling a gateway. If PHP dies after the remote
                // side effect, replay returns unknown instead of refunding twice.
                $record = ['hash' => $hash, 'result' => ['status' => 'unknown']];
                if (!add_option($key, $record, '', false)) throw new Exception('Operation already started.');
                if ($kind === 'refund') {
                    $amount = wc_format_decimal($payload['amount'] ?? '0');
                    if (floatval($amount) <= 0 || floatval($amount) > $order->get_remaining_refund_amount()) throw new Exception('Invalid refund amount.');
                    $refund = wc_create_refund(['order_id' => $order->get_id(), 'amount' => $amount,
                        'reason' => sanitize_text_field($payload['reason'] ?? ''), 'refund_payment' => true,
                        'restock_items' => false]);
                    if (is_wp_error($refund)) throw new Exception('Refund not confirmed.');
                    $result = ['status' => 'completed', 'refund_id' => strval($refund->get_id())];
                } else {
                    $tracking = esc_url_raw($payload['tracking_url'] ?? '', ['https']);
                    $number = sanitize_text_field($payload['tracking_number'] ?? '');
                    if (!$tracking || !$number || !$order->has_status('processing')) throw new Exception('Invalid shipment.');
                    $order->update_meta_data('_ac_tracking_url', $tracking);
                    $order->update_meta_data('_ac_tracking_number', $number);
                    $order->update_meta_data('_ac_shipment_operation', $id);
                    $order->save();
                    $order->update_status('completed', 'Shipment recorded by merchant: ' . $number);
                    $result = ['status' => 'completed', 'order_id' => strval($order->get_id()), 'tracking_url' => $tracking];
                }
                $record['result'] = $result;
                update_option($key, $record, false);
                return $result;
            });
        }
        if ($path === '/catalog') {
            $filters = $data['filters'] ?? [];
            $args = ['status' => 'publish', 'limit' => min(30, max(1, intval($data['limit'] ?? 8))),
                     's' => sanitize_text_field($data['query'] ?? ''), 'return' => 'objects'];
            if (!empty($filters['category'])) $args['category'] = [sanitize_title($filters['category'])];
            foreach (['min_price' => '>=', 'max_price' => '<='] as $field => $compare) {
                if (isset($filters[$field])) $args['meta_query'][] = [
                    'key' => '_price', 'value' => floatval($filters[$field]),
                    'compare' => $compare, 'type' => 'DECIMAL(20,6)',
                ];
            }
            if (isset($filters['min_rating'])) $args['meta_query'][] = [
                'key' => '_wc_average_rating', 'value' => floatval($filters['min_rating']),
                'compare' => '>=', 'type' => 'DECIMAL(3,2)',
            ];
            foreach (($filters['attributes'] ?? []) as $attribute => $value) {
                $taxonomy = wc_attribute_taxonomy_name(sanitize_title($attribute));
                if (!taxonomy_exists($taxonomy)) throw new Exception('Unsupported attribute filter.');
                $args['tax_query'][] = ['taxonomy' => $taxonomy, 'field' => 'slug', 'terms' => sanitize_title($value)];
            }
            if (in_array($filters['sort'] ?? '', ['price_asc', 'price_desc'], true)) {
                $args['orderby'] = 'meta_value_num'; $args['meta_key'] = '_price';
                $args['order'] = $filters['sort'] === 'price_asc' ? 'ASC' : 'DESC';
            } elseif (($filters['sort'] ?? '') === 'rating') {
                $args['orderby'] = 'meta_value_num'; $args['meta_key'] = '_wc_average_rating'; $args['order'] = 'DESC';
            }
            return ['products' => array_values(array_map('ac_product', array_filter(wc_get_products($args),
                function($p) { return $p->is_visible() && $p->is_type(['simple', 'variable']); })))];
        }
        if ($path === '/product') {
            $p = wc_get_product(absint($data['id'] ?? 0));
            return ['product' => $p && $p->get_status() === 'publish' ? ac_product($p, true) : null];
        }
        if ($path === '/policies') {
            $policies = [];
            foreach (['terms' => wc_terms_and_conditions_page_id(), 'privacy' => get_option('wp_page_for_privacy_policy')] as $key => $id) {
                $page = get_post($id);
                if ($page && $page->post_status === 'publish') $policies[] = [
                    'policy_id' => $key, 'title' => $page->post_title, 'content' => wp_strip_all_tags($page->post_content),
                ];
            }
            return ['policies' => $policies];
        }
        $owner = ac_owner($data['owner'] ?? '');
        if ($path === '/orders') {
            $args = ['limit' => min(100, max(1, intval($data['limit'] ?? 20))), 'orderby' => 'date', 'order' => 'DESC',
                     'meta_query' => [['key' => '_ac_owner', 'value' => $owner]]];
            $orders = isset($data['order_id']) ? [wc_get_order(absint($data['order_id']))] : wc_get_orders($args);
            $result = [];
            foreach ($orders as $o) {
                if (!$o || $o->get_meta('_ac_owner') !== $owner || !$o->get_date_paid()) continue;
                $items = [];
                foreach ($o->get_items() as $line) $items[] = [
                    'product_id' => strval($line->get_variation_id() ?: $line->get_product_id()),
                    'title' => $line->get_name(), 'quantity' => $line->get_quantity(),
                    'price' => floatval($line->get_total()) / max(1, $line->get_quantity()),
                ];
                // Woo's completed status means fulfillment complete, not proven delivery.
                $status = $o->has_status('refunded') ? 'refunded' : ($o->has_status('cancelled') ? 'cancelled' : 'processing');
                if ($status === 'processing' && $o->get_meta('_ac_tracking_url')) $status = 'shipped';
                $result[] = ['order_id' => strval($o->get_id()), 'status' => $status,
                             'tracking_url' => $o->get_meta('_ac_tracking_url') ?: null,
                             'placed_at' => $o->get_date_created()->date(DATE_ATOM), 'items' => $items,
                             'total' => floatval($o->get_total()), 'currency' => $o->get_currency()];
            }
            return ['orders' => $result];
        }
        return ac_locked($owner, function() use ($owner, $data, $path) {
            $key = 'ac_cart_' . $owner;
            $lines = get_option($key, []);
            if ($path === '/cart') {
                $action = $data['action'] ?? 'read';
                if (!in_array($action, ['read', 'add', 'update', 'remove'], true)) throw new Exception('Invalid action.');
                if ($action !== 'read') {
                    $id = absint($data['product_id'] ?? 0);
                    if ($action === 'remove') unset($lines[$id]);
                    else {
                        $quantity = intval($data['quantity'] ?? 0);
                        if ($quantity < 1 || $quantity > 100) throw new Exception('Invalid quantity.');
                        if ($action === 'add') $quantity += $lines[$id] ?? 0;
                        $p = wc_get_product($id);
                        if (!$p || !$p->is_type(['simple', 'variation']) || !$p->is_purchasable() ||
                            !$p->is_in_stock() || !$p->has_enough_stock($quantity) || $quantity > 100 ||
                            ($p->is_sold_individually() && $quantity > 1)) throw new Exception('Product unavailable.');
                        $lines[$id] = $quantity;
                    }
                    update_option($key, $lines, false);
                }
                return ['cart' => ac_cart_payload($lines)];
            }
            if ($path === '/handoff') {
                if (!$lines) throw new Exception('Cart is empty.');
                $token = bin2hex(random_bytes(32));
                $key = 'ac_handoff_' . hash('sha256', $token);
                add_option($key, ['owner' => $owner, 'lines' => $lines, 'expires' => time() + 1800], '', false);
                wp_schedule_single_event(time() + 1800, 'ac_delete_option', [$key]);
                return ['url' => add_query_arg('ac_checkout', $token, home_url('/'))];
            }
            throw new Exception('Unknown operation.');
        });
    } catch (Exception $error) {
        return new WP_Error('bridge_request', 'Store request could not be completed.', ['status' => 409]);
    }
}

add_action('rest_api_init', function() {
    foreach (['catalog', 'product', 'cart', 'handoff', 'orders', 'policies', 'operations', 'accounting'] as $route) {
        register_rest_route('agent-commerce/v1', '/' . $route, [
            'methods' => 'POST', 'permission_callback' => 'ac_bridge_auth', 'callback' => 'ac_bridge_call',
        ]);
    }
});

add_action('template_redirect', function() {
    if (!isset($_GET['ac_checkout'])) return;
    $token = sanitize_text_field(wp_unslash($_GET['ac_checkout']));
    if (!preg_match('/^[a-f0-9]{64}$/', $token)) wp_die('Invalid checkout link.', '', ['response' => 404]);
    nocache_headers(); header('Referrer-Policy: no-referrer'); header('X-Frame-Options: DENY');
    $key = 'ac_handoff_' . hash('sha256', $token);
    $handoff = get_option($key);
    if (!$handoff || $handoff['expires'] < time()) wp_die('This checkout link expired. Ask the assistant for a new one.', '', ['response' => 410]);
    // GET renders a confirmation. Crawlers and previews cannot replace a browser cart.
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        echo '<!doctype html><html><meta name="viewport" content="width=device-width"><title>Continue to checkout</title><body>';
        echo '<h1>Continue to checkout</h1><p>This will load your assistant cart into this store. Any existing browser cart will be replaced. Review delivery, discounts and the final total at checkout.</p><form method="post">';
        wp_nonce_field('ac_checkout_' . $token);
        echo '<button type="submit">Continue with this cart</button></form></body></html>'; exit;
    }
    check_admin_referer('ac_checkout_' . $token);
    try {
        ac_locked($key, function() use ($key, $handoff) {
            if (!get_option($key)) throw new Exception('Checkout link already used.');
            if (!WC()->cart) wc_load_cart();
            // Check everything before replacing a cart. Native checkout validates again.
            foreach ($handoff['lines'] as $id => $quantity) {
                $p = wc_get_product($id);
                if (!$p || !$p->is_purchasable() || !$p->is_in_stock() || !$p->has_enough_stock($quantity)) throw new Exception('Cart availability changed.');
            }
            WC()->cart->empty_cart();
            foreach ($handoff['lines'] as $id => $quantity) {
                $p = wc_get_product($id);
                $added = $p->is_type('variation')
                    ? WC()->cart->add_to_cart($p->get_parent_id(), $quantity, $id, $p->get_variation_attributes())
                    : WC()->cart->add_to_cart($id, $quantity);
                if (!$added) throw new Exception('Could not add a product. Please return to the assistant.');
            }
            WC()->session->set('ac_owner', $handoff['owner']);
            WC()->session->set('ac_lines', $handoff['lines']);
            WC()->session->set_customer_session_cookie(true);
            delete_option($key);
        });
        wp_safe_redirect(wc_get_checkout_url()); exit;
    } catch (Exception $error) { wp_die('Checkout could not be prepared. Return to the assistant to review your cart.', '', ['response' => 409]); }
});

function ac_stamp_order($order) {
    if (WC()->session && WC()->session->get('ac_owner')) {
        $order->update_meta_data('_ac_owner', WC()->session->get('ac_owner'));
        $order->update_meta_data('_ac_lines', WC()->session->get('ac_lines'));
    }
}
add_action('woocommerce_checkout_create_order', 'ac_stamp_order');
add_action('woocommerce_store_api_checkout_update_order_meta', function($order) { ac_stamp_order($order); $order->save(); });

function ac_clear_checkout_context() {
    if (WC()->session) {
        WC()->session->__unset('ac_owner');
        WC()->session->__unset('ac_lines');
    }
}
// Later ordinary purchases in this browser must not inherit an old assistant session.
add_action('woocommerce_checkout_order_processed', 'ac_clear_checkout_context');
add_action('woocommerce_store_api_checkout_order_processed', 'ac_clear_checkout_context');

function ac_clear_paid_cart($order_id) {
    $order = wc_get_order($order_id);
    $owner = $order ? $order->get_meta('_ac_owner') : '';
    if (!$owner) return;
    try {
        ac_locked($owner, function() use ($owner, $order) {
            $key = 'ac_cart_' . $owner;
            // Do not erase new cart edits made while the customer was paying.
            if (get_option($key, []) == $order->get_meta('_ac_lines')) delete_option($key);
        });
    } catch (Exception $error) {
        // A busy assistant cart must never turn a successful gateway capture into an error.
        if (!wp_next_scheduled('ac_clear_paid_cart', [$order_id])) {
            wp_schedule_single_event(time() + 30, 'ac_clear_paid_cart', [$order_id]);
        }
    }
}
add_action('woocommerce_payment_complete', 'ac_clear_paid_cart');
add_action('ac_clear_paid_cart', 'ac_clear_paid_cart');
