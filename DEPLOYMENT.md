# Production deployment

## Recommended: Render

1. Rotate any API key that has ever appeared in a file or deployment log.
2. Push this folder to a private GitHub repository. Never commit `.env`.
3. In Render, create a Blueprint and select the repository. Render reads `render.yaml`.
4. Enter `MCP_API_KEY` and the video-provider keys as secret environment variables.
5. Confirm `/health` returns `{"status":"ok"}` on the temporary Render URL.
6. Add your custom domain in Render Settings > Custom Domains.
7. Add the CNAME or A/ANAME record Render displays at your DNS provider.
8. Wait for domain verification and automatic HTTPS activation.

The attached persistent disk stores daily JSON reports and generated Viralizer PDFs under
`/var/data`. Increase the disk size or move reports to managed object storage as usage grows.

## Before public launch

- Add user accounts or a paid usage system before allowing unrestricted video generation.
- Configure per-user quotas; an IP-only limit is insufficient for a commercial product.
- Add a privacy policy and terms covering third-party AI and prediction-market data.
- Monitor MCP and video-provider spending and configure provider-side budget alerts.
