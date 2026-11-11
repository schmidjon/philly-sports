# Philly Sports — TRMNL private plugin

A full-screen plugin for the TRMNL OG (800×480) that splits the screen into quarters. Each quarter covers one team: the Eagles, Phillies, Flyers and 76ers. It shows:

- The team logo, record and division standing
- **Last game:** a W/L badge, the score, the opponent and the date (marked OT/SO/extra innings when it applies)
- **Live:** shown in place of the last game while a game is in progress
- **Next game:** the opponent's logo, the date, the time and the TV channel. In the off-season it shows the next scheduled game, such as the spring-training opener (labeled PRESEASON), or "Schedule TBD" if nothing is scheduled.

## Files

| File | What it is |
|---|---|
| `serverless.py` | TRMNL Serverless function (Python) that fetches ESPN data and returns a compact payload |
| `full.liquid` | Markup for the **Full** layout |
| `sample_data.json` | Example of what the function returns, for testing in the markup editor |

## Why it uses Serverless instead of plain polling

TRMNL rejects polled responses larger than 100 KB. ESPN's team schedule feeds run about 50 KB–1.3 MB, so Liquid alone can't poll them. The Serverless function fetches the feeds inside TRMNL and returns only about 2.5 KB. You still don't host anything.

## Setup

1. In TRMNL, go to **Plugins → Private Plugin → New**. Name it "Philly Sports" and save.
2. Set **Strategy** to **Polling**. If the form requires a polling URL, enter any small JSON URL, for example `https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/phi`. The serverless function supplies the real data.
3. Set the refresh rate. **15 minutes** is a good balance, or 5 minutes if you want live scores to update often.
4. Click **Edit Markup**:
   - On the **Serverless** tab, pick **Python** and paste in `serverless.py`.
   - On the **Full** tab, paste in `full.liquid`.
5. Save, then click **Force Refresh** to see it.
6. Add the plugin to your device's playlist.

Times use the time zone in your TRMNL account settings, or US Eastern if none is set.

## Notes

- Data comes from ESPN's public but unofficial `site.api.espn.com` API. It needs no key, but ESPN could change it without notice.
- Logos are ESPN's scoreboard PNGs with a grayscale filter, so the 1-bit e-ink conversion doesn't turn team colors into blobs.
- When a team hasn't played yet in the current season phase (for example, the playoffs have started but the Phillies haven't played), the function goes back to the regular season and then to last season to find the most recent result.
