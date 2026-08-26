# YoWorld Auction Wishlist Watcher — Cloud Edition

Runs automatically every 15 minutes on GitHub's servers and posts a
Discord message when a new auction listing matches something on your
wishlist. No computer needs to stay on. Discord webhook is already
set in `watcher.py` — no secrets setup required.

## One-time setup (~2 minutes)

1. Go to https://github.com/new, create a repo (Private is fine)
2. Upload this entire folder's contents, keeping the folder structure
   exactly as-is — `.github/workflows/check.yml` must stay at that path
3. Open `watcher.py` in the repo and edit the `WISHLIST` list near the
   top with your item names (partial names work fine — it's a
   substring match, same as the site's own search box)
4. Go to the **Actions** tab -> click "Check YoWorld Auction Wishlist" ->
   **Run workflow** to test it once manually. Check your Discord
   channel for the test result.

That's it — it now runs itself every 15 minutes, forever.

## Editing your wishlist later

Just edit `WISHLIST` in `watcher.py` right on GitHub's web editor and
commit — no need to touch anything else.

## Notes

- Since the webhook URL is hardcoded in the file, **keep this repo
  Private** if it's not already — anyone who can read the code could
  otherwise post to your Discord channel using it. If you ever make
  the repo public, swap the webhook to a GitHub Actions secret instead
  (Settings -> Secrets and variables -> Actions) and reference it via
  `os.environ["DISCORD_WEBHOOK_URL"]`.
- To change how often it checks, edit the `cron` line in
  `.github/workflows/check.yml`. Don't go much more frequent than every
  5 minutes — be considerate of yoworld.net's servers since it's a
  small community-run site, not an official API.
- If yoworld.net changes their API, the run will show an error in the
  Actions log — check `watcher.py`'s `API_URL` and payload fields
  against what you see in DevTools if that happens.
