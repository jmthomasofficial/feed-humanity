# Contributing to Feed Humanity

Feed Humanity is open-source humanitarian infrastructure. Contributions of all kinds move the mission forward — code, data, translations, event resources, and outreach.

---

## Ways to Contribute

### Code
- **AI Dispatch** (`ai-dispatch/`): Matching algorithm improvements, perishability scoring models, route optimization, API endpoints, database performance.
- **AI Playbook** (`ai-playbook/`): Personalized plan generation logic, zip-to-food-bank lookup, tier-specific templates.
- **Data Pipeline**: Social post parsing for `#FeedHumanity` tracking, geocoding, impact aggregation.
- **Infrastructure**: Deployment configs, Docker setup, CI/CD, database migration tooling.

### Data
- Food bank database contributions (location, hours, needs, intake capacity).
- Restaurant surplus partner data (verified contacts, operating hours, typical surplus windows).
- City-level meal count validation and corrections.
- Geographic coverage gaps — we need non-US food bank data especially.

### Translations
Every playbook needs to exist in every major language. Current priority:
Spanish, Portuguese, Mandarin, Hindi, Arabic, French, Swahili.
Translations live in `playbooks/{tier}/{lang}.md` (e.g., `playbooks/individual/es.md`).
Use the English version as the source of truth and translate meaning, not just words.

### Event Kits
- Printable poster designs (open formats: SVG, Figma, Canva-compatible).
- Social media template packs (Stories, Reels/TikTok, Twitter/X cards).
- Email templates for workplace, school, and neighborhood outreach.
- Press release templates for local media.

### Outreach
- Share the repo on Hacker News, Reddit (r/programming, r/opensource, r/technology, r/foodbanks).
- Tag developers who care about social impact.
- Connect food banks or restaurants who want to participate in the AI Dispatch system.

---

## Development Setup

### Requirements
- Python 3.10 or higher
- pip (comes with Python)
- Git

### Installation

```bash
# Clone the repo
git clone https://github.com/feedhumanity/feed-humanity.git
cd feed-humanity

# Set up a virtual environment (strongly recommended)
python -m venv venv
source venv/bin/activate       # Linux/Mac
# venv\Scripts\activate.bat   # Windows CMD

# Install dependencies for ai-dispatch
cd ai-dispatch
pip install -r requirements.txt
cd ..
```

### Running Tests

```bash
# Run the full ai-dispatch test suite
cd ai-dispatch
python -m pytest test_dispatch.py -v

# Run with coverage report
python -m pytest test_dispatch.py --cov=. --cov-report=term-missing
```

All tests must pass before submitting a PR. If you add a feature, add a test for it.

### Code Formatting

We use **Black** for Python formatting and enforce it in CI:

```bash
pip install black
black ai-dispatch/
```

Line length: 88 characters (Black default).

### Type Hints

All Python functions must have type annotations:

```python
# Correct
def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    ...

# Not accepted
def calculate_distance(lat1, lon1, lat2, lon2):
    ...
```

### Docstrings

Every public function and class needs a docstring:

```python
def match_supply_to_demand(supply: FoodSupply, demand_list: list[FoodDemand]) -> MatchResult:
    """
    Match a single food supply source to the best available demand.

    Scores each demand entry by a weighted combination of distance,
    perishability urgency, and dietary fit. Returns the highest-scoring
    match along with the full scoring breakdown.

    Args:
        supply: The available food supply source.
        demand_list: All registered demand entries to score against.

    Returns:
        MatchResult containing the best match and score details.
        Returns None if no viable match exists.
    """
```

---

## Pull Request Process

1. **Fork** the repository and create a branch from `main`.
2. **Name your branch** descriptively: `fix/geocoder-timeout`, `feat/perishability-model`, `docs/spanish-playbook`.
3. **Write tests** for any code changes. Aim for coverage on the changed code paths.
4. **Run the formatter**: `black .` before committing.
5. **Run the tests**: `python -m pytest` must pass with zero failures.
6. **Write a clear PR description**: What does it do? Why does it matter? How was it tested?
7. **Reference any related issues** in the PR description.
8. A maintainer will review within 48 hours on weekdays.

### PR Checklist

Before submitting, verify:
- [ ] Tests pass locally (`python -m pytest`)
- [ ] Code is Black-formatted (`black --check .` returns 0)
- [ ] All new functions have type hints and docstrings
- [ ] No hardcoded credentials, API keys, or sensitive data
- [ ] PR description explains the what and why

---

## Good First Issues

If you are new to the project, these are solid entry points:

**Easy (documentation / data)**
- Add your city's food banks to the data schema documentation
- Translate `playbooks/individual.md` to your native language
- Improve inline comments in `ai-dispatch/matching_engine.py`

**Medium (Python)**
- Add a perishability scoring model that factors in food type and hours until spoilage
- Implement a caching layer for the geocoder (reduce repeated API calls)
- Add input validation to the API endpoints in `ai-dispatch/api.py`

**Harder (algorithm / architecture)**
- Build a demand prediction model using day-of-week and event proximity signals
- Implement route optimization for multi-stop volunteer delivery runs
- Design the `ai-playbook/` personalized plan generator (zip → food banks → custom checklist)

---

## Code of Conduct

This project exists to serve people who need food. Keep that in mind in every interaction:

- Be direct and constructive in code reviews.
- Assume good faith from contributors.
- Center the mission: does this change help more people get fed?
- Disagreements about technical approach belong in issues or PR comments — not in personal attacks.

---

## Contact

Open an issue for bugs, feature requests, or questions. For partnership inquiries (food banks, restaurant chains, corporate sponsors), reach out via [jmthomasofficial.com](https://jmthomasofficial.com).
