# Feed Humanity

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Hashtag](https://img.shields.io/badge/%23FeedHumanity-active-orange)](https://twitter.com/search?q=%23FeedHumanity)

---

Jensen Huang says AGI is here. 318 million people are hungry. This repo contains everything you need to help fix that — whether you're one person with $5, a restaurant with surplus food, or a Fortune 500 company looking for the highest-ROI act of corporate responsibility in history.

---

## What Is Feed Humanity?

Feed Humanity is an AI-organized viral humanitarian campaign launched March 2026 in direct response to the AGI declaration. The premise is simple: if artificial general intelligence is truly here, the first proof that matters is whether it can help end hunger. Feed Humanity uses AI logistics, real-time impact tracking, and a six-tier participation system to mobilize individuals, businesses, corporations, and tech giants — all around a single atomic act. Buy a meal for a stranger. Give it to them. Film it. Post it. Challenge three more people to do the same.

This is not a donation platform. There is no "donate to X." The food IS the substance. The act IS the donation. A 12-year-old with $5 and a phone is fully participating. A Fortune 500 CEO is doing the same thing. That shared simplicity is the point.

---

## The Core Mechanic

1. **Buy a meal** for someone who looks like they could use one. Fast food, groceries, a hot plate — anything edible counts.
2. **Give it** to them. You don't have to be on camera. The food is the star.
3. **Film the moment** — even a selfie with the meal before handoff works.
4. **Post it** with `#FeedHumanity` + your city (example: `#FeedHumanityNashville`).
5. **Challenge three people** by name: `@person1 @person2 @person3 — your turn.`

That is the complete loop. Everything else in this repo is infrastructure to scale that loop.

---

## The AI Layer

AI is not decorating this campaign. It is doing real logistics work at every level:

**AI Dispatch** (`ai-dispatch/`) — A real-time surplus-to-deficit matching engine. Restaurants and grocery stores register surplus food closing-time inventory. Food banks and shelters register what they need. The system matches supply to demand, optimizing for distance, perishability, dietary requirements, and transport windows. Around 80 billion pounds of food are wasted annually in the US. Restaurants discard 22 to 33 percent of what they purchase. This system redirects that waste directly to people who need it.

**AI Playbook Generator** (`ai-playbook/`) — Enter your zip code, budget, and available time. Get a personalized action plan: which food banks near you need help most this week, what to buy at Costco for the maximum meals per dollar, a route for a neighborhood food run, pre-written social posts, and a text template to send your friends.

**AI Impact Tracker** — Every `#FeedHumanity` post is parsed for meal count and geolocation, added to the global counter, and plotted on the live map. Real-time stats update continuously.

**AI Event Logistics** — Volunteer organizers input their city and the system returns venue options, bulk food sourcing contacts, volunteer shift structures, a media kit, and a post-event impact report template.

---

## Quick Start — No Code Required

You do not need to be a developer to participate. These five steps work today:

1. Go to [jmthomasofficial.com/feedhumanity](https://jmthomasofficial.com/feedhumanity) and watch the two-minute overview.
2. Pick your tier: Individual, Crew, Organizer, Business, Corporation, or Tech Giant.
3. Open the playbook for your tier (see `playbooks/` folder in this repo or the website).
4. Do the thing. Buy food. Give it. Film it.
5. Post with `#FeedHumanity` and tag three people.

That is the full participation loop. Log your act on the website to add to the global counter.

---

## For Developers

The repo is organized around the AI infrastructure layers:

| Directory | What It Does |
|---|---|
| `ai-dispatch/` | Surplus-to-deficit matching engine (Python). Core algorithm, REST API, database models, geocoder. |
| `ai-playbook/` | Personalized action plan generator — takes zip, budget, time, returns step-by-step tier plan. |
| `playbooks/` | All six participation tiers as standalone markdown guides. No code required to use these. |
| `event-kit/` | Downloadable organizer resources: logistics checklists, poster files, social templates. |
| `data/` | Live public impact data: meal counts by region, participating cities, partner organizations. |

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, code standards, and good first issues.

### The Matching Problem (ai-dispatch)

```
SUPPLY: restaurants, grocers, caterers, farms
  → what food | how much | when available | perishability window | location

DEMAND: food banks, shelters, soup kitchens, event organizers
  → what they need | capacity | hours | dietary restrictions | location

AI MATCHES → optimize for: distance, perishability, dietary fit, volume
  → output: "Restaurant X → Shelter Y, pickup at 9:30 PM, 47 meals"
```

The matching engine is in `ai-dispatch/matching_engine.py`. The REST API is `ai-dispatch/api.py`. Both are documented inline.

---

## Hashtags

**Primary tracking tag:** `#FeedHumanity`

Every post should include this tag. The impact tracker counts it.

**Supporting tags (use 1-2 per post):**
- `#FeedTheNeed` — action-oriented urgency
- `#EndWorldHunger` — the big goal, searchable
- `#AGIForGood` — ties to the tech narrative
- `#FeedForward` — the chain reaction mechanic
- `#OneMealChallenge` — the atomic unit

**City tag:** Add your city to the primary tag. `#FeedHumanityChicago`, `#FeedHumanityLondon`, `#FeedHumanityTokyo`. This feeds the city leaderboard and helps locals find each other.

---

## The Moment

The companies that fed humanity during the AGI moment will be remembered forever. The ones that did not will be asked why.

If you run a tech company: the CEO challenge is in `playbooks/tech-giant.md`. The ask is simple. Buy someone lunch. Film it. The headline writes itself.

---

## License

[MIT](LICENSE) — do whatever you want with this. Fork it, clone it, build on it, deploy it in your city. The goal is maximum impact, not IP protection.
