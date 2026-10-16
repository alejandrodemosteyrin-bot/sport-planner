## Overview

Build and maintain a personal, automated five-day outdoor activity planner for surfing, kitesurfing, and mountain biking (MTB). Every morning at 09:00 Europe/Madrid, the agent should produce an updated rolling forecast covering today and the next four calendar days.

The goal is to recommend what to do, where to go, when to leave home, when to start and finish the activity, and when to return home or begin remote work, while respecting Google Calendar commitments.

Prioritize worthwhile surf or kite conditions; when neither is suitable, propose a verified MTB route. Compare options on quality, safety, total travel time, useful activity time, and calendar compatibility. Never fabricate forecast values, journey times, routes, or calendar availability.

Default weekday constraints: lunch at 14:30 and work at 15:00, normally from home. The agent may propose later work or working from the campervan when feasible, but must not assume an empty calendar means work is optional. Weekends have no default work constraint, though calendar events still apply.

## Setup

• Install dependencies: Inspect the repository and choose the smallest maintainable stack. Prefer Python with a virtual environment, typed configuration, environment variables for credentials, structured logging, and automated tests. Document the actual installation commands in README.md once implemented. Do not invent commands before the stack exists.
• Configure credentials and integrations: Integrate Google Calendar using OAuth and least-privilege read-only scopes; Google Maps Routes/Directions for verified driving distances and durations; Surf-Forecast for surf conditions; Windguru for wind forecasts; AEMET or another reliable weather provider for alerts and general weather. Use documented APIs or permitted access methods. Do not bypass login restrictions, paywalls, CAPTCHAs, or site terms. If direct access is unavailable, implement an explicitly labeled fallback and report the missing data.
• Configure preferences: Collect and persist the home starting point, preferred surf and kite spots, skill levels, acceptable wave/wind ranges, kite sizes, preferred MTB routes, typical cycling speed, maximum driving time (initially 90 minutes), minimum worthwhile session length, preparation/buffer times, work requirements, and campervan connectivity constraints. Never hardcode or expose the home address in the repository.
• Run the project: Provide a command to generate an on-demand report and configure a daily scheduler for 09:00 Europe/Madrid, handling daylight saving time correctly. Reports should be delivered through an explicitly configured channel. Ensure that the scheduler and notification delivery actually work before claiming automation is active.
• Run tests: Provide commands for unit and integration tests. Mock external services in CI and keep live integration checks optional. Test time zones, weekends, calendar conflicts, routing failures, forecast gaps, and campervan scenarios.
• Always ask at least 3 clarifying questions before starting any complex task
• Always present the plan before executing
• Never make assumptions when information is missing
• Do not add filler content to increase length 
• Review output before final delivery 


## Conventions

• Code style: Keep provider adapters, forecast normalization, activity scoring, calendar analysis, route calculations, itinerary generation, and report delivery separate. Use typed models, explicit units (knots, meters, kilometers, minutes), timezone-aware datetimes, and clear error handling. Cache data only within a sensible provider-specific freshness window.
• Branching / commits: Use focused feature branches and descriptive commits. Never commit OAuth tokens, API keys, personal addresses, calendar contents, or .env files. Include .env.example with placeholders only.
• Testing expectations:
  • Generate exactly five local calendar dates per report, advancing the window by one day each morning.
  • Compare surf using wave height, swell period/direction, wind, tides, spot exposure, and forecast confidence; bigger waves are not automatically better.
  • Compare kite using average wind, gusts, direction, consistency, launch suitability, local restrictions, and safety; do not recommend unsafe offshore or storm conditions.
  • If neither water sport is worthwhile, select a real MTB route using distance, elevation, terrain, fitness, weather, and realistic off-road riding speed. Distinguish verified routes from hypothetical suggestions.
  • Read relevant Google Calendar events and preserve all confirmed commitments. Calendar free time does not itself authorize shifting work.
  • Use actual Google Maps route results for travel distance and duration where available; do not present unverified estimates as live results.
  • Include parking, walking, equipment setup, pack-down, changing/showering, traffic uncertainty, and a configurable safety buffer.
  • On weekdays, target arriving home with enough time for lunch at 14:30 and work at 15:00. If proposing remote work, specify parking, connectivity assumptions, setup time, lunch logistics, and the precise work-ready time. Any later start is a proposal, not an automatic schedule change.
  • On weekends, allow longer sessions and farther destinations, subject to calendar events and safety.
  • Prefer destinations within 90 minutes’ driving, extending the radius only when conditions or schedule justify it.
  • Clearly mark missing data, uncertain forecasts, and lower-confidence predictions four or five days ahead.
  • Never create, move, or cancel calendar events without explicit approval.

## Notes

Daily report specification

Each morning produce a concise, actionable report in the user’s configured language containing:

1. Five-day overview: Date, best activity, destination, ideal conditions window, home departure, home return or remote-work start, and confidence (high/medium/low).
2. Today’s detailed itinerary: Forecast evidence, reason for selection, departure, arrival, preparation, session start/end, pack-down, return journey, lunch, and work start. Include total round-trip distance, driving duration, activity duration, and Google Maps route link when verified.
3. Best opportunities: Best surf day, best kite day, best MTB day, and strongest overall opportunity within the five-day window.
4. Calendar optimization: Conflicts, legitimate flexible windows, and campervan work alternatives. Explicitly distinguish confirmed availability from proposed changes.
5. Changes since yesterday: Forecast improvements or deterioration, changes in destination, weather alerts, and new calendar conflicts.
6. Sources and confidence: Source URLs, retrieval/update timestamps when available, uncertainty, and any unavailable integrations.

## Decision logic

Evaluate surf and kite conditions independently; choose the better worthwhile opportunity rather than blindly enforcing a fixed sport order. When both are poor, recommend MTB if a suitable and safe route fits. If no option is worthwhile or feasible, recommend a rest day instead of manufacturing an itinerary. Maximize useful activity time without jeopardizing work or safety.

## Operational safeguards

Use Europe/Madrid time throughout. Check official warnings and local activity restrictions. Treat forecast data as predictions, not guarantees. Respect provider terms and rate limits. Store only necessary personal data securely. Maintain a previous-report snapshot for day-over-day comparison. Surface errors rather than silently replacing missing values with guesses. Do not claim that a report was delivered, a route was checked, or an integration was connected unless verified.

## Implementation sequence

1. Inspect the repository and identify what already exists.
2. Create configuration, provider interfaces, and a clear integration status check.
3. Implement forecast normalization and activity suitability scoring.
4. Implement calendar constraints and Google Maps itinerary timing.
5. Implement five-day ranking, report generation, and daily comparison.
6. Implement scheduled delivery and integration tests.
7. Document setup, credentials, limitations, and deployment in README.md.

If required configuration is missing, ask only for the essential details and proceed with non-dependent components. Do not claim the system is fully operational until live provider access, routing, scheduling, and report delivery have been validated.