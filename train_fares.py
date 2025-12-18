#!/usr/bin/env python3
"""
Train Fares Script - Fetches GWR train prices for Monday and Thursday evenings
"""

import requests
from datetime import datetime, timedelta
from typing import Generator


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

train_station_code_swansea = "4222"
train_station_code_paddington = "3087"

from_swansea_threshold = 4000
from_paddington_threshold = 6500

def get_target_dates(months_ahead: int = 3) -> Generator[datetime, None, None]:
    """Generate Monday and Thursday dates for the next N months."""
    today = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)
    end_date = today + timedelta(days=months_ahead * 30)
    
    current = today
    while current <= end_date:
        # Monday = 0, Thursday = 3
        if current.weekday() in (0, 3):
            yield current
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


def fetch_journeys(session: requests.Session, departure_datetime: datetime) -> dict | None:
    """Make a POST request to the GWR API for journey information."""
    url = "https://api.gwr.com/rail/journeys"

    from_station_code = train_station_code_paddington
    to_station_code = train_station_code_swansea

    # Monday
    if departure_datetime.weekday() == 0:
        from_station_code = train_station_code_swansea
        to_station_code = train_station_code_paddington

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


def format_for_telegram(date: datetime, trains: list[dict]) -> str:
    """Format train information for a Telegram message."""
    day_name = date.strftime("%A")
    date_str = date.strftime("%d %b %Y")
    
    # Monday = from Swansea, Thursday = from Paddington
    threshold = from_swansea_threshold if date.weekday() == 0 else from_paddington_threshold
    
    lines = [f"🚂 *{day_name} {date_str}*"]
    
    if not trains:
        lines.append("  No trains found")
    else:
        for i, train in enumerate(trains, 1):
            dep_time = train["departure"].strftime("%H:%M")
            price = format_price(train["ticket_cost"], threshold)
            lines.append(f"  {i}. {dep_time} — {price}")
    
    return "\n".join(lines)


def main():
    """Main function to fetch and display train fares."""
    all_messages = []
    
    print("Initializing session...")
    session = create_session()
    
    for target_date in get_target_dates(months_ahead=3):
        print(f"Fetching journeys for {target_date.strftime('%Y-%m-%d %H:%M')}...")
        
        response = fetch_journeys(session, target_date)
        
        if response:
            trains = extract_trains(response, after_time=target_date, limit=3)
            message = format_for_telegram(target_date, trains)
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
