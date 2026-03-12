Put TLS certificate files in this directory before starting `nginx`:

- `fullchain.pem`
- `privkey.pem`

For Let's Encrypt, copy files from:

- `/etc/letsencrypt/live/<your-domain>/fullchain.pem`
- `/etc/letsencrypt/live/<your-domain>/privkey.pem`

Then run:

```bash
docker compose up -d --build
```
