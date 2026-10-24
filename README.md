## Run it

```bash
cp .env.example .env      # fill in MODEL, API_KEY, BASE_URL
./run.sh
     
or

From a fresh clone of this repo, with `.env` filled out:

```bash
docker compose up --build --abort-on-container-exit --exit-code-from harness