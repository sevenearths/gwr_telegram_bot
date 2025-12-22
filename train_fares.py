#!/usr/bin/env python3
"""
Train Fares Script - Fetches GWR train prices for Monday and Thursday evenings
"""

import json
import requests
from datetime import datetime, timedelta
from typing import Generator
from urllib.parse import quote_plus


# Browser-like headers to mimic website requests
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.gwr.com",
    "Referer": "https://www.gwr.com/tickets",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
}

# Default values
DEFAULT_FROM_STATION_CODE = "4222"
DEFAULT_TO_STATION_CODE = "3087"

DEFAULT_OUTBOUND_DAY_OF_THE_WEEK = "Monday"
DEFAULT_OUTBOUND_TIME = "18:00"
DEFAULT_OUTBOUND_FARE_THRESHOLD = 4000

DEFAULT_RETURN_DAY_OF_THE_WEEK = "Thursday"
DEFAULT_RETURN_TIME = "18:00"
DEFAULT_RETURN_FARE_THRESHOLD = 6500

# Day name to weekday number mapping
DAY_NAME_TO_WEEKDAY = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}

# Cache for locations data
_LOCATIONS_CACHE = None
_STATION_CODES_CACHE = None


def load_locations() -> dict:
    """Load and cache the locations.json file."""
    global _LOCATIONS_CACHE, _STATION_CODES_CACHE
    if _LOCATIONS_CACHE is None:
        try:
            with open("locations.json", "r") as f:
                data = json.load(f)
                # Create lookup dicts: nlc code -> station name and nlc code -> station code
                _LOCATIONS_CACHE = {}
                _STATION_CODES_CACHE = {}
                for location in data.get("locations", []):
                    nlc = location.get("nlc")
                    name = location.get("name")
                    code = location.get("code")
                    if nlc and name:
                        _LOCATIONS_CACHE[nlc] = name
                    if nlc and code:
                        _STATION_CODES_CACHE[nlc] = code
        except FileNotFoundError:
            print("Warning: locations.json not found, deep links will use station codes")
            _LOCATIONS_CACHE = {}
            _STATION_CODES_CACHE = {}
    return _LOCATIONS_CACHE


def get_station_name(nlc_code: str) -> str:
    """Get station name from NLC code, falling back to the code if not found."""
    locations = load_locations()
    return locations.get(nlc_code, nlc_code)


def get_station_code(nlc_code: str) -> str:
    """Get station code (abbreviation) from NLC code, falling back to the NLC if not found."""
    load_locations()  # Ensure caches are populated
    return _STATION_CODES_CACHE.get(nlc_code, nlc_code)


# Doesn't work - Thanks thetrainline.com. Nice 1!
def create_trainline_deeplink(
    from_station_code: str,
    to_station_code: str,
    departure_datetime: datetime
) -> str:
    """Create a Trainline deep link for booking."""
    origin_name = get_station_name(from_station_code)
    destination_name = get_station_name(to_station_code)
    
    # Format date as YYYY-MM-DDThh:mm
    date_str = departure_datetime.strftime("%Y-%m-%dT%H:%M")
    
    # Build URL with proper encoding
    base_url = "https://www.thetrainline.com/book/results"
    params = f"origin={quote_plus(origin_name)}&destination={quote_plus(destination_name)}&outwardDate={date_str}"
    
    return f"{base_url}?{params}"


def get_target_dates(
    outbound_day_of_the_week: str = DEFAULT_OUTBOUND_DAY_OF_THE_WEEK,
    outbound_time: str = DEFAULT_OUTBOUND_TIME,
    return_day_of_the_week: str = DEFAULT_RETURN_DAY_OF_THE_WEEK,
    return_time: str = DEFAULT_RETURN_TIME,
    months_ahead: int = 3
) -> Generator[tuple[datetime, str], None, None]:
    """Generate target dates for outbound and return journeys for the next N months.
    
    Yields tuples of (datetime, journey_type) where journey_type is 'outbound' or 'return'.
    """
    outbound_weekday = DAY_NAME_TO_WEEKDAY.get(outbound_day_of_the_week, 0)
    return_weekday = DAY_NAME_TO_WEEKDAY.get(return_day_of_the_week, 3)
    
    outbound_hour, outbound_minute = map(int, outbound_time.split(":"))
    return_hour, return_minute = map(int, return_time.split(":"))
    
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = today + timedelta(days=months_ahead * 30)
    
    current = today
    while current <= end_date:
        if current.weekday() == outbound_weekday:
            yield current.replace(hour=outbound_hour, minute=outbound_minute), "outbound"
        elif current.weekday() == return_weekday:
            yield current.replace(hour=return_hour, minute=return_minute), "return"
        current += timedelta(days=1)


def create_session() -> requests.Session:
    """Create a session with proper initialization."""
    session = requests.Session()
    session.headers.update(HEADERS)
    
    # Initialize the session by hitting the tickets page and API endpoints
    try:
        # Get initial cookies from the main site
        session.get("https://www.gwr.com/tickets", timeout=30)
        # Initialize API session
        session.get("https://api.gwr.com/customer/basket", timeout=30)
        session.get("https://api.gwr.com/rail/locations", timeout=30)
    except requests.RequestException as e:
        print(f"Warning: Session initialization error: {e}")
    
    return session


