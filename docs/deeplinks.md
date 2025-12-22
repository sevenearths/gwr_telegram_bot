## Primary Deep Link Format: Journey Results / Booking
Use this format to deep link to specific journey search results, ready for booking.

```
https://www.thetrainline.com/book/results?
  origin=ORIGIN_STATION&
  destination=DESTINATION_STATION&
  outwardDate=YYYY-MM-DDThh:mm
```

### Parameters
- `origin`: Origin station name or code (e.g., `London+Paddington`, `PAD`, `London`)
- `destination`: Destination station name or code (e.g., `Bristol+Temple+Meads`, `BRI`)
- `outwardDate`: Outward departure date and time in ISO format `YYYY-MM-DDThh:mm` (e.g., `2025-12-23T10:15`)

get the `origin` and `desitnation` codes from localtions.json in the root of the project

### Optional Parameters (commonly supported)
- `returnDate=YYYY-MM-DDThh:mm` – For return journeys
- `adults=1` – Number of adults
- `children=0` – Number of children
- `railcard=...` – Apply a specific railcard

### Example
```
https://www.thetrainline.com/book/results?origin=London+Paddington&destination=Bristol+Temple+Meads&outwardDate=2025-12-23T10:15
```

- On desktop/web: Opens the Trainline website with results.
- On mobile with app installed: Opens the Trainline app directly to the journey results, ready to select and book tickets.

## Alternative Format: Journey Planner Pre-fill
Some links use a slightly different path (observed from shared links):

```
https://www.thetrainline.com/journey?from=ORIGIN&to=DESTINATION&date=YYYY-MM-DD&time=hh:mm
```

This pre-fills the journey planner and may trigger app opening similarly.