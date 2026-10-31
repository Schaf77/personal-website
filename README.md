# Personal website

A JavaScript-free personal website using the existing `nojs` Hugo theme’s default
layout, typography, colors, navigation, and light/dark mode. There is no blog,
RSS feed, or taxonomy. The theme is an unmodified submodule. The only custom
layout is the PGP page, which uses the theme’s styles.

## Run and personalize

Requires Hugo **0.158.0+** (the theme’s minimum version).

```sh
git submodule update --init --recursive
hugo server --disableFastRender
```

Open <http://localhost:1313/>. Edit:

| File | Content |
| --- | --- |
| `hugo.toml` | Real HTTPS `baseURL`, site title, and navigation |
| `content/_index.md` | Name, description, about text, projects, and contact links |
| `content/keys.md` | Introduction to the public-key page |

All personal details and projects shipped here are placeholders. Remove unused
social links and project entries. The key page intentionally starts empty, with
no example cryptographic identity or broken download link.

## Email obfuscation

Use `{{< email "you@example.org" >}}` in Markdown for an email link. The shortcode
encodes both the link destination and visible address as numeric HTML entities.
PGP-page addresses and WKD command examples use the same encoding. Addresses
remain readable, copyable, and clickable, with no JavaScript or extra styling.

HTML minification is disabled in `hugo.toml` because it can decode the entities
back into plain text. Other asset minification remains available with `--minify`.
This follows the [HTML-entity approach described by Spencer Mortensen](https://spencermortensen.com/articles/email-obfuscation/).
It discourages basic harvesting; it does not guarantee spam prevention or hide
the email identity contained in the downloadable OpenPGP key and WKD files.

## Add public PGP keys

The preparation helper requires Python **3.10+** and GnuPG **2.2+**. Use an existing
key; the helper does not generate identities or read your personal keyring. First
export the public part of your key to a file outside this repository:

```sh
gpg --armor --output /tmp/my-public-key.asc --export YOUR_FULL_FINGERPRINT
python3 scripts/publish-key.py --email hello@example.org --key /tmp/my-public-key.asc
hugo --cleanDestinationDir
```

Replace the fingerprint and email with your own. The email must occur in a usable
user ID on the key. The helper accepts ordinary ASCII mailboxes (letters, numbers,
dots, `_`, `+`, `%`, and `-` in the local part).

The helper validates a single public key using a temporary, isolated GnuPG
directory. It creates:

```text
static/keys/FULL_FINGERPRINT.asc             # Public, ASCII-armored download
data/pgp.json                              # Fingerprint, dates, and page links
.well-known/openpgpkey/
├── policy                                 # Empty, required WKD policy file
└── hu/HASH                                 # Binary public key for the mailbox
```

The `/keys/` page automatically lists downloads, complete fingerprints, dates,
and import instructions. Expand “Show raw public key” to read or copy the
ASCII-armored key directly on the page. Download links have `rel="pgpkey"`.
The downloadable export contains the key’s public user IDs. The WKD export is
filtered to the requested email address and excludes photo attributes.

Run the helper again for additional mailboxes on the **same domain**. Each mailbox
has one active WKD key. Running it for the same mailbox replaces that entry and
its WKD file, so you can update signatures or rotate keys. Previously generated
downloads remain at their fingerprint URLs; remove obsolete `.asc` files yourself
if you no longer want to host them. Rebuild and redeploy after any change.

## WKD hosting

The top-level `.well-known/` directory contains the WKD files. Hugo mounts it at
`static/.well-known` so it is published as `/.well-known/`, alongside files from
`static/`. The policy file is intentionally empty.
The helper creates the `hu/` directory when you prepare your first key.

This template implements the **direct method**:

```text
https://example.org/.well-known/openpgpkey/policy
https://example.org/.well-known/openpgpkey/hu/HASH?l=hello
```

Serve the site at the root of the **email domain**, over HTTPS with a valid
certificate. A site at `www.example.org` or under `/personal/` cannot provide direct
WKD for `hello@example.org` unless the email-domain host independently serves the
correct paths. For direct-method discovery, `openpgpkey.example.org` must not
resolve: clients try the advanced method first and may not fall back after an
HTTP failure. If you already use an advanced WKD service, keep that service and
configure it separately rather than replacing it with this direct-method layout.

Configure your web server/CDN to:

- Publish dot directories, including `.well-known`, and zero-byte files.
- Return the policy and binary key with **HTTP 200**, with no login or HTML fallback.
- Serve `hu/*` as `application/octet-stream` and `policy` as `text/plain`.
- Serve `/keys/*.asc` as `application/pgp-keys` (or `text/plain`).
- Return `Access-Control-Allow-Origin: *` for the WKD paths, including `policy`.
- Permit the `?l=...` query string; it does not change which static file is served.

These HTTP headers must be set on your hosting provider; Hugo only generates
files. Ensure deployment/sync tooling includes hidden directories. For example,
`public/*` shell globs omit `.well-known`; deploy `public/` as a whole.

After deployment, check the real URLs and automatic discovery:

```sh
curl -i https://example.org/.well-known/openpgpkey/policy
# Substitute the HASH shown by the helper; this should return binary OpenPGP data.
curl -I 'https://example.org/.well-known/openpgpkey/hu/HASH?l=hello'
gpg --auto-key-locate clear,wkd --locate-keys hello@example.org
```

Use a fresh GnuPG home for a conclusive discovery test if the key is already in
your local keyring. See the [GnuPG WKD hosting guide](https://wiki.gnupg.org/WKDHosting)
and [GnuPG export/filter documentation](https://www.gnupg.org/documentation/manuals/gnupg/GPG-Input-and-Output.html).

## Build

```sh
hugo --cleanDestinationDir --minify
```

Deploy the contents of `public/` with your preferred static host. Do not deploy
the repository itself. Generated output and Hugo cache/lock files are ignored
by Git. `--cleanDestinationDir` removes stale generated pages from earlier builds.

## Docker behind Nginx Proxy Manager

The included `compose.yaml` runs the official `nginx:stable-alpine` image with
`public/` and `deploy/nginx.conf` mounted read-only. Nginx Proxy Manager (NPM)
handles HTTPS and forwards to the container over HTTP on a shared Docker network.
The site container does not publish any host ports.

On the VPS, use a directory such as `/srv/onderka.dev` containing:

```text
compose.yaml
.env
deploy/nginx.conf
public/                 # Complete Hugo build, including .well-known/
```

Copy `.env.example` to `.env` and set `NPM_NETWORK` to an existing user-defined
Docker network joined by your NPM container, for example `npm_default`. To list
the networks joined by NPM, replace `NPM_CONTAINER` with its container name:

```sh
docker inspect NPM_CONTAINER --format '{{json .NetworkSettings.Networks}}'
```

NPM and the site must share the selected network. The external network is reused
by this Compose project; it is not created or removed by it. See
[NPM's Docker network guidance](https://nginxproxymanager.com/advanced-config/#best-practice-use-a-docker-network).

Build locally, then upload to that dedicated directory. Replace `USER` and
`VPS_IP` with your SSH details, and create `/srv/onderka.dev` on the VPS with write
access for your SSH user first:

```sh
hugo --cleanDestinationDir --minify
rsync -avz --chmod=D755,F644 compose.yaml .env.example USER@VPS_IP:/srv/onderka.dev/
rsync -avz --chmod=D755,F644 deploy/ USER@VPS_IP:/srv/onderka.dev/deploy/
rsync -avz --delete --chmod=D755,F644 public/ USER@VPS_IP:/srv/onderka.dev/public/
```

The final command synchronizes only the dedicated `public/` directory, including
hidden WKD files. On the VPS, configure `.env` and start the service:

```sh
cd /srv/onderka.dev
cp .env.example .env
# Edit .env and set NPM_NETWORK to your NPM network before continuing.
docker compose config --quiet
docker compose up -d
docker compose exec onderka-site nginx -t
```

In NPM, create or update the proxy host:

- **Domain:** `onderka.dev`
- **Scheme:** `http`
- **Forward hostname:** `onderka-site`
- **Forward port:** `80`
- **Access:** publicly accessible, including the WKD paths
- **SSL:** select your existing certificate and enable Force SSL
- **Cache Assets:** leave disabled so key updates are served immediately

NPM should forward the original paths to the container. The included Nginx
configuration serves the empty WKD policy, binary keys with the appropriate MIME
type and CORS header, and armored downloads as plain text. It uses relative
directory redirects to preserve HTTPS through the proxy.

Check the public URLs with the commands in the WKD hosting section above.
For content updates, rerun the local build and the `public/` rsync command;
the running container sees updated files without a restart. Keep the mounted
`public/` directory in place and update its contents. After editing
`deploy/nginx.conf`, upload it and run:

```sh
docker compose exec onderka-site nginx -t
docker compose restart onderka-site
```

To update the Nginx image later, run `docker compose pull` followed by
`docker compose up -d`.

Run the key-publishing integration tests with `python3 -m unittest discover -s tests -v`.
They create throwaway keys in a temporary directory, separate from your keyring.