def fetch_journeys(
    session: requests.Session,
    departure_datetime: datetime,
    from_station_code: str,
    to_station_code: str
) -> dict | None:
    """Make a POST request to the GWR API for journey information."""
    url = "https://api.gwr.com/rail/journeys"

    payload = {
        "Data": {
            "locfrom": from_station_code,
            "locto": to_station_code,
            "datetimedepart": departure_datetime.strftime("%Y-%m-%dT%H:%M:%S"),
            "outwarddepartafter": True,
            "openreturn": False,
            "datetimereturn": None,
            "returndepartafter": True,
            "directServicesOnly": False,
            "firstclass": True,
            "standardclass": True,
            "promotion": None,
            "passengergroup": {
                "passengergroups": [
                    {
                        "adults": 1,
                        "children": 0,
                        "numberofrailcards": 0,
                        "originalfareid": "0",
                        "railcardcode": ""
                    }
                ]
            },
            "via": None,
            "avoid": None
        }
    }
    
    try:
        response = session.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching journeys for {departure_datetime}: {e}")
        return None


def extract_trains(response_data: dict, after_time: datetime, limit: int = 3) -> list[dict]:
    """Extract the first N trains departing after the specified time."""
    trains = []
    
    services = response_data.get("data", {}).get("services", [])
    
    for service in services:
        dep_str = service.get("depdatetime")
        if not dep_str:
            continue
        
        dep_time = datetime.fromisoformat(dep_str)
        
        # Only include trains departing at or after the target time
        if dep_time >= after_time:
            fare_info = service.get("_cheapestsinglefarecost", {})
            base_fare = fare_info.get("basetotalfare") if fare_info else None
            
            trains.append({
                "departure": dep_time,
                "ticket_cost": base_fare
            })
            
            if len(trains) >= limit:
                break
    
    return trains


def format_price(pence: int | None, threshold: int | None = None) -> str:
    """Format price from pence to pounds, highlighting if below threshold."""
    if pence is None:
        return "N/A"
    
    price_str = f"£{pence / 100:.2f}"
    
    # Highlight if below threshold
    if threshold is not None and pence < threshold:
        return f"🔥 *{price_str}*"
    
    return price_str


def format_for_telegram(
        date: datetime,
        trains: list[dict],
        fare_threshold: int,
        from_station_code: str,
        to_station_code: str,
        journey_type: str
    ) -> str:
    """Format train information for a Telegram message."""
    day_name = date.strftime("%A")
    date_str = date.strftime("%d %b")
    from_abbrev = get_station_code(from_station_code)
    to_abbrev = get_station_code(to_station_code)
    abbrev = f"{from_abbrev} > {to_abbrev}"
    
    
    lines = [f"🚂 *{day_name} {date_str}* ({abbrev})"]
    
    if not trains:
        lines.append("  No trains found")
    else:
        for i, train in enumerate(trains, 1):
            dep_time = train["departure"].strftime("%H:%M")
            price = format_price(train["ticket_cost"], fare_threshold)
            lines.append(f"  {i}. {dep_time} — {price}")
    
    # Add deep link for booking
    # deep_link = create_trainline_deeplink(from_station_code, to_station_code, date)
    # lines.append(f"  [Book now]({deep_link})")
    
    return "\n".join(lines)


def main(
    from_station_code: str = DEFAULT_FROM_STATION_CODE,
    to_station_code: str = DEFAULT_TO_STATION_CODE,
    outbound_fare_threshold: int = DEFAULT_OUTBOUND_FARE_THRESHOLD,
    return_fare_threshold: int = DEFAULT_RETURN_FARE_THRESHOLD,
    outbound_day_of_the_week: str = DEFAULT_OUTBOUND_DAY_OF_THE_WEEK,
    return_day_of_the_week: str = DEFAULT_RETURN_DAY_OF_THE_WEEK,
    outbound_time: str = DEFAULT_OUTBOUND_TIME,
    return_time: str = DEFAULT_RETURN_TIME,
    months_ahead: int = 3,
):
    """Main function to fetch and display train fares."""
    all_messages = []
    
    print("Initializing session...")
    session = create_session()
    
    for target_date, journey_type in get_target_dates(
        outbound_day_of_the_week=outbound_day_of_the_week,
        outbound_time=outbound_time,
        return_day_of_the_week=return_day_of_the_week,
        return_time=return_time,
        months_ahead=months_ahead
    ):
        print(f"Fetching {journey_type} journeys for {target_date.strftime('%Y-%m-%d %H:%M')}...")
        
        # Determine station codes and threshold based on journey type
        if journey_type == "outbound":
            current_from = from_station_code
            current_to = to_station_code
            threshold = outbound_fare_threshold
        else:  # return
            current_from = to_station_code
            current_to = from_station_code
            threshold = return_fare_threshold
        
        response = fetch_journeys(session, target_date, current_from, current_to)
        
        if response:
            trains = extract_trains(response, after_time=target_date, limit=3)
            message = format_for_telegram(
                target_date,
                trains,
                threshold,
                current_from,
                current_to,
                journey_type
            )
            all_messages.append(message)
        else:
            day_name = target_date.strftime("%A")
            date_str = target_date.strftime("%d %b %Y")
            all_messages.append(f"🚂 *{day_name} {date_str}*\n  ⚠️ Failed to fetch data")
    
    # Combine all messages
    telegram_output = "\n\n".join(all_messages)
    
    print("\n" + "=" * 50)
    print("TELEGRAM MESSAGE OUTPUT:")
    print("=" * 50 + "\n")
    print(telegram_output)
    
    return telegram_output


if __name__ == "__main__":
    main()
