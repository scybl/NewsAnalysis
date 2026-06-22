# NewsWeaver Crawlers

This directory contains the Bloomberg and Guardian crawlers imported from the NewsWeaver repository.

## Layout

- `Bloomberg/get_url/`: fetches Bloomberg article URLs into a MongoDB URL queue.
- `Bloomberg/final_article/`: crawls full Bloomberg articles from the URL queue.
- `Guardian/`: crawls Guardian articles through the Guardian Content API.
- `schedule.txt`: original Windows scheduled task plan.
- `demo/`: static publisher-count dashboard.

## Configuration

The original `.env` files were not copied. Store secrets in the project encrypted secret store before running any crawler:

```bash
.venv/bin/python -m stock_pipeline secrets set mongo.password
.venv/bin/python -m stock_pipeline secrets set guardian.api_key
```

Configure non-secret endpoints with environment variables when needed:

```bash
export MONGODB_DATABASE=news
export MONGODB_COLLECTION=articles
export MONGO_HOST=127.0.0.1
export MONGO_PORT=27017
export MONGO_USER=admin
export MONGO_AUTHSOURCE=admin
```

Bloomberg scripts also need a logged-in Chrome session with the debug port described in their subdirectory README files.

If you connect to MongoDB through SSH tunneling, set `SSH_HOST`, `SSH_PORT`, `SSH_USER`, `SSH_KEY_PATH`, `SSH_REMOTE_HOST`, and `SSH_REMOTE_PORT`.
