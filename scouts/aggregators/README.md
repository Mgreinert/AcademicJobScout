# Adding a new aggregator scout

Each aggregator is a single Python file in `scouts/aggregators/`. Use
`euraxess.py` as a template.

The minimum interface:

```python
from core.models import Posting
from scouts import Scout

class MyAggregatorScout(Scout):
    name = "my_aggregator"   # short identifier shown in source-health

    def fetch(self) -> list[Posting]:
        # Fetch + parse, return a list of Posting objects.
        # Raise on hard failures (the orchestrator catches them
        # and records FETCH_FAILED).
        ...
```

Then add an instance to `gather_scouts()` in `main.py`.

## Aggregators worth adding next, in priority order

1. **H-Net Job Guide** — https://www.h-net.org/jobs/
   Field-tagged academic jobs, strong for humanities/social sciences.
2. **jobs.ac.uk** — strong for UK/Europe positions.
3. **HigherEdJobs** — North American coverage.
4. **AAG Jobs Center** — Association of American Geographers, very on-target.
5. **Academic Jobs Online (AJO)** — many top US/Canada institutions.
6. **Inside Higher Ed Careers** — broad North American.
7. **AAS Job Board** — Association of Asian Studies.
8. **RGS-IBG Job Board** — Royal Geographical Society.

## Notes on fragility

- Aggregator HTML changes occasionally. The `PARSE_EMPTY` health status will
  catch silent breakages on the next run.
- Prefer official feeds (RSS, JSON) over scraping where available.
- Some sites have anti-bot measures (Cloudflare, etc.). For those, either
  use a stable RSS feed or fall back to playwright (not enabled yet).
- Respect each site's robots.txt and ToS. Weekly low-volume scraping for
  personal use is almost always fine.
