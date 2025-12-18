create a python script that:
 - loops through the monday and thursday dates for the next three months
 - makes a request for each date using the time 6pm
 - makes a POST request to https://api.gwr.com/rail/journeys using the schema in @docs/payload.json
 - extracts the time and price for the first three trains to deplart after 6pm (use "depdatetime")
   - loop through data.services in @docs/response.json. "depdatetime" => "departure". "_cheapestsinglefarecost.basetotalfare" => "ticket cost"
- the script outputs the first three trains, as a string, formated for readibility in a telegram message