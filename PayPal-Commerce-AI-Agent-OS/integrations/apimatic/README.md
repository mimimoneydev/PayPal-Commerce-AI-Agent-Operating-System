# APIMatic integration

The repository exports the OpenAPI contract from each real FastAPI application into
APIMatic's `src/spec` layout. This keeps generated SDKs and documentation synchronized
with the routes used by the storefront and merchant portal, including PayPal create,
capture, status, and webhook endpoints.

## Export and validate

From the repository root:

```bash
python scripts/export_openapi.py
npx -y @apimatic/cli@2.1.0 api validate --file integrations/apimatic/retail/src/spec/openapi.json
```

Use `--vertical retail` to export just one contract. Generated specifications are ignored
by Git; regenerate them after route or model changes. APIMatic validation may require
`apimatic auth login`, depending on the account and CLI release.

## Generate an SDK or documentation portal

After authenticating with APIMatic, initialize the selected directory once with
`apimatic quickstart`, retaining its generated configuration and the existing
`src/spec/openapi.json`. Then generate an SDK, for example:

```bash
npx -y @apimatic/cli@2.1.0 sdk generate \
  --input integrations/apimatic/retail \
  --language typescript \
  --destination build/apimatic/retail-typescript \
  --force
```

Keep generated clients under `build/`; they are consumers of the API and must not replace
the server-side authorization, pricing, inventory, PayPal capture, or merchant guardrail
checks. Never put OpenRouter, Channel3, or PayPal secrets into an exported specification.
