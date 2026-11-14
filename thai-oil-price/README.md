# Thai Oil Price Tracker

A free website that collects Thai fuel prices (PTT and Bangchak) every morning and shows today's prices, the daily change, and a history chart.

- `scripts/fetch_prices.py` – gets today's prices and saves them
- `.github/workflows/update.yml` – runs the script every day at ~06:15 Bangkok time
- `index.html` – the website
- `data/prices.csv` – all collected prices (grows by one day each morning)

## Setup (about 10 minutes, no coding)

1. **Create a GitHub account** at github.com (free).
2. **New repository** → name it `thai-oil-price` → choose **Public** → Create.
3. On the new repo page click **"uploading an existing file"**. Unzip this folder on your computer and drag **everything inside it** in (including the `.github` folder — on Mac press Cmd+Shift+. in Finder to see hidden folders). Click **Commit changes**.
   - If the `.github` folder won't upload: in the repo click **Add file → Create new file**, type the name `.github/workflows/update.yml`, paste the contents of that file, and commit.
4. **Allow the bot to save data:** Settings → Actions → General → *Workflow permissions* → select **Read and write permissions** → Save.
5. **Run it once now:** Actions tab → *Update oil prices* → **Run workflow**. After ~30 seconds it should turn green ✅ and a `data/prices.csv` file appears.
   - If it turns red ❌, click it, open the *Fetch prices* step, and send me the error text.
6. **Turn on the website:** Settings → Pages → Source: *Deploy from a branch* → Branch: **main**, folder **/ (root)** → Save. After 1–2 minutes your site is live at
   `https://YOUR-USERNAME.github.io/thai-oil-price/`

From then on it updates itself every morning. GitHub emails you if a run fails.

## Notes
- History starts from the day you set it up.
- Prices are base prices before local maintenance tax, which varies by area.
- GitHub pauses scheduled runs if the repo has no activity for 60 days. The daily data commits count as activity, so this normally won't happen.
